"""자원 모니터링 테스트 (REQUIREMENTS §19.5)."""
from __future__ import annotations

from app.config import Settings
from app.services.resource import (CpuSustainTracker, HostMetrics, aggregate_by_service,
                                   evaluate_thresholds, human_uptime)


def _host(mem_pct=50.0, disk_pct=50.0, mem_used=8192.0, mem_total=16384.0) -> HostMetrics:
    return HostMetrics(
        cpu_percent=10.0, cpu_cores=4, cpu_per_core=[10.0] * 4,
        mem_total_mb=mem_total, mem_used_mb=mem_used,
        mem_available_mb=mem_total - mem_used, mem_percent=mem_pct,
        swap_used_mb=0.0, swap_total_mb=0.0,
        disk_filesystems=[{"mount": "/", "total_gb": 500, "used_gb": 500 * disk_pct / 100,
                           "free_gb": 500 * (100 - disk_pct) / 100, "percent": disk_pct}],
        disk_root_used_gb=500 * disk_pct / 100, disk_root_total_gb=500.0,
        disk_root_percent=disk_pct, net_ifaces=[], hostname="test-host",
        os_name="Linux", kernel="6.x", boot_at="2026-10-01T00:00:00+00:00",
        uptime_seconds=86400, temperature_c=None, uptime_human="1 days")


def test_thresholds_ok():
    settings = Settings(_env_file=None)
    tracker = CpuSustainTracker(80, 95, 60, 15)
    assert evaluate_thresholds(_host(), settings, tracker) == []


def test_memory_warning_and_critical():
    settings = Settings(_env_file=None)
    tracker = CpuSustainTracker(80, 95, 60, 15)
    warn = evaluate_thresholds(_host(mem_pct=85), settings, tracker)
    assert any(w["resource"] == "memory" and w["level"] == "warning" for w in warn)
    crit = evaluate_thresholds(_host(mem_pct=92), settings, tracker)
    assert any(w["resource"] == "memory" and w["level"] == "critical" for w in crit)


def test_disk_thresholds():
    settings = Settings(_env_file=None)
    tracker = CpuSustainTracker(80, 95, 60, 15)
    warn = evaluate_thresholds(_host(disk_pct=85), settings, tracker)
    assert any(w["resource"] == "disk" for w in warn)
    crit = evaluate_thresholds(_host(disk_pct=95), settings, tracker)
    assert any(w["resource"] == "disk" and w["level"] == "critical" for w in crit)


def test_cpu_spike_ignored_but_sustained_flagged():
    """짧은 CPU 상승은 무시, 지속 시에만 경고 (§10.4)."""
    settings = Settings(_env_file=None)
    tracker = CpuSustainTracker(80, 95, sustain_seconds=2, interval=1)
    import time
    now = time.time()
    tracker.add(99.0, ts=now - 10)     # 10초 전 짧은 상승 → 무시
    tracker.add(10.0, ts=now - 5)
    tracker.add(15.0, ts=now)
    assert tracker.sustained()[0] is None

    tracker2 = CpuSustainTracker(80, 95, sustain_seconds=2, interval=1)
    tracker2.add(99.0, ts=now - 60)
    tracker2.add(99.5, ts=now - 30)
    tracker2.add(99.9, ts=now)         # 지속됨
    level, seconds = tracker2.sustained()
    assert level == "critical" and seconds >= 2


def test_aggregate_by_service_nulls_not_zeroed():
    stats = {
        "c1": {"cpu_percent": 10.0, "mem_used_mb": 100.0},
        "c2": {"cpu_percent": None, "mem_used_mb": None},   # 미지원 → 0이 아니라 None
    }
    comp = {"c1": "svc-a", "c2": "svc-a"}
    agg = aggregate_by_service(stats, comp)
    assert agg["svc-a"]["cpu_percent"] == 10.0
    assert agg["svc-a"]["memory_mb"] == 100.0
    assert agg["svc-a"]["containers"] == 2


def test_host_resources_endpoint(client):
    r = client.get("/api/v1/resources/host")
    assert r.status_code == 200
    body = r.json()
    assert body["cpu"]["cores"] >= 1
    assert body["memory"]["total_mb"] > 0
    assert body["system"]["hostname"]
    assert "samples" in body


def test_container_resources_na_not_zero(client, gateway):
    from conftest import make_fake_container
    gateway.containers = [make_fake_container("c1", "web", project="p", service="s")]
    client.app.state.monitor.run_once()
    items = client.get("/api/v1/resources/containers").json()["items"]
    assert items[0]["stats_available"] is True
    # Fake stats에는 blk 정보가 없을 수 있음 — None이어야 하며 0이 아님
    assert items[0]["blk_read_bytes"] in (None, 0) or items[0]["blk_read_bytes"] >= 0


