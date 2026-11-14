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
    _ensure_additive_columns()


# 추가 전용(additive) 컬럼 목록. SQLite의 create_all은 기존 테이블에 컬럼을
# 추가하지 않으므로, 기존 설치를 깨지 않도록 여기서 ALTER TABLE을 수행한다.
# 삭제/타입 변경은 하지 않는다 — 파괴적 마이그레이션은 수동 절차로 남긴다.
_ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "endpoints": {
        "auth_type": "VARCHAR(16) DEFAULT 'none'",
        "credentials_ref": "VARCHAR(300)",
        "auth_hint": "VARCHAR(300)",
    },
}


def _ensure_additive_columns() -> None:
    from sqlalchemy import inspect, text

    engine = get_engine()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


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
