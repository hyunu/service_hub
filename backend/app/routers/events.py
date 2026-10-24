"""이벤트/감사 로그/배포(읽기 전용 스텁) 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AuditLog, Deployment, DeploymentStep, Event, Setting
from ..security import HubError, get_read_actor, require_auth
from ..services.events import record_audit

router = APIRouter(tags=["events"], dependencies=[Depends(require_auth)])
deploy_router = APIRouter(prefix="/deployments", tags=["deployments"],
                          dependencies=[Depends(require_auth)])


@router.get("/events")
def list_events(severity: str | None = None, service_id: str | None = None,
                limit: int = 100, db: Session = Depends(get_db)):
    stmt = select(Event)
    if severity:
        stmt = stmt.where(Event.severity == severity)
    if service_id:
        stmt = stmt.where(Event.service_id == service_id)
    rows = list(db.execute(stmt.order_by(Event.id.desc()).limit(min(limit, 500))).scalars())
    return {"items": [{"id": e.id, "ts": e.ts, "severity": e.severity, "kind": e.kind,
                       "service_id": e.service_id, "container_id": e.container_id,
                       "message": e.message, "detail": e.detail} for e in rows]}


READ_STATE_KEY = "events_state"


def _unread_since(db: Session) -> str | None:
    row = db.get(Setting, READ_STATE_KEY)
    return (row.value or {}).get("last_read_at") if row else None


@router.get("/events/unread-count")
def events_unread_count(db: Session = Depends(get_db)):
    """읽지 않은(warning/critical) 이벤트 수 — 상단 알림 뱃지용.

    서버에 저장된 ``last_read_at`` 이후 이벤트만 센다. 이벤트를 확인하면
    ``POST /events/acknowledge``가 시각을 갱신해 뱃지가 줄어든다.
    """
    from sqlalchemy import func

    last = _unread_since(db)
    stmt = select(func.count(Event.id)).where(
        Event.severity.in_(["warning", "critical"]))
    if last:
        stmt = stmt.where(Event.ts > last)
    return {"count": int(db.scalar(stmt) or 0), "last_read_at": last}


@router.post("/events/acknowledge")
def acknowledge_events(db: Session = Depends(get_db)):
    """이벤트 확인 처리 — 이 시각 이후 이벤트만 미읽음으로 센다."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    row = db.get(Setting, READ_STATE_KEY)
    if row is None:
        row = Setting(key=READ_STATE_KEY, value={})
        db.add(row)
    # JSON 컬럼은 내부 변경이 dirty 추적되지 않으므로 재할당한다.
    row.value = {**(row.value or {}), "last_read_at": now}
    db.commit()
    return {"ok": True, "last_read_at": now}


@router.get("/audit-logs")
def list_audit_logs(limit: int = 100, db: Session = Depends(get_db)):
    rows = list(db.execute(select(AuditLog).order_by(AuditLog.id.desc())
                           .limit(min(limit, 500))).scalars())
    return {"items": [{"id": a.id, "ts": a.ts, "actor": a.actor, "action": a.action,
                       "target": a.target, "detail": a.detail} for a in rows]}


def _require_allowed_service(settings, service_id: str) -> None:
    """배포 허용 목록이 설정된 경우 해당 서비스만 허용한다."""
    allowed = settings.deploy_allowed
    if allowed and service_id not in allowed:
        raise HubError(
            status_code=403,
            detail=f"'{service_id}'는 배포 허용 목록에 없습니다 "
                   f"(HUB_DEPLOY_ALLOWED_SERVICES)",
            code="service_not_allowed")


def _deploy_disabled():
    raise HubError(status_code=503,
                        detail="배포 기능은 아직 비활성화되어 있습니다 (Phase 3). "
                               "HUB_ENABLE_DEPLOY 설정과 docs/SECURITY.md를 확인하세요.",
                        code="deploy_disabled")


@deploy_router.get("")
def list_deployments(service_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Deployment)
    if service_id:
        stmt = stmt.where(Deployment.service_id == service_id)
    rows = list(db.execute(stmt.order_by(Deployment.started_at.desc()).limit(100)).scalars())
    return {"items": [{"deployment_id": d.id, "service_id": d.service_id, "status": d.status,
                       "requested_by": d.requested_by, "error": d.error,
                       "started_at": d.started_at, "finished_at": d.finished_at}
                      for d in rows]}


