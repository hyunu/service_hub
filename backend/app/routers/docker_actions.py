"""컨테이너/이미지 조작 라우터 — 시작/정지/제거 (REQUIREMENTS §8, §13.4).

안전 원칙 (AGENTS.md 규칙 #1, #3, #7):
  - **기본 잠금**: ``HUB_ENABLE_DOCKER_ACTIONS=false``면 모든 조작이 503.
  - 허브 자신(``com.hub.self`` 라벨 또는 ``service-hub`` 프로젝트)은 절대 조작하지 않는다.
  - ``HUB_PROTECTED_CONTAINERS`` / ``HUB_PROTECTED_PROJECTS``(콤마 구분)로 보호 대상을 지정한다.
  - 제거는 **실행 중이면 거부**(먼저 중지)하고, 정확한 이름 입력(confirm)을 요구한다.
  - 사용 중인 이미지와 허브 이미지(``n100-service-hub-*``)는 제거할 수 없다.
  - 모든 조작은 감사 로그에 기록한다. 임의 셸/임의 명령 파라미터는 받지 않는다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Container, ContainerAssignment
from ..security import HubError, get_read_actor, require_auth
from ..services.events import record_audit
from ..services.grouping import resolve_container

router = APIRouter(tags=["docker-actions"], dependencies=[Depends(require_auth)])

HUB_SELF_PROJECT = "service-hub"
HUB_IMAGE_PREFIX = "n100-service-hub-"


class RemoveRequest(BaseModel):
    confirm: str = Field(min_length=1, max_length=256)


def _require_enabled():
    settings = get_settings()
    if not settings.enable_docker_actions:
        raise HubError(
            status_code=503,
            detail="Docker 조작 기능이 비활성화되어 있습니다 "
                   "(HUB_ENABLE_DOCKER_ACTIONS=false)",
            code="docker_actions_disabled")
    return settings


def _patterns(value: str) -> list[str]:
    return [p.strip().lower() for p in (value or "").split(",") if p.strip()]


def _protection_reason(row: Container, settings) -> str | None:
    labels = row.labels or {}
    if row.component_name == "hub-self" or str(labels.get("com.hub.self")).lower() == "true" \
            or (row.compose_project or "") == HUB_SELF_PROJECT:
        return "허브 자신의 컨테이너는 조작할 수 없습니다"
    name = (row.name or "").lower()
    for pat in _patterns(settings.protected_containers):
        if name == pat or name.startswith(pat):
            return f"보호된 컨테이너입니다 (HUB_PROTECTED_CONTAINERS: {pat})"
    project = (row.compose_project or "").lower()
    for pat in _patterns(settings.protected_projects):
        if project == pat:
            return f"보호된 compose 프로젝트입니다 (HUB_PROTECTED_PROJECTS: {pat})"
    return None


def _target(db: Session, container_id: str) -> Container:
    row = resolve_container(db, container_id)
    if row is None:
        raise HubError(status_code=404, detail="컨테이너를 찾을 수 없습니다",
                       code="container_not_found")
    return row


def _live_state(container_id: str) -> str | None:
    """게이트웨이 기준 실제 상태 (DB는 최대 monitor_interval 만큼 지연될 수 있다)."""
    from ..dependencies import get_gateway
    for snap in get_gateway().list_containers() or []:
        if snap.container_id == container_id:
            return snap.state
    return None


def _guard(db: Session, container_id: str) -> tuple:
    settings = _require_enabled()
    row = _target(db, container_id)
    reason = _protection_reason(row, settings)
    if reason:
        raise HubError(status_code=403, detail=reason, code="protected_container")
    return settings, row


@router.get("/images")
def list_images():
    """이미지 목록 (읽기 전용). 조작 게이트와 무관하게 조회만 허용한다."""
    from ..dependencies import get_gateway
    return {"items": get_gateway().list_images(),
            "actions_enabled": get_settings().enable_docker_actions}


@router.post("/containers/{container_id}/start")
def start_container(container_id: str, db: Session = Depends(get_db),
                    actor: str = Depends(get_read_actor)):
    from ..dependencies import get_gateway
    _settings, row = _guard(db, container_id)
    res = get_gateway().container_start(row.container_id)
    if not res.get("ok"):
        raise HubError(status_code=409,
                       detail=f"시작에 실패했습니다: {res.get('error') or '알 수 없는 오류'}",
                       code="docker_action_failed")
    row.state = "running"
    row.status_text = "Up (started via hub)"
    record_audit(db, actor, "container.start", target=row.container_id,
                 detail={"name": row.name})
    db.commit()
    return {"ok": True, "container_id": row.container_id, "action": "start",
            "runtime_changed": True}


@router.post("/containers/{container_id}/stop")
def stop_container(container_id: str, db: Session = Depends(get_db),
                   actor: str = Depends(get_read_actor)):
    from ..dependencies import get_gateway
    _settings, row = _guard(db, container_id)
    res = get_gateway().container_stop(row.container_id)
    if not res.get("ok"):
        raise HubError(status_code=409,
                       detail=f"정지에 실패했습니다: {res.get('error') or '알 수 없는 오류'}",
                       code="docker_action_failed")
    row.state = "exited"
    row.status_text = "Exited (stopped via hub)"
    if row.management_state == "managed":
        row.management_state = "stopped"
    record_audit(db, actor, "container.stop", target=row.container_id,
                 detail={"name": row.name})
    db.commit()
    return {"ok": True, "container_id": row.container_id, "action": "stop",
            "runtime_changed": True}


@router.post("/containers/{container_id}/remove")
def remove_container(container_id: str, body: RemoveRequest,
                     db: Session = Depends(get_db),
                     actor: str = Depends(get_read_actor)):
    """중지된 컨테이너를 제거한다. 실행 중이면 거부(먼저 중지).

    정확한 컨테이너 이름을 confirm으로 요구한다. DB 인벤토리 행과 수동 그룹핑도 함께 정리한다.
    """
    from ..dependencies import get_gateway
    _settings, row = _guard(db, container_id)
    state = _live_state(row.container_id) or row.state
    if state == "running":
        raise HubError(status_code=409,
                       detail="실행 중인 컨테이너는 제거할 수 없습니다. 먼저 중지하세요.",
                       code="container_running")
    if body.confirm != row.name:
        raise HubError(status_code=422,
                       detail=f"확인 이름이 일치하지 않습니다 (정확히 '{row.name}' 입력)",
                       code="confirm_mismatch")
    res = get_gateway().container_remove(row.container_id)
    if not res.get("ok"):
        raise HubError(status_code=409,
                       detail=f"제거에 실패했습니다: {res.get('error') or '알 수 없는 오류'}",
                       code="docker_action_failed")

    assignment = db.get(ContainerAssignment, row.container_id)
    if assignment is not None:
        db.delete(assignment)
    name = row.name
    db.delete(row)
    record_audit(db, actor, "container.remove", target=container_id,
                 detail={"name": name, "runtime_changed": True})
    db.commit()
    return {"ok": True, "container_id": container_id, "action": "remove",
            "runtime_changed": True}


@router.post("/images/{image_id}/remove")
def remove_image(image_id: str, body: RemoveRequest, db: Session = Depends(get_db),
                 actor: str = Depends(get_read_actor)):
    """사용 중이 아닌 이미지를 제거한다. 허브 이미지는 보호된다."""
    from ..dependencies import get_gateway
    _require_enabled()
    gateway = get_gateway()
    images = gateway.list_images()
    image = next((i for i in images
                  if i.get("id") == image_id or str(i.get("id", "")).startswith(image_id)
                  or image_id in (i.get("tags") or [])), None)
    if image is None:
        raise HubError(status_code=404, detail="이미지를 찾을 수 없습니다",
                       code="image_not_found")

    tags = image.get("tags") or []
    if any(str(t).startswith(HUB_IMAGE_PREFIX) for t in tags):
        raise HubError(status_code=403, detail="허브 이미지는 제거할 수 없습니다",
                       code="protected_image")

    users = [s.name for s in (gateway.list_containers() or [])
             if s.image in tags or s.image == image_id]
    if users:
        raise HubError(status_code=409,
                       detail=f"사용 중인 이미지입니다: {', '.join(users[:3])}",
                       code="image_in_use")

    expected = tags[0] if tags else str(image.get("id"))[:12]
    if body.confirm not in {expected, str(image.get("id")),
                            str(image.get("id"))[:12], str(image.get("id"))[7:19]}:
        raise HubError(status_code=422,
                       detail=f"확인 값이 일치하지 않습니다 (예: {expected})",
                       code="confirm_mismatch")

    res = gateway.image_remove(str(image.get("id")))
    if not res.get("ok"):
        raise HubError(status_code=409,
                       detail=f"이미지 제거에 실패했습니다: {res.get('error') or '알 수 없는 오류'}",
                       code="docker_action_failed")
    record_audit(db, actor, "image.remove", target=str(image.get("id")),
                 detail={"tags": tags, "size_mb": image.get("size_mb")})
    db.commit()
    return {"ok": True, "image_id": image.get("id"), "action": "remove",
            "runtime_changed": True}
