"""인증/설정 마법사 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..security import (SESSION_COOKIE, HubError, admin_exists, create_admin,
                        get_session_info, login as do_login, logout as do_logout,
                        require_auth)

router = APIRouter(tags=["auth"])


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


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
