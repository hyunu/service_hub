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

    def do_GET(self):  # noqa: N802
        code, body = self.routes.get(self.path, (404, {"detail": "not found", "code": "nf"}))
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

    def start(routes: dict[str, tuple[int, dict]]):
        handler = type("Handler", (_Stub,), {"routes": routes})
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


def test_deploy_plan_disabled_message(stub_server, monkeypatch, tmp_path):
    pytest.importorskip("yaml")
    f = tmp_path / "service.yaml"
    f.write_text("schema_version: 1\nservice: {}\n", encoding="utf-8")
    url = stub_server({"/api/v1/deployments/plan": (503,
        {"detail": "deployments disabled (Phase 3)", "code": "deploy_disabled"})})
    monkeypatch.setenv("HUB_URL", url)
    with pytest.raises(SystemExit) as exc:
        main(["deploy", "plan", str(f)])
    assert exc.value.code == 4


def test_schema_file_exists_and_is_valid_json():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == 1


def test_packaged_schema_in_sync_with_repo_schema():
    packaged = (REPO / "cli" / "hub_cli" / "schemas" / "service.schema.v1.json").read_text(encoding="utf-8")
    canonical = SCHEMA.read_text(encoding="utf-8")
    assert json.loads(packaged) == json.loads(canonical), (
        "cli/hub_cli/schemas/ 복사본이 저장소 루트 schemas/와 다릅니다. 동기화하세요.")
