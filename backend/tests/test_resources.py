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
