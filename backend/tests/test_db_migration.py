"""기존 DB에 추가 컬럼을 안전하게 붙이는지 검증한다.

`create_all`은 기존 테이블에 컬럼을 추가하지 않으므로, 배포된 허브가
업데이트 후에도 깨지지 않도록 additive 마이그레이션이 필요하다.
"""
from __future__ import annotations

import sqlite3

from sqlalchemy import inspect

from app.config import Settings, set_settings
from app.db import _ensure_additive_columns, get_engine, init_db, reset_db_state


def test_endpoint_auth_columns_added_to_legacy_table(tmp_path):
    db_path = tmp_path / "legacy.db"
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE endpoints ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, service_id VARCHAR(64), "
        "name VARCHAR(120), type VARCHAR(16), exposure VARCHAR(16), "
        "hostname VARCHAR(256), host_port INTEGER, container VARCHAR(120), "
        "container_port INTEGER)"
    )
    con.execute(
        "INSERT INTO endpoints (service_id, name, container, container_port) "
        "VALUES ('old-app', 'web', 'web', 80)"
    )
    con.commit()
    con.close()

    set_settings(Settings(db_path=str(db_path), status_cache=str(tmp_path / "s.json"),
                          monitor_enabled=False, _env_file=None))
    reset_db_state()
    try:
        init_db()
        _ensure_additive_columns()  # 멱등성: 두 번 호출해도 실패하지 않는다
        cols = {c["name"] for c in inspect(get_engine()).get_columns("endpoints")}
        assert {"auth_type", "credentials_ref", "auth_hint", "auth_header",
                "api_base_path", "health_path", "docs_url", "bind_addr"} <= cols

        con = sqlite3.connect(db_path)
        try:
            row = con.execute("SELECT auth_type FROM endpoints").fetchone()
        finally:
            con.close()
        assert row == ("none",)
    finally:
        reset_db_state()
