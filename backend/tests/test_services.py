"""서비스 레지스트리 테스트 (REQUIREMENTS §19.1)."""
from __future__ import annotations

from conftest import mutate

VALID_SERVICE = {
    "id": "ai-platform",
    "name": "AI Platform",
    "description": "AI 추론 및 프런트엔드 서비스",
    "category": "ai",
    "deployment_path": "/srv/services/ai-platform",
    "compose_file": "compose.yaml",
    "components": [
        {"name": "frontend", "role": "frontend", "required": True},
        {"name": "backend", "role": "backend", "required": True},
    ],
    "endpoints": [
        {"name": "web", "type": "http", "exposure": "proxy", "hostname": "ai.home",
         "container": "frontend", "container_port": 3000},
    ],
}


def test_register_service(client):
    r = mutate(client, "POST", "/api/v1/services", json=VALID_SERVICE)
    assert r.status_code == 201, r.text
    assert r.json()["id"] == "ai-platform"


def test_duplicate_id_rejected(client):
    mutate(client, "POST", "/api/v1/services", json=VALID_SERVICE)
    r = mutate(client, "POST", "/api/v1/services", json=VALID_SERVICE)
    assert r.status_code == 409
    assert r.json()["code"] == "duplicate_service_id"


def test_invalid_id_rejected(client):
    bad = {**VALID_SERVICE, "id": "Bad_ID!"}
    r = mutate(client, "POST", "/api/v1/services", json=bad)
    assert r.status_code == 422
    assert r.json()["code"] == "invalid_service_id"


def test_invalid_category_rejected(client):
    bad = {**VALID_SERVICE, "category": "unknown-cat"}
    r = mutate(client, "POST", "/api/v1/services", json=bad)
    assert r.status_code == 422


def test_proxy_endpoint_requires_hostname(client):
    bad = {**VALID_SERVICE, "endpoints": [
        {"name": "web", "type": "http", "exposure": "proxy",
         "container": "frontend", "container_port": 3000}]}
    r = mutate(client, "POST", "/api/v1/services", json=bad)
    assert r.status_code == 422
    assert r.json()["code"] == "hostname_required"


def test_service_without_containers_allowed(client):
    r = mutate(client, "POST", "/api/v1/services", json={
        "id": "future-app", "name": "Future App", "description": "아직 배포 전",
        "category": "dev"})
    assert r.status_code == 201
    assert r.json()["containers"] == {"total": 0, "running": 0, "stopped": 0}
    assert r.json()["status"] == "registered"


def test_description_editable(client):
    mutate(client, "POST", "/api/v1/services", json=VALID_SERVICE)
    r = mutate(client, "PATCH", "/api/v1/services/ai-platform",
               json={"description": "수정된 설명", "notes": "운영 주의사항"})
    assert r.status_code == 200
    detail = client.get("/api/v1/services/ai-platform").json()
    assert detail["description"] == "수정된 설명"
    assert detail["notes"] == "운영 주의사항"


def test_delete_removes_registry_only(client, gateway):
    """서비스 삭제는 관리 레코드만 지운다 — 컨테이너 런타임은 무변경."""
    from conftest import make_fake_container
    mutate(client, "POST", "/api/v1/services", json=VALID_SERVICE)
    gateway.containers = [make_fake_container(
        "c1", "ai-platform-frontend", project="ai-platform", service="frontend",
        host_port=18080, container_port=3000)]
    client.app.state.monitor.run_once()      # 실제 런타임 반영
    cid_before = [i["container_id"] for i in client.get("/api/v1/containers").json()["items"]]
    assert cid_before == ["c1"]

    r = mutate(client, "DELETE", "/api/v1/services/ai-platform?confirm=ai-platform")
    assert r.status_code == 200, r.text
    assert r.json()["runtime_unchanged"] is True

    after = client.get("/api/v1/containers").json()["items"]
    assert [i["container_id"] for i in after] == cid_before, "컨테이너가 삭제/변경됨!"
    assert after[0]["management_state"] == "unmanaged"
    assert client.get("/api/v1/services/ai-platform").status_code == 404
    # 실제 게이트웨이 컨테이너는 그대로 살아 있어야 한다
    assert gateway.containers[0].id == "c1"


def test_delete_requires_confirm_match(client):
    mutate(client, "POST", "/api/v1/services", json=VALID_SERVICE)
    r = mutate(client, "DELETE", "/api/v1/services/ai-platform?confirm=wrong")
    assert r.status_code == 422
    assert client.get("/api/v1/services/ai-platform").status_code == 200


def test_service_logs_via_gateway(client, gateway):
    from conftest import make_fake_container
    mutate(client, "POST", "/api/v1/services", json=VALID_SERVICE)
    gateway.containers = [make_fake_container(
        "c9", "frontend", project="ai-platform", service="frontend")]
    client.app.state.monitor.run_once()      # 컨테이너를 서비스에 연결
    r = client.get("/api/v1/services/ai-platform/logs?tail=10")
    assert r.status_code == 200
    assert any("fake log" in line for line in r.json()["lines"])
