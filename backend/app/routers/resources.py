"""자원 라우터 (REQUIREMENTS §10). 미지원 지표는 null(N/A)로 반환 — 0으로 대체 금지."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Container, ResourceSample, Service
from ..security import require_auth
from ..services.resource import collect_host

router = APIRouter(prefix="/resources", tags=["resources"],
                   dependencies=[Depends(require_auth)])


@router.get("/host")
def host_resources(db: Session = Depends(get_db)):
    settings = get_settings()
    host = None
    error = None
    try:
        host = collect_host()
    except Exception as exc:
        error = type(exc).__name__
    samples = list(db.execute(select(ResourceSample)
                              .where(ResourceSample.scope == "host")
                              .order_by(ResourceSample.id.desc()).limit(120)).scalars())
    samples.reverse()
    warnings = []
    if host is not None:
        from ..services.resource import CpuSustainTracker, evaluate_thresholds
        tracker = CpuSustainTracker(warn_pct=settings.cpu_warn_pct,
                                    crit_pct=settings.cpu_crit_pct,
                                    sustain_seconds=settings.cpu_sustain_seconds,
                                    interval=settings.monitor_interval)
        tracker.add(host.cpu_percent or 0.0)
        warnings = evaluate_thresholds(host, settings, tracker)
    return {
        "cpu": {"percent": host.cpu_percent if host else None,
                "cores": host.cpu_cores if host else None,
                "per_core": host.cpu_per_core if host else None},
        "memory": {"total_mb": host.mem_total_mb if host else None,
                   "used_mb": host.mem_used_mb if host else None,
                   "available_mb": host.mem_available_mb if host else None,
                   "percent": host.mem_percent if host else None,
                   "cached_mb": None,
                   "swap_used_mb": host.swap_used_mb if host else None,
                   "swap_total_mb": host.swap_total_mb if host else None},
        "disk": {"filesystems": host.disk_filesystems if host else None,
                 "root_used_gb": host.disk_root_used_gb if host else None,
                 "root_total_gb": host.disk_root_total_gb if host else None,
                 "root_percent": host.disk_root_percent if host else None},
        "network": {"interfaces": host.net_ifaces if host else None},
        "system": {"hostname": host.hostname if host else None,
                   "os": host.os_name if host else None,
                   "kernel": host.kernel if host else None,
                   "booted_at": host.boot_at if host else None,
                   "uptime_seconds": host.uptime_seconds if host else None,
                   "uptime_human": host.uptime_human if host else None,
                   "temperature_c": host.temperature_c if host else None},
        "warnings": warnings,
        "samples": [{"ts": s.ts, "cpu_percent": s.cpu_percent,
                     "mem_used_mb": s.mem_used_mb, "extras": s.extras}
                    for s in samples],
        "collection_error": error,
    }


@router.get("/containers")
def container_resources(db: Session = Depends(get_db)):
    from ..dependencies import get_gateway
    gateway = get_gateway()
    rows = list(db.execute(select(Container).where(Container.state == "running")).scalars())
    # docker stats 는 컨테이너별로 ~1초 걸리므로 병렬로 수집한다.
    stats_map = gateway.stats_many([row.container_id for row in rows])
    items = []
    for row in rows:
        stats = stats_map.get(row.container_id)
        items.append({
            "container_id": row.container_id, "name": row.name, "service_id": row.service_id,
            "state": row.state, "health": row.health, "restart_count": row.restart_count,
            "cpu_percent": (stats or {}).get("cpu_percent"),
            "mem_used_mb": (stats or {}).get("mem_used_mb"),
            "mem_limit_mb": (stats or {}).get("mem_limit_mb"),
            "net_rx_bytes": (stats or {}).get("net_rx_bytes"),
            "net_tx_bytes": (stats or {}).get("net_tx_bytes"),
            "blk_read_bytes": (stats or {}).get("blk_read_bytes"),
            "blk_write_bytes": (stats or {}).get("blk_write_bytes"),
            "stats_available": stats is not None,
        })
    return {"items": items, "note": "미지원 지표는 null(N/A)입니다 — 0이 아닙니다"}


@router.get("/services")
def service_resources(db: Session = Depends(get_db)):
    from ..dependencies import get_gateway
    from ..services.resource import aggregate_by_service
    gateway = get_gateway()
    rows = list(db.execute(select(Container)).scalars())
    ids_running = [r.container_id for r in rows if r.state == "running"]
    # docker stats 는 컨테이너별로 ~1초 걸리므로 병렬로 수집한다.
    stats_map = gateway.stats_many(ids_running)
    stats = {cid: (stats_map.get(cid) or {}) for cid in ids_running}
    comp_service = {r.container_id: r.service_id for r in rows}
    agg = aggregate_by_service(stats, comp_service)
    services = {s.id: s for s in db.execute(select(Service)).scalars()}
    items = []
    for sid, entry in agg.items():
        svc = services.get(sid)
        svc_rows = [r for r in rows if r.service_id == sid]
        items.append({
            "service_id": sid,
            "name": svc.name if svc else None,
            "status": svc.status if svc else None,
            "cpu_percent": entry["cpu_percent"],
            "memory_mb": entry["memory_mb"],
            "containers": entry["containers"],
            "restarts": sum(r.restart_count for r in svc_rows),
            "note": entry["note"],
        })
    items.sort(key=lambda x: x["memory_mb"], reverse=True)
    return {"items": items}


@router.get("/warnings")
def resource_warnings(db: Session = Depends(get_db)):
    settings = get_settings()
    from ..services.resource import CpuSustainTracker, evaluate_thresholds
    host = collect_host()
    tracker = CpuSustainTracker(warn_pct=settings.cpu_warn_pct, crit_pct=settings.cpu_crit_pct,
                                sustain_seconds=settings.cpu_sustain_seconds,
                                interval=settings.monitor_interval)
    tracker.add(host.cpu_percent or 0.0)
    return {"warnings": evaluate_thresholds(host, settings, tracker),
            "thresholds": {"mem_warn_pct": settings.mem_warn_pct,
                           "mem_crit_pct": settings.mem_crit_pct,
                           "disk_warn_pct": settings.disk_warn_pct,
                           "disk_crit_pct": settings.disk_crit_pct,
                           "cpu_warn_pct": settings.cpu_warn_pct,
                           "cpu_crit_pct": settings.cpu_crit_pct,
                           "cpu_sustain_seconds": settings.cpu_sustain_seconds}}
