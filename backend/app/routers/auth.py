"""인증/설정 마법사 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Setting, utcnow as _utcnow_str
from ..security import (SESSION_COOKIE, HubError, admin_exists, create_admin,
                        get_read_actor, get_session_info, hash_password,
                        login as do_login, logout as do_logout, require_auth,
                        verify_password)
from ..services.events import record_audit

router = APIRouter(tags=["auth"])


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
    info = get_session_info(hub_session)
    if info:
        return {"authenticated": True, "username": info["username"], "csrf_token": info["csrf"]}
    if not admin_exists(db):
        return {"authenticated": False, "setup_required": True}
    return {"authenticated": False, "setup_required": False}


# 보호 예시: 라우터 전체에 require_auth를 단다 (시스템 라우터는 GET 중심이라 별도 처리)
protected = [Depends(require_auth)]
