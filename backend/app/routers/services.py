"""서비스 레지스트리 라우터 (REQUIREMENTS §5).

중요: DELETE는 관리 DB 레코드만 삭제한다 — 컨테이너/볼륨/이미지는 건드리지 않는다.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Container, Endpoint, PortReservation, Service, ServiceComponent
from ..security import HubError, get_read_actor, require_auth
from ..services.events import record_audit

router = APIRouter(prefix="/services", tags=["services"],
                   dependencies=[Depends(require_auth)])

SERVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
CATEGORIES = {"web", "backend", "database", "ai", "automation", "media", "dev", "infra", "other"}


class ComponentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = "other"
    required: bool = True
    description: str = ""


class EndpointIn(BaseModel):
    name: str
    type: str = "http"
    exposure: str = "internal"
    hostname: str | None = None
    host_port: int | None = None
    container: str
    container_port: int


class ServiceCreate(BaseModel):
    id: str
    name: str
    description: str = ""
    category: str = "other"
    repository_url: str | None = None
    branch: str | None = None
    deployment_type: str = "docker-compose"
    deployment_path: str | None = None
    compose_file: str | None = None
    version: str | None = None
    documentation: str | None = None
    tags: list[str] = []
    components: list[ComponentIn] = []
    endpoints: list[EndpointIn] = []


class ServicePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    documentation: str | None = None
    tags: list[str] | None = None
    notes: str | None = None
    version: str | None = None


def _validate(body_id: str, category: str) -> None:
    if not SERVICE_ID_RE.match(body_id):
        raise HubError(status_code=422,
                            detail="서비스 ID는 영문 소문자/숫자/하이픈으로 구성되어야 합니다",
                            code="invalid_service_id")
    if category not in CATEGORIES:
        raise HubError(status_code=422,
                            detail=f"category는 {sorted(CATEGORIES)} 중 하나여야 합니다",
                            code="invalid_category")


def _service_or_404(db: Session, service_id: str) -> Service:
    svc = db.get(Service, service_id)
    if svc is None:
        raise HubError(status_code=404, detail=f"서비스 '{service_id}'를 찾을 수 없습니다",
                            code="service_not_found")
    return svc


def _container_rows(db: Session, service_id: str) -> list[Container]:
    return list(db.execute(select(Container).where(Container.service_id == service_id)).scalars())


def _cpu_mem_for(db: Session, service_id: str) -> tuple[float | None, float | None]:
    from ..models import ResourceSample
    row = db.execute(select(ResourceSample)
                     .where(ResourceSample.scope == "service",
                            ResourceSample.scope_id == service_id)
                     .order_by(ResourceSample.id.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        return None, None
    return row.cpu_percent, row.mem_used_mb


def _summary(db: Session, svc: Service) -> dict:
    rows = _container_rows(db, svc.id)
    cpu, mem = _cpu_mem_for(db, svc.id)
    return {
        "id": svc.id, "name": svc.name, "description": svc.description,
        "category": svc.category, "status": svc.status, "version": svc.version,
        "containers": {
            "total": len(rows),
            "running": sum(1 for r in rows if r.state == "running"),
            "stopped": sum(1 for r in rows if r.state != "running"),
        },
        "endpoints": [{"name": e.name, "type": e.type, "exposure": e.exposure,
                       "hostname": e.hostname, "host_port": e.host_port,
                       "container": e.container, "container_port": e.container_port}
                      for e in svc.endpoints],
        "cpu_percent": cpu, "memory_mb": mem,
        "last_deployed_at": svc.last_deployed_at,
    }


@router.get("")
def list_services(search: str | None = None, status: str | None = None,
                  category: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Service)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(or_(Service.id.ilike(term), Service.name.ilike(term),
                              Service.description.ilike(term)))
    if status:
        stmt = stmt.where(Service.status == status)
    if category:
        stmt = stmt.where(Service.category == category)
    items = [_summary(db, s) for s in db.execute(stmt.order_by(Service.id)).scalars()]
    return {"items": items, "count": len(items)}


@router.post("", status_code=201)
def create_service(body: ServiceCreate, db: Session = Depends(get_db),
                   actor: str = Depends(get_read_actor)):
    _validate(body.id, body.category)
    if db.get(Service, body.id) is not None:
        raise HubError(status_code=409, detail=f"서비스 ID '{body.id}'는 이미 등록되어 있습니다",
                            code="duplicate_service_id")
    svc = Service(id=body.id, name=body.name, description=body.description,
                  category=body.category, repository_url=body.repository_url,
                  branch=body.branch, deployment_type=body.deployment_type,
                  deployment_path=body.deployment_path, compose_file=body.compose_file,
                  version=body.version, documentation=body.documentation, tags=body.tags)
    db.add(svc)
    for comp in body.components:
        db.add(ServiceComponent(service_id=body.id, name=comp.name, role=comp.role,
                                required=comp.required, description=comp.description))
    for ep in body.endpoints:
        if ep.exposure == "proxy" and not ep.hostname:
            raise HubError(status_code=422, detail="proxy 노출에는 hostname이 필요합니다",
                                code="hostname_required")
        db.add(Endpoint(service_id=body.id, name=ep.name, type=ep.type, exposure=ep.exposure,
                        hostname=ep.hostname, host_port=ep.host_port, container=ep.container,
                        container_port=ep.container_port))
    record_audit(db, actor, "service.create", target=body.id)
    db.commit()
    return _summary(db, svc)


@router.post("/validate")
def validate_service_spec(payload: dict, db: Session = Depends(get_db)):
    """service.yaml(dict) 또는 파일 경로를 검증한다. DB에 아무것도 쓰지 않는다."""
    from ..services.service_spec import SpecError, parse_spec, validate_spec_dict

    try:
        if isinstance(payload.get("path"), str):
            spec = parse_spec(payload["path"])
        else:
            spec = validate_spec_dict(payload)
    except SpecError as exc:
        raise HubError(status_code=422, detail=str(exc), code=exc.code) from exc
    return {"valid": True, "spec": spec.model_dump(), "errors": []}


@router.get("/{service_id}")
def get_service(service_id: str, db: Session = Depends(get_db)):
    svc = _service_or_404(db, service_id)
    rows = _container_rows(db, service_id)
    summary = _summary(db, svc)
    missing = [c.name for c in svc.components if c.required
               and not any(r.component_name == c.name and r.state == "running" for r in rows)]
    return {
        **summary,
        "repository_url": svc.repository_url, "branch": svc.branch,
        "deployment_type": svc.deployment_type, "deployment_path": svc.deployment_path,
        "compose_file": svc.compose_file, "documentation": svc.documentation,
        "tags": svc.tags, "notes": svc.notes,
        "created_at": svc.created_at, "updated_at": svc.updated_at,
        "last_healthcheck_at": svc.last_healthcheck_at,
        "components": [{"name": c.name, "role": c.role, "required": c.required,
                        "description": c.description} for c in svc.components],
        "containers_detail": [{"container_id": r.container_id, "name": r.name,
                               "component": r.component_name, "state": r.state,
                               "management_state": r.management_state, "image": r.image}
                              for r in rows],
        "warnings": ([f"필수 컨테이너가 실행되지 않음: {', '.join(missing)}"] if missing else []),
    }


@router.patch("/{service_id}")
def patch_service(service_id: str, body: ServicePatch, db: Session = Depends(get_db),
                  actor: str = Depends(get_read_actor)):
    svc = _service_or_404(db, service_id)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    for key, value in updates.items():
        setattr(svc, key, value)
    from ..models import utcnow
    svc.updated_at = utcnow()
    record_audit(db, actor, "service.update", target=service_id, detail={"fields": list(updates)})
    db.commit()
    return _summary(db, svc)


@router.delete("/{service_id}")
def delete_service(service_id: str, confirm: str = Query(...),
                   db: Session = Depends(get_db), actor: str = Depends(get_read_actor)):
    """관리 레코드만 삭제한다. 컨테이너/볼륨/이미지는 변경하지 않는다 (runtime_unchanged=true)."""
    svc = _service_or_404(db, service_id)
    if confirm != service_id:
        raise HubError(status_code=422,
                            detail="confirm 파라미터에 서비스 ID를 정확히 입력하세요",
                            code="confirm_mismatch")
    db.execute(PortReservation.__table__.delete().where(
        PortReservation.service_id == service_id))
    db.execute(Container.__table__.delete().where(
        Container.service_id == service_id).where(
        Container.component_name == "hub-self"))  # no-op 안전 가드
    # 컨테이너 행의 service_id 참조는 레코드 삭제 대상이 아님 — 소속 해제만
    for row in _container_rows(db, service_id):
        row.service_id = None
        row.component_name = None
        row.management_state = "unmanaged"
    record_audit(db, actor, "service.delete", target=service_id,
                 detail={"runtime_unchanged": True})
    db.delete(svc)
    db.commit()
    return {"deleted": service_id, "runtime_unchanged": True,
            "note": "컨테이너/볼륨/이미지는 변경되지 않았습니다"}


@router.get("/{service_id}/containers")
def service_containers(service_id: str, db: Session = Depends(get_db)):
    _service_or_404(db, service_id)
    rows = _container_rows(db, service_id)
    return {"items": [{"container_id": r.container_id, "name": r.name, "image": r.image,
                       "state": r.state, "status_text": r.status_text,
                       "management_state": r.management_state,
                       "component": r.component_name, "health": r.health,
                       "restart_count": r.restart_count, "ports": r.ports}
                      for r in rows]}


@router.get("/{service_id}/endpoints")
def service_endpoints(service_id: str, db: Session = Depends(get_db)):
    svc = _service_or_404(db, service_id)
    return {"items": [{"name": e.name, "type": e.type, "exposure": e.exposure,
                       "hostname": e.hostname, "host_port": e.host_port,
                       "container": e.container, "container_port": e.container_port}
                      for e in svc.endpoints]}


@router.get("/{service_id}/logs")
def service_logs(service_id: str, tail: int = 200, db: Session = Depends(get_db)):
    """서비스 소속 컨테이너 로그. Docker 게이트웨이를 통해서만 접근 (임의 셸 없음)."""
    from ..dependencies import get_gateway
    _service_or_404(db, service_id)
    gateway = get_gateway()
    lines: list[str] = []
    for row in _container_rows(db, service_id):
        text = gateway.container_logs(row.container_id, tail=tail)
        if text:
            for line in text.splitlines():
                lines.append(f"[{row.name}] {line}")
    return {"lines": lines[-tail:], "truncated": len(lines) > tail}


@router.get("/{service_id}/events")
def service_events(service_id: str, limit: int = 50, db: Session = Depends(get_db)):
    from ..models import Event
    _service_or_404(db, service_id)
    rows = list(db.execute(select(Event).where(Event.service_id == service_id)
                           .order_by(Event.id.desc()).limit(limit)).scalars())
    return {"items": [{"id": e.id, "ts": e.ts, "severity": e.severity, "kind": e.kind,
                       "message": e.message} for e in rows]}
