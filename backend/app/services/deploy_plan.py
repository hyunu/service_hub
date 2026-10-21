"""배포 계획 생성 (REQUIREMENTS §13.2). 컨테이너를 변경하지 않는다.

계획과 실제는 다를 수 있다 — 배포 후 실제 상태를 다시 조회한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .service_spec import ServiceSpec


@dataclass
class PlanContext:
    """계획 생성에 필요한 '관찰된' 환경 (순수 입력 — 여기서 Docker를 호출하지 않는다)."""
    available_env: set[str] = field(default_factory=set)
    conflicting_ports: set[int] = field(default_factory=set)
    mem_available_mb: float | None = None
    compose_ok: bool = True
    current_containers: dict[str, dict] = field(default_factory=dict)
    # current_containers: {compose_service_name: {"image": str, "state": str}}


def _change_for(name: str, ctx: PlanContext) -> dict:
    cur = ctx.current_containers.get(name)
    if cur is None:
        return {"name": name, "action": "create", "detail": "새로 생성"}
    state = cur.get("state")
    if state != "running":
        return {"name": name, "action": "start", "detail": f"중지 상태({state})에서 시작"}
    return {"name": name, "action": "unchanged", "detail": "변경 없음"}


def build_plan(spec: ServiceSpec, ctx: PlanContext) -> dict:
    impact: list[dict] = []
    warnings: list[dict] = []
    validation: list[dict] = []

    changes = ([_change_for(c.name, ctx) for c in spec.containers]
               if spec.containers
               else [{"name": "compose", "action": "apply", "detail": "compose 프로젝트 배포"}])

    # 1) Compose 검증
    validation.append({
        "check": "Compose syntax",
        "result": "PASS" if ctx.compose_ok else "FAIL",
    })
    if not ctx.compose_ok:
        impact.append({"message": "Compose 파일 검증에 실패했습니다"})

    # 2) 포트 충돌
    conflicts = [ep.host_port for ep in spec.endpoints
                 if ep.host_port and ep.host_port in ctx.conflicting_ports]
    validation.append({
        "check": "Port conflicts",
        "result": "NONE" if not conflicts else "CONFLICT",
        "detail": conflicts or None,
    })
    for port in conflicts:
        impact.append({"message": f"호스트 포트 {port}가 이미 사용 중입니다"})

    # 3) 필수 환경 변수
    missing = [name for name in spec.security.required_env
               if name not in ctx.available_env]
    validation.append({
        "check": "Required variables",
        "result": "PASS" if not missing else "MISSING",
        "detail": missing or None,
    })
    if missing:
        impact.append({"message": f"필수 환경 변수가 없습니다: {', '.join(missing)}"})

    # 4) 자원 경고
    res_warn = []
    need = spec.resources.memory_limit_mb
    if need and ctx.mem_available_mb is not None and need > ctx.mem_available_mb:
        res_warn.append(f"요청 메모리 {need}MB > 가용 {int(ctx.mem_available_mb)}MB")
    validation.append({
        "check": "Resource warnings",
        "result": "NONE" if not res_warn else "WARNING",
        "detail": res_warn or None,
    })
    for w in res_warn:
        warnings.append({"level": "warning", "message": w})

    result = "READY" if not impact else "BLOCKED"
    return {
        "service": spec.service.id,
        "changes": changes,
        "ports": [{"name": ep.name, "host_port": ep.host_port,
                   "container_port": ep.container_port, "exposure": ep.exposure}
                  for ep in spec.endpoints],
        "data": [{"name": v.name, "purpose": v.purpose} for v in spec.volumes],
        "impact": impact,
        "validation": validation,
        "warnings": warnings,
        "result": result,
        "runtime_unchanged": True,
        "note": "계획은 예측이다 — 배포 후 실제 상태를 다시 조회한다.",
    }