@deploy_router.get("/{deployment_id}")
def get_deployment(deployment_id: str, db: Session = Depends(get_db)):
    d = db.get(Deployment, deployment_id)
    if d is None:
        raise HubError(status_code=404, detail="배포 작업을 찾을 수 없습니다",
                            code="deployment_not_found")
    steps = list(db.execute(select(DeploymentStep)
                            .where(DeploymentStep.deployment_id == deployment_id)
                            .order_by(DeploymentStep.seq)).scalars())
    return {"deployment_id": d.id, "service_id": d.service_id, "status": d.status,
            "plan": d.plan, "error": d.error, "started_at": d.started_at,
            "finished_at": d.finished_at,
            "steps": [{"seq": s.seq, "name": s.name, "status": s.status,
                       "detail": s.detail, "at": s.at} for s in steps]}


def _collect_plan_context(db: Session, spec):
    """관찰된 환경을 모아 PlanContext를 만든다 (DB + 게이트웨이 읽기 전용)."""
    from ..dependencies import get_gateway
    from ..services.deploy_plan import PlanContext
    from ..services.ports import build_registry

    conflicting: set[int] = set()
    for item in build_registry(db):
        # 실제 점유된 포트와, 다른 서비스가 예약한 포트 모두 충돌로 본다.
        # 단, **같은 서비스**가 이미 쓰고 있는 포트는 재배포 시 충돌이 아니다.
        if item.get("host_port") and (item.get("in_use") or item.get("reserved")):
            if item.get("service_id") == spec.service.id:
                continue
            conflicting.add(item["host_port"])

    gateway = get_gateway()
    current: dict[str, dict] = {}
    snapshots = gateway.list_containers() or []
    project = getattr(spec.deployment, "project_name", None) or spec.service.id
    for snap in snapshots:
        if snap.compose_project == project and snap.compose_service:
            current[snap.compose_service] = {"image": snap.image, "state": snap.state}

    # 필수 환경 변수는 서버 환경변수에서 존재 여부만 확인 (값은 노출하지 않음)
    import os
    available_env = set(os.environ)

    mem_available = None
    try:
        from ..services.resource import collect_host
        host = collect_host()
        mem_available = getattr(host, "mem_available_mb", None)
    except Exception:
        mem_available = None

    return PlanContext(available_env=available_env, conflicting_ports=conflicting,
                       mem_available_mb=mem_available, compose_ok=True,
                       current_containers=current)


@deploy_router.post("/plan")
def plan_deployment(payload: dict, db: Session = Depends(get_db),
                    actor: str = Depends(get_read_actor)):
    """배포 계획 생성 — 컨테이너를 변경하지 않는다.

    CLI는 `{"service_definition": <service.yaml dict>}`로 POST한다.
    직접 호출 시에는 스펙 dict를 그대로 보내도 된다.
    """
    from ..services.deploy_plan import build_plan
    from ..services.service_spec import SpecError, parse_spec, validate_spec_dict

    spec_dict = payload.get("service_definition", payload)
    try:
        if isinstance(spec_dict, str):
            spec = parse_spec(spec_dict)
        else:
            spec = validate_spec_dict(spec_dict)
    except SpecError as exc:
        raise HubError(status_code=422, detail=str(exc), code=exc.code) from exc
    _require_allowed_service(get_settings(), spec.service.id)
    ctx = _collect_plan_context(db, spec)
    plan = build_plan(spec, ctx)
    record_audit(db, actor, "deploy.plan", target=spec.service.id,
                 detail={"result": plan["result"]})
    db.commit()
    return plan


