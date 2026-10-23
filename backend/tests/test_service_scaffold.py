"""서비스 파일 생성(scaffold) 테스트.

AI 에이전트가 MCP로 서비스 정의 파일을 만들고 배포까지 진행할 수 있어야 한다.
안전: 경로/파일명 고정, 배포 게이트 필요, 덮어쓰기 확인.
"""
from __future__ import annotations

from conftest import mutate

SERVICE_YAML = """\
schema_version: 1
service:
  id: scaffold-app
  name: Scaffold App
  description: scaffold 테스트 서비스
  category: dev
deployment:
  type: docker-compose
  compose_file: compose.yaml
containers:
  - name: web
    role: other
    required: true
"""

COMPOSE_YAML = """\
services:
  web:
    image: alpine:latest
    command: ["sleep", "60"]
"""


def _client(app_factory, tmp_path):
    return app_factory(admin=True, enable_deploy=True, deploy_workdir=str(tmp_path),
                       gateway_allow_mutations=True)


def test_scaffold_writes_files(app_factory, tmp_path):
    client = _client(app_factory, tmp_path)
    try:
        r = mutate(client, "POST", "/api/v1/services/scaffold-app/scaffold",
                   json={"service_yaml": SERVICE_YAML, "compose_yaml": COMPOSE_YAML})
        assert r.status_code == 201, r.text
        d = tmp_path / "scaffold-app"
        assert (d / "service.yaml").read_text(encoding="utf-8") == SERVICE_YAML
        assert "services:" in (d / "compose.yaml").read_text(encoding="utf-8")
        logs = client.get("/api/v1/audit-logs").json()["items"]
        assert any(a["action"] == "service.scaffold" for a in logs)
    finally:
        client.__exit__(None, None, None)


def test_scaffold_requires_deploy_gate(client):
    r = mutate(client, "POST", "/api/v1/services/scaffold-app/scaffold",
               json={"service_yaml": SERVICE_YAML, "compose_yaml": COMPOSE_YAML})
    assert r.status_code == 503
    assert r.json()["code"] == "deploy_disabled"


def test_scaffold_rejects_id_mismatch_and_bad_compose(app_factory, tmp_path):
    client = _client(app_factory, tmp_path)
    try:
        r = mutate(client, "POST", "/api/v1/services/other-app/scaffold",
                   json={"service_yaml": SERVICE_YAML, "compose_yaml": COMPOSE_YAML})
        assert r.status_code == 422
        assert r.json()["code"] == "id_mismatch"

        r2 = mutate(client, "POST", "/api/v1/services/scaffold-app/scaffold",
                    json={"service_yaml": SERVICE_YAML, "compose_yaml": "foo: bar\n"})
        assert r2.status_code == 422
        assert r2.json()["code"] == "compose_invalid"

        r3 = mutate(client, "POST", "/api/v1/services/Bad_ID/scaffold",
                    json={"service_yaml": SERVICE_YAML, "compose_yaml": COMPOSE_YAML})
        assert r3.status_code == 422
        assert r3.json()["code"] == "invalid_service_id"
    finally:
        client.__exit__(None, None, None)


def test_scaffold_overwrite_requires_confirm(app_factory, tmp_path):
    client = _client(app_factory, tmp_path)
    try:
        body = {"service_yaml": SERVICE_YAML, "compose_yaml": COMPOSE_YAML}
        assert mutate(client, "POST", "/api/v1/services/scaffold-app/scaffold",
                      json=body).status_code == 201
        # 덮어쓰기 옵션 없음
        r = mutate(client, "POST", "/api/v1/services/scaffold-app/scaffold", json=body)
        assert r.status_code == 409
        assert r.json()["code"] == "already_exists"
        # overwrite만 있고 confirm 없음
        r2 = mutate(client, "POST", "/api/v1/services/scaffold-app/scaffold",
                    json={**body, "overwrite": True})
        assert r2.status_code == 409
        # 둘 다 있으면 허용
        r3 = mutate(client, "POST", "/api/v1/services/scaffold-app/scaffold",
                    json={**body, "overwrite": True, "confirm": "scaffold-app"})
        assert r3.status_code == 201, r3.text
    finally:
        client.__exit__(None, None, None)


def test_scaffold_requires_csrf(app_factory, tmp_path):
    client = _client(app_factory, tmp_path)
    try:
        r = client.post("/api/v1/services/scaffold-app/scaffold",
                        json={"service_yaml": SERVICE_YAML, "compose_yaml": COMPOSE_YAML},
                        headers={"X-CSRF-Token": "forged"})
        assert r.status_code == 403
        assert r.json()["code"] == "csrf"
    finally:
        client.__exit__(None, None, None)
