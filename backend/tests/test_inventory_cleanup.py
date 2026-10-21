"""컨테이너 인벤토리 정리 테스트 — 사라진 컨테이너의 행이 누적되지 않는다.

재gression 사유:
  재기동/배포로 컨테이너 ID가 바뀌면 이전 인스턴스의 행이 DB에 남아
  대시보드에 같은 이름(hub-backend 등)이 여러 개로 중복 표시되었다.
"""
from __future__ import annotations

from conftest import make_fake_container, mutate


def _rows(client):
    return client.get("/api/v1/containers").json()["items"]


def test_removed_container_row_is_deleted(client, gateway):
    """컨테이너가 삭제되면 인벤토리 행도 사라진다."""
    gateway.containers = [make_fake_container("c1", "app-web", project="proj", service="web")]
    client.app.state.monitor.run_once()
    assert {c["container_id"] for c in _rows(client)} == {"c1"}

    gateway.containers = []
    client.app.state.monitor.run_once()
    assert _rows(client) == []


def test_previous_instance_of_same_name_is_removed(client, gateway):
    """같은 이름으로 재기동되면 이전 ID 행은 제거되고 새 ID 행만 남는다."""
    gateway.containers = [make_fake_container("c1", "hub-backend", project="proj")]
    client.app.state.monitor.run_once()
    assert len(_rows(client)) == 1

    gateway.containers = [make_fake_container("c2", "hub-backend", project="proj")]
    client.app.state.monitor.run_once()

    rows = _rows(client)
    assert len(rows) == 1
    assert rows[0]["container_id"] == "c2"


def test_hub_self_previous_instance_is_removed(client, gateway):
    """허브 자기 자신(구 compose 프로젝트)의 이전 인스턴스도 정리된다."""
    gateway.containers = [
        make_fake_container("h1", "hub-backend", project="service-hub"),
        make_fake_container("h2", "hub-frontend", project="service-hub"),
    ]
    client.app.state.monitor.run_once()
    assert len(_rows(client)) == 2

    gateway.containers = [make_fake_container("h3", "hub-backend", project="service-hub")]
    client.app.state.monitor.run_once()

    rows = _rows(client)
    assert [r["container_id"] for r in rows] == ["h3"]


def test_service_component_container_removed_becomes_missing(client, gateway):
    """서비스 컴포넌트의 컨테이너가 사라지면 등록 정보는 유지하고 'missing'로 표시한다."""
    r = mutate(client, "POST", "/api/v1/services", json={
        "id": "svc-a", "name": "svc-a", "description": "", "category": "infra",
        "components": [{"name": "web", "required": True}]})
    assert r.status_code == 201, r.text

    gateway.containers = [make_fake_container("c1", "svc-a-web", project="proj", service="web")]
    client.app.state.monitor.run_once()
    rows = _rows(client)
    assert len(rows) == 1 and rows[0]["management_state"] == "managed"

    gateway.containers = []
    client.app.state.monitor.run_once()

    rows = _rows(client)
    assert len(rows) == 1                      # 행은 유지 (등록 정보 보존)
    assert rows[0]["management_state"] == "missing"
    assert rows[0]["state"] == "exited"
    detail = client.get("/api/v1/services/svc-a").json()
    assert detail["status"] == "missing"      # 서비스 상태도 누락으로


def test_docker_unavailable_keeps_all_rows(client, gateway):
    """Docker를 읽을 수 없으면(연결 불가) 어떤 행도 지우지 않는다."""
    gateway.containers = [make_fake_container("c1", "app-web", project="proj")]
    client.app.state.monitor.run_once()
    assert len(_rows(client)) == 1

    gateway.connected = False
    client.app.state.monitor.run_once()

    rows = _rows(client)
    assert len(rows) == 1
    assert rows[0]["management_state"] == "unknown"


def test_dangling_manual_assignment_is_removed(client, gateway):
    """사라진 컨테이너를 가리키는 수동 연결(assignment)도 정리된다."""
    mutate(client, "POST", "/api/v1/services", json={
        "id": "grp", "name": "grp", "description": "", "category": "infra",
        "components": []})
    gateway.containers = [make_fake_container("c1", "proj-web-1", project="proj", service="web")]
    client.app.state.monitor.run_once()

    r = mutate(client, "POST", "/api/v1/orphans/attach",
               json={"service_id": "grp", "container_ids": ["c1"]})
    assert r.status_code == 200, r.text
    assert _rows(client)[0]["manual"] is True

    gateway.containers = []
    client.app.state.monitor.run_once()

    rows = _rows(client)
    # 행은 등록 정보 보존 차원에서 남지만 "missing"로 표시된다
    assert len(rows) == 1
    assert rows[0]["management_state"] == "missing"
    # 수동 연결(assignment)은 사라진 컨테이너를 가리키므로 정리된다
    assert rows[0]["manual"] is False
