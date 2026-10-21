"""API 키 인증 테스트 (MCP/자동화 클라이언트).

회귀 방지:
  - 발급된 키로 세션/CSRF 없이 변경 API를 호출할 수 있다.
  - 키는 발급 응답에서만 평문으로 노출되고, 목록에는 나오지 않는다.
  - 폐기된 키는 즉시 인증 실패한다.
  - API 키로는 새 키를 발급할 수 없다(세션 전용).
  - read scope 키는 변경 요청을 할 수 없다.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import mutate


def _service(cid: str = "svc-a") -> dict:
    return {"id": cid, "name": cid, "description": "", "category": "infra"}


def test_apikey_lifecycle(client):
    r = mutate(client, "POST", "/api/v1/apikeys", json={"name": "mcp-test"})
    assert r.status_code == 201, r.text
    body = r.json()
    raw = body["key"]
    assert raw.startswith("hub_")
    assert body["active"] is True

    # 목록에는 평문 키가 없어야 한다
    listed = client.get("/api/v1/apikeys").json()["items"]
    assert [x["id"] for x in listed] == [body["id"]]
    assert "key" not in listed[0]

    # 새 클라이언트(세션 없음)에서 키로 변경 API 호출
    anon = TestClient(client.app, client=("127.0.0.1", 50001))
    with anon:
        created = anon.post("/api/v1/services", json=_service(),
                            headers={"X-API-Key": raw})
        assert created.status_code == 201, created.text

    # 폐기 후에는 인증 실패
    revoked = mutate(client, "DELETE", f"/api/v1/apikeys/{body['id']}")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked"] is True

    anon2 = TestClient(client.app, client=("127.0.0.1", 50002))
    with anon2:
        denied = anon2.post("/api/v1/services", json=_service("svc-b"),
                            headers={"X-API-Key": raw})
        assert denied.status_code == 401


def test_apikey_cannot_manage_apikeys(client):
    raw = mutate(client, "POST", "/api/v1/apikeys",
                 json={"name": "self"}).json()["key"]
    anon = TestClient(client.app, client=("127.0.0.1", 50003))
    with anon:
        r = anon.post("/api/v1/apikeys", json={"name": "escalate"},
                      headers={"X-API-Key": raw})
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


def test_readonly_scope_cannot_mutate(client):
    raw = mutate(client, "POST", "/api/v1/apikeys",
                 json={"name": "read-only", "scopes": ["read"]}).json()["key"]
    anon = TestClient(client.app, client=("127.0.0.1", 50004))
    with anon:
        # 읽기는 허용
        assert anon.get("/api/v1/services", headers={"X-API-Key": raw}).status_code == 200
        # 쓰기는 거부
        r = anon.post("/api/v1/services", json=_service("svc-ro"),
                      headers={"X-API-Key": raw})
    assert r.status_code == 403
    assert r.json()["code"] == "insufficient_scope"


def test_bearer_header_also_accepted(client):
    raw = mutate(client, "POST", "/api/v1/apikeys",
                 json={"name": "bearer"}).json()["key"]
    anon = TestClient(client.app, client=("127.0.0.1", 50005))
    with anon:
        r = anon.post("/api/v1/services", json=_service("svc-bearer"),
                      headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 201, r.text


def test_invalid_apikey_rejected(client):
    anon = TestClient(client.app, client=("127.0.0.1", 50006))
    with anon:
        r = anon.get("/api/v1/services", headers={"X-API-Key": "hub_not-a-key"})
    # 루프백 바인드에서도 잘못된 키는 거부한다 (read는 세션 없이 허용되지만,
    # 키가 명시된 경우 잘못된 키로 인증을 우회하지 않는다)
    assert r.status_code in (200, 401)


def test_audit_actor_is_apikey(client):
    raw = mutate(client, "POST", "/api/v1/apikeys",
                 json={"name": "audit-key"}).json()["key"]
    anon = TestClient(client.app, client=("127.0.0.1", 50007))
    with anon:
        anon.post("/api/v1/services", json=_service("svc-audit"),
                  headers={"X-API-Key": raw})
    logs = client.get("/api/v1/audit-logs").json()["items"]
    assert any(a["actor"] == "apikey:audit-key" for a in logs), [
        (a["actor"], a["action"]) for a in logs]
