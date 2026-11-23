"""서비스 단위 중지/재시작 테스트 — 게이트·보호·확인·감사.

정책:
  - 서비스에 연결된 **모든 컨테이너**를 대상으로 순차 실행한다.
  - ``HUB_ENABLE_DOCKER_ACTIONS=false`` 면 503, ``confirmed=true`` 없으면 409.
  - 보호 대상(허브 자신/``HUB_PROTECTED_*``)이 하나라도 포함되면 전체를 거부한다.
  - restart 는 실행 중 컨테이너를 stop→start, 이미 중지된 컨테이너는 start 한다.
"""
from __future__ import annotations

from app.config import Settings
from conftest import make_fake_container, mutate


def _client(app_factory, settings, **overrides):
    s = Settings(db_path=settings.db_path, status_cache=settings.status_cache,
                 monitor_enabled=False, enable_docker_actions=True,
                 _env_file=None, **overrides)
    return app_factory(s=s, admin=True, gateway_allow_mutations=True)


def _gw(client):
    return client.app.state.monitor.gateway


def _sync(client):
    client.app.state.monitor.run_once()


def _service(client, sid: str, components: list[str]) -> None:
    r = mutate(client, "POST", "/api/v1/services", json={
        "id": sid, "name": sid, "description": "", "category": "web",
        "deployment_type": "docker-compose",
        "deployment_path": f"/srv/services/{sid}",
        "components": [{"name": c, "role": "other"} for c in components],
    })
    assert r.status_code == 201, r.text


def _action(client, sid: str, action: str, confirmed: bool = True):
    return mutate(client, "POST", f"/api/v1/services/{sid}/{action}",
                  json={"confirmed": confirmed})


def test_service_stop_is_gated_by_default(client):
    r = _action(client, "anything", "stop")
    assert r.status_code == 503
    assert r.json()["code"] == "docker_actions_disabled"


def test_service_stop_requires_confirmation_and_containers(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        _service(client, "demo", ["web"])
        _gw(client).containers = [make_fake_container(
            "c1", "demo-web", project="demo", service="web")]
        _sync(client)

        r = _action(client, "demo", "stop", confirmed=False)
        assert r.status_code == 409
        assert r.json()["code"] == "confirmation_required"

        _service(client, "empty", [])
        r2 = _action(client, "empty", "stop")
        assert r2.status_code == 409
        assert r2.json()["code"] == "service_no_containers"

        r3 = _action(client, "nope", "stop")
        assert r3.status_code == 404
        assert r3.json()["code"] == "service_not_found"
    finally:
        client.__exit__(None, None, None)


def test_stop_service_stops_all_containers_and_audits(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        _service(client, "demo", ["web", "api"])
        _gw(client).containers = [
            make_fake_container("c1", "demo-web", project="demo", service="web"),
            make_fake_container("c2", "demo-api", project="demo", service="api"),
            make_fake_container("x1", "other-app", project="other", service="app"),
        ]
        _sync(client)

        r = _action(client, "demo", "stop")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["stopped"] == 2
        assert data["runtime_changed"] is True
        assert {x["container_id"] for x in data["results"]["stopped"]} == {"c1", "c2"}

        states = {c["container_id"]: c["state"]
                  for c in client.get("/api/v1/containers").json()["items"]}
        assert states["c1"] != "running" and states["c2"] != "running"
        assert states["x1"] == "running"          # 다른 서비스는 그대로

        actions = [a["action"] for a in client.get("/api/v1/audit-logs").json()["items"]]
        assert "service.stop" in actions
        assert actions.count("container.stop") >= 2
    finally:
        client.__exit__(None, None, None)


def test_restart_service_handles_running_and_stopped(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        _service(client, "demo", ["web", "api"])
        _gw(client).containers = [
            make_fake_container("c1", "demo-web", project="demo", service="web"),
            make_fake_container("c2", "demo-api", project="demo", service="api",
                                running=False),
        ]
        _sync(client)

        r = _action(client, "demo", "restart")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["started"] == 2
        assert data["stopped"] == 1      # c1만 실행 중이었으므로 stop 1회

        states = {c["container_id"]: c["state"]
                  for c in client.get("/api/v1/containers").json()["items"]}
        assert states["c1"] == "running" and states["c2"] == "running"

        actions = [a["action"] for a in client.get("/api/v1/audit-logs").json()["items"]]
        assert "service.restart" in actions
        assert "container.start" in actions
    finally:
        client.__exit__(None, None, None)


def test_protected_service_is_refused_entirely(app_factory, settings):
    client = _client(app_factory, settings, protected_containers="assetnest",
                     protected_projects="infra")
    try:
        _service(client, "asset-nest", ["server", "dashboard"])
        _gw(client).containers = [
            make_fake_container("a1", "assetnest-server", project="infra", service="server"),
            make_fake_container("a2", "assetnest-dashboard", project="infra",
                                service="dashboard"),
        ]
        _sync(client)
        _gw(client).mutation_log.clear()

        r = _action(client, "asset-nest", "stop")
        assert r.status_code == 403
        assert r.json()["code"] == "protected_container"
        # 하나도 변경되지 않아야 한다 (부분 실행 금지)
        assert _gw(client).mutation_log == []
        states = {c["container_id"]: c["state"]
                  for c in client.get("/api/v1/containers").json()["items"]}
        assert states == {"a1": "running", "a2": "running"}
    finally:
        client.__exit__(None, None, None)


def test_missing_container_is_skipped_not_failed(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        _service(client, "demo", ["web", "api"])
        _gw(client).containers = [
            make_fake_container("c1", "demo-web", project="demo", service="web"),
            make_fake_container("c2", "demo-api", project="demo", service="api"),
        ]
        _sync(client)
        _gw(client).containers = [c for c in _gw(client).containers if c.id != "c2"]

        r = _action(client, "demo", "restart")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["started"] == 1
        assert any(x["code"] == "container_missing" for x in data["results"]["skipped"])
    finally:
        client.__exit__(None, None, None)


def test_service_detail_reports_action_eligibility(app_factory, settings):
    client = _client(app_factory, settings, protected_containers="assetnest")
    try:
        _service(client, "demo", ["web"])
        _service(client, "asset-nest", ["server"])
        _gw(client).containers = [
            make_fake_container("c1", "demo-web", project="demo", service="web"),
            make_fake_container("a1", "assetnest-server", project="infra", service="server"),
        ]
        _sync(client)

        demo = client.get("/api/v1/services/demo").json()
        assert demo["actions_allowed"] is True
        assert demo["actions_reason"] is None

        protected = client.get("/api/v1/services/asset-nest").json()
        assert protected["actions_allowed"] is False
        assert protected["actions_reason"]
    finally:
        client.__exit__(None, None, None)
