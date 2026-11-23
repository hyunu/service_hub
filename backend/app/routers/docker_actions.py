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
from ..services.protection import HUB_IMAGE_PREFIX, protection_reason

router = APIRouter(tags=["docker-actions"], dependencies=[Depends(require_auth)])

class RemoveRequest(BaseModel):
    confirm: str = Field(min_length=1, max_length=256)


# 일괄 정리의 확인 문구. 자동 전체 삭제를 막기 위해 명시 입력을 요구한다.
CLEANUP_CONFIRM = "cleanup"


class CleanupRequest(BaseModel):
    """미사용 정리 요청.

    ``container_ids`` 는 **사용자가 명시적으로 선택한 대상만** 받는다.
    (서버가 "전체 미사용"을 스스로 골라 지우는 경로는 없다.)
    """
    container_ids: list[str] = Field(default_factory=list, max_length=200)
    confirm: str = Field(min_length=1, max_length=64)
    remove_dangling_images: bool = True


def _require_enabled():
    settings = get_settings()
    if not settings.enable_docker_actions:
        raise HubError(
            status_code=503,
            detail="Docker 조작 기능이 비활성화되어 있습니다 "
                   "(HUB_ENABLE_DOCKER_ACTIONS=false)",
            code="docker_actions_disabled")
    return settings


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


def _image_in_use(image: dict, containers: list) -> str | None:
    """dangling 이미지가 어떤 컨테이너에도 쓰이지 않는지 확인한다.

    컨테이너의 ``image`` 값은 생성 시 참조(태그 또는 ID)이므로 둘 다 비교한다.
    """
    iid = str(image.get("id") or "")
    short = iid.replace("sha256:", "")[:12]
    tags = [str(t) for t in (image.get("tags") or [])]
    for c in containers:
        ref = str(c.image or "")
        if ref in tags or ref == iid:
            return c.name
        if short and ref.replace("sha256:", "").startswith(short):
            return c.name
    return None


def _guard(db: Session, container_id: str) -> tuple:
    settings = _require_enabled()
    row = _target(db, container_id)
    reason = protection_reason(row, settings)
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


@router.post("/containers/cleanup")
def cleanup_unused_containers(body: CleanupRequest, db: Session = Depends(get_db),
                              actor: str = Depends(get_read_actor)):
    """중지된 **미관리** 컨테이너와 dangling 이미지를 한 번에 정리한다.

    안전 규칙 (AGENTS.md 규칙 #1, #7):
      - ``HUB_ENABLE_DOCKER_ACTIONS=false`` 면 503.
      - 실행 중 / 허브 자신 / 보호 대상 / 서비스에 연결된 컨테이너는 건너뛴다
        (결과의 ``skipped`` 에 사유를 남긴다 — 조용히 무시하지 않는다).
      - ``container_ids`` 는 명시적 선택만 받는다. 서버가 임의로 전체를 고르지 않는다.
      - 이미지는 **태그가 없고(dangling) 어떤 컨테이너도 쓰지 않는** 것만 제거한다.
        볼륨/네트워크는 건드리지 않는다.
      - 모든 제거는 감사 로그에 기록한다.
    """
    from ..dependencies import get_gateway

    settings = _require_enabled()
    if body.confirm != CLEANUP_CONFIRM:
        raise HubError(status_code=422,
                       detail=f"확인 문구가 일치하지 않습니다 ('{CLEANUP_CONFIRM}' 입력)",
                       code="confirm_mismatch")
    if not body.container_ids and not body.remove_dangling_images:
        raise HubError(status_code=422, detail="정리할 대상을 지정하세요",
                       code="nothing_to_clean")

    gateway = get_gateway()
    live = {s.container_id: s for s in (gateway.list_containers() or [])}
    removed: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()

    for ref in body.container_ids:
        if ref in seen:
            continue
        seen.add(ref)
        row = resolve_container(db, ref)
        if row is None:
            skipped.append({"container_id": ref, "name": None,
                            "reason": "컨테이너를 찾을 수 없습니다",
                            "code": "container_not_found"})
            continue
        base = {"container_id": row.container_id, "name": row.name,
                "image": row.image}
        reason = protection_reason(row, settings)
        if reason:
            skipped.append({**base, "reason": reason, "code": "protected_container"})
            continue
        if row.management_state != "unmanaged":
            skipped.append({**base,
                            "reason": "서비스에 연결된 컨테이너는 일괄 정리 대상이 아닙니다",
                            "code": "container_managed"})
            continue
        snap = live.get(row.container_id)
        if snap is None:
            skipped.append({**base, "reason": "Docker에서 컨테이너를 찾을 수 없습니다",
                            "code": "container_missing"})
            continue
        if snap.state == "running":
            skipped.append({**base, "reason": "실행 중인 컨테이너는 제거할 수 없습니다. 먼저 중지하세요.",
                            "code": "container_running"})
            continue
        res = gateway.container_remove(row.container_id)
        if not res.get("ok"):
            skipped.append({**base,
                            "reason": f"제거에 실패했습니다: {res.get('error') or '알 수 없는 오류'}",
                            "code": "docker_action_failed"})
            continue
        assignment = db.get(ContainerAssignment, row.container_id)
        if assignment is not None:
            db.delete(assignment)
        cid, name = row.container_id, row.name
        db.delete(row)
        record_audit(db, actor, "container.remove", target=cid,
                     detail={"name": name, "image": base["image"], "bulk": True})
        removed.append({"container_id": cid, "name": name, "image": base["image"]})

    images_removed: list[dict] = []
    images_skipped: list[dict] = []
    freed_mb = 0.0
    if body.remove_dangling_images:
        # 컨테이너 제거 후의 상태를 기준으로 사용 여부를 다시 판단한다.
        containers = gateway.list_containers() or []
        for img in gateway.list_images():
            iid = str(img.get("id") or "")
            tags = [str(t) for t in (img.get("tags") or [])]
            if tags:
                continue  # dangling(태그 없음)만 대상 — 태그 이미지는 개별 제거로만
            user = _image_in_use(img, containers)
            if user:
                images_skipped.append({"image_id": iid,
                                       "reason": f"사용 중인 컨테이너가 있습니다: {user}"})
                continue
            res = gateway.image_remove(iid)
            if not res.get("ok"):
                images_skipped.append({
                    "image_id": iid,
                    "reason": f"제거에 실패했습니다: {res.get('error') or '알 수 없는 오류'}"})
                continue
            size = img.get("size_mb") or 0
            freed_mb += float(size or 0)
            record_audit(db, actor, "image.remove", target=iid,
                         detail={"dangling": True, "size_mb": size})
            images_removed.append({"image_id": iid, "size_mb": size})

    if removed or images_removed:
        record_audit(db, actor, "cleanup.run", target=None,
                     detail={"removed": [r["container_id"] for r in removed],
                             "skipped": len(skipped),
                             "images_removed": [i["image_id"] for i in images_removed],
                             "freed_image_mb": round(freed_mb, 1)})
        db.commit()

    return {"ok": True, "removed": removed, "skipped": skipped,
            "images_removed": images_removed, "images_skipped": images_skipped,
            "freed_image_mb": round(freed_mb, 1),
            "runtime_changed": bool(removed or images_removed)}


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
