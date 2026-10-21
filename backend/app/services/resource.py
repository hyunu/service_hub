"""자원 수집 및 임계값 판정 (REQUIREMENTS §10).

- 호스트: psutil 사용 (Linux /proc 기반 측정과 macOS 모두 지원)
- 컨테이너: Docker stats (미지원 지표는 None → API에서 N/A로 표시, 0으로 대체 금지)
- 임계값: 메모리/디스크 80/90, CPU 80/95 + 지속 시간
"""
from __future__ import annotations

import platform
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

import psutil

from ..config import Settings
from ..docker_client import DockerGateway


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HostMetrics:
    cpu_percent: float | None
    cpu_cores: int
    cpu_per_core: list[float | None]
    mem_total_mb: float
    mem_used_mb: float
    mem_available_mb: float
    mem_percent: float
    swap_used_mb: float
    swap_total_mb: float
    disk_filesystems: list[dict]
    disk_root_used_gb: float | None
    disk_root_total_gb: float | None
    disk_root_percent: float | None
    net_ifaces: list[dict]
    hostname: str
    os_name: str
    kernel: str
    boot_at: str
    uptime_seconds: float
    temperature_c: float | None
    uptime_human: str


def human_uptime(seconds: float) -> str:
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} days")
    if hours:
        parts.append(f"{hours} hours")
    parts.append(f"{minutes} min")
    return " ".join(parts)


def collect_host() -> HostMetrics:
    cpu_percent = psutil.cpu_percent(interval=0.1)
    per_core = psutil.cpu_percent(interval=0.1, percpu=True)
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    boot = psutil.boot_time()

    filesystems = []
    root_used = root_total = root_pct = None
    try:
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            entry = {
                "mount": part.mountpoint,
                "device": part.device,
                "total_gb": round(usage.total / 1073741824, 1),
                "used_gb": round(usage.used / 1073741824, 1),
                "free_gb": round(usage.free / 1073741824, 1),
                "percent": usage.percent,
            }
            filesystems.append(entry)
            if part.mountpoint == "/":
                root_used, root_total, root_pct = (entry["used_gb"], entry["total_gb"],
                                                   entry["percent"])
    except Exception:
        pass

    net_ifaces = []
    try:
        counters = psutil.net_io_counters(pernic=True)
        for iface, c in counters.items():
            net_ifaces.append({"iface": iface, "rx_bytes": c.bytes_recv, "tx_bytes": c.bytes_sent,
                               "rx_packets": c.packets_recv, "tx_packets": c.packets_sent,
                               "errs_in": c.errin, "errs_out": c.errout,
                               "drop_in": c.dropin, "drop_out": c.dropout})
    except Exception:
        pass

    temperature = None
    try:
        temps = psutil.sensors_temperatures()
        for name in ("coretemp", "cpu_thermal", "soc_thermal"):
            if name in temps and temps[name]:
                temperature = round(temps[name][0].current, 1)
                break
    except Exception:
        pass

    uptime = time.time() - boot
    return HostMetrics(
        cpu_percent=cpu_percent,
        cpu_cores=psutil.cpu_count(logical=True) or 1,
        cpu_per_core=per_core,
        mem_total_mb=round(vm.total / 1048576, 1),
        mem_used_mb=round(vm.used / 1048576, 1),
        mem_available_mb=round(vm.available / 1048576, 1),
        mem_percent=vm.percent,
        swap_used_mb=round(swap.used / 1048576, 1),
        swap_total_mb=round(swap.total / 1048576, 1),
        disk_filesystems=filesystems,
        disk_root_used_gb=root_used,
        disk_root_total_gb=root_total,
        disk_root_percent=root_pct,
        net_ifaces=net_ifaces,
        hostname=platform.node(),
        os_name=f"{platform.system()} {platform.release()}",
        kernel=platform.version(),
        boot_at=datetime.fromtimestamp(boot, tz=timezone.utc).isoformat(),
        uptime_seconds=uptime,
        temperature_c=temperature,
        uptime_human=human_uptime(uptime),
    )


