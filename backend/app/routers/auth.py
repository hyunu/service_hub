"""인증/설정 마법사 라우터."""
from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Setting, utcnow as _utcnow_str
from ..security import (SESSION_COOKIE, HubError, admin_exists, create_admin,
                        get_read_actor, get_valid_session, hash_password,
                        login as do_login, logout as do_logout, require_auth,
                        reset_admin, verify_password)
from ..services.events import record_audit

router = APIRouter(tags=["auth"])

RESET_TOKEN_HEADER = "X-Hub-Admin-Reset-Token"


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.get("/setup/status")
def setup_status(db: Session = Depends(get_db)):
    return {"setup_required": not admin_exists(db)}


@router.post("/setup/admin", status_code=201)
def setup_admin(body: SetupRequest, request: Request, db: Session = Depends(get_db)):
    if admin_exists(db):
        raise HubError(status_code=409, detail="관리자가 이미 설정되어 있습니다",
                            code="already_setup")
    create_admin(db, body.username, body.password)
    db.commit()
    ip = request.client.host if request.client else "unknown"
    token, csrf = do_login(db, body.username, body.password, ip)
    from fastapi.responses import JSONResponse
    out = JSONResponse({"created": True, "username": body.username, "csrf_token": csrf},
                       status_code=201)
    out.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", path="/")
    return out


@router.post("/auth/login")
def auth_login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    token, csrf = do_login(db, body.username, body.password, ip)
    resp = {"ok": True, "username": body.username, "csrf_token": csrf}
    from fastapi.responses import JSONResponse
    out = JSONResponse(resp)
    out.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", path="/")
    return out


@router.post("/auth/change-password")
def auth_change_password(body: ChangePasswordRequest, request: Request,
                         db: Session = Depends(get_db),
                         actor: str = Depends(get_read_actor),
                         _auth: dict = Depends(require_auth)):
    """현 비밀번호를 확인한 뒤 관리자 비밀번호를 변경한다.

    보안: 인증 세션 + CSRF (require_auth) 필요. 감사 로그에 기록하며,
    기존 세션은 유효하도록 유지한다 (다른 기기에서의 접근은 비밀번호 변경으로 차단).
    """
    row = db.get(Setting, "admin")
    if row is None:
        raise HubError(status_code=404, detail="관리자가 설정되지 않았습니다",
                        code="not_setup")
    if not verify_password(body.current_password, row.value.get("password_hash", "")):
        # 401을 쓰면 프론트엔드의 전역 "세션 만료" 처리(401/403 -> 로그아웃)가
        # 잘못 동작한다. 세션 자체는 유효하므로 입력 오류(400)로 응답한다.
        raise HubError(status_code=400, detail="현재 비밀번호가 올바르지 않습니다",
                        code="invalid_current_password")
    if body.current_password == body.new_password:
        raise HubError(status_code=400, detail="새 비밀번호가 현재 비밀번호와 같습니다",
                        code="same_password")

    # JSON 컬럼은 내부 변경이 dirty로 추적되지 않으므로 반드시 재할당한다.
    row.value = {**row.value,
                 "password_hash": hash_password(body.new_password),
                 "password_changed_at": _utcnow_str()}
    row.updated_at = _utcnow_str()
    db.flush()
    record_audit(db, actor, "auth.password_change",
                 target=row.value.get("username"),
                 detail={"ip": request.client.host if request.client else "unknown"})
    db.commit()
    return {"ok": True}


@router.post("/auth/logout")
def auth_logout(request: Request):
    do_logout(request.cookies.get(SESSION_COOKIE))
    from fastapi.responses import JSONResponse
    out = JSONResponse({"ok": True})
    out.delete_cookie(SESSION_COOKIE, path="/")
    return out


@router.get("/auth/session")
def auth_session(hub_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
                 db: Session = Depends(get_db)):
    info = get_valid_session(db, hub_session)
    if info:
        return {"authenticated": True, "username": info["username"], "csrf_token": info["csrf"]}
    if not admin_exists(db):
        return {"authenticated": False, "setup_required": True}
    return {"authenticated": False, "setup_required": False}


# ------------------------------------------------------ 비밀번호 분실 복구 --

def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost") or host.startswith("127.")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _secrets_equal(a: str, b: str) -> bool:
    """Timing-safe 문자열 비교."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _reset_token_used(db: Session, token: str) -> bool:
    """이 복구 토큰이 이미 사용되었는지 확인한다 (1회 사용 원칙)."""
    row = db.get(Setting, "admin_reset_token_used")
    if row is None:
        return False
    return row.value.get("token_hash") == _token_hash(token)


@router.post("/auth/reset-admin")
def auth_reset_admin(request: Request, db: Session = Depends(get_db),
                     x_hub_admin_reset_token: str | None = Header(default=None)):
    """관리자 비밀번호 분실 복구 — 관리자 자격 증명을 초기화한다.

    관리자 행(사용자명/비밀번호 해시)과 해당 관리자의 WebAuthn 자격 증명만
    지운다. 서비스/포트/컨테이너/이벤트 등 다른 데이터는 건드리지 않는다.
    초기화 후에는 로그인 화면 대신 **설정 마법사**가 다시 나타난다.

    허용 조건 (둘 중 하나를 만족해야 한다):
      1. 요청이 루프백에서 왔다 (서버/컨테이너 로컬 실행).
      2. ``HUB_ADMIN_RESET_TOKEN`` 이 설정되어 있고 요청 헤더가 일치한다.
         이 토큰은 **1회 사용** 후 폐기된다 (같은 토큰 재사용 불가).

    그 외에는 403 ``reset_not_allowed`` 로 거절한다 — 인증 우회 경로를
    새로 만들지 않는다 (docs/SECURITY.md).
    """
    settings = get_settings()
    loopback = _is_loopback(request)
    token = (x_hub_admin_reset_token or "").strip()
    configured = (settings.admin_reset_token or "").strip()

    if not loopback:
        if not configured or not token:
            raise HubError(
                status_code=403,
                detail="관리자 초기화는 루프백 또는 복구 토큰이 필요합니다",
                code="reset_not_allowed")
        if not _secrets_equal(token, configured):
            raise HubError(status_code=403, detail="복구 토큰이 올바르지 않습니다",
                           code="reset_token_invalid")
        if _reset_token_used(db, token):
            raise HubError(status_code=403,
                           detail="이 복구 토큰은 이미 사용되었습니다. "
                                  "새 토큰을 설정한 뒤 다시 시도하세요.",
                           code="reset_token_used")

    if not admin_exists(db):
        raise HubError(status_code=404, detail="관리자가 설정되지 않았습니다",
                       code="not_setup")

    removed = reset_admin(db)
    if not loopback and configured:
        # 복구 토큰 1회 사용 처리 — 같은 토큰으로는 다시 초기화할 수 없다.
        db.merge(Setting(key="admin_reset_token_used", value={
            "token_hash": _token_hash(configured),
            "at": _utcnow_str(),
        }))
    record_audit(db, f"loopback:{request.client.host}" if loopback else "token",
                 "auth.admin_reset", target=removed,
                 detail={"ip": request.client.host if request.client else "unknown",
                         "loopback": loopback})
    db.commit()
    return {"ok": True, "reset": True, "username": removed, "setup_required": True}


# 보호 예시: 라우터 전체에 require_auth를 단다 (시스템 라우터는 GET 중심이라 별도 처리)
protected = [Depends(require_auth)]
