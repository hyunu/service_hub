"""수동 그룹핑 — 컨테이너를 서비스 컴포넌트에 명시적으로 연결한다.

원칙:
  - **DB 연결만** 수행한다. 컨테이너를 재생성/재시작/중지하지 않는다.
  - 연결은 ``container_assignments``에 남겨 주기 동기화(sync_inventory)에서도 유지된다.
  - 이미 다른 서비스에 연결된 컨테이너는 덮어쓰지 않는다(건너뛰고 사유 반환).
  - hub 자기 자신(component_name=hub-self)은 그룹핑 대상이 아니다.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Container, ContainerAssignment, Service, ServiceComponent
from .events import record_audit

# 수동 그룹핑이 자동 생성한 컴포넌트임을 표시(해제 시 함께 정리하기 위함).
GROUPING_COMPONENT_NOTE = "수동 그룹핑으로 생성됨"


def component_name_for(row: Container) -> str:
    """기본 컴포넌트 이름 — compose 서비스명 우선, 없으면 컨테이너 이름."""
    name = (row.compose_service or "").strip() or (row.name or "").strip()
    return (name or row.container_id[:12])[:120]


def attach_one(db: Session, svc: Service, row: Container, component_name: str,
               actor: str) -> dict:
    """컨테이너 1개를 서비스 컴포넌트에 연결하고 감사 로그를 남긴다(커밋은 호출자)."""
    component_name = (component_name or "").strip()[:120] or component_name_for(row)
    comp = db.execute(select(ServiceComponent).where(
        ServiceComponent.service_id == svc.id,
        ServiceComponent.name == component_name)).scalar_one_or_none()
    if comp is None:
        # 필수(required=False)로 만들지 않는다 — 그룹핑한 컨테이너가 사라져도
        # 서비스 자체가 "missing"으로 판정되지 않게 한다.
        db.add(ServiceComponent(service_id=svc.id, name=component_name, role="other",
                                required=False,
                                description=GROUPING_COMPONENT_NOTE))
    assignment = db.get(ContainerAssignment, row.container_id)
    if assignment is None:
        db.add(ContainerAssignment(container_id=row.container_id, service_id=svc.id,
                                   component_name=component_name, created_by=actor))
    else:
        assignment.service_id = svc.id
        assignment.component_name = component_name
    previous_owner = row.service_id
    row.service_id = svc.id
    row.component_name = component_name
    row.management_state = "managed" if row.state == "running" else "stopped"
    record_audit(db, actor, "container.attach_manual", target=row.container_id,
                 detail={"service_id": svc.id, "component": component_name,
                         "previous_owner": previous_owner,
                         "container_recreated": False})
    return {"container_id": row.container_id, "name": row.name, "ok": True,
            "service_id": svc.id, "component": component_name}


def detach_one(db: Session, row: Container, actor: str) -> dict:
    """명시적 연결을 제거한다(커밋은 호출자). 컨테이너 런타임은 건드리지 않는다."""
    assignment = db.get(ContainerAssignment, row.container_id)
    previous = row.service_id
    if assignment is None and not previous:
        return {"detached": False, "container_id": row.container_id,
                "reason": "연결된 서비스가 없습니다"}
    if assignment is not None:
        previous_service = assignment.service_id
        previous_component = assignment.component_name
        db.delete(assignment)
        # 자동 생성 컴포넌트는 더 이상 참조가 없으면 함께 제거한다.
        # 남겨두면 다음 sync에서 이름 자동매칭으로 다시 연결되어 해제가 무효가 된다.
        comp = db.execute(select(ServiceComponent).where(
            ServiceComponent.service_id == previous_service,
            ServiceComponent.name == previous_component)).scalar_one_or_none()
        if comp is not None and comp.description == GROUPING_COMPONENT_NOTE:
            db.flush()   # 위 delete를 반영한 뒤 참조 여부 확인
            still_used = db.execute(select(ContainerAssignment).where(
                ContainerAssignment.service_id == previous_service,
                ContainerAssignment.component_name == previous_component)).first()
            if still_used is None:
                db.delete(comp)
    row.service_id = None
    row.component_name = None
    row.management_state = "unmanaged"
    record_audit(db, actor, "container.detach", target=row.container_id,
                 detail={"previous_service": previous})
    return {"detached": True, "container_id": row.container_id,
            "previous_service": previous}


def resolve_container(db: Session, ref: str) -> Container | None:
    """전체 ID 또는 고유한 짧은 ID 접두사로 컨테이너를 찾는다."""
    row = db.get(Container, ref)
    if row is not None:
        return row
    matches = list(db.execute(select(Container).where(
        Container.container_id.like(f"{ref}%"))).scalars())
    return matches[0] if len(matches) == 1 else None


def bulk_attach(db: Session, svc: Service, container_ids: list[str],
                component_name: str | None, actor: str) -> dict:
    """여러 컨테이너를 한 서비스로 묶는다. 컨테이너별 결과를 반환한다."""
    results: list[dict] = []
    seen: set[str] = set()
    for cid in container_ids:
        if cid in seen:
            continue
        seen.add(cid)
        row = resolve_container(db, cid)
        if row is None:
            results.append({"container_id": cid, "ok": False,
                            "reason": "컨테이너를 찾을 수 없습니다"})
            continue
        if row.component_name == "hub-self":
            results.append({"container_id": row.container_id, "name": row.name, "ok": False,
                            "reason": "허브 자신은 그룹핑할 수 없습니다"})
            continue
        if row.service_id and row.service_id != svc.id:
            results.append({"container_id": row.container_id, "name": row.name, "ok": False,
                            "reason": f"이미 서비스 '{row.service_id}'에 연결되어 있습니다"})
            continue
        results.append(attach_one(db, svc, row, component_name or "", actor))

    attached = sum(1 for r in results if r["ok"])
    return {"service_id": svc.id, "attached": attached,
            "skipped": len(results) - attached, "results": results}
