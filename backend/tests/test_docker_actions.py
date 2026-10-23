"""컨테이너/이미지 조작 테스트 — 게이트·보호·확인·감사.

AGENTS.md 규칙 #1(기존 서비스 보호), #7(위험 API는 권한/승인 강제 + 테스트) 대응.
"""
from __future__ import annotations

from app.config import Settings
from conftest import make_fake_container, mutate


def _client(app_factory, settings, **overrides):
    """Docker 조작이 켜진 클라이언트 (테스트별 보호 설정 주입 가능)."""
    s = Settings(db_path=settings.db_path, status_cache=settings.status_cache,
                 monitor_enabled=False, enable_docker_actions=True,
                 _env_file=None, **overrides)
    return app_factory(s=s, admin=True, gateway_allow_mutations=True)


def _gw(client):
    return client.app.state.monitor.gateway


def _sync(client):
    client.app.state.monitor.run_once()


def test_actions_disabled_by_default(client):
    """기본값은 잠금 — 컨테이너를 조회조차 하기 전에 503."""
    r = mutate(client, "POST", "/api/v1/containers/anything/start")
    assert r.status_code == 503
    assert r.json()["code"] == "docker_actions_disabled"


def test_start_and_stop_container(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        _gw(client).containers = [make_fake_container("c1", "web", project="p",
                                                      service="web", running=False)]
        _sync(client)
        r = mutate(client, "POST", "/api/v1/containers/c1/start")
        assert r.status_code == 200, r.text
        assert r.json()["runtime_changed"] is True
        assert client.get("/api/v1/containers/c1").json()["state"] == "running"

        r2 = mutate(client, "POST", "/api/v1/containers/c1/stop")
        assert r2.status_code == 200, r2.text
        assert client.get("/api/v1/containers/c1").json()["state"] != "running"

        actions = [a["action"] for a in client.get("/api/v1/audit-logs").json()["items"]]
        assert "container.start" in actions and "container.stop" in actions
    finally:
        client.__exit__(None, None, None)


def test_hub_self_container_is_protected(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        _gw(client).containers = [make_fake_container("hub1", "hub-backend",
                                                      project="service-hub",
                                                      service="backend")]
        _sync(client)
        r = mutate(client, "POST", "/api/v1/containers/hub1/stop")
        assert r.status_code == 403
        assert r.json()["code"] == "protected_container"
    finally:
        client.__exit__(None, None, None)


def test_protected_container_and_project(app_factory, settings):
    client = _client(app_factory, settings, protected_containers="assetnest",
                     protected_projects="infra")
    try:
        _gw(client).containers = [
            make_fake_container("a1", "assetnest-server", project="other", service="s"),
            make_fake_container("a2", "mongo", project="infra", service="db"),
            make_fake_container("a3", "free-app", project="free", service="app"),
        ]
        _sync(client)
        # 이름 접두사 보호
        r = mutate(client, "POST", "/api/v1/containers/a1/start")
        assert r.status_code == 403 and r.json()["code"] == "protected_container"
        # compose 프로젝트 보호
        r2 = mutate(client, "POST", "/api/v1/containers/a2/start")
        assert r2.status_code == 403 and r2.json()["code"] == "protected_container"
        # 보호 대상이 아니면 허용
        r3 = mutate(client, "POST", "/api/v1/containers/a3/start")
        assert r3.status_code == 200, r3.text
    finally:
        client.__exit__(None, None, None)


def test_remove_requires_stop_and_exact_confirm(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        _gw(client).containers = [make_fake_container("c9", "old-app", project="p",
                                                      service="app", running=True)]
        _sync(client)
        # 실행 중이면 거부
        r = mutate(client, "POST", "/api/v1/containers/c9/remove",
                   json={"confirm": "old-app"})
        assert r.status_code == 409
        assert r.json()["code"] == "container_running"

        mutate(client, "POST", "/api/v1/containers/c9/stop")
        # 확인 이름 불일치
        r2 = mutate(client, "POST", "/api/v1/containers/c9/remove",
                    json={"confirm": "wrong"})
        assert r2.status_code == 422
        assert r2.json()["code"] == "confirm_mismatch"

        # 정확한 이름 → 제거
        r3 = mutate(client, "POST", "/api/v1/containers/c9/remove",
                    json={"confirm": "old-app"})
        assert r3.status_code == 200, r3.text
        assert client.get("/api/v1/containers/c9").status_code == 404
        actions = [a["action"] for a in client.get("/api/v1/audit-logs").json()["items"]]
        assert "container.remove" in actions
    finally:
        client.__exit__(None, None, None)


def test_images_list_is_read_only(app_factory, settings):
    """조작 게이트가 꺼져 있어도 이미지 목록 조회는 가능해야 한다."""
    from app.config import Settings as S

    s = S(db_path=settings.db_path, status_cache=settings.status_cache,
          monitor_enabled=False, enable_docker_actions=False, _env_file=None)
    client = app_factory(s=s, admin=True, gateway_allow_mutations=False)
    try:
        _gw(client).images = [{"id": "sha256:aaa", "short_id": "sha256:aaa",
                               "tags": ["alpine:latest"], "size_mb": 5.0,
                               "created_at": None}]
        r = client.get("/api/v1/images")
        assert r.status_code == 200
        assert r.json()["actions_enabled"] is False
        assert len(r.json()["items"]) == 1
    finally:
        client.__exit__(None, None, None)


def test_image_remove_blocks_in_use_and_hub_images(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        _gw(client).images = [
            {"id": "sha256:use1", "short_id": "sha256:use1", "tags": ["alpine:latest"],
             "size_mb": 5.0, "created_at": None},
            {"id": "sha256:hub1", "short_id": "sha256:hub1",
             "tags": ["n100-service-hub-backend:0.1.0"], "size_mb": 200.0,
             "created_at": None},
            {"id": "sha256:free", "short_id": "sha256:free", "tags": ["unused:1"],
             "size_mb": 9.0, "created_at": None},
        ]
        _gw(client).containers = [make_fake_container("c1", "web", project="p",
                                                      service="web", image="alpine:latest")]
        _sync(client)

        # 사용 중 → 거부
        r = mutate(client, "POST", "/api/v1/images/sha256:use1/remove",
                   json={"confirm": "alpine:latest"})
        assert r.status_code == 409
        assert r.json()["code"] == "image_in_use"

        # 허브 이미지 → 거부
        r2 = mutate(client, "POST", "/api/v1/images/sha256:hub1/remove",
                    json={"confirm": "n100-service-hub-backend:0.1.0"})
        assert r2.status_code == 403
        assert r2.json()["code"] == "protected_image"

        # 미사용 → 확인 불일치 422
        r3 = mutate(client, "POST", "/api/v1/images/sha256:free/remove",
                    json={"confirm": "nope"})
        assert r3.status_code == 422

        # 미사용 + 올바른 확인 → 제거
        r4 = mutate(client, "POST", "/api/v1/images/sha256:free/remove",
                    json={"confirm": "unused:1"})
        assert r4.status_code == 200, r4.text
        assert [i["id"] for i in client.get("/api/v1/images").json()["items"]] == [
            "sha256:use1", "sha256:hub1"]
        actions = [a["action"] for a in client.get("/api/v1/audit-logs").json()["items"]]
        assert "image.remove" in actions
    finally:
        client.__exit__(None, None, None)


def test_actions_require_csrf(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        _gw(client).containers = [make_fake_container("c1", "web", project="p",
                                                      service="web")]
        _sync(client)
        r = client.post("/api/v1/containers/c1/start",
                        headers={"X-CSRF-Token": "forged"})
        assert r.status_code == 403
        assert r.json()["code"] == "csrf"
    finally:
        client.__exit__(None, None, None)
