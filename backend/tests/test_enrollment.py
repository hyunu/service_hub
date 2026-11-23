"""일회용 등록 토큰 테스트 — 발급/교환/1회용/TTL/scope/세션 전용/게이트."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.db import get_session_factory
from app.models import EnrollmentToken
from app.routers.enrollment import reset_enrollment_state
from conftest import mutate


def _client(app_factory, settings, **overrides):
    s = Settings(db_path=settings.db_path, status_cache=settings.status_cache,
                 monitor_enabled=False, enable_enrollment=True,
                 _env_file=None, **overrides)
    return app_factory(s=s, admin=True)


def _create(client, name="ai-onboard", scopes=("*",), ttl=10):
    return mutate(client, "POST", "/api/v1/enrollment/tokens",
                  json={"name": name, "scopes": list(scopes), "ttl_minutes": ttl})


def test_enrollment_is_gated_off_by_default(client):
    r = mutate(client, "POST", "/api/v1/enrollment/tokens",
               json={"name": "x", "scopes": ["*"]})
    assert r.status_code == 503
    assert r.json()["code"] == "enrollment_disabled"
    r2 = client.post("/api/v1/auth/enroll", json={"token": "enroll_bogus"})
    assert r2.status_code == 503


def test_create_and_exchange_token(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        r = _create(client, name="pc-a", scopes=("*",))
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["token"].startswith("enroll_")
        assert data["scopes"] == ["*"]
        assert data["active"] is True

        # 교환 (세션/키 없이)
        r2 = client.post("/api/v1/auth/enroll", json={"token": data["token"]})
        assert r2.status_code == 200, r2.text
        issued = r2.json()
        assert issued["ok"] is True
        assert issued["api_key"].startswith("hub_")
        assert issued["scopes"] == ["*"]

        # 발급된 키로 인증
        caps = client.get("/api/v1/system/capabilities",
                          headers={"X-API-Key": issued["api_key"]})
        assert caps.status_code == 200
        assert caps.json()["auth"]["scopes"] == ["*"]

        # 1회용 — 재사용 거부
        r3 = client.post("/api/v1/auth/enroll", json={"token": data["token"]})
        assert r3.status_code == 401
        assert r3.json()["code"] == "invalid_enrollment_token"

        actions = [a["action"] for a in client.get("/api/v1/audit-logs").json()["items"]]
        assert "enrollment.create" in actions
        assert "enrollment.exchange" in actions
    finally:
        client.__exit__(None, None, None)
        reset_enrollment_state()


def test_expired_and_revoked_tokens_are_rejected(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        r = _create(client, name="expired")
        token_id = r.json()["id"]
        token = r.json()["token"]
        db = get_session_factory()()
        try:
            row = db.get(EnrollmentToken, token_id)
            row.expires_at = (datetime.now(timezone.utc)
                              - timedelta(minutes=1)).isoformat()
            db.commit()
        finally:
            db.close()
        r2 = client.post("/api/v1/auth/enroll", json={"token": token})
        assert r2.status_code == 401

        r3 = _create(client, name="to-revoke")
        token3 = r3.json()["token"]
        token3_id = r3.json()["id"]
        del_r = mutate(client, "DELETE", f"/api/v1/enrollment/tokens/{token3_id}")
        assert del_r.status_code == 200
        assert del_r.json()["revoked"] is True
        r4 = client.post("/api/v1/auth/enroll", json={"token": token3})
        assert r4.status_code == 401
    finally:
        client.__exit__(None, None, None)
        reset_enrollment_state()


def test_read_scope_key_cannot_mutate(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        r = _create(client, name="read-only", scopes=("read",))
        issued = client.post("/api/v1/auth/enroll",
                             json={"token": r.json()["token"]}).json()
        client.cookies.clear()   # API 키 경로만 검증 (세션 쿠키 제거)
        bad = client.post("/api/v1/services", headers={"X-API-Key": issued["api_key"]},
                          json={"service": {"id": "x", "name": "X",
                                            "description": "", "category": "web"}})
        assert bad.status_code == 403
        assert bad.json()["code"] == "insufficient_scope"
    finally:
        client.__exit__(None, None, None)
        reset_enrollment_state()


def test_api_key_cannot_manage_enrollment_tokens(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        r = _create(client, name="seed")
        issued = client.post("/api/v1/auth/enroll",
                             json={"token": r.json()["token"]}).json()
        client.cookies.clear()   # 세션 제거 — API 키만으로 관리 API 접근 시도
        # 세션 전용 — API 키로는 토큰 발급 불가
        r2 = client.post("/api/v1/enrollment/tokens",
                         headers={"X-API-Key": issued["api_key"]},
                         json={"name": "x", "scopes": ["*"]})
        assert r2.status_code == 401
    finally:
        client.__exit__(None, None, None)
        reset_enrollment_state()


def test_invalid_scope_and_rate_limit(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        bad = _create(client, name="bad", scopes=("admin",))
        assert bad.status_code == 422
        assert bad.json()["code"] == "invalid_scope"

        # IP별 실패 제한 (10회 후 429)
        codes = []
        for _ in range(11):
            codes.append(client.post("/api/v1/auth/enroll",
                                     json={"token": "enroll_bogus"}).status_code)
        assert codes[:10] == [401] * 10
        assert codes[10] == 429
    finally:
        client.__exit__(None, None, None)
        reset_enrollment_state()
