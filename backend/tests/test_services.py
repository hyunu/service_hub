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
        host_port=50180, container_port=3000)]
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
    lines = r.json()["lines"]
    # 프런트엔드 계약: 문자열이 아니라 {ts, stream, message} 객체여야 한다
    assert lines and all(isinstance(line, dict) for line in lines)
    assert all({"ts", "stream", "message"} <= set(line) for line in lines)
    assert any("fake log" in line["message"] for line in lines)
    assert all(line["message"].startswith("[frontend]") for line in lines)


def test_validate_spec_endpoint_ok(client):
    body = {
        "schema_version": 1,
        "service": {"id": "sample-app", "name": "Sample", "description": "샘플",
                    "category": "web"},
        "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    }
    r = mutate(client, "POST", "/api/v1/services/validate", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert data["spec"]["service"]["id"] == "sample-app"


def test_validate_spec_endpoint_reports_errors(client):
    body = {"schema_version": 1,
            "service": {"id": "Bad", "name": "x", "description": "y", "category": "web"},
            "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"}}
    r = mutate(client, "POST", "/api/v1/services/validate", json=body)
    assert r.status_code == 422
    assert r.json()["code"] in ("invalid_service_id", "spec_validation_failed")


def test_validate_spec_endpoint_requires_auth(anon_client):
    r = anon_client.post("/api/v1/services/validate", json={"schema_version": 1})
    assert r.status_code in (401, 403)


AUTH_SERVICE = {
    "id": "auth-app",
    "name": "Auth App",
    "description": "인증 메타데이터 테스트",
    "category": "web",
    "deployment_path": "/srv/services/auth-app",
    "compose_file": "compose.yaml",
    "endpoints": [{
        "name": "web", "type": "http", "exposure": "host", "host_port": 50180,
        "container": "web", "container_port": 80,
        "auth": {"type": "basic",
                 "credentials_ref": "1password://n100/auth-app/basic",
                 "hint": "운영자에게 요청"},
    }],
}

AUTH_EXPECTED = {"type": "basic",
                 "credentials_ref": "1password://n100/auth-app/basic",
                 "hint": "운영자에게 요청"}


def test_host_port_outside_policy_rejected_on_register(client):
    payload = {
        "id": "bad-port-app", "name": "Bad Port", "description": "범위 밖",
        "category": "web",
        "endpoints": [{"name": "web", "type": "http", "exposure": "host",
                       "host_port": 18080, "container": "web", "container_port": 80}],
    }
    r = mutate(client, "POST", "/api/v1/services", json=payload)
    assert r.status_code == 422
    assert r.json()["code"] == "host_port_out_of_range"
    assert client.get("/api/v1/services/bad-port-app").status_code == 404


def test_endpoint_auth_metadata_roundtrip(client):
    r = mutate(client, "POST", "/api/v1/services", json=AUTH_SERVICE)
    assert r.status_code == 201, r.text

    detail = client.get("/api/v1/services/auth-app").json()
    assert detail["endpoints"][0]["auth"] == AUTH_EXPECTED

    items = client.get("/api/v1/services/auth-app/endpoints").json()["items"]
    assert items[0]["auth"] == AUTH_EXPECTED


def test_endpoint_auth_can_be_updated_later(client):
    """기존 서비스도 auth 참조를 나중에 기록할 수 있다 (런타임 무변경)."""
    payload = {**VALID_SERVICE, "id": "legacy-app", "name": "Legacy",
               "endpoints": [{"name": "web", "type": "http", "exposure": "host",
                              "host_port": 50180, "container": "frontend",
                              "container_port": 80}]}
    mutate(client, "POST", "/api/v1/services", json=payload)
    r = mutate(client, "PATCH", "/api/v1/services/legacy-app/endpoints/web/auth",
               json={"auth": {"type": "basic",
                              "credentials_ref": "operator://ask-admin",
                              "hint": "운영자에게 요청"}})
    assert r.status_code == 200, r.text
    assert r.json()["auth"]["type"] == "basic"

    detail = client.get("/api/v1/services/legacy-app").json()
    assert detail["endpoints"][0]["auth"]["credentials_ref"] == "operator://ask-admin"


def test_endpoint_auth_update_rejects_raw_value(client):
    mutate(client, "POST", "/api/v1/services", json=AUTH_SERVICE)
    r = mutate(client, "PATCH", "/api/v1/services/auth-app/endpoints/web/auth",
               json={"auth": {"type": "basic", "credentials_ref": "hunter2"}})
    assert r.status_code == 422


def test_service_access_resolves_url_and_auth(client):
    mutate(client, "POST", "/api/v1/services", json=AUTH_SERVICE)
    r = client.get("/api/v1/services/auth-app/access",
                   headers={"X-Forwarded-Host": "100.85.245.79"})
    assert r.status_code == 200, r.text
    ep = r.json()["endpoints"][0]
    assert ep["url"] == "http://100.85.245.79:50180"
    assert ep["reachable"] is True
    assert ep["auth"] == AUTH_EXPECTED


def test_service_access_internal_endpoint_has_no_url(client):
    payload = {**VALID_SERVICE, "id": "internal-app", "name": "Internal",
               "endpoints": [{"name": "api", "type": "http", "exposure": "internal",
                              "container": "backend", "container_port": 8000}]}
    mutate(client, "POST", "/api/v1/services", json=payload)
    ep = client.get("/api/v1/services/internal-app/access").json()["endpoints"][0]
    assert ep["url"] is None
    assert ep["reachable"] is False
    assert ep["auth"]["type"] == "none"
