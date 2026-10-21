"""관리자 초기화(비밀번호 분실 복구) 테스트 — REQUIREMENTS §15.18.

핵심 보안 성질:
  * 루프백이 아니면 복구 토큰 없이는 초기화할 수 없다.
  * 복구 토큰은 1회만 사용할 수 있다.
  * 초기화하면 기존 세션이 무효가 되고 설정 마법사가 다시 나타난다.
  * 관리자 자격 증명(비밀번호 해시·패스워드 키)만 지운다 — 서비스 데이터는 유지된다.
"""
from __future__ import annotations

import pytest

from app.config import Settings
from app.models import AuditLog, Service, Setting, WebAuthnCredential


def _session():
    from app.db import get_session_factory
    return get_session_factory()()


def _make_settings(base: Settings, **kw) -> Settings:
    return Settings(
        db_path=base.db_path,
        status_cache=base.status_cache,
        monitor_enabled=False,
        _env_file=None,
        **kw,
    )


def test_reset_requires_setup_state_first(anon_client):
    """관리자가 없으면 초기화할 필요가 없고 404로 거절한다."""
    assert anon_client.get("/api/v1/setup/status").json() == {"setup_required": True}
    r = anon_client.post("/api/v1/auth/reset-admin")
    assert r.status_code == 404
    assert r.json()["code"] == "not_setup"


def test_loopback_reset_clears_admin_and_invalidates_session(app_factory, settings):
    """루프백 요청은 초기화할 수 있고, 기존 세션은 무효가 된다."""
    client = app_factory(admin=True)
    try:
        assert client.get("/api/v1/setup/status").json() == {"setup_required": False}
        assert client.get("/api/v1/auth/session").json()["authenticated"] is True

        r = client.post("/api/v1/auth/reset-admin")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reset"] is True
        assert body["username"] == "admin"
        assert body["setup_required"] is True

        # 설정 마법사가 다시 나타난다
        assert client.get("/api/v1/setup/status").json() == {"setup_required": True}
        # 이전 세션은 무효
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False
        # 변경 작업은 세션 없이 수행할 수 없다 (401)
        r = client.post("/api/v1/auth/change-password",
                        json={"current_password": "secure-pass-123",
                              "new_password": "newer-pass-123"})
        assert r.status_code == 401
    finally:
        client.__exit__(None, None, None)


def test_reset_keeps_other_data(app_factory, settings):
    """서비스/포트 등 다른 데이터는 초기화로 지워지지 않는다."""
    client = app_factory(admin=True)
    try:
        with _session() as db:
            db.add(Service(id="keep-me", name="Keep Me", category="web"))
            db.commit()

        client.post("/api/v1/auth/reset-admin")

        with _session() as db:
            assert db.get(Service, "keep-me") is not None
    finally:
        client.__exit__(None, None, None)


def test_reset_removes_webauthn_credentials(app_factory, settings):
    """관리자에 등록된 패스워드 키도 함께 삭제된다."""
    from app.security import user_handle
    client = app_factory(admin=True)
    try:
        with _session() as db:
            db.add(WebAuthnCredential(
                credential_id="cred-1", public_key="pub", user_handle=user_handle("admin")))
            db.commit()

        client.post("/api/v1/auth/reset-admin")

        with _session() as db:
            assert db.query(WebAuthnCredential).all() == []
    finally:
        client.__exit__(None, None, None)


def test_reset_writes_audit_log(app_factory, settings):
    """초기화는 감사 로그에 남는다."""
    client = app_factory(admin=True)
    try:
        client.post("/api/v1/auth/reset-admin")
        with _session() as db:
            actions = [a.action for a in db.query(AuditLog).all()]
            assert "auth.admin_reset" in actions
    finally:
        client.__exit__(None, None, None)


def test_non_loopback_reset_without_token_is_forbidden(app_factory, settings, monkeypatch):
    """비루프백 + 토큰 없음 → 403 reset_not_allowed (인증 우회 금지)."""
    from app.config import set_settings
    import app.routers.auth as auth_router
    s = _make_settings(settings, admin_reset_token="")
    set_settings(s)
    client = app_factory(s=s)
    try:
        monkeypatch.setattr(auth_router, "_is_loopback", lambda request: False)
        r = client.post("/api/v1/auth/reset-admin")
        assert r.status_code == 403
        assert r.json()["code"] == "reset_not_allowed"
    finally:
        client.__exit__(None, None, None)


def test_non_loopback_reset_with_valid_token_succeeds(app_factory, settings, monkeypatch):
    """비루프백 + 올바른 토큰 → 초기화 성공, 토큰은 1회 사용."""
    from app.config import set_settings
    import app.routers.auth as auth_router
    s = _make_settings(settings, admin_reset_token="secret-token")
    set_settings(s)
    client = app_factory(admin=True, s=s)
    try:
        monkeypatch.setattr(auth_router, "_is_loopback", lambda request: False)
        r = client.post("/api/v1/auth/reset-admin",
                        headers={"X-Hub-Admin-Reset-Token": "secret-token"})
        assert r.status_code == 200, r.text
        r2 = client.post("/api/v1/auth/reset-admin",
                         headers={"X-Hub-Admin-Reset-Token": "secret-token"})
        assert r2.status_code == 403
        assert r2.json()["code"] == "reset_token_used"
    finally:
        client.__exit__(None, None, None)


def test_non_loopback_reset_with_wrong_token_is_rejected(app_factory, settings, monkeypatch):
    """비루프백 + 잘못된 토큰 → 403."""
    from app.config import set_settings
    import app.routers.auth as auth_router
    s = _make_settings(settings, admin_reset_token="secret-token")
    set_settings(s)
    client = app_factory(s=s)
    try:
        monkeypatch.setattr(auth_router, "_is_loopback", lambda request: False)
        r = client.post("/api/v1/auth/reset-admin",
                        headers={"X-Hub-Admin-Reset-Token": "nope"})
        assert r.status_code == 403
        assert r.json()["code"] == "reset_token_invalid"
    finally:
        client.__exit__(None, None, None)


def test_new_admin_gets_new_session_epoch(app_factory, settings):
    """관리자를 새로 만들면 epoch가 바뀌어 이전 세션과 구분된다."""
    from app.security import admin_epoch
    client = app_factory(admin=True)
    try:
        with _session() as db:
            first = admin_epoch(db)
        assert first
        client.post("/api/v1/auth/reset-admin")
        r = client.post("/api/v1/setup/admin",
                        json={"username": "admin2", "password": "another-pass-123"})
        assert r.status_code == 201, r.text
        with _session() as db:
            second = admin_epoch(db)
        assert second and second != first
    finally:
        client.__exit__(None, None, None)
