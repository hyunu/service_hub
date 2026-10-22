"""배포 실행기 (REQUIREMENTS §13.3). 게이트가 닫혀 있으면 절대 실행하지 않는다.

상태: queued -> validating -> running -> verifying -> succeeded | failed
허용 작업: compose config/up/down + 헬스체크. 임의 셸 실행 경로 없음.
"""
from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from ..db import get_session_factory
from ..models import Deployment, DeploymentStep
from .deploy_plan import PlanContext, build_plan


class DeploymentBusy(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _session():
    """실행기 내부 세션 — 커밋/롤백/종료를 보장한다.

    (db.session_scope()는 제너레이터라 with 문에 바로 쓸 수 없다.)
    """
    s = get_session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


class DeployRunner:
    def __init__(self, *, gateway, workdir_resolver, enable_deploy: bool,
                 snapshot_root: str | None = None) -> None:
        self.gateway = gateway
        self.workdir_resolver = workdir_resolver
        self.enable_deploy = enable_deploy
        self.snapshot_root = snapshot_root
        self._active: set[str] = set()
        self._lock = threading.Lock()

    # -- 게이트/중복 -----------------------------------------------------
    def _require_enabled(self) -> None:
        if not self.enable_deploy:
            raise PermissionError(
                "배포 기능이 비활성화되어 있습니다 (HUB_ENABLE_DEPLOY=false)")

    def acquire(self, service_id: str) -> None:
        with self._lock:
            if service_id in self._active:
                raise DeploymentBusy(f"'{service_id}' 배포가 이미 진행 중입니다")
            self._active.add(service_id)

    def release(self, service_id: str) -> None:
        with self._lock:
            self._active.discard(service_id)

    # -- 실행 ------------------------------------------------------------
    def run(self, spec, ctx: PlanContext, actor: str) -> Deployment:
        self._require_enabled()
        plan = build_plan(spec, ctx)
        if plan["result"] != "READY":
            raise ValueError(
                "배포 계획이 READY가 아닙니다: " +
                "; ".join(i["message"] for i in plan["impact"]))

        deployment_id = f"dep-{uuid.uuid4().hex[:12]}"
        with _session() as db:
            dep = Deployment(id=deployment_id, service_id=spec.service.id,
                             status="queued", requested_by=actor, plan=plan,
                             started_at=_now())
            db.add(dep)
            self._step(db, deployment_id, 0, "queued", "ok", "작업 생성")
        return self._execute(deployment_id, spec, plan, actor)

    # -- 내부 ------------------------------------------------------------
    def _step(self, db, deployment_id: str, seq: int, name: str, status: str,
              detail: str) -> None:
        db.add(DeploymentStep(deployment_id=deployment_id, seq=seq, name=name,
                              status=status, detail=detail, at=_now()))

    def _set_status(self, db, deployment_id: str, status: str,
                    finished: bool = False) -> None:
        dep = db.get(Deployment, deployment_id)
        if dep is not None:
            dep.status = status
            if finished:
                dep.finished_at = _now()

    def _execute(self, deployment_id: str, spec, plan: dict, actor: str = "system") -> Deployment:
        service_id = spec.service.id
        project = getattr(spec.deployment, "project_name", None) or service_id
        workdir = self.workdir_resolver(service_id)
        compose_file = getattr(spec.deployment, "compose_file", "compose.yaml")

        try:
            # validating — 배포 정의 파일 스냅샷(롤백용). 실패해도 배포는 계속한다.
            from .deploy_snapshot import take_snapshot
            snap = take_snapshot(workdir, self.snapshot_root, service_id,
                                 deployment_id, actor)
            with _session() as db:
                self._set_status(db, deployment_id, "validating")
                self._step(db, deployment_id, 1, "validating", "ok",
                           f"compose_file={compose_file}, "
                           f"snapshot={snap['dir'] if snap else 'none'}")
            cfg = self.gateway.compose_config(workdir, project)
            if not cfg.get("ok"):
                return self._fail(deployment_id, 1,
                                  f"Compose 검증 실패: {cfg.get('stderr')}")

            # running
            with _session() as db:
                self._set_status(db, deployment_id, "running")
                self._step(db, deployment_id, 2, "running", "ok", "compose up")
            up = self.gateway.compose_up(workdir, project)
            if not up.get("ok"):
                return self._fail(deployment_id, 2, f"배포 실패: {up.get('stderr')}")

            # verifying
            with _session() as db:
                self._set_status(db, deployment_id, "verifying")
                self._step(db, deployment_id, 3, "verifying", "ok", "헬스체크")
            snaps = self.gateway.list_containers() or []
            running = [s for s in snaps
                       if s.compose_project == project and s.state == "running"]
            required = [c.name for c in spec.containers if c.required]
            missing = [n for n in required
                       if not any(s.compose_service == n for s in running)]
            if missing:
                return self._fail(deployment_id, 3,
                                  f"필수 컨테이너 미기동: {', '.join(missing)}")

            with _session() as db:
                self._set_status(db, deployment_id, "succeeded", finished=True)
                self._step(db, deployment_id, 4, "succeeded", "ok", "완료")
                from ..models import Service
                svc = db.get(Service, service_id)
                if svc is not None:
                    svc.last_deployed_at = _now()
                    svc.status = "healthy"
            return self._get(deployment_id)
        finally:
            self.release(service_id)

    def _fail(self, deployment_id: str, seq: int, message: str) -> Deployment:
        with _session() as db:
            dep = db.get(Deployment, deployment_id)
            if dep is not None:
                dep.status = "failed"
                dep.error = message
                dep.finished_at = _now()
            self._step(db, deployment_id, seq + 100, "failed", "error", message)
        return self._get(deployment_id)

    def _get(self, deployment_id: str) -> Deployment:
        with _session() as db:
            dep = db.get(Deployment, deployment_id)
            if dep is not None:
                _ = list(dep.steps)  # eager load (expire_on_commit=False 로 유지됨)
                db.expunge(dep)
            return dep
