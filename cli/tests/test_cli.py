"""CLI tests. Network-dependent tests use a stub HTTP server (no real backend needed)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from hub_cli.main import CliError, main

REPO = Path(__file__).resolve().parent.parent.parent
SCHEMA = REPO / "schemas" / "service.schema.v1.json"


class _Stub(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, dict]] = {}
    post_routes: dict[str, tuple[int, dict]] = {}

    def do_GET(self):  # noqa: N802
        _Stub.last_headers = dict(self.headers)
        code, body = self.routes.get(self.path, (404, {"detail": "not found", "code": "nf"}))
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):  # noqa: N802
        _Stub.last_post_path = self.path
        _Stub.last_headers = dict(self.headers)
        length = int(self.headers.get("Content-Length") or 0)
        _Stub.last_post_body = self.rfile.read(length).decode() if length else ""
        code, body = self.post_routes.get(self.path,
                                          (404, {"detail": "not found", "code": "nf"}))
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence
        pass


@pytest.fixture()
def stub_server():
    servers = []

    def start(routes: dict[str, tuple[int, dict]],
              post_routes: dict[str, tuple[int, dict]] | None = None):
        handler = type("Handler", (_Stub,), {
            "routes": routes, "post_routes": post_routes or {}})
        srv = HTTPServer(("127.0.0.1", 0), handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}/api/v1"

    yield start
    for s in servers:
        s.shutdown()


def test_status_human(capsys, stub_server, monkeypatch):
    url = stub_server({"/api/v1/system/status": (200, {
        "hub_name": "TestHub",
        "server": {"hostname": "n100", "os": "Linux", "uptime_human": "3 days"},
        "docker": {"connected": True, "server_version": "27.0"},
        "counts": {"containers_running": 9, "containers_stopped": 9, "orphans": 3},
        "monitor": {"state": "ok", "last_ok_at": "2026-10-21T12:00:00+09:00"},
        "warnings": [],
    })})
    monkeypatch.setenv("HUB_URL", url)
    main(["status"])
    out = capsys.readouterr().out
    assert "TestHub" in out
    assert "connected" in out
    assert "9" in out


def test_api_key_header_is_sent(stub_server, monkeypatch, capsys):
    """HUB_API_KEY가 있으면 X-API-Key 헤더로 전달된다 (비루프백 배포)."""
    url = stub_server({"/api/v1/system/status": (200, {"hub_name": "TestHub"})})
    monkeypatch.setenv("HUB_URL", url)
    monkeypatch.setenv("HUB_API_KEY", "hub_test_key")
    main(["status"])
    assert _Stub.last_headers.get("X-API-Key") == "hub_test_key"


def test_no_api_key_header_when_unset(stub_server, monkeypatch, capsys):
    url = stub_server({"/api/v1/system/status": (200, {"hub_name": "TestHub"})})
    monkeypatch.setenv("HUB_URL", url)
    monkeypatch.delenv("HUB_API_KEY", raising=False)
    main(["status"])
    assert "X-API-Key" not in _Stub.last_headers


def test_401_explains_api_key(stub_server, monkeypatch, capsys):
    url = stub_server({"/api/v1/system/status": (401, {
        "detail": "로그인이 필요합니다", "code": "unauthorized"})})
    monkeypatch.setenv("HUB_URL", url)
    monkeypatch.delenv("HUB_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        main(["status"])
    err = capsys.readouterr().err
    assert "HUB_API_KEY" in err


def test_status_json_is_pure_json(stub_server, monkeypatch, capsys):
    url = stub_server({"/api/v1/system/status": (200, {"hub_name": "TestHub"})})
    monkeypatch.setenv("HUB_URL", url)
    main(["status", "--json"])
    out = capsys.readouterr().out
    assert json.loads(out)["hub_name"] == "TestHub"  # must parse as pure JSON


def test_unreachable_backend_exit_code(monkeypatch):
    monkeypatch.setenv("HUB_URL", "http://127.0.0.1:1/api/v1")
    with pytest.raises(SystemExit) as exc:
        main(["status"])
    assert exc.value.code == 3


def test_not_found_exit_code(stub_server, monkeypatch):
    url = stub_server({})
    monkeypatch.setenv("HUB_URL", url)
    with pytest.raises(SystemExit) as exc:
        main(["service", "show", "nope"])
    assert exc.value.code == 5


def test_service_list_render(capsys, stub_server, monkeypatch):
    url = stub_server({"/api/v1/services": (200, {"items": [{
        "id": "ai-platform", "name": "AI Platform", "status": "healthy",
        "containers": {"running": 4, "total": 4}, "cpu_percent": 12.3, "memory_mb": 512.0,
    }]})})
    monkeypatch.setenv("HUB_URL", url)
    main(["service", "list"])
    out = capsys.readouterr().out
    assert "ai-platform" in out and "AI Platform" in out and "12.3" in out


def test_service_list_null_shows_na(capsys, stub_server, monkeypatch):
    url = stub_server({"/api/v1/services": (200, {"items": [{
        "id": "no-containers", "name": "Empty", "status": "registered",
        "containers": {"running": 0, "total": 0}, "cpu_percent": None, "memory_mb": None,
    }]})})
    monkeypatch.setenv("HUB_URL", url)
    main(["service", "list"])
    assert "N/A" in capsys.readouterr().out


def test_validate_good_schema(capsys, tmp_path, monkeypatch):
    f = tmp_path / "service.yaml"
    f.write_text(
        "schema_version: 1\n"
        "service:\n"
        "  id: sample-app\n"
        "  name: Sample Application\n"
        "  description: 샘플 웹 애플리케이션\n"
        "  category: web\n"
        "deployment:\n"
        "  type: docker-compose\n"
        "  compose_file: compose.yaml\n"
        "endpoints:\n"
        "  - name: frontend\n"
        "    type: http\n"
        "    exposure: proxy\n"
        "    hostname: sample.home\n"
        "    container: frontend\n"
        "    container_port: 3000\n",
        encoding="utf-8")
    pytest.importorskip("yaml")
    main(["service", "validate", str(f)])
    assert "검증 통과" in capsys.readouterr().out


def test_validate_rejects_bad_id(tmp_path, capsys):
    f = tmp_path / "service.yaml"
    f.write_text(
        "schema_version: 1\n"
        "service:\n"
        "  id: Bad_ID!\n"
        "  name: X\n"
        "  description: Y\n"
        "  category: web\n"
        "deployment:\n"
        "  type: docker-compose\n"
        "  compose_file: compose.yaml\n",
        encoding="utf-8")
    pytest.importorskip("yaml")
    with pytest.raises(SystemExit) as exc:
        main(["service", "validate", str(f)])
    assert exc.value.code == 4


def test_validate_rejects_secret_field(tmp_path):
    f = tmp_path / "service.yaml"
    f.write_text(
        "schema_version: 1\n"
        "service: {id: x-app, name: X, description: Y, category: web}\n"
        "deployment: {type: docker-compose, compose_file: compose.yaml}\n"
        "password: hunter2\n",
        encoding="utf-8")
    pytest.importorskip("yaml")
    with pytest.raises(SystemExit) as exc:
        main(["service", "validate", str(f)])
    assert exc.value.code == 4


def test_orphan_list_render(capsys, stub_server, monkeypatch):
    url = stub_server({"/api/v1/orphans": (200, {"items": [{
        "name": "rogue", "container_id_short": "abc123", "image": "nginx:latest",
        "state": "running", "reason": "서비스 등록 정보 없음",
        "guessed_service": None, "ports": ["8080->80/tcp"],
    }]})})
    monkeypatch.setenv("HUB_URL", url)
    main(["orphan", "list"])
    out = capsys.readouterr().out
    assert "rogue" in out and "nginx:latest" in out


def test_port_available_json(stub_server, monkeypatch, capsys):
    url = stub_server({"/api/v1/ports/available?count=3&protocol=tcp": (200,
        {"candidates": [8001, 8002, 8003]})})
    monkeypatch.setenv("HUB_URL", url)
    main(["port", "available", "--count", "3", "--json"])
    assert json.loads(capsys.readouterr().out)["candidates"] == [8001, 8002, 8003]


def test_deploy_plan_renders(stub_server, monkeypatch, tmp_path, capsys):
    pytest.importorskip("yaml")
    f = tmp_path / "service.yaml"
    f.write_text("schema_version: 1\nservice: {id: demo-app}\n", encoding="utf-8")
    url = stub_server({}, post_routes={
        "/api/v1/deployments/plan": (200, {
            "service": "demo-app", "result": "READY", "changes": [], "ports": [],
            "validation": [], "impact": [], "runtime_unchanged": True})})
    monkeypatch.setenv("HUB_URL", url)
    main(["deploy", "plan", str(f)])
    out = capsys.readouterr().out
    assert "demo-app" in out and "READY" in out


def test_schema_file_exists_and_is_valid_json():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == 1


def test_packaged_schema_in_sync_with_repo_schema():
    packaged = (REPO / "cli" / "hub_cli" / "schemas" / "service.schema.v1.json").read_text(encoding="utf-8")
    canonical = SCHEMA.read_text(encoding="utf-8")
    assert json.loads(packaged) == json.loads(canonical), (
        "cli/hub_cli/schemas/ 복사본이 저장소 루트 schemas/와 다릅니다. 동기화하세요.")


def test_service_new_creates_layout(tmp_path, capsys):
    code = main(["service", "new", "demo-app", "--dir", str(tmp_path)])
    assert code is None or code == 0
    assert (tmp_path / "demo-app" / "service.yaml").exists()
    assert (tmp_path / "demo-app" / "compose.yaml").exists()
    assert (tmp_path / "demo-app" / ".env.example").exists()
    assert (tmp_path / "demo-app" / ".gitignore").exists()


def test_service_new_then_validate_roundtrip(tmp_path, capsys):
    main(["service", "new", "demo-app", "--dir", str(tmp_path)])
    # 생성한 service.yaml은 스키마 검증을 통과해야 한다
    main(["service", "validate", str(tmp_path / "demo-app")])


def test_service_new_rejects_existing(tmp_path, capsys):
    (tmp_path / "demo-app").mkdir()
    with pytest.raises(SystemExit) as exc:
        main(["service", "new", "demo-app", "--dir", str(tmp_path)])
    assert exc.value.code == 4


def test_service_new_rejects_bad_id(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["service", "new", "Bad_ID", "--dir", str(tmp_path)])
    assert exc.value.code == 4


def test_deploy_apply_requires_yes(tmp_path, monkeypatch, capsys):
    # --yes 없이는 백엔드 호출조차 하지 않고 거부한다 (컨테이너 변경 방지)
    f = tmp_path / "service.yaml"
    f.write_text("schema_version: 1\n", encoding="utf-8")
    monkeypatch.setenv("HUB_URL", "http://127.0.0.1:1/api/v1")
    with pytest.raises(SystemExit) as exc:
        main(["deploy", "apply", "demo-app"])
    assert exc.value.code == 4


def test_deploy_apply_with_yes_posts(stub_server, monkeypatch, capsys):
    url = stub_server({}, post_routes={
        "/api/v1/deployments": (202, {"deployment_id": "dep-1", "service_id": "demo-app",
                                      "status": "succeeded", "error": None})})
    monkeypatch.setenv("HUB_URL", url)
    main(["deploy", "apply", "demo-app", "--yes"])
    out = capsys.readouterr().out
    assert "dep-1" in out and "succeeded" in out
    assert json.loads(_Stub.last_post_body)["service_id"] == "demo-app"
    assert json.loads(_Stub.last_post_body)["confirmed"] is True


def test_deploy_status_renders(stub_server, monkeypatch, capsys):
    url = stub_server({"/api/v1/deployments/dep-1": (200, {
        "deployment_id": "dep-1", "service_id": "demo-app", "status": "succeeded",
        "steps": []})})
    monkeypatch.setenv("HUB_URL", url)
    main(["deploy", "status", "dep-1"])
    out = capsys.readouterr().out
    assert "dep-1" in out and "succeeded" in out


# ------------------------------------------------------------ admin reset --

def _make_hub_db(path: Path, username: str = "admin") -> None:
    """Hub DB와 비슷한 최소 스키마를 만든다 (settings + webauthn_credentials)."""
    import sqlite3
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE settings (key VARCHAR(64) PRIMARY KEY, value JSON, "
                "updated_at VARCHAR(40))")
    con.execute("CREATE TABLE webauthn_credentials (id INTEGER PRIMARY KEY, "
                "credential_id VARCHAR(128) UNIQUE, public_key TEXT, sign_count INTEGER, "
                "user_handle VARCHAR(128), label VARCHAR(120), device_type VARCHAR(32), "
                "backed_up BOOLEAN, created_at VARCHAR(40), last_used_at VARCHAR(40))")
    con.execute("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("admin", json.dumps({"username": username, "password_hash": "x",
                                      "created_at": "2026-10-21T00:00:00+00:00",
                                      "session_epoch": "abc"}),
                 "2026-10-21T00:00:00+00:00"))
    import base64
    handle = base64.urlsafe_b64encode(username.encode()).decode().rstrip("=")
    con.execute("INSERT INTO webauthn_credentials (credential_id, public_key, sign_count, "
                "user_handle, label, created_at) VALUES (?, ?, 0, ?, ?, ?)",
                ("cred-1", "pub", handle, "패스워드 키", "2026-10-21T00:00:00+00:00"))
    con.commit()
    con.close()


def test_admin_reset_requires_yes(monkeypatch):
    """--yes 없이는 백엔드를 호출하지 않고 거부한다."""
    monkeypatch.setenv("HUB_URL", "http://127.0.0.1:1/api/v1")
    with pytest.raises(SystemExit) as exc:
        main(["admin", "reset"])
    assert exc.value.code == 4


def test_admin_reset_api_posts(stub_server, monkeypatch, capsys):
    """API 모드는 reset-admin 엔드포인트를 호출한다."""
    url = stub_server({}, post_routes={
        "/api/v1/auth/reset-admin": (200, {"ok": True, "reset": True,
                                           "username": "admin", "setup_required": True})})
    monkeypatch.setenv("HUB_URL", url)
    main(["admin", "reset", "--yes"])
    out = capsys.readouterr().out
    assert "초기화" in out
    assert _Stub.last_post_path == "/api/v1/auth/reset-admin"


def test_admin_reset_api_sends_token(stub_server, monkeypatch, capsys):
    """복구 토큰이 주어지면 헤더로 전송된다."""
    url = stub_server({}, post_routes={
        "/api/v1/auth/reset-admin": (200, {"ok": True, "reset": True,
                                           "username": "admin", "setup_required": True})})
    monkeypatch.setenv("HUB_URL", url)
    main(["admin", "reset", "--yes", "--token", "secret-token"])
    capsys.readouterr()
    assert _Stub.last_headers.get("X-Hub-Admin-Reset-Token") == "secret-token"


def test_admin_reset_offline_deletes_admin_row(tmp_path, capsys):
    """오프라인 모드는 DB 파일에서 관리자 자격 증명만 지운다."""
    import sqlite3
    db = tmp_path / "hub.db"
    _make_hub_db(db)
    main(["admin", "reset", "--yes", "--db", str(db)])
    out = capsys.readouterr().out
    assert "초기화" in out

    con = sqlite3.connect(str(db))
    rows = con.execute("SELECT key FROM settings").fetchall()
    creds = con.execute("SELECT credential_id FROM webauthn_credentials").fetchall()
    con.close()
    assert rows == []
    assert creds == []
    # 백업 파일이 남는다
    assert list(tmp_path.glob("hub.db.bak-*"))


def test_admin_reset_offline_keeps_other_settings(tmp_path):
    """다른 설정 키는 지우지 않는다."""
    import sqlite3
    db = tmp_path / "hub.db"
    _make_hub_db(db)
    con = sqlite3.connect(str(db))
    con.execute("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("other", json.dumps({"x": 1}), "2026-10-21T00:00:00+00:00"))
    con.commit()
    con.close()

    main(["admin", "reset", "--yes", "--db", str(db)])

    con = sqlite3.connect(str(db))
    keys = [r[0] for r in con.execute("SELECT key FROM settings").fetchall()]
    con.close()
    assert keys == ["other"]


def test_admin_reset_offline_missing_db(tmp_path):
    """DB 파일이 없으면 종료 코드 5."""
    with pytest.raises(SystemExit) as exc:
        main(["admin", "reset", "--yes", "--db", str(tmp_path / "nope.db")])
    assert exc.value.code == 5


def test_admin_reset_offline_requires_admin(tmp_path):
    """관리자가 없는 DB는 거절한다."""
    import sqlite3
    db = tmp_path / "hub.db"
    _make_hub_db(db)
    con = sqlite3.connect(str(db))
    con.execute("DELETE FROM settings WHERE key='admin'")
    con.commit()
    con.close()
    with pytest.raises(SystemExit) as exc:
        main(["admin", "reset", "--yes", "--db", str(db)])
    assert exc.value.code == 5



# ---------------------------------------------------------------- apikey --

def test_service_new_chowns_to_backend_uid_when_root(tmp_path, monkeypatch, capsys):
    """root로 생성하면 롤백 쓰기 권한을 위해 10001:10001로 소유권을 맞춘다."""
    import os as _os

    chowned = []
    monkeypatch.setattr(_os, "geteuid", lambda: 0)
    monkeypatch.setattr(_os, "chown", lambda p, u, g: chowned.append((str(p), u, g)))
    main(["service", "new", "chown-app", "--dir", str(tmp_path)])
    assert chowned, "chown이 호출되지 않음"
    assert all(u == 10001 and g == 10001 for _, u, g in chowned)
    assert any(p.endswith("chown-app/service.yaml") for p, _, _ in chowned)


def test_apikey_create_offline_and_list(tmp_path, capsys):
    """오프라인 모드로 키를 발급하고, 평문은 1회만 출력된다."""
    import hashlib
    import sqlite3

    db = tmp_path / "hub.db"
    _make_hub_db(db)
    main(["apikey", "create", "--name", "claude-code", "--db", str(db)])
    out = capsys.readouterr().out
    assert "API 키를 발급했습니다" in out

    con = sqlite3.connect(str(db))
    rows = con.execute("SELECT id, name, scopes, key_hash FROM api_keys").fetchall()
    con.close()
    assert len(rows) == 1
    key_id, name, scopes, key_hash = rows[0]
    assert name == "claude-code"
    assert json.loads(scopes) == ["*"]
    # 저장된 값은 해시이며, 평문 키를 알 수 없어야 한다
    assert len(key_hash) == 64
    assert "hub_" not in key_hash

    main(["apikey", "list", "--db", str(db)])
    listed = capsys.readouterr().out
    assert key_id in listed
    assert "활성" in listed
    assert hashlib.sha256(b"x").hexdigest() != key_hash


def test_apikey_create_prints_key_once(tmp_path, capsys):
    """출력에 평문 키가 포함되고, 목록에는 포함되지 않는다."""
    db = tmp_path / "hub.db"
    _make_hub_db(db)
    main(["apikey", "create", "--name", "ai", "--db", str(db), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["key"].startswith("hub_")

    main(["apikey", "list", "--db", str(db), "--json"])
    listed = json.loads(capsys.readouterr().out)
    assert data["key"] not in json.dumps(listed)


def test_apikey_revoke_offline(tmp_path, capsys):
    import sqlite3

    db = tmp_path / "hub.db"
    _make_hub_db(db)
    main(["apikey", "create", "--name", "ai", "--db", str(db), "--json"])
    key_id = json.loads(capsys.readouterr().out)["id"]

    main(["apikey", "revoke", key_id, "--db", str(db)])
    assert "폐기" in capsys.readouterr().out

    con = sqlite3.connect(str(db))
    revoked = con.execute("SELECT revoked_at FROM api_keys WHERE id=?",
                          (key_id,)).fetchone()[0]
    con.close()
    assert revoked


def test_apikey_create_without_db_is_rejected(monkeypatch):
    """DB 경로가 없으면 대시보드/--db 사용법을 안내하고 종료 코드 2."""
    monkeypatch.delenv("HUB_DB_PATH", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(["apikey", "create", "--name", "x"])
    assert exc.value.code == 2