@deploy_router.post("", status_code=202)
def create_deployment(payload: dict, db: Session = Depends(get_db),
                      actor: str = Depends(get_read_actor)):
    """배포 실행 — HUB_ENABLE_DEPLOY=true 에서만. 화이트리스트 compose 작업만 수행한다.

    CLI는 `{"service_id": ..., "confirmed": true}`로 POST한다(스펙은 서버에서 해석).
    직접 호출 시에는 `{"spec": <service.yaml dict>}` 또는 스펙 dict를 보낸다.
    """
    from ..dependencies import build_deploy_runner
    from ..services.deploy_plan import build_plan
    from ..services.deploy_runner import DeploymentBusy
    from ..services.service_spec import SpecError, parse_spec, validate_spec_dict

    settings = get_settings()
    ok, _reason = settings.deploy_gate()
    if not ok:
        _deploy_disabled()

    spec_dict = payload.get("spec") or payload.get("service_definition")
    if spec_dict is None:
        # CLI의 service_id 기반 호출: 작업 디렉터리의 service.yaml을 해석한다
        from ..dependencies import build_deploy_runner as _b  # noqa: F401
        service_id = payload.get("service_id")
        if not service_id:
            raise HubError(status_code=422, detail="spec 또는 service_id가 필요합니다",
                           code="spec_required")
        import os
        base = os.environ.get("HUB_DEPLOY_WORKDIR") or "./services-local"
        try:
            spec = parse_spec(f"{base.rstrip('/')}/{service_id}")
        except SpecError as exc:
            raise HubError(status_code=422, detail=str(exc), code=exc.code) from exc
    else:
        try:
            if isinstance(spec_dict, str):
                spec = parse_spec(spec_dict)
            else:
                spec = validate_spec_dict(spec_dict)
        except SpecError as exc:
            raise HubError(status_code=422, detail=str(exc), code=exc.code) from exc

    _require_allowed_service(settings, spec.service.id)
    ctx = _collect_plan_context(db, spec)
    plan = build_plan(spec, ctx)
    if plan["result"] != "READY":
        raise HubError(
            status_code=409,
            detail="배포 계획이 READY가 아닙니다: " +
                   "; ".join(i["message"] for i in plan["impact"]),
            code="plan_not_ready")

    runner = build_deploy_runner()
    try:
        runner.acquire(spec.service.id)
    except DeploymentBusy as exc:
        raise HubError(status_code=409, detail=str(exc),
                       code="deployment_busy") from exc

    record_audit(db, actor, "deploy.apply", target=spec.service.id,
                 detail={"result": plan["result"]})
    db.commit()

    try:
        dep = runner.run(spec, ctx, actor=actor)
    except PermissionError as exc:
        raise HubError(status_code=503, detail=str(exc),
                       code="deploy_disabled") from exc
    except ValueError as exc:
        raise HubError(status_code=409, detail=str(exc), code="plan_not_ready") from exc
    finally:
        runner.release(spec.service.id)

    result = {"deployment_id": dep.id, "service_id": dep.service_id, "status": dep.status,
              "error": dep.error, "started_at": dep.started_at,
              "finished_at": dep.finished_at}

    # 무인 운영: 실패하면 직전 성공 배포로 자동 롤백
    if dep.status == "failed" and settings.deploy_auto_rollback:
        from ..services.deploy_rollback import latest_successful, perform_rollback
        prev = latest_successful(db, dep.service_id, exclude=dep.id)
        if prev is not None:
            try:
                rb = perform_rollback(db, prev, actor=f"{actor} (auto-rollback)",
                                      reason=f"deployment {dep.id} failed")
                result["auto_rollback"] = rb
                result["auto_rolled_back"] = rb.get("status") == "succeeded"
            except HubError as exc:
                result["auto_rollback_error"] = {"detail": exc.detail, "code": exc.code}

    from ..services.deploy_notify import notify_deployment
    notify_deployment(dep)
    return result


@deploy_router.post("/{deployment_id}/rollback", status_code=202)
def rollback_deployment(deployment_id: str, payload: dict | None = None,
                        db: Session = Depends(get_db),
                        actor: str = Depends(get_read_actor)):
    """배포 시점 스냅샷으로 되돌려 재배포한다 (REQUIREMENTS §13.4).

    - 대상 배포는 ``succeeded``여야 하고, 그 배포의 스냅샷이 있어야 한다.
    - 실행 로직은 `perform_rollback` 으로 분리되어 자동 롤백과 공유한다.
    - DB/볼륨 변경은 자동 롤백하지 않는다(요구사항 §13.4).
    """
    from ..services.deploy_rollback import perform_rollback

    settings = get_settings()
    ok, reason = settings.deploy_gate()
    if not ok:
        _deploy_disabled()   # type: ignore[misc]

    dep = db.get(Deployment, deployment_id)
    if dep is None:
        raise HubError(status_code=404, detail="배포 작업을 찾을 수 없습니다",
                       code="deployment_not_found")
    _require_allowed_service(settings, dep.service_id)
    result = perform_rollback(db, dep, actor=actor)
    record_audit(db, actor, "deploy.rollback", target=dep.service_id,
                 detail={"from_deployment": deployment_id,
                         "new_deployment": result.get("deployment_id")})
    db.commit()
    return result


@deploy_router.get("/{deployment_id}/logs")
def deployment_logs(deployment_id: str, db: Session = Depends(get_db)):
    d = db.get(Deployment, deployment_id)
    if d is None:
        raise HubError(status_code=404, detail="배포 작업을 찾을 수 없습니다",
                            code="deployment_not_found")
    return {"lines": [], "note": "배포 로그는 Phase 3에서 기록됩니다"}
