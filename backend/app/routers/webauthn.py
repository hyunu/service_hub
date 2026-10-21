"""WebAuthn (생체인식/패스워드리스) 라우터 (REQUIREMENTS §15).

WebAuthn은 브라우저가 **보안 컨텍스트(HTTPS)** 에서만 허용한다. 따라서
``HUB_WEBAUTHN_RP_ID`` + ``HUB_WEBAUTHN_ORIGIN`` 이 모두 설정돼 있을 때만
동작하며, 그 외에는 모든 엔드포인트가 503 ``webauthn_disabled``를 반환한다.

플로우:
  등록  POST /webauthn/register/begin  -> 챌린지 발급(세션 필수)
        POST /webauthn/register/finish -> 증명 검증 + 공개키 저장
  로그인 POST /webauthn/login/begin     -> 챌린지 발급(익명, 잠금 제한 적용)
        POST /webauthn/login/finish    -> 서명 검증 + 세션 발급

보안 원칙:
  - 서버에는 **공개키만** 저장한다 (생체 정보/비밀키는 저장되지 않음).
  - 챌린지는 1회용 + 5분 TTL이며 메모리에만 둔다 (재사용 방지).
  - 패스워드 로그인과 동일한 잠금 제한(5회/5분)을 공유한다.
  - 임의 셸 실행 경로 없음 — WebAuthn 표준 검증만 수행한다.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from cbor2 import loads as cbor_loads
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from ..config import get_settings
from ..db import get_db
from ..models import Setting, WebAuthnCredential, utcnow
from ..security import (
    SESSION_COOKIE, HubError, admin_epoch, create_session, get_read_actor,
    is_locked, lockout_minutes, register_failure, require_auth, user_handle,
)
from ..services.events import record_audit

router = APIRouter(tags=["webauthn"])

# ------------------------------ 챌린지 저장소 ------------------------------
# 1회용 + TTL. 프로세스 메모리에만 두며, 재시작 시 무효화된다 (정상 동작).
_CHALLENGES: dict[str, tuple[bytes, float, dict]] = {}
_CH_LOCK = threading.Lock()
CHALLENGE_TTL = 300  # 초


def _put_challenge(key: str, challenge: bytes, meta: dict | None = None) -> None:
    with _CH_LOCK:
        _CHALLENGES[key] = (challenge, time.time() + CHALLENGE_TTL, meta or {})


def _pop_challenge(key: str) -> tuple[bytes, dict] | None:
    """1회용 챌린지 꺼내기 — 사용 즉시 삭제된다 (재사용 불가)."""
    with _CH_LOCK:
        item = _CHALLENGES.pop(key, None)
    if item is None:
        return None
    challenge, expires_at, meta = item
    if time.time() > expires_at:
        return None
    return challenge, meta


def reset_webauthn_state() -> None:
    """남은 챌린지를 비운다 (테스트 격리용)."""
    with _CH_LOCK:
        _CHALLENGES.clear()


# --------------------------------- 공통 ---------------------------------

def _require_enabled() -> "Any":  # noqa: ANN401 -> Settings
    settings = get_settings()
    if not settings.webauthn_enabled:
        raise HubError(status_code=503,
                        detail="WebAuthn이 설정되지 않았습니다 (HTTPS/보안 컨텍스트 필요)",
                        code="webauthn_disabled")
    return settings


def _admin_username(db: Session) -> str | None:
    row = db.get(Setting, "admin")
    if row is None:
        return None
    username = row.value.get("username")
    return str(username) if username else None


def _credentials_for(db: Session, username: str) -> list[WebAuthnCredential]:
    return list(db.scalars(select(WebAuthnCredential)
                           .where(WebAuthnCredential.user_handle == _user_handle(username))
                           .order_by(WebAuthnCredential.id)))


def _user_handle(username: str) -> str:
    """WebAuthn user_handle — security.user_handle 와 동일 인코딩."""
    return user_handle(username)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


COSE_ALG_ES256 = -7


def _cose_alg(public_key_b64: str) -> int | None:
    """저장된 COSE 공개키에서 알고리즘 ID(key 3)를 읽는다."""
    try:
        cose = cbor_loads(base64url_to_bytes(public_key_b64))
        alg = cose.get(3) if isinstance(cose, dict) else None
        return int(alg) if alg is not None else None
    except Exception:
        return None


def _normalize_es256_signature(public_key_b64: str, credential: dict) -> dict:
    """ES256 서명을 raw(r‖s) -> DER로 정규화한다.

    RFC 8152(COSE)상 ES256 서명은 raw r‖s(64바이트)이지만, 이 환경의
    py-webauthn 3.0.1 + cryptography 50 조합은 DER(ASN.1)만 검증에
    통과시킨다 (실측: 동일 서명 raw 64B -> 실패, DER -> 성공).
    r·s 값은 그대로 두고 인코딩만 바꾸므로 검증 강도는 달라지지 않는다.

    EdDSA(-8)는 raw 64바이트가 규격상 정답이고 RS256(-257)은 이미 DER이므로,
    ES256일 때만 변환한다.
    """
    if _cose_alg(public_key_b64) != COSE_ALG_ES256:
        return credential
    response = credential.get("response")
    if not isinstance(response, dict):
        return credential
    sig_b64 = response.get("signature")
    if not isinstance(sig_b64, str):
        return credential
    try:
        sig = base64url_to_bytes(sig_b64)
    except Exception:
        return credential
    if len(sig) != 64:
        return credential
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    try:
        der = encode_dss_signature(r, s)
    except Exception:
        return credential
    return {**credential,
            "response": {**response, "signature": bytes_to_base64url(der)}}


class RegisterBeginRequest(BaseModel):
    label: str | None = Field(default=None, max_length=120)


class LoginBeginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)


# -------------------------------- 자격증명 목록 --------------------------------

@router.get("/webauthn/credentials")
def list_credentials(db: Session = Depends(get_db),
                     auth: dict = Depends(require_auth)):
    """등록된 패스워드리스 목록 — 공개키 원문은 반환하지 않는다."""
    _require_enabled()
    rows = _credentials_for(db, auth["username"])
    return {"items": [{
        "id": c.id,
        "label": c.label,
        "device_type": c.device_type,
        "backed_up": c.backed_up,
        "created_at": c.created_at,
        "last_used_at": c.last_used_at,
    } for c in rows]}


@router.delete("/webauthn/credentials/{credential_pk}", status_code=200)
def delete_credential(credential_pk: int, request: Request,
                      db: Session = Depends(get_db),
                      auth: dict = Depends(require_auth),
                      actor: str = Depends(get_read_actor)):
    """패스워드리스 삭제 — 최소 1개는 남겨 두는 것을 권장한다 (경고는 클라이언트가)."""
    _require_enabled()
    row = db.get(WebAuthnCredential, credential_pk)
    # 자신의 자격증명만 지울 수 있다 (다른 사용자 자격증명 접근 차단)
    if row is None or row.user_handle != _user_handle(auth["username"]):
        raise HubError(status_code=404, detail="해당 자격 증명이 없습니다",
                        code="credential_not_found")
    db.delete(row)
    record_audit(db, actor, "webauthn.credential_delete",
                 target=auth["username"], detail={"credential_id": row.credential_id})
    db.commit()
    return {"ok": True}


# ---------------------------------- 등록 ----------------------------------

@router.post("/webauthn/register/begin")
def register_begin(request: Request, body: RegisterBeginRequest | None = None,
                   db: Session = Depends(get_db),
                   auth: dict = Depends(require_auth)):
    """패스워드리스 등록 시작 — 챌린지 발급 (로그인 세션 + CSRF 필요)."""
    settings = _require_enabled()
    username = auth["username"]
    if _admin_username(db) != username:
        raise HubError(status_code=403, detail="패스워드 키 등록 권한이 없습니다",
                        code="forbidden")

    existing = _credentials_for(db, username)
    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.name,
        user_name=username,
        user_id=username.encode("utf-8"),
        timeout=settings.webauthn_timeout_ms,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        # 이미 등록한 자격증명은 중복 등록을 차단한다
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
            for c in existing
        ] or None,
    )
    _put_challenge(f"reg:{username}", options.challenge,
                   {"label": body.label if body else None})
    return {"publicKey": json.loads(options_to_json(options)),
            "expires_in": CHALLENGE_TTL}


@router.post("/webauthn/register/finish")
def register_finish(request: Request, body: dict[str, Any] = Body(...),
                    db: Session = Depends(get_db),
                    auth: dict = Depends(require_auth),
                    actor: str = Depends(get_read_actor)):
    """패스워드리스 등록 완료 — 증명(Attestation) 검증 후 공개키를 저장한다."""
    settings = _require_enabled()
    username = auth["username"]
    if _admin_username(db) != username:
        raise HubError(status_code=403, detail="패스워드 키 등록 권한이 없습니다",
                        code="forbidden")

    found = _pop_challenge(f"reg:{username}")
    if found is None:
        raise HubError(status_code=400,
                        detail="등록 요청이 만료되었습니다. 다시 시도하세요",
                        code="challenge_expired")
    challenge, meta = found

    try:
        verified = verify_registration_response(
            credential=body,
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            require_user_verification=False,
        )
    except Exception:
        # 검증 실패 사유는 노출하지 않는다 (docs/SECURITY.md — 내부 사유 미노출)
        raise HubError(status_code=400,
                        detail="패스워드 키 등록 검증에 실패했습니다",
                        code="webauthn_registration_failed")

    credential_id = bytes_to_base64url(verified.credential_id)
    exists = db.scalar(select(WebAuthnCredential)
                       .where(WebAuthnCredential.credential_id == credential_id))
    if exists is not None:
        raise HubError(status_code=409, detail="이미 등록된 패스워드 키입니다",
                        code="credential_exists")

    label = (meta.get("label") or "").strip() or "패스워드 키"
    row = WebAuthnCredential(
        credential_id=credential_id,
        public_key=bytes_to_base64url(verified.credential_public_key),
        sign_count=int(verified.sign_count or 0),
        user_handle=_user_handle(username),
        label=label[:120],
        device_type=str(verified.credential_device_type.value),
        backed_up=bool(verified.credential_backed_up),
        created_at=utcnow(),
    )
    db.add(row)
    record_audit(db, actor, "webauthn.credential_register",
                 target=username, detail={"label": label,
                                          "device_type": row.device_type,
                                          "backed_up": row.backed_up})
    db.commit()
    return {"ok": True, "id": row.id, "label": row.label}


# --------------------------------- 로그인 ---------------------------------

@router.post("/webauthn/login/begin")
def login_begin(request: Request, body: LoginBeginRequest,
                db: Session = Depends(get_db)):
    """패스워드리스 로그인 시작 — 익명 엔드포인트 (잠금 제한 적용)."""
    settings = _require_enabled()
    username = body.username
    ip = _client_ip(request)

    if is_locked(username, ip):
        raise HubError(status_code=429,
                        detail=f"로그인 제한: {lockout_minutes()}분 후 다시 시도하세요",
                        code="locked")
    if _admin_username(db) != username:
        # 존재하지 않는 사용자명은 401. (등록된 키가 없는 관리자는 400 no_credentials로
        # 구분되므로 사용자명 존재 여부는 드러난다 — 이 허브는 단일 관리자 도구이며
        # 사용자명(admin)을 비밀로 두지 않으며, 비밀번호 로그인 경로도 동일하다.)
        raise HubError(status_code=401, detail="사용자명 또는 패스워드 키가 올바르지 않습니다",
                        code="invalid_credentials")

    creds = _credentials_for(db, username)
    if not creds:
        raise HubError(status_code=400,
                        detail="등록된 패스워드 키가 없습니다. 비밀번호로 로그인하세요",
                        code="no_credentials")

    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        timeout=settings.webauthn_timeout_ms,
        user_verification=UserVerificationRequirement.PREFERRED,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
            for c in creds
        ],
    )
    _put_challenge(f"login:{username}", options.challenge)
    return {"publicKey": json.loads(options_to_json(options)),
            "expires_in": CHALLENGE_TTL}


@router.post("/webauthn/login/finish")
def login_finish(request: Request, body: dict[str, Any] = Body(...),
                 db: Session = Depends(get_db)):
    """패스워드리스 로그인 완료 — 서명 검증 후 세션 쿠키를 발급한다."""
    settings = _require_enabled()
    username = body.get("username")
    if not isinstance(username, str) or _admin_username(db) != username:
        raise HubError(status_code=401, detail="사용자명 또는 패스워드 키가 올바르지 않습니다",
                        code="invalid_credentials")
    ip = _client_ip(request)

    if is_locked(username, ip):
        raise HubError(status_code=429,
                        detail=f"로그인 제한: {lockout_minutes()}분 후 다시 시도하세요",
                        code="locked")

    found = _pop_challenge(f"login:{username}")
    if found is None:
        raise HubError(status_code=400,
                        detail="로그인 요청이 만료되었습니다. 다시 시도하세요",
                        code="challenge_expired")
    challenge, _meta = found

    # 검증에는 자격증명 본문만 넘긴다 (username 등 부가 키는 분리)
    credential_body = {k: v for k, v in body.items() if k != "username"}

    # 신원을 알 수 없는 자격증명 ID는 저장소에서 찾는다 (응답 전체는 아래서 검증)
    try:
        credential_key = bytes_to_base64url(base64url_to_bytes(str(body.get("id", ""))))
    except Exception:
        raise HubError(status_code=401, detail="사용자명 또는 패스워드 키가 올바르지 않습니다",
                        code="invalid_credentials")

    row = db.scalar(select(WebAuthnCredential)
                    .where(WebAuthnCredential.credential_id == credential_key))
    if row is None or row.user_handle != _user_handle(username):
        register_failure(username, ip)
        raise HubError(status_code=401, detail="사용자명 또는 패스워드 키가 올바르지 않습니다",
                        code="invalid_credentials")

    # ES256 raw(r‖s) 서명을 DER로 정규화 (아래 헬퍼 주석 참조)
    credential_body = _normalize_es256_signature(row.public_key, credential_body)

    try:
        verified = verify_authentication_response(
            credential=credential_body,
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            credential_public_key=base64url_to_bytes(row.public_key),
            credential_current_sign_count=row.sign_count,
            require_user_verification=False,
        )
    except Exception:
        register_failure(username, ip)
        raise HubError(status_code=401, detail="사용자명 또는 패스워드 키가 올바르지 않습니다",
                        code="invalid_credentials")

    # 클론 감지: sign_count가 역전되면 자격증명이 복제됐을 가능성이 있다.
    if int(verified.new_sign_count) and row.sign_count and \
            int(verified.new_sign_count) < row.sign_count:
        register_failure(username, ip)
        raise HubError(status_code=401, detail="패스워드 키 검증에 실패했습니다",
                        code="invalid_credentials")

    row.sign_count = int(verified.new_sign_count or 0)
    row.last_used_at = utcnow()
    db.flush()

    token, csrf = create_session(username, admin_epoch(db))
    db.commit()

    out = JSONResponse({"ok": True, "username": username, "csrf_token": csrf,
                        "method": "webauthn"})
    out.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", path="/")
    return out
