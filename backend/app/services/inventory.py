"""컨테이너 인벤토리 동기화 및 관리 상태 판정 (docs/ARCHITECTURE.md §5, REQUIREMENTS §8).

관리 상태 판정 규칙:
  managed   — 서비스 컴포넌트와 매칭되는 컨테이너 (compose 서비스명 또는 컨테이너 이름)
  stopped   — managed인데 실행 중이 아님
  mismatch  — 매칭은 되지만 기록된 서비스 소속과 다름(다른 서비스에 이미 매칭됨) 등 불일치
  unmanaged — 어떤 서비스 컴포넌트에도 매칭되지 않음 (hub 자체 제외)
  missing   — 등록된 필수 컴포넌트에 대응 컨테이너가 없음 (서비스 판정용)
  unknown   — Docker 연결 불가로 판정 불가 (정상으로 취급하지 않음)
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..docker_client import ContainerSnapshot, DockerGateway
from ..models import Container, Service, ServiceComponent
from .events import record_event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def match_component(components: list[ServiceComponent],
                    snap: ContainerSnapshot) -> ServiceComponent | None:
    """컨테이너 스냅샷에 대응하는 컴포넌트를 찾는다.

    우선순위: compose 서비스명 → 컨테이너 이름 → 이름-하위문자열(정확히 1개인 경우만).
    모호하면(None 반환) unmanaged로 분류해 잘못된 연결을 방지한다.
    """
    cs = _norm(snap.compose_service)
    if cs:
        for comp in components:
            if _norm(comp.name) == cs:
                return comp
    name = _norm(snap.name)
    for comp in components:
        if _norm(comp.name) == name:
            return comp
    partial = [c for c in components if _norm(c.name) in name or name in _norm(c.name)]
    return partial[0] if len(partial) == 1 else None


def sync_inventory(db: Session, gateway: DockerGateway) -> dict:
    """Docker 스냅샷을 containers 테이블에 동기화하고 판정을 기록한다.

    Docker 불가 시에도 컨테이너 행을 삭제하지 않는다 — 기존 정보를 보존하고
    management_state=unknown으로 표시한다.
    """
    services = list(db.execute(select(Service)).scalars())
    comp_map = {s.id: list(s.components) for s in services}

    snaps = gateway.list_containers()
    if snaps is None:
        for row in db.execute(select(Container)).scalars():
            row.management_state = "unknown"
            row.observed_at = _now()
        db.flush()
        return {"docker_available": False, "total": None, "unmanaged": None}

    now = _now()
    matched: dict[str, tuple[str, str]] = {}   # container_id -> (service_id, component)
    result = {"docker_available": True, "total": len(snaps), "unmanaged": 0}

    for snap in snaps:
        row = db.get(Container, snap.container_id)
        if row is None:
            row = Container(container_id=snap.container_id)
            db.add(row)
        row.name = snap.name
        row.image = snap.image
        row.state = snap.state
        row.status_text = snap.status_text
        row.health = snap.health
        row.restart_count = snap.restart_count
        row.compose_project = snap.compose_project
        row.compose_service = snap.compose_service
        row.ports = snap.ports
        row.networks = snap.networks
        row.mounts = snap.mounts
        row.labels = snap.labels
        row.container_created_at = snap.container_created_at
        row.started_at = snap.started_at
        row.observed_at = now

        if snap.is_hub_self:
            # 관리 시스템 자기 자신은 서비스 레지스트리 대상이 아니다.
            row.management_state = "managed"
            row.service_id = None
            row.component_name = "hub-self"
            continue

        component = None
        service = None
        for svc in services:
            comp = match_component(comp_map.get(svc.id, []), snap)
            if comp is not None:
                service, component = svc, comp
                break

        if service is None:
            row.management_state = "unmanaged"
            row.service_id = None
            row.component_name = None
            result["unmanaged"] += 1
            continue

        existing_owner = matched.get(snap.container_id)
        if existing_owner and existing_owner[0] != service.id:
            row.management_state = "mismatch"
            record_event(
                db, "container_mismatch",
                f"컨테이너 {snap.name}가 여러 서비스와 매칭되었습니다: "
                f"{existing_owner[0]}, {service.id}",
                severity="warning", service_id=service.id, container_id=snap.container_id)
        else:
            matched[snap.container_id] = (service.id, component.name)
            row.management_state = "managed" if snap.state == "running" else "stopped"

        row.service_id = service.id
        row.component_name = component.name

    # 서비스 차원 판정: 등록 정보와 실제 상태 비교 (missing/stopped 반영)
    for svc in services:
        rows = list(db.execute(select(Container).where(Container.service_id == svc.id)).scalars())
        svc.status = compute_service_status(svc, rows)
        svc.last_healthcheck_at = now

    db.flush()
    return result


def compute_service_status(svc: Service, rows: list[Container]) -> str:
    comps = svc.components
    if not comps:
        return "registered"
    running = {r.component_name for r in rows
               if r.management_state == "managed" and r.state == "running"}
    required = {c.name for c in comps if c.required}
    present = {r.component_name for r in rows}
    if required and required.issubset(running):
        return "healthy"
    if running:
        return "warning"
    if present & {c.name for c in comps}:
        return "stopped"
    return "missing"


def orphan_list(db: Session) -> list[dict]:
    """미관리 컨테이너 목록 + 추정 서비스/사유."""
    services = list(db.execute(select(Service)).scalars())
    rows = list(db.execute(select(Container).where(
        Container.management_state.in_(["unmanaged", "unknown"]))).scalars())
    out = []
    for row in rows:
        guessed = guess_service(services, row)
        out.append({
            "container_id": row.container_id,
            "container_id_short": row.container_id[:12],
            "name": row.name,
            "image": row.image,
            "state": row.state,
            "status_text": row.status_text,
            "ports": [f"{p.get('host_port')}->{p.get('container_port')}/{p.get('proto')}"
                      if p.get("host_port") else f"{p.get('container_port')}/{p.get('proto')} (내부)"
                      for p in row.ports or []],
            "networks": row.networks,
            "mounts": [m.get("source") for m in row.mounts or [] if m.get("source")],
            "compose_project": row.compose_project,
            "created_at": row.container_created_at,
            "guessed_service": guessed,
            "reason": ("Docker 연결 불가로 확인할 수 없음" if row.management_state == "unknown"
                       else "서비스 등록 정보와 매칭되는 컴포넌트 없음"),
            "management_state": row.management_state,
        })
    return out


def guess_service(services: list[Service], row: Container) -> str | None:
    """compose 프로젝트/컨테이너 이름과 서비스 ID 유사도로 힌트만 제시한다."""
    candidates = {row.compose_project, row.name}
    for svc in services:
        for cand in candidates:
            if not cand:
                continue
            c = _norm(cand).replace("_", "-")
            if _norm(svc.id) in c or c in _norm(svc.id) or _norm(svc.name) in c:
                return svc.id
    return None
