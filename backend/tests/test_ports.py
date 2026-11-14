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
        "service_id": "port-app", "host_port": 50101, "protocol": "tcp",
        "container_port": 8080, "component": "web"})
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "reserved"


def test_double_reservation_rejected(client):
    _register(client)
    body = {"service_id": "port-app", "host_port": 50102, "protocol": "tcp"}
    assert mutate(client, "POST", "/api/v1/ports/reservations", json=body).status_code == 201
    r = mutate(client, "POST", "/api/v1/ports/reservations", json=body)
    assert r.status_code == 409
    assert r.json()["code"] == "already_reserved"


def test_tcp_udp_distinct(client):
    _register(client)
    body = {"service_id": "port-app", "host_port": 50103}
    assert mutate(client, "POST", "/api/v1/ports/reservations",
                  json={**body, "protocol": "tcp"}).status_code == 201
    assert mutate(client, "POST", "/api/v1/ports/reservations",
                  json={**body, "protocol": "udp"}).status_code == 201


def test_actually_bound_port_rejected(client, gateway):
    """이미 Docker가 점유 중인 포트는 예약 거부 (§9.3 3~4단계)."""
    _register(client)
    gateway.containers = [make_fake_container("c1", "busy", host_port=50110,
                                              container_port=80)]
    monitor = client.app.state.monitor   # 모니터 1사이클로 실제 점유 반영
    monitor.run_once()
    r = mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "port-app", "host_port": 50110, "protocol": "tcp"})
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


def test_reservation_outside_policy_rejected(client):
    """50000번대 밖의 포트는 예약할 수 없다 (라우터 포워딩 대역)."""
    _register(client)
    r = mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "port-app", "host_port": 18080})
    assert r.status_code == 409
    assert r.json()["code"] == "host_port_out_of_range"


def test_available_range_outside_policy_rejected(client):
    r = client.get("/api/v1/ports/available?range=8000-9000")
    assert r.status_code == 422
    assert r.json()["code"] == "range_out_of_policy"


def test_available_candidates_are_within_policy(client):
    r = client.get("/api/v1/ports/available?count=3")
    assert r.status_code == 200
    assert r.json()["candidates"]
    assert all(50000 <= p <= 59999 for p in r.json()["candidates"])


def test_reservation_for_unknown_service(client):
    r = mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "ghost", "host_port": 50104})
    assert r.status_code == 409
    assert r.json()["code"] == "service_not_found"


def test_available_candidates_exclude_taken(client):
    _register(client)
    mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "port-app", "host_port": 50105})
    r = client.get("/api/v1/ports/available?count=5&range=50100-50120")
    assert r.status_code == 200
    assert 50105 not in r.json()["candidates"]
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

    threads = [threading.Thread(target=attempt, args=(50106,)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201, 409], f"중복 예약 발생: {results}"


def test_registry_distinguishes_reserved_vs_in_use(client, gateway):
    """예약됨(reserved)과 실제 점유(bound) 구분."""
    _register(client)
    mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "port-app", "host_port": 50107})
    items = client.get("/api/v1/ports").json()["items"]
    mine = [i for i in items if i["host_port"] == 50107]
    assert mine and mine[0]["state"] == "reserved" and mine[0]["in_use"] is False


def test_delete_reservation(client):
    _register(client)
    r = mutate(client, "POST", "/api/v1/ports/reservations", json={
        "service_id": "port-app", "host_port": 50108})
    rid = r.json()["reservation_id"]
    assert mutate(client, "DELETE", f"/api/v1/ports/reservations/{rid}").status_code == 200
    r2 = mutate(client, "DELETE", f"/api/v1/ports/reservations/{rid}")
    assert r2.status_code == 404