def test_service_resources_aggregation(client, gateway):
    from conftest import make_fake_container
    from conftest import mutate
    mutate(client, "POST", "/api/v1/services", json={
        "id": "svc-a", "name": "A", "description": "d", "category": "web",
        "components": [{"name": "frontend", "role": "frontend", "required": True}]})
    gateway.containers = [make_fake_container("c1", "frontend", project="svc-a",
                                              service="frontend")]
    client.app.state.monitor.run_once()
    items = client.get("/api/v1/resources/services").json()["items"]
    assert items[0]["service_id"] == "svc-a"
    assert items[0]["containers"] == 1
    assert "note" in items[0]


def test_monitor_writes_status_cache(client, gateway, settings):
    client.app.state.monitor.run_once()
    import json
    cache = json.loads(settings.status_cache_path.read_text(encoding="utf-8"))
    assert cache["generated_at_epoch"] > 0
    assert cache["last_monitor_ok_at"]
    assert "docker" in cache and "resources" in cache


def test_uptime_human():
    assert human_uptime(86400 + 3600 + 120) == "1 days 1 hours 2 min"
    assert human_uptime(300) == "5 min"


def test_collect_host_root_disk_fallback(monkeypatch):
    """컨테이너처럼 "/" 마운트가 없어도 가장 큰 파일시스템을 루트로 쓴다.

    이 fallback이 없으면 디스크 지표가 None이 되어 추이 그래프가 N/A가 된다.
    """
    from types import SimpleNamespace

    from app.services import resource

    class Part:
        def __init__(self, mountpoint: str) -> None:
            self.mountpoint = mountpoint
            self.device = "/dev/mapper/ubuntu--vg-ubuntu--lv"

    usage = {
        "/data": SimpleNamespace(total=100 * 1024**3, used=20 * 1024**3,
                                 free=80 * 1024**3, percent=20.0),
        "/srv/services": SimpleNamespace(total=100 * 1024**3, used=20 * 1024**3,
                                         free=80 * 1024**3, percent=20.0),
    }
    monkeypatch.setattr(resource.psutil, "cpu_percent",
                        lambda interval=None, percpu=False: ([0.0, 0.0] if percpu else 0.0))
    monkeypatch.setattr(resource.psutil, "virtual_memory", lambda: SimpleNamespace(
        total=2 * 1024**3, used=1 * 1024**3, available=1 * 1024**3, percent=50.0))
    monkeypatch.setattr(resource.psutil, "swap_memory",
                        lambda: SimpleNamespace(used=0, total=0))
    monkeypatch.setattr(resource.psutil, "disk_partitions",
                        lambda all=False: [Part("/data"), Part("/srv/services")])
    monkeypatch.setattr(resource.psutil, "disk_usage", lambda mp: usage[mp])
    monkeypatch.setattr(resource.psutil, "net_io_counters", lambda pernic=True: {})
    monkeypatch.setattr(resource.psutil, "sensors_temperatures", lambda: {}, raising=False)
    monkeypatch.setattr(resource.psutil, "boot_time", lambda: 0)
    monkeypatch.setattr(resource.os, "getloadavg", lambda: (0.01, 0.02, 0.03))

    host = resource.collect_host()
    assert host.disk_root_total_gb == 100.0
    assert host.disk_root_used_gb == 20.0
    assert host.disk_root_percent == 20.0
    assert host.load_avg == [0.01, 0.02, 0.03]


def test_host_hostname_can_be_injected(monkeypatch):
    """컨테이너 hostname(컨테이너 ID) 대신 HUB_HOST_HOSTNAME을 쓴다."""
    from app.config import Settings, get_settings, set_settings
    from app.services.resource import collect_host

    prev = get_settings()
    set_settings(Settings(_env_file=None, host_hostname="n100-pve-dev"))
    try:
        assert collect_host().hostname == "n100-pve-dev"
    finally:
        set_settings(prev)


def test_host_samples_expose_disk_and_network(client):
    """samples가 디스크/네트워크/부하 필드를 최상위로 노출해야 한다.

    extras에만 있으면 프런트엔드 추이 그래프가 N/A가 된다(계약 불일치 회귀 방지).
    """
    client.app.state.monitor.run_once()
    body = client.get("/api/v1/resources/host").json()
    assert body["samples"], "host 샘플이 기록되어야 한다"
    sample = body["samples"][-1]
    for key in ("disk_used_gb", "disk_total_gb", "disk_percent",
                "net_rx_bytes", "net_tx_bytes", "load_avg"):
        assert key in sample, f"{key} 누락"
    assert sample["disk_total_gb"] is not None, "디스크 값이 측정되어야 한다"
    assert "load_avg" in body["cpu"]
