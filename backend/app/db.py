"""SQLite 엔진/세션 — WAL, foreign_keys ON (docs/ARCHITECTURE.md §2)."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionFactory: sessionmaker | None = None


def get_engine():
    global _engine, _SessionFactory
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.db_url,
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(_engine, "connect")
        def _set_pragmas(dbapi_conn, _):  # pragma: no cover - sqlite 직접 설정
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker:
    get_engine()
    assert _SessionFactory is not None
    return _SessionFactory


def init_db() -> None:
    from . import models  # noqa: F401 — 모델 등록

    Base.metadata.create_all(bind=get_engine())


def session_scope() -> Iterator[Session]:
    """백그라운드 루프용 세션 컨텍스트."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI 의존성."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_db_state() -> None:
    """테스트에서 엔진을 재생성할 때 사용."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
