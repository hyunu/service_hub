"""이벤트/감사 로그/배포(읽기 전용 스텁) 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AuditLog, Deployment, DeploymentStep, Event
from ..security import HubError, require_auth

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


@router.get("/audit-logs")
def list_audit_logs(limit: int = 100, db: Session = Depends(get_db)):
    rows = list(db.execute(select(AuditLog).order_by(AuditLog.id.desc())
                           .limit(min(limit, 500))).scalars())
    return {"items": [{"id": a.id, "ts": a.ts, "actor": a.actor, "action": a.action,
                       "target": a.target, "detail": a.detail} for a in rows]}


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


@deploy_router.post("/plan")
def plan_deployment():
    _deploy_disabled()   # Phase 3에서 구현 — 현재는 항상 차단


@deploy_router.post("")
def create_deployment():
    _deploy_disabled()


@deploy_router.get("/{deployment_id}/logs")
def deployment_logs(deployment_id: str, db: Session = Depends(get_db)):
    d = db.get(Deployment, deployment_id)
    if d is None:
        raise HubError(status_code=404, detail="배포 작업을 찾을 수 없습니다",
                            code="deployment_not_found")
    return {"lines": [], "note": "배포 로그는 Phase 3에서 기록됩니다"}
