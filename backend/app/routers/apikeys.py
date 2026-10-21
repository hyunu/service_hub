"""API 키 관리 라우터 (MCP/자동화 클라이언트용).

- 키는 발급 시 **한 번만** 평문으로 반환하고 서버에는 SHA-256 해시만 저장한다.
- 발급/조회/폐기는 **브라우저 세션 전용**이다 (API 키가 스스로 키를 만들 수 없음).
- 폐기는 revoked_at 만 기록한다 — 기존 데이터/컨테이너는 건드리지 않는다.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ApiKey
from ..security import (HubError, get_read_actor, hash_api_key,
                        require_session_auth)
from ..services.events import record_audit

router = APIRouter(prefix="/apikeys", tags=["apikeys"],
                   dependencies=[Depends(require_session_auth)])

VALID_SCOPES = {"read", "write", "deploy"}
KEY_PREFIX = "hub_"


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["*"])
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public(row: ApiKey) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "username": row.username,
        "scopes": row.scopes or [],
        "created_at": row.created_at,
        "created_by": row.created_by,
        "last_used_at": row.last_used_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "active": not row.revoked_at and not _expired(row),
    }


def _expired(row: ApiKey) -> bool:
    if not row.expires_at:
        return False
    try:
        return row.expires_at < _utcnow()
    except Exception:
        return False


@router.get("")
def list_api_keys(db: Session = Depends(get_db)):
    rows = list(db.execute(select(ApiKey).order_by(ApiKey.created_at.desc())).scalars())
    return {"items": [_public(r) for r in rows], "count": len(rows)}


@router.post("", status_code=201)
def create_api_key(body: ApiKeyCreate, db: Session = Depends(get_db),
                   actor: str = Depends(get_read_actor)):
    scopes = [s.strip().lower() for s in (body.scopes or ["*"]) if s.strip()]
    if not scopes:
        scopes = ["*"]
    if "*" not in scopes:
        unknown = [s for s in scopes if s not in VALID_SCOPES]
        if unknown:
            raise HubError(status_code=422,
                           detail=f"알 수 없는 scope입니다: {unknown} "
                                  f"(사용 가능: {sorted(VALID_SCOPES)} 또는 '*')",
                           code="invalid_scope")

    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    expires_at = None
    if body.expires_in_days:
        expires_at = (datetime.now(timezone.utc)
                      + timedelta(days=body.expires_in_days)).isoformat()

    row = ApiKey(id=str(uuid.uuid4()), key_hash=hash_api_key(raw), name=body.name,
                 username="admin", scopes=scopes, created_at=_utcnow(),
                 expires_at=expires_at, created_by=actor)
    db.add(row)
    record_audit(db, actor, "apikey.create", target=row.id,
                 detail={"name": body.name, "scopes": scopes})
    db.commit()
    # 평문 키는 이 응답에서만 노출된다.
    return {**_public(row), "key": raw,
            "note": "이 키는 다시 표시되지 않습니다. 안전한 곳에 보관하세요."}


@router.delete("/{key_id}")
def revoke_api_key(key_id: str, db: Session = Depends(get_db),
                   actor: str = Depends(get_read_actor)):
    row = db.get(ApiKey, key_id)
    if row is None:
        raise HubError(status_code=404, detail="API 키를 찾을 수 없습니다",
                       code="api_key_not_found")
    if row.revoked_at:
        return {**_public(row), "revoked": False, "note": "이미 폐기된 키입니다."}
    row.revoked_at = _utcnow()
    record_audit(db, actor, "apikey.revoke", target=row.id, detail={"name": row.name})
    db.commit()
    return {**_public(row), "revoked": True}
