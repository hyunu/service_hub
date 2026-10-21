"""이벤트/감사 로그 기록 (docs/ARCHITECTURE.md §5)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog, Event


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_event(db: Session, kind: str, message: str, severity: str = "info",
                 service_id: str | None = None, container_id: str | None = None,
                 detail: dict | None = None, dedupe_minutes: int = 60) -> Event | None:
    """중복 억제: 동일 (kind, service_id, container_id)가 최근 dedupe_minutes 내에
    있으면 새 이벤트를 만들지 않는다 (모니터링 주기마다 반복 기록 방지)."""
    if dedupe_minutes:
        since = (_utcnow() - timedelta(minutes=dedupe_minutes)).isoformat()
        existing = db.execute(
            select(Event).where(
                Event.kind == kind,
                Event.service_id == service_id,
                Event.container_id == container_id,
                Event.ts >= since,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return None
    ev = Event(ts=_utcnow().isoformat(), severity=severity, kind=kind,
               service_id=service_id, container_id=container_id,
               message=message, detail=detail or {})
    db.add(ev)
    db.flush()
    return ev


def record_audit(db: Session, actor: str, action: str, target: str | None = None,
                 detail: dict | None = None) -> AuditLog:
    log = AuditLog(ts=_utcnow().isoformat(), actor=actor, action=action,
                   target=target, detail=detail or {})
    db.add(log)
    db.flush()
    return log
