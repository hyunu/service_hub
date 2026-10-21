"""인증/세션/CSRF (REQUIREMENTS §15).

- 최초 1회 관리자 생성 (하드코딩 기본 비밀번호 없음)
- 로그인: bcrypt, 분당 5회 실패 제한 + 5분 잠금
- 세션: HttpOnly 쿠키 + CSRF 토큰 (변경 작업에 X-CSRF-Token 요구)
- 루프백 전용 바인드일 때만 읽기 API를 세션 없이 허용 (로컬 CLI/AI 접근).
  비루프백 바인드에서는 모든 API에 인증을 요구한다.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from datetime import datetime, timezone

import bcrypt
from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import ApiKey, Setting, WebAuthnCredential


class HubError(HTTPException):
    """HTTPException에 기계 판독용 ``code``를 추가한 공통 오류.

    응답 본문은 ``{"detail": ..., "code": ...}`` 형태가 된다 (main.py 핸들러).
    """

    def __init__(self, status_code: int, detail: str, code: str = "error",
                 headers: dict | None = None) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


SESSION_COOKIE = "hub_session"
SESSIONS: dict[str, dict] = {}          # token -> {username, csrf, created_at}
_SESSION_LOCK = threading.Lock()

_LOGIN_FAILS: dict[str, list[float]] = {}
_MAX_FAILS = 5
_LOCK_SECONDS = 300


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def admin_exists(db: Session) -> bool:
    row = db.get(Setting, "admin")
    return bool(row and row.value.get("username"))


def admin_epoch(db: Session) -> str | None:
    """현재 관리자 세션 epoch.

    관리자가 새로 만들어질 때마다 다른 값이 발급된다. 세션에 담긴 epoch가
    현재 값과 다르면(관리자 초기화/재설정) 기존 세션은 무효로 취급한다.
    """
    row = db.get(Setting, "admin")
    if row is None:
        return None
    epoch = row.value.get("session_epoch")
    return str(epoch) if epoch else None


def user_handle(username: str) -> str:
    """WebAuthn user_handle — base64url(사용자명), 패딩 제거.

    webauthn.helpers.bytes_to_base64url 과 동일한 인코딩이다.
    """
    return base64.urlsafe_b64encode(username.encode("utf-8")).decode("ascii").rstrip("=")


def create_admin(db: Session, username: str, password: str) -> None:
    if admin_exists(db):
        raise HubError(status_code=409, detail="관리자가 이미 설정되어 있습니다",
                            code="already_setup")  # type: ignore[arg-type]
    db.add(Setting(key="admin", value={
        "username": username,
        "password_hash": hash_password(password),
        "created_at": _utcnow(),
        # 관리자가 새로 만들어질 때마다 바뀌는 값 — 기존 세션 무효화용
        "session_epoch": secrets.token_hex(16),
    }))
    db.flush()


def reset_admin(db: Session) -> str | None:
    """관리자 자격 증명을 초기화한다 (비밀번호 분실 복구).

    관리자 행과 그 관리자에게 등록된 WebAuthn 자격 증명만 삭제한다.
    서비스/포트/컨테이너/이벤트 등 다른 데이터는 건드리지 않는다.
    관리자 행이 사라지므로 ``admin_epoch`` 가 None 이 되고, 기존 세션은
    자동으로 무효가 된다 (require_auth).

    반환값: 삭제된 관리자 사용자명 (관리자가 없었다면 None)
    """
    row = db.get(Setting, "admin")
    if row is None:
        return None
    username = row.value.get("username")
    if username:
        handle = user_handle(str(username))
        for cred in db.query(WebAuthnCredential).filter(
                WebAuthnCredential.user_handle == handle).all():
            db.delete(cred)
    db.delete(row)
    db.flush()
    # 로그인 잠금 기록을 지운다 (잠금 상태로 초기화가 막히지 않도록)
    with _SESSION_LOCK:
        _LOGIN_FAILS.clear()
    return str(username) if username else None


def _lock_key(username: str, ip: str) -> str:
    return f"{username}@{ip}"


def is_locked(username: str, ip: str) -> bool:
    fails = _LOGIN_FAILS.get(_lock_key(username, ip), [])
    window = [t for t in fails if time.time() - t < _LOCK_SECONDS]
    _LOGIN_FAILS[_lock_key(username, ip)] = window
    return len(window) >= _MAX_FAILS


def register_failure(username: str, ip: str) -> None:
    _LOGIN_FAILS.setdefault(_lock_key(username, ip), []).append(time.time())


def create_session(username: str, epoch: str | None = None) -> tuple[str, str]:
    """새 세션을 발급한다 — (token, csrf) 반환.

    패스워드 로그인과 WebAuthn 로그인 모두 이 헬퍼를 공유한다.
    ``epoch`` 는 발급 시점의 관리자 epoch — 관리자가 초기화/재설정되면
    이 값이 달라져 기존 세션이 무효가 된다.
    """
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    with _SESSION_LOCK:
        SESSIONS[token] = {"username": username, "csrf": csrf, "created_at": _utcnow(),
                            "epoch": epoch}
    return token, csrf


def lockout_minutes() -> int:
    """잠금 지속 시간(분) — 오류 메시지/문서에서 공유한다."""
    return _LOCK_SECONDS // 60


def login(db: Session, username: str, password: str, ip: str) -> tuple[str, str]:
    if is_locked(username, ip):
        raise HubError(status_code=429,
                            detail=f"로그인 제한: {_LOCK_SECONDS // 60}분 후 다시 시도하세요",
                            code="locked")
    row = db.get(Setting, "admin")
    if row is None or not verify_password(password, row.value.get("password_hash", "")) \
            or row.value.get("username") != username:
        register_failure(username, ip)
        raise HubError(status_code=401, detail="사용자명 또는 비밀번호가 올바르지 않습니다",
                            code="invalid_credentials")
    _LOGIN_FAILS.pop(_lock_key(username, ip), None)
    return create_session(username, admin_epoch(db))


def logout(token: str | None) -> None:
    if token:
        with _SESSION_LOCK:
            SESSIONS.pop(token, None)


def reset_security_state() -> None:
    """모든 세션/로그인 실패 기록을 초기화한다 (테스트 격리용)."""
    with _SESSION_LOCK:
        SESSIONS.clear()
    _LOGIN_FAILS.clear()


def get_session_info(token: str | None) -> dict | None:
    if not token:
        return None
    with _SESSION_LOCK:
        info = SESSIONS.get(token)
    if info is None:
        return None
    return {"username": info["username"], "csrf": info["csrf"], "epoch": info.get("epoch")}


def get_valid_session(db: Session, token: str | None) -> dict | None:
    """현재 관리자 상태와 일치하는 세션만 반환한다.

    관리자가 초기되었거나 새로 만들어진 경우(epoch 불일치) 세션은 무효다.
    """
    info = get_session_info(token)
    if info is None:
        return None
    epoch = admin_epoch(db)
    if epoch is None or info.get("epoch") != epoch:
        return None
    return info


def require_auth(request: Request, db: Session = Depends(get_db),
                 hub_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
                 x_csrf_token: str | None = Header(default=None),
                 x_api_key: str | None = Header(default=None, alias="X-API-Key"),
                 authorization: str | None = Header(default=None)) -> dict:
    """mutation은 항상 인증+CSRF. 읽기(GET)는 루프백 전용 바인드에서만 생략.

    MCP/자동화 클라이언트를 위해 API 키(X-API-Key 또는 Authorization: Bearer ...)도
    허용한다. API 키는 헤더 기반 비브라우저 클라이언트이므로 CSRF 토큰을 요구하지 않는다.
    """
    settings = get_settings()
    session = get_valid_session(db, hub_session)
    mutation = request.method not in ("GET", "HEAD", "OPTIONS")

    if session is None:
        key = x_api_key or authorization
        api_auth = verify_api_key(db, key) if key else None
        if api_auth:
            scopes = api_auth.get("scopes") or ["*"]
            if mutation and "*" not in scopes and not ({"write", "deploy"} & set(scopes)):
                raise HubError(status_code=403,
                               detail="이 API 키에는 쓰기 권한이 없습니다",
                               code="insufficient_scope")
            return {"username": api_auth["username"], "auth": "api_key", "scopes": scopes}
        if mutation or not settings.loopback_only:
            raise HubError(status_code=401, detail="로그인이 필요합니다", code="unauthorized")
        return {"username": "local-loopback"}

    if mutation and (not x_csrf_token or x_csrf_token != session["csrf"]):
        raise HubError(status_code=403, detail="CSRF 토큰이 일치하지 않습니다", code="csrf")
    return {"username": session["username"]}


def require_session_auth(request: Request, db: Session = Depends(get_db),
                         hub_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
                         x_csrf_token: str | None = Header(default=None)) -> dict:
    """브라우저 세션 전용 인증 (API 키로는 접근 불가).

    API 키 발급/폐기 같은 관리 작업에 사용한다 — 키가 스스로 새 키를 만들 수
    없도록 하기 위함이다.
    """
    session = get_valid_session(db, hub_session)
    if session is None:
        raise HubError(status_code=401, detail="로그인이 필요합니다", code="unauthorized")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not x_csrf_token or x_csrf_token != session["csrf"]:
            raise HubError(status_code=403, detail="CSRF 토큰이 일치하지 않습니다", code="csrf")
    return {"username": session["username"]}


def get_read_actor(request: Request, db: Session = Depends(get_db),
                   hub_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
                   x_api_key: str | None = Header(default=None, alias="X-API-Key"),
                   authorization: str | None = Header(default=None)) -> str:
    """감사 로그용 주체 표기 (세션 > API 키 > 로컬)."""
    session = get_session_info(hub_session)
    if session:
        return session["username"]
    key = x_api_key or authorization
    if key:
        info = verify_api_key(db, key)
        if info:
            return f"apikey:{info['name'] or info['api_key_id'][:8]}"
    client = request.client
    return f"local:{client.host}" if client else "local"


def masked(value: str | None) -> str | None:
    """비밀로 간주되는 값 마스킹 (요구사항 §15.4)."""
    if not value:
        return value
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]


SECRET_KEY_HINTS = ("PASSWORD", "TOKEN", "KEY", "SECRET", "PASSWD")


def mask_env_dict(env: dict | None) -> dict:
    if not env:
        return {}
    return {k: (masked(v) if any(h in k.upper() for h in SECRET_KEY_HINTS) else v)
            for k, v in env.items()}


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_api_key(db: Session, key: str) -> dict | None:
    """API 키로 인증한다. 성공 시 {"username": ..., "scopes": [...] } 반환."""
    if not key or not key.strip():
        return None
    k = key.strip()
    if k.startswith("Bearer "):
        k = k[7:].strip()
    h = hash_api_key(k)
    row = db.query(ApiKey).filter(ApiKey.key_hash == h).first()
    if row is None:
        return None
    if row.revoked_at:
        return None
    if row.expires_at:
        try:
            if row.expires_at < _utcnow():
                return None
        except Exception:
            pass
    _touch_api_key(row)
    scopes = row.scopes or ["*"]
    return {"username": row.username or "admin", "scopes": scopes,
            "api_key_id": row.id, "name": row.name}


def _touch_api_key(row: ApiKey) -> None:
    """마지막 사용 시각을 별도 세션으로 기록한다.

    요청의 트랜잭션을 오염시키지 않도록 분리한다. 1분 이내 재사용은 생략.
    """
    now = _utcnow()
    last = row.last_used_at
    if last:
        try:
            from datetime import datetime
            if (datetime.fromisoformat(now) - datetime.fromisoformat(last)).total_seconds() < 60:
                return
        except Exception:
            pass
    try:
        from .db import get_session_factory
        with get_session_factory()() as s:
            fresh = s.get(ApiKey, row.id)
            if fresh is not None:
                fresh.last_used_at = now
                s.commit()
    except Exception:
        pass
