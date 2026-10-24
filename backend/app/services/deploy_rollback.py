"""배포 롤백 실행 — 라우터와 자동 롤백(무인 배포)이 공유한다.

동작:
  1) 대상 배포(성공)의 스냅샷을 배포 디렉터리에 복원
  2) 스냅샷의 service.yaml 로 계획을 다시 만들고 READY 확인
  3) 일반 배포 경로(게이트/실행기)로 재배포
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Deployment
from ..security import HubError


def latest_successful(db: Session, service_id: str,
                      exclude: str | None = None) -> Deployment | None:
    """해당 서비스의 가장 최근 성공 배포(스냅샷 후보)."""
    stmt = (select(Deployment)
            .where(Deployment.service_id == service_id, Deployment.status == "succeeded")
            .order_by(Deployment.finished_at.desc()))
    for dep in db.execute(stmt).scalars():
        if exclude and dep.id == exclude:
            continue
        return dep
    return None


def perform_rollback(db: Session, dep: Deployment, *, actor: str,
                     reason: str | None = None) -> dict:
    """성공한 배포의 스냅샷으로 되돌려 재배포한다."""
    from ..dependencies import build_deploy_runner
    from ..routers.events import _collect_plan_context
    from .deploy_plan import build_plan
    from .deploy_runner import DeploymentBusy
    from .deploy_snapshot import restore_snapshot
    from .service_spec import SpecError, parse_spec

    settings = get_settings()
    ok, reason_gate = settings.deploy_gate()
    if not ok:
        raise HubError(status_code=503, detail=reason_gate, code="deploy_disabled")

    if dep.status != "succeeded":
        raise HubError(status_code=409,
                       detail=f"성공한 배포만 롤백할 수 있습니다 (현재: {dep.status})",
                       code="rollback_not_allowed")

    runner = build_deploy_runner()
    workdir = runner.workdir_resolver(dep.service_id)
    try:
        restored = restore_snapshot(settings.deploy_snapshot_dir, dep.service_id,
                                    dep.id, workdir)
    except PermissionError as exc:
        raise HubError(status_code=409, detail=str(exc),
                       code="snapshot_restore_forbidden") from exc
    except FileNotFoundError as exc:
        raise HubError(status_code=409, detail=str(exc), code="snapshot_missing") from exc

    try:
        spec = parse_spec(workdir)
    except SpecError as exc:
        raise HubError(status_code=409,
                       detail=f"스냅샷의 service.yaml을 해석할 수 없습니다: {exc}",
                       code="snapshot_incomplete") from exc

    ctx = _collect_plan_context(db, spec)
    plan = build_plan(spec, ctx)
    if plan["result"] != "READY":
        raise HubError(status_code=409,
                       detail="롤백 계획이 READY가 아닙니다: " +
                              "; ".join(i["message"] for i in plan["impact"]),
                       code="plan_not_ready")

    try:
        runner.acquire(dep.service_id)
    except DeploymentBusy as exc:
        raise HubError(status_code=409, detail=str(exc), code="deployment_busy") from exc

    try:
        new = runner.run(spec, ctx, actor=actor)
    except PermissionError as exc:
        raise HubError(status_code=503, detail=str(exc), code="deploy_disabled") from exc
    except ValueError as exc:
        raise HubError(status_code=409, detail=str(exc), code="plan_not_ready") from exc
    finally:
        runner.release(dep.service_id)

    from .deploy_notify import notify_deployment
    notify_deployment(new, extra={"rollback_of": dep.id, "reason": reason})

    return {"deployment_id": new.id, "service_id": new.service_id,
            "status": new.status, "error": new.error,
            "rollback_of": dep.id, "restored_files": restored,
            "reason": reason}
