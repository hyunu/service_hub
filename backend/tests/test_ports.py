"""포트 관리 테스트 (REQUIREMENTS §19.2)."""
from __future__ import annotations

import threading

from conftest import make_fake_container, mutate


def _register(client, sid="port-app"):
    r = mutate(client, "POST", "/api/v1/services", json={
        "id": sid, "name": "Port App", "description": "포트 테스트", "category": "web",
        "components": [{"name": "web", "role": "frontend", "required": True}]})
    assert r.status_code == 201, r.text


def test_reserve_available_port(client):
    _register(client)
    r = mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "port-app", "host_port": 18801, "protocol": "tcp",
        "container_port": 8080, "component": "web"})
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "reserved"


def test_double_reservation_rejected(client):
    _register(client)
    body = {"service_id": "port-app", "host_port": 18802, "protocol": "tcp"}
    assert mutate(client, "POST", "/api/v1/ports/reservations", json=body).status_code == 201
    r = mutate(client, "POST", "/api/v1/ports/reservations", json=body)
    assert r.status_code == 409
    assert r.json()["code"] == "already_reserved"


def test_tcp_udp_distinct(client):
    _register(client)
    body = {"service_id": "port-app", "host_port": 18803}
    assert mutate(client, "POST", "/api/v1/ports/reservations",
                  json={**body, "protocol": "tcp"}).status_code == 201
    assert mutate(client, "POST", "/api/v1/ports/reservations",
                  json={**body, "protocol": "udp"}).status_code == 201


def test_actually_bound_port_rejected(client, gateway):
    """이미 Docker가 점유 중인 포트는 예약 거부 (§9.3 3~4단계)."""
    _register(client)
    gateway.containers = [make_fake_container("c1", "busy", host_port=18810,
                                              container_port=80)]
    monitor = client.app.state.monitor   # 모니터 1사이클로 실제 점유 반영
    monitor.run_once()
    r = mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "port-app", "host_port": 18810, "protocol": "tcp"})
    assert r.status_code == 409
    assert r.json()["code"] in ("in_use", "bind_failed")


def test_protected_ports_rejected(client):
    _register(client)
    for port in (22, 8420):
        r = mutate(client, "POST", "/api/v1/ports/reservations", json={
            "service_id": "port-app", "host_port": port})
        assert r.status_code == 409, f"보호 포트 {port}가 거부되지 않음"
        assert r.json()["code"] == "protected_port"


def test_port_range_validation(client):
    _register(client)
    r = mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "port-app", "host_port": 70000})
    assert r.status_code == 422


def test_reservation_for_unknown_service(client):
    r = mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "ghost", "host_port": 18804})
    assert r.status_code == 409
    assert r.json()["code"] == "service_not_found"


def test_available_candidates_exclude_taken(client):
    _register(client)
    mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "port-app", "host_port": 18805})
    r = client.get("/api/v1/ports/available?count=5&range=18800-18820")
    assert r.status_code == 200
    assert 18805 not in r.json()["candidates"]
    assert len(r.json()["candidates"]) == 5


def test_concurrent_reservations_no_duplicate(client):
    """동시 예약 — 고유 인덱스로 중복 예약이 발생하면 안 된다."""
    _register(client)
    results = []

    def attempt(port):
        import httpx
        # 같은 앱 인스턴스에 대해 스레드에서 동시에 예약 시도
        r = client.post("/api/v1/ports/reservations",
                        headers={"X-CSRF-Token": client.csrf},
                        json={"service_id": "port-app", "host_port": port})
        results.append(r.status_code)

    threads = [threading.Thread(target=attempt, args=(18806,)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201, 409], f"중복 예약 발생: {results}"


def test_registry_distinguishes_reserved_vs_in_use(client, gateway):
    """예약됨(reserved)과 실제 점유(bound) 구분."""
    _register(client)
    mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "port-app", "host_port": 18807})
    items = client.get("/api/v1/ports").json()["items"]
    mine = [i for i in items if i["host_port"] == 18807]
    assert mine and mine[0]["state"] == "reserved" and mine[0]["in_use"] is False


def test_delete_reservation(client):
    _register(client)
    r = mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "port-app", "host_port": 18808})
    rid = r.json()["reservation_id"]
    assert mutate(client, "DELETE", f"/api/v1/ports/reservations/{rid}").status_code == 200
    r2 = mutate(client, "DELETE", f"/api/v1/ports/reservations/{rid}")
    assert r2.status_code == 404
