"""이벤트 확인(unread 뱃지) 테스트.

상단 뱃지는 "마지막 확인 시각 이후 warning/critical 이벤트 수"를 센다.
이벤트 화면을 열면 acknowledge 되어 뱃지가 0이 된다.
"""
from __future__ import annotations

from conftest import mutate


def _add_event(db, ts: str, severity: str = "warning", message: str = "m") -> None:
    from app.models import Event

    db.add(Event(ts=ts, severity=severity, kind="test", message=message))
    db.commit()


def test_unread_count_and_acknowledge(client):
    from app.db import get_session_factory

    with get_session_factory()() as s:
        _add_event(s, "2026-10-23T01:00:00+00:00", "warning", "old warning")
        _add_event(s, "2026-10-23T02:00:00+00:00", "critical", "critical")
        _add_event(s, "2026-10-23T03:00:00+00:00", "info", "info ignored")

    body = client.get("/api/v1/events/unread-count").json()
    assert body["count"] == 2          # warning + critical (info 제외)
    assert body["last_read_at"] is None

    r = mutate(client, "POST", "/api/v1/events/acknowledge")
    assert r.status_code == 200, r.text
    assert r.json()["last_read_at"]

    after = client.get("/api/v1/events/unread-count").json()
    assert after["count"] == 0
    assert after["last_read_at"] == r.json()["last_read_at"]


def test_new_event_after_acknowledge_counts(client):
    from app.db import get_session_factory

    mutate(client, "POST", "/api/v1/events/acknowledge")
    with get_session_factory()() as s:
        _add_event(s, "2099-01-01T00:00:00+00:00", "warning", "future warning")
    assert client.get("/api/v1/events/unread-count").json()["count"] == 1


def test_acknowledge_requires_csrf(client):
    r = client.post("/api/v1/events/acknowledge",
                    headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    assert r.json()["code"] == "csrf"
