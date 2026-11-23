"""AI 온보딩용 일회용 등록 토큰 라우터.

흐름:
  1) 사람이 대시보드(세션)에서 **짧은 TTL의 일회용 토큰**을 발급한다.
  2) 대상 PC의 AI가 ``POST /auth/enroll`` 로 토큰을 **1회** 교환해 일반 API 키를 받는다.
  3) 서버는 토큰/키 모두 **해시만** 저장하고, 교환은 감사 로그에 남긴다.

안전장치:
  - 토큰 관리(발급/조회/폐기)는 **세션 전용** (API 키가 스스로 토큰을 만들 수 없다).
  - 교환 엔드포인트는 토큰 필수 + IP별 시도 제한 + 1회용 + 짧은 TTL + 게이트(기본 꺼짐).
  - 평문 토큰/키는 응답에서 한 번만 노출한다.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import ApiKey, EnrollmentToken
from ..security import HubError, hash_api_key, require_session_auth
from ..services.events import record_audit

router = APIRouter(tags=["enrollment"])

ENROLL_PREFIX = "enroll_"
KEY_PREFIX = "hub_"
VALID_SCOPES = {"read", "write", "deploy", "*"}

# IP별 교환 실패 제한 (성공 시 초기화)
_FAIL_WINDOW = 60.0
_FAIL_MAX = 10
_FAILS: dict[str, list[float]] = {}
_FAILS_LOCK = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _expired_at(value: str | None) -> bool:
    if not value:
        return False
    try:
        return datetime.fromisoformat(value) <= _now()
    except Exception:
        return True


def _check_rate(ip: str) -> None:
    now = time.time()
    with _FAILS_LOCK:
        recent = [t for t in _FAILS.get(ip, []) if now - t < _FAIL_WINDOW]
        _FAILS[ip] = recent
        if len(recent) >= _FAIL_MAX:
            raise HubError(status_code=429,
                           detail="등록 시도가 너무 많습니다. 잠시 후 다시 시도하세요",
                           code="rate_limited")


def _record_failure(ip: str) -> None:
    with _FAILS_LOCK:
        _FAILS.setdefault(ip, []).append(time.time())


def _clear_failures(ip: str) -> None:
    with _FAILS_LOCK:
        _FAILS.pop(ip, None)


def reset_enrollment_state() -> None:
    """테스트 격리용 — IP별 실패 기록을 비운다."""
    with _FAILS_LOCK:
        _FAILS.clear()


def _public(row: EnrollmentToken) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "scopes": row.scopes or [],
        "created_at": row.created_at,
        "created_by": row.created_by,
        "expires_at": row.expires_at,
        "used_at": row.used_at,
        "used_by_ip": row.used_by_ip,
        "revoked_at": row.revoked_at,
        "active": (not row.used_at and not row.revoked_at
                   and not _expired_at(row.expires_at)),
    }


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["*"])
    ttl_minutes: int | None = Field(default=None, ge=1, le=1440)


class EnrollRequest(BaseModel):
    token: str = Field(min_length=8, max_length=256)


def _normalize_scopes(raw: list[str]) -> list[str]:
    scopes = [s.strip().lower() for s in (raw or ["*"]) if s.strip()]
    if not scopes:
        scopes = ["*"]
    if "*" not in scopes:
        unknown = [s for s in scopes if s not in VALID_SCOPES]
        if unknown:
            raise HubError(status_code=422,
                           detail=f"알 수 없는 scope입니다: {unknown} "
                                  f"(사용 가능: {sorted(VALID_SCOPES)} 또는 '*')",
                           code="invalid_scope")
    return scopes


@router.post("/enrollment/tokens", status_code=201)
def create_enrollment_token(body: TokenCreate, db: Session = Depends(get_db),
                            session: dict = Depends(require_session_auth)):
    """일회용 등록 토큰을 발급한다 (세션 전용, 평문은 이 응답에서만)."""
    settings = get_settings()
    if not settings.enable_enrollment:
        raise HubError(status_code=503,
                       detail="등록 토큰 기능이 비활성화되어 있습니다 "
                              "(HUB_ENABLE_ENROLLMENT=false)",
                       code="enrollment_disabled")
    scopes = _normalize_scopes(body.scopes)
    ttl = body.ttl_minutes or settings.enrollment_ttl_minutes
    ttl = max(1, min(ttl, settings.enrollment_max_ttl_minutes))
    raw = ENROLL_PREFIX + secrets.token_urlsafe(32)
    row = EnrollmentToken(
        id=str(uuid.uuid4()),
        token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        name=body.name,
        scopes=scopes,
        created_at=_iso(_now()),
        created_by=session["username"],
        expires_at=_iso(_now() + timedelta(minutes=ttl)),
    )
    db.add(row)
    record_audit(db, session["username"], "enrollment.create", target=row.id,
                 detail={"name": row.name, "scopes": scopes, "ttl_minutes": ttl})
    db.commit()
    return {**_public(row), "token": raw, "ttl_minutes": ttl,
            "note": "이 토큰은 다시 표시되지 않습니다. AI에 1회 전달하세요."}


@router.get("/enrollment/tokens")
def list_enrollment_tokens(db: Session = Depends(get_db),
                           _session: dict = Depends(require_session_auth)):
    rows = list(db.execute(
        select(EnrollmentToken).order_by(EnrollmentToken.created_at.desc())).scalars())
    return {"items": [_public(r) for r in rows], "count": len(rows)}


@router.delete("/enrollment/tokens/{token_id}")
def revoke_enrollment_token(token_id: str, db: Session = Depends(get_db),
                            session: dict = Depends(require_session_auth)):
    row = db.get(EnrollmentToken, token_id)
    if row is None:
        raise HubError(status_code=404, detail="등록 토큰을 찾을 수 없습니다",
                       code="enrollment_token_not_found")
    if row.revoked_at:
        return {**_public(row), "revoked": False, "note": "이미 폐기된 토큰입니다."}
    row.revoked_at = _iso(_now())
    record_audit(db, session["username"], "enrollment.revoke", target=row.id,
                 detail={"name": row.name})
    db.commit()
    return {**_public(row), "revoked": True}


@router.post("/auth/enroll")
def exchange_enrollment_token(body: EnrollRequest, request: Request,
                              db: Session = Depends(get_db)):
    """일회용 토큰을 API 키로 교환한다 (1회용, TTL, IP별 시도 제한)."""
    settings = get_settings()
    if not settings.enable_enrollment:
        raise HubError(status_code=503,
                       detail="등록 토큰 기능이 비활성화되어 있습니다 "
                              "(HUB_ENABLE_ENROLLMENT=false)",
                       code="enrollment_disabled")
    ip = request.client.host if request.client else "unknown"
    _check_rate(ip)

    token = body.token.strip()
    if not token.startswith(ENROLL_PREFIX):
        _record_failure(ip)
        raise HubError(status_code=401, detail="유효하지 않은 등록 토큰입니다",
                       code="invalid_enrollment_token")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = db.execute(select(EnrollmentToken).where(
        EnrollmentToken.token_hash == token_hash)).scalar_one_or_none()
    if (row is None or row.revoked_at or row.used_at
            or _expired_at(row.expires_at)):
        _record_failure(ip)
        raise HubError(status_code=401, detail="유효하지 않거나 만료/사용된 등록 토큰입니다",
                       code="invalid_enrollment_token")

    # 단일 사용 보장: 조건부 UPDATE가 1행일 때만 키를 발급한다.
    now = _iso(_now())
    result = db.execute(update(EnrollmentToken).where(
        EnrollmentToken.id == row.id,
        EnrollmentToken.used_at.is_(None),
        EnrollmentToken.revoked_at.is_(None),
    ).values(used_at=now, used_by_ip=ip))
    if result.rowcount != 1:
        _record_failure(ip)
        raise HubError(status_code=401, detail="이미 사용된 등록 토큰입니다",
                       code="invalid_enrollment_token")

    raw_key = KEY_PREFIX + secrets.token_urlsafe(32)
    scopes = row.scopes or ["*"]
    key = ApiKey(
        id=str(uuid.uuid4()), key_hash=hash_api_key(raw_key),
        name=f"enrolled:{row.name}"[:120], username="admin", scopes=scopes,
        created_at=now, expires_at=None, created_by=f"enroll:{row.id}"[:120],
    )
    db.add(key)
    record_audit(db, f"enroll:{row.name}"[:120], "enrollment.exchange",
                 target=key.id,
                 detail={"token_id": row.id, "scopes": scopes, "ip": ip})
    db.commit()
    _clear_failures(ip)
    return {"ok": True, "api_key": raw_key, "api_key_id": key.id,
            "name": key.name, "scopes": scopes,
            "note": "이 키는 다시 표시되지 않습니다. 클라이언트 설정에만 저장하세요."}
