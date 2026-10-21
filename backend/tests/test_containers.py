"""컨테이너/미관리/인벤토리 테스트 (REQUIREMENTS §19.3)."""
from __future__ import annotations

from conftest import make_fake_container, mutate

SERVICE = {
    "id": "web-stack", "name": "Web Stack", "description": "웹 스택", "category": "web",
    "components": [
        {"name": "frontend", "role": "frontend", "required": True},
        {"name": "backend", "role": "backend", "required": True},
    ],
}


def _run_monitor(client):
    return client.app.state.monitor.run_once()


def test_container_listing_and_management_states(client, gateway):
    mutate(client, "POST", "/api/v1/services", json=SERVICE)
    gateway.containers = [
        make_fake_container("c1", "web-frontend", project="web-stack",
                            service="frontend", host_port=18080),
        make_fake_container("c2", "web-backend", project="web-stack",
                            service="backend", running=False),
        make_fake_container("c3", "rogue", project="someone-else", service="mystery"),
    ]
    _run_monitor(client)

    items = client.get("/api/v1/containers").json()["items"]
    by_id = {i["container_id"]: i for i in items}
    assert by_id["c1"]["management_state"] == "managed"
    assert by_id["c2"]["management_state"] == "stopped"
    assert by_id["c3"]["management_state"] == "unmanaged"

    # 필터
    stopped = client.get("/api/v1/containers?state=stopped").json()["items"]
    assert [i["container_id"] for i in stopped] == ["c2"]
    unmanaged = client.get("/api/v1/containers?management=unmanaged").json()["items"]
    assert [i["container_id"] for i in unmanaged] == ["c3"]


def test_orphan_detection_with_reason_and_guess(client, gateway):
    mutate(client, "POST", "/api/v1/services", json=SERVICE)
    gateway.containers = [
        make_fake_container("c1", "web-frontend", project="web-stack", service="frontend"),
        make_fake_container("c9", "web-stack-extra", project="web-stack", service="extra"),
    ]
    _run_monitor(client)
    items = client.get("/api/v1/orphans").json()["items"]
    assert [o["container_id"] for o in items] == ["c9"]
    assert items[0]["reason"]
    assert items[0]["guessed_service"] == "web-stack"   # compose 프로젝트명 유사도 힌트


def test_service_status_warning_when_required_missing(client, gateway):
    mutate(client, "POST", "/api/v1/services", json=SERVICE)
    gateway.containers = [make_fake_container(
        "c1", "web-frontend", project="web-stack", service="frontend")]
    _run_monitor(client)
    detail = client.get("/api/v1/services/web-stack").json()
    assert detail["status"] == "warning"
    assert any("backend" in w for w in detail["warnings"])


def test_attach_orphan_is_db_only(client, gateway):
    """연결은 DB만 수정한다 — 컨테이너 재생성 없음."""
    mutate(client, "POST", "/api/v1/services", json=SERVICE)
    gateway.containers = [make_fake_container("c9", "mystery-web", project="mystery")]
    _run_monitor(client)
    before = client.get("/api/v1/containers/c9").json()

    r = mutate(client, "POST", "/api/v1/orphans/c9/attach",
               json={"service_id": "web-stack", "component_name": "backend"})
    assert r.status_code == 200, r.text
    assert r.json()["runtime_unchanged"] is True

    after = client.get("/api/v1/containers/c9").json()
    assert after["service_id"] == "web-stack"
    assert after["state"] == before["state"]              # 런타임 상태 무변경
    assert after["container_id"] == before["container_id"]
    assert gateway.containers[0].id == "c9"               # 재생성되지 않음

    # 연결 후에는 더 이상 미관리가 아님
    orphans = client.get("/api/v1/orphans").json()["items"]
    assert all(o["container_id"] != "c9" for o in orphans)


def test_attach_to_unknown_service_404(client, gateway):
    gateway.containers = [make_fake_container("c9", "x")]
    _run_monitor(client)
    r = mutate(client, "POST", "/api/v1/orphans/c9/attach",
               json={"service_id": "ghost", "component_name": "a"})
    assert r.status_code == 404


def test_review_state(client, gateway):
    gateway.containers = [make_fake_container("c9", "x")]
    _run_monitor(client)
    r = mutate(client, "POST", "/api/v1/orphans/c9/review", json={"review_state": "reviewed"})
    assert r.status_code == 200
    assert client.get("/api/v1/containers/c9").json()["labels"]["hub.review_state"] == "reviewed"


def test_docker_unavailable_marks_unknown_and_api_survives(client, gateway, settings):
    """Docker 연결 실패 → unknown 처리, API는 계속 200 (§8.2, §19.3)."""
    mutate(client, "POST", "/api/v1/services", json=SERVICE)
    gateway.containers = [make_fake_container("c1", "web-frontend", project="web-stack",
                                              service="frontend")]
    _run_monitor(client)
    assert client.get("/api/v1/containers").json()["items"][0]["management_state"] == "managed"

    gateway.connected = False       # 데몬 끊김 시뮬레이션
    _run_monitor(client)

    rows = client.get("/api/v1/containers").json()["items"]
    assert rows[0]["management_state"] == "unknown", "기존 행이 unknown으로 표시되지 않음"
    assert client.get("/api/v1/orphans").status_code == 200
    status = client.get("/api/v1/system/status").json()
    assert status["docker"]["connected"] is False
    assert status["monitor"]["state"] == "ok"   # 모니터 자체는 살아 있음


def test_docker_connection_error_event_once(client, gateway):
    gateway.connected = False
    _run_monitor(client)
    _run_monitor(client)   # 두 번째 사이클에서 중복 이벤트 금지
    events = client.get("/api/v1/events").json()["items"]
    conn_events = [e for e in events if e["kind"] == "docker_connection_error"]
    assert len(conn_events) == 1


def test_container_detail_includes_networks_volumes_stats(client, gateway):
    gateway.containers = [make_fake_container("c1", "web-frontend", project="web-stack",
                                              service="frontend", host_port=18080)]
    _run_monitor(client)
    detail = client.get("/api/v1/containers/c1").json()
    assert detail["networks"] == ["bridge"]
    assert detail["stats"] is not None
    assert detail["ports"][0]["host_port"] == 18080
