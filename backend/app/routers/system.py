"""시스템 상태/개요/설정 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Container, Event, Service, Setting
from ..security import HubError, get_read_actor, require_auth
from ..services.events import record_audit
from ..services.resource import collect_host

router = APIRouter(prefix="/system", tags=["system"],
                   dependencies=[Depends(require_auth)])


@router.get("/status")
def system_status(request: Request, db: Session = Depends(get_db)):
    """CLI `hub status`용 경량 상태."""
    settings = get_settings()
    docker_row = db.get(Setting, "docker")
    monitor_row = db.get(Setting, "last_monitor_ok_at")
    containers = list(db.execute(select(Container)).scalars())
    services = list(db.execute(select(Service)).scalars())
    warnings = []
    mem_pct = _latest_host_metric(db, "mem_percent")
    if mem_pct is not None:
        if mem_pct >= settings.mem_crit_pct:
            warnings.append({"level": "critical", "resource": "memory",
                             "message": f"메모리 사용률 {mem_pct:.0f}%"})
        elif mem_pct >= settings.mem_warn_pct:
            warnings.append({"level": "warning", "resource": "memory",
                             "message": f"메모리 사용률 {mem_pct:.0f}%"})

    return {
        "hub_name": settings.name,
        "server": _server_summary(db),
        "docker": docker_row.value if docker_row else {"connected": False},
        "counts": {
            "services": len(services),
            "containers_running": sum(1 for c in containers if c.state == "running"),
            "containers_stopped": sum(1 for c in containers if c.state not in ("running",)),
            "orphans": sum(1 for c in containers if c.management_state == "unmanaged"),
        },
        "monitor": {
            "state": "ok" if monitor_row else "never_run",
            "last_ok_at": monitor_row.value.get("at") if monitor_row else None,
        },
        "warnings": warnings,
        "generated_at": _iso_now(),
    }


@router.get("/overview")
def system_overview(db: Session = Depends(get_db)):
    settings = get_settings()
    docker_row = db.get(Setting, "docker")
    monitor_row = db.get(Setting, "last_monitor_ok_at")
    host = None
    try:
        host = collect_host()
    except Exception:
        pass
    containers = list(db.execute(select(Container)).scalars())
    services = list(db.execute(select(Service)).scalars())
    events = list(db.execute(select(Event).order_by(Event.id.desc()).limit(10)).scalars())
    from ..monitor import Monitor  # 순환 참조 회피 — 임계값 함수만 사용
    from ..services.resource import CpuSustainTracker, evaluate_thresholds
    warnings: list[dict] = []
    if host is not None:
        tracker = CpuSustainTracker(warn_pct=settings.cpu_warn_pct,
                                    crit_pct=settings.cpu_crit_pct,
                                    sustain_seconds=settings.cpu_sustain_seconds,
                                    interval=settings.monitor_interval)
        tracker.add(host.cpu_percent or 0.0)
        warnings = evaluate_thresholds(host, settings, tracker)
    return {
        "server": {
            "hostname": host.hostname if host else None,
            "os": host.os_name if host else None,
            "kernel": host.kernel if host else None,
            "uptime_seconds": host.uptime_seconds if host else None,
            "uptime_human": host.uptime_human if host else None,
            "booted_at": host.boot_at if host else None,
        },
        "docker": docker_row.value if docker_row else {"connected": False},
        "resources": {
            "cpu": {"percent": host.cpu_percent if host else None,
                    "cores": host.cpu_cores if host else None},
            "memory": {"total_mb": host.mem_total_mb if host else None,
                       "used_mb": host.mem_used_mb if host else None,
                       "available_mb": host.mem_available_mb if host else None,
                       "percent": host.mem_percent if host else None},
            "disk": {"total_gb": host.disk_root_total_gb if host else None,
                     "used_gb": host.disk_root_used_gb if host else None,
                     "percent": host.disk_root_percent if host else None},
        },
        "counts": {
            "services": len(services),
            "containers_running": sum(1 for c in containers if c.state == "running"),
            "containers_stopped": sum(1 for c in containers if c.state != "running"),
            "orphans": sum(1 for c in containers if c.management_state == "unmanaged"),
        },
        "last_monitor_ok_at": monitor_row.value.get("at") if monitor_row else None,
        "recent_events": [_event_dict(e) for e in events],
        "warnings": warnings,
    }


class SettingsUpdate(BaseModel):
    name: str | None = None
    monitor_interval: int | None = None
    mem_warn_pct: float | None = None
    mem_crit_pct: float | None = None
    disk_warn_pct: float | None = None
    disk_crit_pct: float | None = None
    cpu_warn_pct: float | None = None
    cpu_crit_pct: float | None = None
    cpu_sustain_seconds: int | None = None


@router.get("/settings")
def get_system_settings(db: Session = Depends(get_db)):
    settings = get_settings()
    overrides = db.get(Setting, "runtime")
    vals = overrides.value if overrides else {}
    return {
        "hub_name": vals.get("name", settings.name),
        "bind": settings.bind,
        "port": settings.port,
        "loopback_only": settings.loopback_only,
        "monitor_interval": vals.get("monitor_interval", settings.monitor_interval),
        "enable_deploy": settings.enable_deploy,
        "thresholds": {
            "mem_warn_pct": vals.get("mem_warn_pct", settings.mem_warn_pct),
            "mem_crit_pct": vals.get("mem_crit_pct", settings.mem_crit_pct),
            "disk_warn_pct": vals.get("disk_warn_pct", settings.disk_warn_pct),
            "disk_crit_pct": vals.get("disk_crit_pct", settings.disk_crit_pct),
            "cpu_warn_pct": vals.get("cpu_warn_pct", settings.cpu_warn_pct),
            "cpu_crit_pct": vals.get("cpu_crit_pct", settings.cpu_crit_pct),
            "cpu_sustain_seconds": vals.get("cpu_sustain_seconds", settings.cpu_sustain_seconds),
        },
    }


@router.put("/settings")
def put_system_settings(body: SettingsUpdate, db: Session = Depends(get_db),
                        actor: str = Depends(get_read_actor)):
    if body.monitor_interval is not None and not (5 <= body.monitor_interval <= 3600):
        raise HubError(status_code=422, detail="수집 주기는 5~3600초 범위여야 합니다",
                            code="invalid_interval")
    overrides = db.get(Setting, "runtime")
    if overrides is None:
        overrides = Setting(key="runtime", value={})
        db.add(overrides)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    overrides.value = {**overrides.value, **updates}
    record_audit(db, actor, "settings.update", target="runtime", detail={"fields": list(updates)})
    db.commit()
    return {"ok": True, "updated": list(updates)}


@router.get("/search")
def global_search(q: str, db: Session = Depends(get_db)):
    """전역 검색: 서비스/컨테이너/포트/도메인/이미지 (§11.1)."""
    term = q.strip().lower()
    if not term:
        return {"services": [], "containers": [], "ports": [], "endpoints": []}
    services = [{"id": s.id, "name": s.name, "description": s.description}
                for s in db.execute(select(Service)).scalars()
                if term in s.id.lower() or term in s.name.lower() or term in s.description.lower()]
    containers = [{"container_id": c.container_id, "name": c.name, "image": c.image,
                   "state": c.state, "service_id": c.service_id}
                  for c in db.execute(select(Container)).scalars()
                  if term in c.name.lower() or term in (c.image or "").lower()
                  or term in c.container_id.lower()]
    ports = []
    endpoints = []
    for c in db.execute(select(Container)).scalars():
        for p in c.ports or []:
            if p.get("host_port") and term in str(p["host_port"]):
                ports.append({"host_port": p["host_port"], "protocol": p.get("proto"),
                              "container_name": c.name, "service_id": c.service_id})
    for s in db.execute(select(Service)).scalars():
        for e in s.endpoints:
            if term in e.hostname.lower() if e.hostname else False:
                endpoints.append({"service_id": s.id, "name": e.name, "hostname": e.hostname})
    return {"services": services, "containers": containers, "ports": ports,
            "endpoints": endpoints}


# ------------------------------------------------------------- helpers

def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _server_summary(db: Session) -> dict:
    host = None
    try:
        host = collect_host()
    except Exception:
        pass
    if host is None:
        return {"hostname": None, "os": None, "uptime_human": None,
                "note": "호스트 정보를 수집할 수 없음"}
    return {"hostname": host.hostname, "os": host.os_name, "kernel": host.kernel,
            "uptime_human": host.uptime_human, "booted_at": host.boot_at}


def _latest_host_metric(db: Session, key: str) -> float | None:
    from ..models import ResourceSample
    row = db.execute(select(ResourceSample).where(ResourceSample.scope == "host")
                     .order_by(ResourceSample.id.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        return None
    mapping = {"mem_percent": (row.mem_used_mb, row.mem_limit_mb)}
    if key == "mem_percent" and row.mem_limit_mb:
        return round(row.mem_used_mb / row.mem_limit_mb * 100, 1)
    return None


def _event_dict(e) -> dict:
    return {"id": e.id, "ts": e.ts, "severity": e.severity, "kind": e.kind,
            "service_id": e.service_id, "container_id": e.container_id, "message": e.message}