@dataclass
class CpuSustainTracker:
    """CPU 지속 시간 판정 — 짧은 상승에 반응하지 않기 위한 버퍼."""
    warn_pct: float
    crit_pct: float
    sustain_seconds: int
    interval: int
    buffer: deque = field(default_factory=lambda: deque(maxlen=120))

    def add(self, cpu_percent: float, ts: float | None = None) -> None:
        self.buffer.append((ts or time.time(), cpu_percent))

    def sustained(self) -> tuple[str | None, float | None]:
        """(레벨, 지속초과시간). 레벨: warning/critical/None"""
        if not self.buffer:
            return None, None
        now = self.buffer[-1][0]
        window = max(self.sustain_seconds * 0.5, 1.0)
        for level, threshold in (("critical", self.crit_pct), ("warning", self.warn_pct)):
            over = [t for t, v in self.buffer if v >= threshold]
            if over and (now - over[-1]) <= self.interval * 3 and (now - over[0]) >= window:
                return level, round(now - over[0], 1)
        return None, None


def evaluate_thresholds(host: HostMetrics, settings: Settings,
                        cpu_tracker: CpuSustainTracker) -> list[dict]:
    warnings: list[dict] = []
    if host.mem_percent >= settings.mem_crit_pct:
        warnings.append({"level": "critical", "resource": "memory",
                         "message": f"메모리 사용률 {host.mem_percent:.0f}% "
                                    f"(위험 임계 {settings.mem_crit_pct:.0f}%)"})
    elif host.mem_percent >= settings.mem_warn_pct:
        warnings.append({"level": "warning", "resource": "memory",
                         "message": f"메모리 사용률 {host.mem_percent:.0f}% "
                                    f"(주의 임계 {settings.mem_warn_pct:.0f}%)"})
    if host.swap_total_mb > 0 and host.swap_used_mb > 0:
        ratio = host.swap_used_mb / host.swap_total_mb * 100
        if ratio >= 25:
            warnings.append({"level": "warning", "resource": "swap",
                             "message": f"스왑 사용 증가: {host.swap_used_mb:.0f}/"
                                        f"{host.swap_total_mb:.0f} MB"})
    if host.disk_root_percent is not None:
        if host.disk_root_percent >= settings.disk_crit_pct:
            warnings.append({"level": "critical", "resource": "disk",
                             "message": f"디스크 사용률 {host.disk_root_percent:.0f}% "
                                        f"(위험 임계 {settings.disk_crit_pct:.0f}%)"})
        elif host.disk_root_percent >= settings.disk_warn_pct:
            warnings.append({"level": "warning", "resource": "disk",
                             "message": f"디스크 사용률 {host.disk_root_percent:.0f}% "
                                        f"(주의 임계 {settings.disk_warn_pct:.0f}%)"})
    level, seconds = cpu_tracker.sustained()
    if level:
        threshold = cpu_tracker.crit_pct if level == "critical" else cpu_tracker.warn_pct
        warnings.append({"level": level, "resource": "cpu",
                         "message": f"CPU {threshold:.0f}% 이상 지속 ({seconds:.0f}초)"})
    return warnings


def collect_container_stats(gateway: DockerGateway, container_ids: list[str]) -> dict[str, dict]:
    """컨테이너별 stats. 실패/미지원 지표는 None (0으로 대체하지 않음)."""
    out: dict[str, dict] = {}
    for cid in container_ids:
        stats = gateway.stats(cid)
        out[cid] = stats or {"cpu_percent": None, "mem_used_mb": None, "mem_limit_mb": None,
                             "net_rx_bytes": None, "net_tx_bytes": None,
                             "blk_read_bytes": None, "blk_write_bytes": None}
    return out


def aggregate_by_service(container_stats: dict[str, dict],
                         container_service: dict[str, str | None]) -> dict[str, dict]:
    agg: dict[str, dict] = {}
    for cid, sid in container_service.items():
        if not sid:
            continue
        stats = container_stats.get(cid) or {}
        entry = agg.setdefault(sid, {"cpu_percent": 0.0, "memory_mb": 0.0, "containers": 0,
                                     "containers_with_stats": 0})
        entry["containers"] += 1
        if stats.get("cpu_percent") is not None:
            entry["cpu_percent"] += stats["cpu_percent"]
        if stats.get("mem_used_mb") is not None:
            entry["memory_mb"] += stats["mem_used_mb"]
            entry["containers_with_stats"] += 1
    for entry in agg.values():
        entry["cpu_percent"] = round(entry["cpu_percent"], 2)
        entry["memory_mb"] = round(entry["memory_mb"], 1)
        entry["note"] = ("컨테이너 합산값은 호스트 측정값과 다를 수 있습니다 "
                         "(캐시/공유 메모리 차이).")
    return agg
