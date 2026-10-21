"""백그라운드 모니터 — §13.3 요구: 오류가 관리 UI를 중단시키지 않아야 한다.

주기(기본 15s): Docker ping → 컨테이너 인벤토리 → 포트 비교 → 자원 수집 →
임계값 판정 → status.json 캐시 기록(MOTD/CLI용).
단계별 오류는 격리된다. 마지막 정상 수집 시각은 settings.last_monitor_ok_at.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import select

from .config import Settings, get_settings
from .db import get_session_factory
from .docker_client import DockerGateway
from .models import Container, Event, Service, Setting
from .services import inventory, ports as portsvc, resource as resrc
from .services.events import record_event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Monitor:
    def __init__(self, gateway: DockerGateway, settings: Settings | None = None) -> None:
        self.gateway = gateway
        self.settings = settings or get_settings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.cpu_tracker = resrc.CpuSustainTracker(
            warn_pct=self.settings.cpu_warn_pct, crit_pct=self.settings.cpu_crit_pct,
            sustain_seconds=self.settings.cpu_sustain_seconds,
            interval=self.settings.monitor_interval)
        self.last_host: resrc.HostMetrics | None = None
        self.last_warnings: list[dict] = []
        self.last_ok_at: str | None = None

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="hub-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # 절대 루프를 죽이지 않는다
                traceback.print_exc()
            self._stop.wait(self.settings.monitor_interval)

    # ------------------------------------------------------------- pipeline
    def run_once(self) -> dict:
        result: dict = {}
        factory = get_session_factory()

        # 1) Docker 연결 상태
        status = self.gateway.status()
        with factory() as db:
            prev = db.get(Setting, "docker")
            if prev is None:
                prev = Setting(key="docker", value={})
                db.add(prev)
            if not status.connected and prev.value.get("connected") is not False:
                record_event(db, "docker_connection_error",
                             "Docker 데몬에 연결할 수 없습니다 — 컨테이너 상태를 확인할 수 없음",
                             severity="critical")
            prev.value = {"connected": status.connected,
                          "server_version": status.server_version,
                          "error": status.error, "checked_at": _now()}
            db.commit()

        # 2) 인벤토리 동기화 (연결 불가 시 unknown 처리 — 행 보존)
        with factory() as db:
            try:
                inv = inventory.sync_inventory(db, self.gateway)
                result["inventory"] = inv
                if status.connected and inv.get("unmanaged"):
                    record_event(db, "orphan_detected",
                                 f"미관리 컨테이너 {inv['unmanaged']}개 발견",
                                 severity="warning", dedupe_minutes=360)
                db.commit()
            except Exception as exc:
                db.rollback()
                result["inventory_error"] = type(exc).__name__

        # 3) 포트 비교 (충돌/미예약 점유 감지)
        with factory() as db:
            try:
                registry = portsvc.build_registry(db)
                conflicts = [p for p in registry if p["state"] == "conflict"]
                unreserved = [p for p in registry if p["state"].startswith("in_use")
                              and p.get("service_id")]
                if conflicts:
                    record_event(db, "port_conflict",
                                 f"포트 충돌 {len(conflicts)}건 감지",
                                 severity="critical",
                                 detail={"ports": [p["host_port"] for p in conflicts[:10]]})
                if unreserved:
                    record_event(db, "port_unreserved",
                                 f"예약 정보 없이 점유된 서비스 포트 {len(unreserved)}건",
                                 severity="warning",
                                 detail={"ports": [p["host_port"] for p in unreserved[:10]]})
                db.commit()
            except Exception as exc:
                db.rollback()
                result["ports_error"] = type(exc).__name__

        # 4) 자원 수집
        with factory() as db:
            try:
                host = resrc.collect_host()
                self.last_host = host
                self.cpu_tracker.add(host.cpu_percent or 0.0)
                db.add(resrc_sample(host))
                container_ids = [r[0] for r in db.execute(
                    select(Container.container_id).where(Container.state == "running")).all()]
                stats = resrc.collect_container_stats(self.gateway, container_ids)
                comp_service = dict(db.execute(select(Container.container_id,
                                                      Container.service_id)).all())
                for cid, st in stats.items():
                    db.add(_container_sample(cid, st))
                agg = resrc.aggregate_by_service(stats, comp_service)
                for sid, entry in agg.items():
                    db.add(_service_sample(sid, entry))

                warnings = resrc.evaluate_thresholds(host, self.settings, self.cpu_tracker)
                prev_levels = {w.get("resource"): w.get("level") for w in self.last_warnings}
                for w in warnings:
                    if prev_levels.get(w["resource"]) != w["level"]:
                        record_event(db, "resource_warning", w["message"],
                                     severity="warning" if w["level"] == "warning" else "critical")
                self.last_warnings = warnings
                result["warnings"] = len(warnings)
                db.commit()
            except Exception as exc:
                db.rollback()
                result["resources_error"] = type(exc).__name__

        # 5) status.json 캐시 + 마지막 정상 수집 시각
        try:
            self.last_ok_at = _now()
            self.write_status_cache()
            with factory() as db:
                row = db.get(Setting, "last_monitor_ok_at")
                if row is None:
                    row = Setting(key="last_monitor_ok_at", value={})
                    db.add(row)
                row.value = {"at": self.last_ok_at}
                row.updated_at = self.last_ok_at
                db.commit()
        except Exception as exc:
            result["cache_error"] = type(exc).__name__
        return result

    # ------------------------------------------------------------- cache
    def write_status_cache(self) -> None:
        """MOTD/CLI용 캐시. Docker 호출 없이 빠르게 읽을 수 있어야 한다."""
        factory = get_session_factory()
        host = self.last_host
        with factory() as db:
            docker_row = db.get(Setting, "docker")
            docker_val = docker_row.value if docker_row else {}
            containers = list(db.execute(select(Container)).scalars())
            services = list(db.execute(select(Service)).scalars())
            events = list(db.execute(select(Event).order_by(Event.id.desc()).limit(5)).scalars())
            running = sum(1 for c in containers if c.state == "running" and c.service_id)
            stopped = sum(1 for c in containers if c.state != "running" and c.service_id)
            orphans = sum(1 for c in containers if c.management_state == "unmanaged")

        payload = {
            "hub_name": self.settings.name.upper(),
            "generated_at": _now(),
            "generated_at_epoch": time.time(),
            "last_monitor_ok_at": self.last_ok_at,
            "server": {
                "hostname": host.hostname if host else None,
                "os": host.os_name if host else None,
                "uptime_human": host.uptime_human if host else None,
            },
            "docker": {
                "connected": bool(docker_val.get("connected")),
                "running": running,
                "stopped": stopped,
                "orphans": orphans,
            },
            "resources": {
                "cpu_percent": host.cpu_percent if host else None,
                "memory_used_mb": host.mem_used_mb if host else None,
                "memory_total_mb": host.mem_total_mb if host else None,
                "disk_used_gb": host.disk_root_used_gb if host else None,
                "disk_total_gb": host.disk_root_total_gb if host else None,
            },
            "services": [
                {"id": s.id, "name": s.name, "status": s.status,
                 "containers_running": sum(1 for c in containers
                                           if c.service_id == s.id and c.state == "running")}
                for s in services
            ],
            "recent_events": [{"message": e.message, "severity": e.severity} for e in events],
            "management": {"dashboard": f"http://{self._host_ip()}:{self.settings.port}"},
            "warnings": self.last_warnings,
        }
        tmp = self.settings.status_cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.settings.status_cache_path)

    def _host_ip(self) -> str:
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"


def resrc_sample(host: resrc.HostMetrics):
    from .models import ResourceSample
    # 네트워크 누적값(루프백 제외). 수집 실패로 인터페이스가 없으면 None(미지)로 둔다.
    ifaces = host.net_ifaces or []
    if ifaces:
        net_rx = sum(int(i.get("rx_bytes") or 0) for i in ifaces if i.get("iface") != "lo")
        net_tx = sum(int(i.get("tx_bytes") or 0) for i in ifaces if i.get("iface") != "lo")
    else:
        net_rx = net_tx = None
    return ResourceSample(ts=_now(), scope="host", scope_id=None,
                          cpu_percent=host.cpu_percent, mem_used_mb=host.mem_used_mb,
                          mem_limit_mb=host.mem_total_mb,
                          net_rx_bytes=net_rx, net_tx_bytes=net_tx,
                          extras={"swap_used_mb": host.swap_used_mb,
                                  "disk_used_gb": host.disk_root_used_gb,
                                  "disk_total_gb": host.disk_root_total_gb,
                                  "disk_percent": host.disk_root_percent,
                                  "load_avg": host.load_avg})


def _container_sample(cid: str, st: dict):
    from .models import ResourceSample
    return ResourceSample(ts=_now(), scope="container", scope_id=cid,
                          cpu_percent=st.get("cpu_percent"),
                          mem_used_mb=st.get("mem_used_mb"),
                          mem_limit_mb=st.get("mem_limit_mb"),
                          net_rx_bytes=st.get("net_rx_bytes"),
                          net_tx_bytes=st.get("net_tx_bytes"), extras={})


def _service_sample(sid: str, entry: dict):
    from .models import ResourceSample
    return ResourceSample(ts=_now(), scope="service", scope_id=sid,
                          cpu_percent=entry["cpu_percent"],
                          mem_used_mb=entry["memory_mb"], mem_limit_mb=None,
                          net_rx_bytes=None, net_tx_bytes=None,
                          extras={"containers": entry["containers"]})
