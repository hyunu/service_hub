"""원격(HTTP) MCP 모드의 API 키 인증 테스트.

원격 모드에서는 클라이언트가 매 요청에 X-API-Key(또는 Bearer)를 보내야 하며,
그 키가 허브 호출에 그대로 사용된다(도구 실행 컨텍스트로 전달).
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from hub_mcp import server as srv


def _app():
    async def ok(request):
        return PlainTextResponse(srv._REQUEST_API_KEY.get() or "none")

    app = Starlette(routes=[Route("/mcp", ok, methods=["POST"])])
    app.add_middleware(srv.RequireApiKeyMiddleware)
    return app


def test_requires_api_key():
    client = TestClient(_app())
    r = client.post("/mcp")
    assert r.status_code == 401
    assert "X-API-Key" in r.text


def test_api_key_is_forwarded_to_tool_context():
    client = TestClient(_app())
    r = client.post("/mcp", headers={"X-API-Key": "hub_test123"})
    assert r.status_code == 200
    assert r.text == "hub_test123"


def test_bearer_token_also_accepted():
    client = TestClient(_app())
    r = client.post("/mcp", headers={"Authorization": "Bearer hub_bearer"})
    assert r.status_code == 200
    assert r.text == "hub_bearer"


def test_client_uses_request_key_over_env(monkeypatch):
    monkeypatch.setenv("HUB_API_KEY", "hub_env")
    assert srv._client().api_key == "hub_env"

    token = srv._REQUEST_API_KEY.set("hub_request")
    try:
        assert srv._client().api_key == "hub_request"
    finally:
        srv._REQUEST_API_KEY.reset(token)
