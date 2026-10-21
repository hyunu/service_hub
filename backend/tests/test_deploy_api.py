"""배포 API 테스트 — 계획(읽기 전용) 및 실행(게이트) (REQUIREMENTS §13)."""
from __future__ import annotations

from conftest import mutate

SPEC_BODY = {
    "schema_version": 1,
    "service": {"id": "sample-app", "name": "Sample", "description": "샘플",
                "category": "web"},
    "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    "containers": [{"name": "app", "role": "backend", "required": True}],
}


def test_plan_endpoint_returns_ready(client):
    r = mutate(client, "POST", "/api/v1/deployments/plan", json=SPEC_BODY)
    assert r.status_code == 200
    data = r.json()
    assert data["result"] in ("READY", "BLOCKED")
    assert data["runtime_unchanged"] is True


def test_plan_accepts_cli_service_definition_payload(client):
    r = mutate(client, "POST", "/api/v1/deployments/plan",
               json={"service_definition": SPEC_BODY})
    assert r.status_code == 200
    assert r.json()["service"] == "sample-app"


def test_plan_endpoint_invalid_spec_422(client):
    bad = {**SPEC_BODY, "schema_version": 9}
    r = mutate(client, "POST", "/api/v1/deployments/plan", json=bad)
    assert r.status_code == 422
    assert r.json()["code"] == "unsupported_schema_version"


def test_plan_requires_auth(anon_client):
    r = anon_client.post("/api/v1/deployments/plan", json=SPEC_BODY)
    assert r.status_code in (401, 403)


def test_apply_still_locked_when_deploy_disabled(client):
    r = mutate(client, "POST", "/api/v1/deployments",
               json={"service_id": "sample-app", "spec": SPEC_BODY})
    assert r.status_code == 503
    assert r.json()["code"] == "deploy_disabled"
