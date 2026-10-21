"""인증/세션/CSRF (REQUIREMENTS §15).

- 최초 1회 관리자 생성 (하드코딩 기본 비밀번호 없음)
- 로그인: bcrypt, 분당 5회 실패 제한 + 5분 잠금
- 세션: HttpOnly 쿠키 + CSRF 토큰 (변경 작업에 X-CSRF-Token 요구)
- 루프백 전용 바인드일 때만 읽기 API를 세션 없이 허용 (로컬 CLI/AI 접근).
  비루프백 바인드에서는 모든 API에 인증을 요구한다.
"""
from __future__ import annotations

import secrets
import threading
import time
from datetime import datetime, timezone

import bcrypt
from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Setting


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


def create_admin(db: Session, username: str, password: str) -> None:
    if admin_exists(db):
        raise HubError(status_code=409, detail="관리자가 이미 설정되어 있습니다",
                            code="already_setup")  # type: ignore[arg-type]
    db.add(Setting(key="admin", value={
        "username": username,
        "password_hash": hash_password(password),
        "created_at": _utcnow(),
    }))
    db.flush()


def _lock_key(username: str, ip: str) -> str:
    return f"{username}@{ip}"


def is_locked(username: str, ip: str) -> bool:
    fails = _LOGIN_FAILS.get(_lock_key(username, ip), [])
    window = [t for t in fails if time.time() - t < _LOCK_SECONDS]
    _LOGIN_FAILS[_lock_key(username, ip)] = window
    return len(window) >= _MAX_FAILS


def register_failure(username: str, ip: str) -> None:
    _LOGIN_FAILS.setdefault(_lock_key(username, ip), []).append(time.time())


def create_session(username: str) -> tuple[str, str]:
    """새 세션을 발급한다 — (token, csrf) 반환.

    패스워드 로그인과 WebAuthn 로그인 모두 이 헬퍼를 공유한다.
    """
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    with _SESSION_LOCK:
        SESSIONS[token] = {"username": username, "csrf": csrf, "created_at": _utcnow()}
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
    return create_session(username)


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
    return {"username": info["username"], "csrf": info["csrf"]}


def require_auth(request: Request, db: Session = Depends(get_db),
                 hub_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
                 x_csrf_token: str | None = Header(default=None)) -> dict:
    """mutation은 항상 인증+CSRF. 읽기(GET)는 루프백 전용 바인드에서만 생략."""
    settings = get_settings()
    session = get_session_info(hub_session)
    mutation = request.method not in ("GET", "HEAD", "OPTIONS")

    if session is None:
        if mutation or not settings.loopback_only:
            raise HubError(status_code=401, detail="로그인이 필요합니다", code="unauthorized")
        return {"username": "local-loopback"}

    if mutation and (not x_csrf_token or x_csrf_token != session["csrf"]):
        raise HubError(status_code=403, detail="CSRF 토큰이 일치하지 않습니다", code="csrf")
    return {"username": session["username"]}


def get_read_actor(request: Request,
                   hub_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> str:
    """감사 로그용 주체 표기."""
    session = get_session_info(hub_session)
    if session:
        return session["username"]
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
