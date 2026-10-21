"""컨테이너/미관리 라우터 (REQUIREMENTS §8). 읽기 전용 + DB 연결(attach)만 허용."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Container, Service, ServiceComponent
from ..security import HubError, get_read_actor, require_auth
from ..services.events import record_audit, record_event
from ..services.inventory import orphan_list

router = APIRouter(tags=["containers"], dependencies=[Depends(require_auth)])


@router.get("/containers")
def list_containers(state: str = "all", management: str | None = None,
                    db: Session = Depends(get_db)):
    rows = list(db.execute(select(Container)).scalars())
    if state == "running":
        rows = [r for r in rows if r.state == "running"]
    elif state == "stopped":
        rows = [r for r in rows if r.state != "running"]
    if management:
        rows = [r for r in rows if r.management_state == management]
    return {"items": [_dict(r) for r in rows], "count": len(rows)}


@router.get("/containers/{container_id}")
def get_container(container_id: str, db: Session = Depends(get_db)):
    row = db.get(Container, container_id) or _by_prefix(db, container_id)
    if row is None:
        raise HubError(status_code=404, detail="컨테이너를 찾을 수 없습니다",
                            code="container_not_found")
    return _dict(row, detail=True)


@router.get("/orphans")
def list_orphans(db: Session = Depends(get_db)):
    return {"items": orphan_list(db)}


class AttachRequest(BaseModel):
    service_id: str
    component_name: str


class ReviewRequest(BaseModel):
    review_state: str   # reviewed | ignored | pending


@router.post("/orphans/{container_id}/attach")
def attach_orphan(container_id: str, body: AttachRequest, db: Session = Depends(get_db),
                  actor: str = Depends(get_read_actor)):
    """미관리 컨테이너를 서비스 컴포넌트에 연결한다.

    안전: DB 레코드 연결만 수행한다. 컨테이너를 재생성/재시작하지 않는다.
    """
    row = db.get(Container, container_id)
    if row is None:
        raise HubError(status_code=404, detail="컨테이너를 찾을 수 없습니다",
                            code="container_not_found")
    svc = db.get(Service, body.service_id)
    if svc is None:
        raise HubError(status_code=404, detail=f"서비스 '{body.service_id}'를 찾을 수 없습니다",
                            code="service_not_found")
    comp = db.execute(select(ServiceComponent).where(
        ServiceComponent.service_id == body.service_id,
        ServiceComponent.name == body.component_name)).scalar_one_or_none()
    if comp is None:
        comp = ServiceComponent(service_id=body.service_id, name=body.component_name,
                                role="other", required=False,
                                description="미관리 컨테이너 연결로 생성됨")
        db.add(comp)
    previous_owner = row.service_id
    row.service_id = body.service_id
    row.component_name = body.component_name
    row.management_state = "managed" if row.state == "running" else "stopped"
    record_audit(db, actor, "orphan.attach", target=container_id,
                 detail={"service_id": body.service_id, "component": body.component_name,
                         "previous_owner": previous_owner,
                         "container_recreated": False})
    record_event(db, "orphan_attached",
                 f"컨테이너 {row.name}이(가) 서비스 {body.service_id}/{body.component_name}에 연결됨",
                 service_id=body.service_id, container_id=container_id)
    db.commit()
    return {"attached": True, "container_id": container_id,
            "service_id": body.service_id, "component": body.component_name,
            "runtime_unchanged": True,
            "note": "컨테이너는 재생성되지 않았습니다 (DB 연결만 수행)"}


@router.post("/orphans/{container_id}/review")
def review_orphan(container_id: str, body: ReviewRequest, db: Session = Depends(get_db),
                  actor: str = Depends(get_read_actor)):
    if body.review_state not in ("reviewed", "ignored", "pending"):
        raise HubError(status_code=422, detail="review_state가 올바르지 않습니다",
                            code="invalid_review_state")
    row = db.get(Container, container_id)
    if row is None:
        raise HubError(status_code=404, detail="컨테이너를 찾을 수 없습니다",
                            code="container_not_found")
    labels = dict(row.labels or {})
    labels["hub.review_state"] = body.review_state
    row.labels = labels
    record_audit(db, actor, "orphan.review", target=container_id,
                 detail={"review_state": body.review_state})
    db.commit()
    return {"ok": True, "container_id": container_id, "review_state": body.review_state}


def _by_prefix(db: Session, prefix: str) -> Container | None:
    rows = list(db.execute(select(Container).where(
        Container.container_id.like(f"{prefix}%"))).scalars())
    return rows[0] if len(rows) == 1 else None


def _dict(row: Container, detail: bool = False) -> dict:
    base = {
        "container_id": row.container_id,
        "container_id_short": row.container_id[:12],
        "name": row.name, "image": row.image, "state": row.state,
        "status_text": row.status_text, "management_state": row.management_state,
        "service_id": row.service_id, "component": row.component_name,
        "compose_project": row.compose_project, "compose_service": row.compose_service,
        "ports": row.ports, "health": row.health, "restart_count": row.restart_count,
        "observed_at": row.observed_at,
    }
    if detail:
        from ..dependencies import get_gateway
        stats = get_gateway().stats(row.container_id)
        base.update({
            "networks": row.networks, "mounts": row.mounts, "labels": row.labels,
            "created_at": row.container_created_at, "started_at": row.started_at,
            "stats": stats,
        })
    return base
