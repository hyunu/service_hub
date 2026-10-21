"""컨테이너/미관리 라우터 (REQUIREMENTS §8). 읽기 전용 + DB 연결(attach)만 허용."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Container, ContainerAssignment, Service
from ..security import HubError, get_read_actor, require_auth
from ..services.events import record_audit, record_event
from ..services.grouping import (attach_one, bulk_attach, detach_one,
                                 resolve_container)
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
    manual_ids = {a.container_id
                  for a in db.execute(select(ContainerAssignment)).scalars()}
    return {"items": [_dict(r, manual=r.container_id in manual_ids) for r in rows],
            "count": len(rows)}


@router.get("/containers/{container_id}")
def get_container(container_id: str, db: Session = Depends(get_db)):
    row = resolve_container(db, container_id)
    if row is None:
        raise HubError(status_code=404, detail="컨테이너를 찾을 수 없습니다",
                            code="container_not_found")
    manual = db.get(ContainerAssignment, row.container_id) is not None
    return _dict(row, detail=True, manual=manual)


@router.get("/orphans")
def list_orphans(db: Session = Depends(get_db)):
    return {"items": orphan_list(db)}


class AttachRequest(BaseModel):
    service_id: str
    component_name: str


class BulkAttachRequest(BaseModel):
    service_id: str
    container_ids: list[str] = Field(min_length=1, max_length=200)
    # 지정하면 선택한 컨테이너를 모두 이 컴포넌트 하나로 묶는다.
    # 비우면 각 컨테이너의 compose 서비스명(없으면 컨테이너 이름)을 쓴다.
    component_name: str | None = Field(default=None, max_length=120)


class ReviewRequest(BaseModel):
    review_state: str   # reviewed | ignored | pending


@router.post("/orphans/attach")
def attach_orphans(body: BulkAttachRequest, db: Session = Depends(get_db),
                   actor: str = Depends(get_read_actor)):
    """여러 미관리 컨테이너를 한 서비스로 **수동 그룹핑**한다.

    - 명시적 연결(container_assignments)을 남기므로 주기 동기화에서도 유지된다.
    - 이미 다른 서비스에 연결된 컨테이너는 덮어쓰지 않고 건너뛴다(결과에 사유 포함).
    - 안전: DB 레코드 연결만 수행하며 컨테이너를 재생성/재시작하지 않는다.
    """
    svc = db.get(Service, body.service_id)
    if svc is None:
        raise HubError(status_code=404, detail=f"서비스 '{body.service_id}'를 찾을 수 없습니다",
                            code="service_not_found")
    result = bulk_attach(db, svc, body.container_ids, body.component_name, actor)
    if result["attached"]:
        record_event(db, "containers_grouped",
                     f"컨테이너 {result['attached']}개를 서비스 {svc.id}에 그룹핑",
                     service_id=svc.id,
                     detail={"attached": result["attached"],
                             "skipped": result["skipped"]})
    db.commit()
    return {**result, "runtime_unchanged": True,
            "note": "컨테이너는 재생성되지 않았습니다 (DB 연결만 수행)"}


@router.post("/orphans/{container_id}/attach")
def attach_orphan(container_id: str, body: AttachRequest, db: Session = Depends(get_db),
                  actor: str = Depends(get_read_actor)):
    """미관리 컨테이너 1개를 서비스 컴포넌트에 연결한다 (일괄 연결의 단일 버전).

    안전: DB 레코드 연결만 수행한다. 컨테이너를 재생성/재시작하지 않는다.
    """
    row = resolve_container(db, container_id)
    if row is None:
        raise HubError(status_code=404, detail="컨테이너를 찾을 수 없습니다",
                            code="container_not_found")
    svc = db.get(Service, body.service_id)
    if svc is None:
        raise HubError(status_code=404, detail=f"서비스 '{body.service_id}'를 찾을 수 없습니다",
                            code="service_not_found")
    result = attach_one(db, svc, row, body.component_name, actor)
    record_event(db, "orphan_attached",
                 f"컨테이너 {row.name}이(가) 서비스 {svc.id}/{body.component_name}에 연결됨",
                 service_id=svc.id, container_id=row.container_id)
    db.commit()
    return {"attached": True, "container_id": row.container_id,
            "service_id": svc.id, "component": body.component_name,
            "runtime_unchanged": True,
            "note": "컨테이너는 재생성되지 않았습니다 (DB 연결만 수행)",
            "result": result}


@router.post("/containers/{container_id}/detach")
def detach_container(container_id: str, db: Session = Depends(get_db),
                     actor: str = Depends(get_read_actor)):
    """수동 그룹핑을 해제한다 (DB 연결만 제거, 컨테이너는 그대로).

    이름이 선언된 컴포넌트와 일치하는 컨테이너는 다음 동기화에서 자동 연결될 수 있다.
    """
    row = resolve_container(db, container_id)
    if row is None:
        raise HubError(status_code=404, detail="컨테이너를 찾을 수 없습니다",
                            code="container_not_found")
    result = detach_one(db, row, actor)
    db.commit()
    return {**result, "runtime_unchanged": True,
            "note": "자동 매칭되는 컨테이너는 다음 동기화에서 다시 연결될 수 있습니다"}


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


def _dict(row: Container, detail: bool = False, manual: bool = False) -> dict:
    base = {
        "container_id": row.container_id,
        "container_id_short": row.container_id[:12],
        "name": row.name, "image": row.image, "state": row.state,
        "status_text": row.status_text, "management_state": row.management_state,
        "service_id": row.service_id, "component": row.component_name,
        "manual": manual,
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
