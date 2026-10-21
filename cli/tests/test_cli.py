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
        code, body = self.routes.get(self.path, (404, {"detail": "not found", "code": "nf"}))
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):  # noqa: N802
        _Stub.last_post_path = self.path
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
