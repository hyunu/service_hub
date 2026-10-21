"""WebAuthn (생체인식/패스워드리스) 테스트 (REQUIREMENTS §15).

가짜 인증기(FakeAuthenticator)가 실제 P-256 키쌍으로 서명까지 수행해,
등록 -> 목록 조회 -> 로그인 -> 세션 발급까지 **엔드투엔드**로 검증한다.
단순 플러밍 검증(설정 없음/챌린지 만료/인증 필요)도 함께 본다.
"""
from __future__ import annotations

import hashlib
import json
import struct

import cbor2
import pytest
from app.config import Settings
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from webauthn.helpers import bytes_to_base64url

from conftest import mutate

RP_ID = "example.test"
ORIGIN = "https://example.test"
ADMIN = {"username": "admin", "password": "secure-pass-123"}


# ------------------------------ 가짜 인증기 ------------------------------

def _b64(buf: bytes) -> str:
    return bytes_to_base64url(buf)


class FakeAuthenticator:
    """WebAuthn 행사를 재현하는 소프트웨어 인증기.

    - 등록: fmt "none" 증명 서명 없음 (구조만 정확하면 됨)
    - 로그인: ES256 실제 서명 (서버가 검증한다)
    """

    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = hashlib.sha256(self.key.private_numbers().private_value
                                            .to_bytes(32, "big")).digest()
        self.sign_count = 0

    def _client_data_json(self, typ: str, challenge_b64: str) -> bytes:
        return json.dumps({
            "type": typ,
            "challenge": challenge_b64,
            "origin": ORIGIN,
            "crossOrigin": False,
        }, separators=(",", ":")).encode("utf-8")

    def _auth_data(self, flags: int, attested: bytes | None) -> bytes:
        rp_hash = hashlib.sha256(RP_ID.encode("utf-8")).digest()
        out = rp_hash + bytes([flags]) + struct.pack(">I", self.sign_count)
        if attested is not None:
            out += attested
        return out

    def _cose_public_key(self) -> bytes:
        nums = self.key.public_key().public_numbers()
        return cbor2.dumps({
            1: 2,                     # kty: EC2
            3: -7,                    # alg: ES256
            -1: 1,                    # crv: P-256
            -2: nums.x.to_bytes(32, "big"),
            -3: nums.y.to_bytes(32, "big"),
        })

    def register_credential(self, challenge_b64: str) -> dict:
        client_data = self._client_data_json("webauthn.create", challenge_b64)
        aaguid = b"\x00" * 16
        cred_len = struct.pack(">H", len(self.credential_id))
        attested = (aaguid + cred_len + self.credential_id + self._cose_public_key())
        # flags: UP(0x01) | UV(0x04) | AT(0x40)
        auth_data = self._auth_data(0x45, attested)
        attestation_object = cbor2.dumps({"fmt": "none", "attStmt": {},
                                          "authData": auth_data})
        return {
            "id": _b64(self.credential_id),
            "rawId": _b64(self.credential_id),
            "type": "public-key",
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
            "response": {
                "clientDataJSON": _b64(client_data),
                "attestationObject": _b64(attestation_object),
                "transports": ["internal", "hybrid"],
            },
        }

    def assertion_credential(self, challenge_b64: str, *,
                             tamper_signature: bool = False) -> dict:
        client_data = self._client_data_json("webauthn.get", challenge_b64)
        self.sign_count += 1
        # flags: UP(0x01) | UV(0x04)
        auth_data = self._auth_data(0x05, None)
        to_sign = auth_data + hashlib.sha256(client_data).digest()
        der = self.key.sign(to_sign, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        if tamper_signature:
            signature = bytes([signature[0] ^ 0xFF]) + signature[1:]
        return {
            "id": _b64(self.credential_id),
            "rawId": _b64(self.credential_id),
            "type": "public-key",
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
            "response": {
                "clientDataJSON": _b64(client_data),
                "authenticatorData": _b64(auth_data),
                "signature": _b64(signature),
            },
        }


# --------------------------------- 픽스처 ---------------------------------

@pytest.fixture()
def wa_client(app_factory, settings):
    """WebAuthn이 설정된(HTTPS 전제) 관리자 클라이언트."""
    s = Settings(db_path=settings.db_path,
                 status_cache=settings.status_cache,
                 monitor_enabled=False,
                 webauthn_rp_id=RP_ID,
                 webauthn_origin=ORIGIN,
                 _env_file=None)
    c = app_factory(s=s, admin=True)
    yield c
    c.__exit__(None, None, None)


def _begin_register(client) -> dict:
    r = mutate(client, "POST", "/api/v1/webauthn/register/begin",
               json={"label": "테스트 인증기"})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------- 비활성화 ---------------------------------

def test_disabled_without_config(client):
    """rp_id/origin이 없으면 모든 엔드포인트가 503 webauthn_disabled."""
    for method, path, payload in [
        ("GET", "/api/v1/webauthn/credentials", None),
        ("POST", "/api/v1/webauthn/register/begin", {"label": "x"}),
        ("POST", "/api/v1/webauthn/login/begin", {"username": "admin"}),
    ]:
        if method == "GET":
            r = client.get(path)
        else:
            r = mutate(client, "POST", path, json=payload)
        assert r.status_code == 503, (path, r.status_code, r.text)
        assert r.json()["code"] == "webauthn_disabled"


def test_disabled_when_origin_missing(app_factory, settings):
    """rp_id만 있고 origin이 없으면(부분 설정) 꺼진 상태를 유지한다."""
    s = Settings(db_path=settings.db_path, status_cache=settings.status_cache,
                 monitor_enabled=False, webauthn_rp_id=RP_ID, webauthn_origin="",
                 _env_file=None)
    c = app_factory(s=s, admin=True)
    try:
        r = mutate(c, "POST", "/api/v1/webauthn/register/begin", json={"label": "x"})
        assert r.status_code == 503
        assert r.json()["code"] == "webauthn_disabled"
    finally:
        c.__exit__(None, None, None)


# ------------------------------- 등록 인증/권한 -------------------------------

def test_register_begin_requires_auth(anon_client, app_factory, settings):
    """로그인 세션 없이 챌린지를 받을 수 없다 (CSRF 포함)."""
    s = Settings(db_path=settings.db_path, status_cache=settings.status_cache,
                 monitor_enabled=False, webauthn_rp_id=RP_ID, webauthn_origin=ORIGIN,
                 _env_file=None)
    c = app_factory(s=s)          # 관리자 설정 X
    try:
        # 관리자 설정 후 로그아웃 = 세션 없음
        c.post("/api/v1/setup/admin", json=ADMIN)
        c.post("/api/v1/auth/logout")
        r = c.post("/api/v1/webauthn/register/begin", json={"label": "x"})
        assert r.status_code == 401
        assert r.json()["code"] == "unauthorized"
    finally:
        c.__exit__(None, None, None)


def test_register_begin_requires_csrf(wa_client):
    r = wa_client.post("/api/v1/webauthn/register/begin", json={"label": "x"},
                       headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    assert r.json()["code"] == "csrf"


def test_register_begin_returns_options(wa_client):
    body = _begin_register(wa_client)
    pk = body["publicKey"]
    assert pk["rp"]["id"] == RP_ID
    assert pk["challenge"]                      # base64url 문자열
    assert pk["user"]["name"] == "admin"
    assert pk["user"]["id"]                     # base64url(user_id)
    assert body["expires_in"] >= 60


def test_register_finish_without_challenge(wa_client):
    """챌린지 없이(또는 만료 후) 등록 마무리를 시도하면 거부된다."""
    auth = FakeAuthenticator()
    r = mutate(wa_client, "POST", "/api/v1/webauthn/register/finish",
               json=auth.register_credential("ZmFrZS1jaGFsbGVuZ2U"))
    assert r.status_code == 400
    assert r.json()["code"] == "challenge_expired"


def test_register_challenge_is_single_use(wa_client):
    """동일 챌린지로 두 번 등록할 수 없다 (재사용 방지)."""
    options = _begin_register(wa_client)
    auth = FakeAuthenticator()
    cred = auth.register_credential(options["publicKey"]["challenge"])

    r = mutate(wa_client, "POST", "/api/v1/webauthn/register/finish", json=cred)
    assert r.status_code == 200, r.text

    r2 = mutate(wa_client, "POST", "/api/v1/webauthn/register/finish", json=cred)
    assert r2.status_code == 400
    assert r2.json()["code"] == "challenge_expired"


# ------------------------------ 엔드투엔드 플로우 ------------------------------

def test_full_register_and_login_flow(wa_client):
    """등록 -> 목록 -> 로그아웃 -> 패스워드리스 로그인 -> 세션 발급."""
    auth = FakeAuthenticator()

    # 1) 등록
    options = _begin_register(wa_client)
    reg = mutate(wa_client, "POST", "/api/v1/webauthn/register/finish",
                 json=auth.register_credential(options["publicKey"]["challenge"]))
    assert reg.status_code == 200, reg.text
    assert reg.json()["ok"] is True
    cred_pk = reg.json()["id"]

    # 2) 목록 조회 — 공개키 원문은 노출하지 않는다
    lst = wa_client.get("/api/v1/webauthn/credentials")
    assert lst.status_code == 200
    items = lst.json()["items"]
    assert len(items) == 1
    assert items[0]["label"] == "테스트 인증기"
    assert items[0]["last_used_at"] is None
    assert "public_key" not in items[0]

    # 3) 감사 로그에 등록 기록
    audit = wa_client.get("/api/v1/audit-logs")
    if audit.status_code == 200:
        actions = [a.get("action") for a in audit.json().get("items", [])]
        assert "webauthn.credential_register" in actions

    # 4) 로그아웃 후 패스워드리스 로그인
    wa_client.post("/api/v1/auth/logout")
    assert wa_client.get("/api/v1/auth/session").json()["authenticated"] is False

    login_opt = mutate(wa_client, "POST", "/api/v1/webauthn/login/begin",
                       json={"username": "admin"})
    assert login_opt.status_code == 200, login_opt.text
    challenge = login_opt.json()["publicKey"]["challenge"]

    finish_body = auth.assertion_credential(challenge)
    finish_body["username"] = "admin"
    fin = wa_client.post("/api/v1/webauthn/login/finish", json=finish_body)
    assert fin.status_code == 200, fin.text
    assert fin.json()["method"] == "webauthn"
    assert fin.json()["csrf_token"]
    # 새 세션의 CSRF 토큰으로 교체 (프론트엔드도 동일하게 처리해야 함)
    wa_client.csrf = fin.json()["csrf_token"]

    # 세션이 실제로 동작하는가?
    sess = wa_client.get("/api/v1/auth/session")
    assert sess.status_code == 200
    assert sess.json()["authenticated"] is True
    assert sess.json()["username"] == "admin"

    # 5) 다음 인증에서 sign_count가 갱신된다
    assert wa_client.post("/api/v1/auth/logout").status_code == 200
    opt2 = mutate(wa_client, "POST", "/api/v1/webauthn/login/begin",
                  json={"username": "admin"})
    body2 = auth.assertion_credential(opt2.json()["publicKey"]["challenge"])
    body2["username"] = "admin"
    fin2 = wa_client.post("/api/v1/webauthn/login/finish", json=body2)
    assert fin2.status_code == 200, fin2.text
    assert auth.sign_count == 2
    wa_client.csrf = fin2.json()["csrf_token"]

    # 6) 자격증명 삭제 (본인 것) — fin2 세션이 살아 있는 상태
    delr = mutate(wa_client, "DELETE", f"/api/v1/webauthn/credentials/{cred_pk}")
    assert delr.status_code == 200, delr.text
    assert wa_client.get("/api/v1/webauthn/credentials").json()["items"] == []


def test_login_rejects_tampered_signature(wa_client):
    """서명이 조작되면 패스워드리스 로그인이 거부되고 잠금 카운트가 오른다."""
    auth = FakeAuthenticator()
    options = _begin_register(wa_client)
    mutate(wa_client, "POST", "/api/v1/webauthn/register/finish",
           json=auth.register_credential(options["publicKey"]["challenge"]))
    wa_client.post("/api/v1/auth/logout")

    for _ in range(5):
        opt = mutate(wa_client, "POST", "/api/v1/webauthn/login/begin",
                     json={"username": "admin"})
        assert opt.status_code == 200, opt.text
        body = auth.assertion_credential(opt.json()["publicKey"]["challenge"],
                                         tamper_signature=True)
        body["username"] = "admin"
        fin = wa_client.post("/api/v1/webauthn/login/finish", json=body)
        assert fin.status_code == 401, fin.text
        assert fin.json()["code"] == "invalid_credentials"

    # 5회 실패 후 패스워드/패스워드리스 모두 잠긴다 (기존 잠금 제한 재사용)
    locked = mutate(wa_client, "POST", "/api/v1/webauthn/login/begin",
                    json={"username": "admin"})
    assert locked.status_code == 429
    assert locked.json()["code"] == "locked"

    pw = wa_client.post("/api/v1/auth/login", json=ADMIN)
    assert pw.status_code == 429


def test_login_finish_rejects_unknown_credential(wa_client):
    """등록되지 않은 자격증명 ID로는 로그인할 수 없다."""
    real = FakeAuthenticator()
    options = _begin_register(wa_client)
    mutate(wa_client, "POST", "/api/v1/webauthn/register/finish",
           json=real.register_credential(options["publicKey"]["challenge"]))
    wa_client.post("/api/v1/auth/logout")

    opt = mutate(wa_client, "POST", "/api/v1/webauthn/login/begin",
                 json={"username": "admin"})
    assert opt.status_code == 200, opt.text

    stranger = FakeAuthenticator()          # 저장소에 없는 자격증명
    body = stranger.assertion_credential(opt.json()["publicKey"]["challenge"])
    body["username"] = "admin"
    fin = wa_client.post("/api/v1/webauthn/login/finish", json=body)
    assert fin.status_code == 401
    assert fin.json()["code"] == "invalid_credentials"


def test_login_begin_unknown_user_rejected(wa_client):
    """등록되지 않은 사용자명은 401로 거부한다."""
    r = mutate(wa_client, "POST", "/api/v1/webauthn/login/begin",
               json={"username": "nobody"})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


def test_login_begin_without_registered_passkey(wa_client):
    """관리자에게 등록된 키가 없으면 400 no_credentials 로 비밀번호 로그인을 안내한다."""
    r = mutate(wa_client, "POST", "/api/v1/webauthn/login/begin",
               json={"username": "admin"})
    assert r.status_code == 400
    assert r.json()["code"] == "no_credentials"


def test_credential_delete_not_found(wa_client):
    r = mutate(wa_client, "DELETE", "/api/v1/webauthn/credentials/99999")
    assert r.status_code == 404
    assert r.json()["code"] == "credential_not_found"
