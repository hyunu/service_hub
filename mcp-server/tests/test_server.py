"""MCP 도구 등록/동작 테스트."""
from __future__ import annotations

import asyncio

import pytest

from hub_mcp import server as srv


def test_tools_are_exposed():
    tools = asyncio.run(srv.server.list_tools())
    names = {t.name for t in tools}
    required = {
        "hub_status", "hub_services_list", "hub_service_get", "hub_service_register",
        "hub_containers_list", "hub_orphans_list", "hub_orphans_attach",
        "hub_ports_list", "hub_service_logs", "hub_deploy_plan", "hub_deploy_apply",
        "hub_deploy_status",
    }
    assert required <= names
    # 모든 도구는 설명을 가져야 한다 (AI가 선택 근거로 사용)
    assert all(t.description for t in tools)


class FakeClient:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def validate_spec(self, spec):
        return {"valid": True, "spec": spec, "errors": []}

    def create_service(self, payload):
        self.created.append(payload)
        return {"id": payload["id"], "name": payload["name"], "status": "registered"}

    def get(self, path, params=None):
        return {"items": [], "path": path}

    def post(self, path, payload, timeout=None):
        self.created.append({"path": path, "payload": payload})
        return {"deployment_id": "dep-1", "status": "succeeded"}

    def post_raw(self, path, body, content_type, timeout=None):
        self.created.append({"path": path, "bytes": len(body),
                             "content_type": content_type})
        return {"ok": True, "files": 1, "target": "/srv/services/svc"}


SPEC = {
    "schema_version": 1,
    "service": {"id": "my-app", "name": "My App", "description": "설명", "category": "web"},
    "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
}


@pytest.fixture()
def fake(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(srv, "_client", lambda: client)
    return client


def test_register_dry_run_does_not_create(fake):
    out = srv.hub_service_register(SPEC, deployment_path="/srv/services/my-app", dry_run=True)
    assert out["ok"] is True
    assert out["data"]["dry_run"] is True
    assert out["data"]["payload"]["deployment_path"] == "/srv/services/my-app"
    assert fake.created == []


def test_register_creates_service(fake):
    out = srv.hub_service_register(SPEC, deployment_path="/srv/services/my-app")
    assert out["ok"] is True
    assert fake.created[0]["id"] == "my-app"
    assert out["data"]["service"]["status"] == "registered"


def test_deploy_apply_requires_confirmation(fake):
    out = srv.hub_deploy_apply(service_id="my-app", confirmed=False)
    assert out["ok"] is False
    assert out["code"] == "confirmation_required"
    assert fake.created == []


def test_deploy_apply_confirmed(fake):
    out = srv.hub_deploy_apply(service_id="my-app", confirmed=True)
    assert out["ok"] is True
    assert fake.created[0]["path"] == "/deployments"


def test_deploy_apply_requires_target(fake):
    out = srv.hub_deploy_apply(confirmed=True)
    assert out["ok"] is False
    assert out["code"] == "spec_required"


def test_sync_source_dry_run(tmp_path):
    (tmp_path / "app.py").write_text("print(1)")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("x")
    out = srv.hub_service_sync_source("svc", str(tmp_path), dry_run=True)
    assert out["ok"] is True
    assert out["data"]["files"] == 1          # node_modules 제외
    assert out["data"]["dry_run"] is True


def test_sync_source_uploads(fake, tmp_path):
    (tmp_path / "app.py").write_text("print(1)")
    out = srv.hub_service_sync_source("svc", str(tmp_path))
    assert out["ok"] is True
    assert out["data"]["files"] == 1
    # 서버 응답은 FakeClient 가 받는다
    assert out["data"]["result"] is not None


def test_sync_source_invalid_path():
    out = srv.hub_service_sync_source("svc", "/definitely/not/a/dir")
    assert out["ok"] is False
    assert out["code"] == "invalid_path"


def test_api_error_is_structured(fake, monkeypatch):
    from hub_mcp.client import HubApiError

    def boom(*args, **kwargs):
        raise HubApiError("로그인이 필요합니다", status=401, code="unauthorized")

    monkeypatch.setattr(fake, "get", boom)
    out = srv.hub_status()
    assert out["ok"] is False
    assert out["status"] == 401
    assert out["code"] == "unauthorized"


def test_full_workflow_tools_are_exposed():
    tools = asyncio.run(srv.server.list_tools())
    names = {t.name for t in tools}
    assert {"hub_service_spec_guide", "hub_service_validate", "hub_service_scaffold",
            "hub_deployments_list", "hub_deploy_rollback"} <= names


def test_spec_guide_calls_api(fake):
    out = srv.hub_service_spec_guide()
    assert out["ok"] is True
    assert out["data"]["path"] == "/services/spec/guide"


def test_validate_posts_spec(fake):
    out = srv.hub_service_validate(SPEC)
    assert out["ok"] is True
    assert fake.created[0]["path"] == "/services/validate"
    assert fake.created[0]["payload"]["service"]["id"] == "my-app"


def test_scaffold_posts_files(fake):
    out = srv.hub_service_scaffold("my-app", "a: 1\n", "services: {}\n")
    assert out["ok"] is True
    assert fake.created[0]["path"] == "/services/my-app/scaffold"
    assert fake.created[0]["payload"]["service_yaml"] == "a: 1\n"


def test_deployments_list(fake):
    out = srv.hub_deployments_list(service_id="my-app")
    assert out["ok"] is True
    assert out["data"]["path"] == "/deployments"


def test_rollback_requires_confirmation(fake):
    out = srv.hub_deploy_rollback("dep-1", confirmed=False)
    assert out["ok"] is False
    assert out["code"] == "confirmation_required"
    assert fake.created == []


def test_rollback_confirmed(fake):
    out = srv.hub_deploy_rollback("dep-1", confirmed=True)
    assert out["ok"] is True
    assert fake.created[0]["path"] == "/deployments/dep-1/rollback"


def test_deployment_guide_tool():
    """접속한 AI가 배포 모델을 스스로 파악할 수 있어야 한다."""
    out = srv.hub_deployment_guide()
    assert out["model"]["build_context"].startswith("/srv/services/")
    assert "sync_source" in out["model"]["source_sync"]
    assert "SSH" in out["model"]["source_sync"]
    assert any("hub_deploy_apply" in step for step in out["workflow"])
    assert "시크릿" in out["markdown"]
    assert "deploy_disabled" in out["error_codes"]


def test_deployment_guide_resource_and_prompt_are_exposed():
    resources = asyncio.run(srv.server.list_resources())
    assert any(r.uri == "hub://guides/deployment" for r in resources)
    prompts = asyncio.run(srv.server.list_prompts())
    assert any(p.name == "deploy_service" for p in prompts)


def test_deployment_guide_is_in_tool_list():
    tools = asyncio.run(srv.server.list_tools())
    assert any(t.name == "hub_deployment_guide" for t in tools)
