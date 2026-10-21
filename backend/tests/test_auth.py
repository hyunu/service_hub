"""인증/설정 마법사 테스트 (REQUIREMENTS §15).

``anon_client`` = 완전 익명(설정/세션 없음), ``client`` = 관리자 설정 + 로그인 완료.
"""
from __future__ import annotations

from app.security import mask_env_dict, masked

ADMIN = {"username": "admin", "password": "secure-pass-123"}


def test_first_run_requires_setup(anon_client):
    r = anon_client.get("/api/v1/auth/session")
    assert r.json() == {"authenticated": False, "setup_required": True}
    r2 = anon_client.get("/api/v1/setup/status")
    assert r2.json()["setup_required"] is True


def test_admin_created_once_no_default_password(anon_client):
    r = anon_client.post("/api/v1/setup/admin", json=ADMIN)
    assert r.status_code == 201, r.text
    assert anon_client.cookies.get("hub_session")       # 세션 쿠키 설정됨
    r2 = anon_client.post("/api/v1/setup/admin", json={"username": "admin2",
                                                       "password": "secure-pass-456"})
    assert r2.status_code == 409
    assert r2.json()["code"] == "already_setup"


def test_weak_password_rejected(anon_client):
    r = anon_client.post("/api/v1/setup/admin", json={"username": "admin", "password": "short"})
    assert r.status_code == 422


def test_wrong_password_401(anon_client):
    anon_client.post("/api/v1/setup/admin", json=ADMIN)
    anon_client.post("/api/v1/auth/logout")
    r = anon_client.post("/api/v1/auth/login",
                         json={"username": "admin", "password": "wrong-pass"})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


def test_login_lockout_after_5_failures(anon_client):
    anon_client.post("/api/v1/setup/admin", json=ADMIN)
    anon_client.post("/api/v1/auth/logout")
    for _ in range(5):
        anon_client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    r = anon_client.post("/api/v1/auth/login", json=ADMIN)
    assert r.status_code == 429
    assert r.json()["code"] == "locked"


def test_mutation_requires_auth(anon_client):
    """루프백에서도 변경 작업은 인증(+CSRF)이 필요하다."""
    r = anon_client.post("/api/v1/services", json={"id": "x-app", "name": "X",
                                                   "description": "d", "category": "web"})
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


def test_mutation_requires_csrf(auth_client):
    r = auth_client.post("/api/v1/services", json={"id": "x-app", "name": "X",
                                                  "description": "d", "category": "web"},
                         headers={"X-CSRF-Token": "forged-token"})
    assert r.status_code == 403
    assert r.json()["code"] == "csrf"


def test_authenticated_mutation_ok(auth_client):
    r = auth_client.post("/api/v1/services", json={"id": "x-app", "name": "X",
                                                   "description": "d", "category": "web"},
                         headers={"X-CSRF-Token": auth_client.csrf})
    assert r.status_code == 201, r.text


def test_reads_open_on_loopback_only(app_factory, settings):
    """루프백 전용 바인드에서는 로컬 CLI용 GET 허용. 비루프백에서는 전체 인증."""
    c = app_factory()   # 설정 기본값 = 127.0.0.1 (루프백)
    assert c.get("/api/v1/system/status").status_code == 200
    c.__exit__(None, None, None)

    external = settings.model_copy(update={"bind": "0.0.0.0"})
    c2 = app_factory(s=external)   # 비루프백 바인드
    r = c2.get("/api/v1/system/status")
    assert r.status_code == 401, "외부 바인드인데 인증 없이 읽기가 열려 있음"
    c2.__exit__(None, None, None)


def test_secret_masking():
    assert masked("hunter2secret") == "hu****et"
    assert masked("ab") == "****"
    env = {"DB_PASSWORD": "p1", "PLAIN": "ok", "API_TOKEN": "t1"}
    masked_env = mask_env_dict(env)
    assert masked_env["DB_PASSWORD"] != "p1"
    assert masked_env["API_TOKEN"] != "t1"
    assert masked_env["PLAIN"] == "ok"


def test_no_arbitrary_shell_endpoint(anon_client):
    """임의 셸 실행 API가 존재하지 않아야 한다 (§15.7)."""
    for path in ("/api/v1/exec", "/api/v1/shell", "/api/v1/system/exec",
                 "/api/v1/containers/{cid}/exec", "/api/v1/deployments/exec"):
        r = anon_client.post(path.replace("{cid}", "c1"), json={"cmd": "rm -rf /"})
        assert r.status_code in (404, 405, 503), f"예상 밖 엔드포인트 응답: {path} → {r.status_code}"
