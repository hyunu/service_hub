"""MCP 클라이언트/변환 로직 테스트 (서버 불필요)."""
from __future__ import annotations

import pytest

from hub_mcp.client import HubApiError, HubClient, normalize_base
from hub_mcp.server import spec_to_service_payload


SPEC = {
    "schema_version": 1,
    "service": {"id": "my-app", "name": "My App", "description": "설명", "category": "web"},
    "source": {"repository_url": "https://example.com/repo.git", "branch": "main"},
    "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    "containers": [{"name": "web", "role": "frontend"}],
    "endpoints": [{"name": "web", "type": "http", "exposure": "host",
                   "host_port": 8080, "container": "web", "container_port": 80}],
}


def test_normalize_base():
    assert normalize_base("http://127.0.0.1:8420") == "http://127.0.0.1:8420/api/v1"
    assert normalize_base("http://127.0.0.1:8420/api/v1/") == "http://127.0.0.1:8420/api/v1"
    assert normalize_base("https://hub.example.com") == "https://hub.example.com/api/v1"


def test_spec_to_payload_maps_spec_fields():
    p = spec_to_service_payload(SPEC, "/srv/services/my-app")
    assert p["id"] == "my-app"
    assert p["deployment_type"] == "docker-compose"
    assert p["compose_file"] == "compose.yaml"
    assert p["deployment_path"] == "/srv/services/my-app"
    assert p["components"] == [{"name": "web", "role": "frontend"}]
    assert p["endpoints"][0]["host_port"] == 8080
    assert p["repository_url"] == "https://example.com/repo.git"


def test_payload_omits_none_values():
    p = spec_to_service_payload(SPEC)
    assert "deployment_path" not in p          # 미지정 시 필드를 만들지 않는다
    assert "version" not in p


def test_client_sends_api_key(monkeypatch):
    seen = {}

    def fake_request(method, url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs.get("headers")
        class R:
            status_code = 200
            content = b"{}"
            def json(self): return {}
        return R()

    monkeypatch.setattr("httpx.request", fake_request)
    c = HubClient(base_url="http://hub:8420", api_key="hub_test")
    c.get("/status")
    assert seen["url"] == "http://hub:8420/api/v1/status"
    assert seen["headers"]["X-API-Key"] == "hub_test"


def test_client_error_message(monkeypatch):
    def fake_request(method, url, **kwargs):
        class R:
            status_code = 403
            content = b'{"detail":"\\uc774 API \\ud0a4\\uc5d0\\ub294 \\uc4f0\\uae30 \\uad8c\\ud55c\\uc774 \\uc5c6\\uc2b5\\ub2c8\\ub2e4","code":"insufficient_scope"}'
            text = content.decode()
            def json(self): return {"detail": "이 API 키에는 쓰기 권한이 없습니다",
                                    "code": "insufficient_scope"}
        return R()

    monkeypatch.setattr("httpx.request", fake_request)
    c = HubClient(base_url="http://hub:8420", api_key="hub_x")
    with pytest.raises(HubApiError) as exc:
        c.post("/services", {})
    assert exc.value.status == 403
    assert exc.value.code == "insufficient_scope"
    assert "쓰기 권한" in str(exc.value)
