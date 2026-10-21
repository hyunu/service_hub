"""POST /services 두 가지 payload 형식 테스트.

대시보드 등록 폼/JSON 붙여넣기는 service.yaml 중첩 형식으로 보내고,
CLI/스크립트는 평탄 형식을 쓴다. 둘 다 동작해야 한다 (회귀 방지).
"""
from __future__ import annotations

from conftest import mutate


NESTED = {
    "service": {"id": "nested-svc", "name": "Nested Service",
                "description": "중첩 형식", "category": "infra"},
    "deployment": {"type": "docker-compose", "deployment_path": "/srv/services/nested-svc",
                   "compose_file": "compose.yaml"},
}


def test_create_service_with_nested_payload(client):
    """대시보드가 보내는 {service, deployment} 형식으로 등록된다."""
    r = mutate(client, "POST", "/api/v1/services", json=NESTED)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == "nested-svc"
    assert body["name"] == "Nested Service"

    detail = client.get("/api/v1/services/nested-svc").json()
    assert detail["deployment_type"] == "docker-compose"
    assert detail["deployment_path"] == "/srv/services/nested-svc"
    assert detail["compose_file"] == "compose.yaml"


def test_create_service_with_nested_payload_and_components(client):
    """스펙의 containers/endpoints가 컴포넌트/엔드포인트로 저장된다."""
    payload = {
        "schema_version": 1,
        "service": {"id": "spec-svc", "name": "Spec Service",
                    "description": "스펙 형식", "category": "web"},
        "source": {"repository_url": "https://example.com/r.git", "branch": "dev"},
        "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
        "containers": [{"name": "web", "role": "frontend"},
                       {"name": "api", "role": "backend", "required": False}],
        "endpoints": [{"name": "web", "type": "http", "exposure": "host",
                       "host_port": 18080, "container": "web", "container_port": 80}],
        "resources": {"memory_limit_mb": 512},
    }
    r = mutate(client, "POST", "/api/v1/services", json=payload)
    assert r.status_code == 201, r.text

    detail = client.get("/api/v1/services/spec-svc").json()
    assert sorted(c["name"] for c in detail["components"]) == ["api", "web"]
    required = {c["name"]: c["required"] for c in detail["components"]}
    assert required == {"api": False, "web": True}
    assert detail["endpoints"][0]["host_port"] == 18080
    assert detail["repository_url"] == "https://example.com/r.git"
    assert detail["branch"] == "dev"


def test_create_service_flat_payload_still_works(client):
    """기존 평탄 형식도 그대로 동작한다 (CLI/스크립트 호환)."""
    r = mutate(client, "POST", "/api/v1/services", json={
        "id": "flat-svc", "name": "Flat", "description": "평탄 형식",
        "category": "backend", "deployment_type": "manual",
        "deployment_path": "/srv/services/flat-svc",
    })
    assert r.status_code == 201, r.text
    detail = client.get("/api/v1/services/flat-svc").json()
    assert detail["deployment_type"] == "manual"


def test_create_service_missing_required_fields(client):
    """중첩 형식이어도 필수값이 없으면 422 + 읽을 수 있는 메시지."""
    r = mutate(client, "POST", "/api/v1/services", json={
        "service": {"name": "이름만 있음"},
        "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    })
    assert r.status_code == 422
    assert r.json()["code"] == "missing_fields"


def test_create_service_invalid_id(client):
    r = mutate(client, "POST", "/api/v1/services", json={
        "service": {"id": "Bad_ID", "name": "X", "description": "d", "category": "web"},
        "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    })
    assert r.status_code == 422
    assert r.json()["code"] == "invalid_service_id"
