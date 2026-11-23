"""미사용 컨테이너 일괄 정리 테스트 — 게이트·보호·확인·감사.

AGENTS.md 규칙 #1(기존 서비스 보호), #7(위험 API는 권한/승인 강제 + 테스트) 대응.

정책:
  - 후보는 **중지된 미관리(unmanaged)** 컨테이너만.
  - 실행 중/허브 자신/보호 대상/서비스 소속은 항상 건너뛴다.
  - dangling(태그 없음) 이미지만 함께 제거하고, 사용 중이거나 태그가 있는 이미지는 남긴다.
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


def _cleanup(client, ids, **extra):
    body = {"container_ids": ids, "confirm": "cleanup"}
    body.update(extra)
    return mutate(client, "POST", "/api/v1/containers/cleanup", json=body)


def _service(client, sid: str, components: list[str]) -> None:
    r = mutate(client, "POST", "/api/v1/services", json={
        "id": sid, "name": sid, "description": "", "category": "web",
        "deployment_type": "docker-compose",
        "deployment_path": f"/srv/services/{sid}",
        "components": [{"name": c, "role": "other"} for c in components],
    })
    assert r.status_code == 201, r.text


def test_cleanup_is_gated_by_default(client):
    """기본 잠금 — 게이트가 꺼져 있으면 503."""
    r = _cleanup(client, ["c1"])
    assert r.status_code == 503
    assert r.json()["code"] == "docker_actions_disabled"


def test_cleanup_requires_confirm_and_target(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        _gw(client).containers = [make_fake_container(
            "c1", "old-app", project="p", service="app", running=False)]
        _sync(client)

        r = mutate(client, "POST", "/api/v1/containers/cleanup",
                   json={"container_ids": ["c1"], "confirm": "nope"})
        assert r.status_code == 422
        assert r.json()["code"] == "confirm_mismatch"

        r2 = _cleanup(client, [], remove_dangling_images=False)
        assert r2.status_code == 422
        assert r2.json()["code"] == "nothing_to_clean"
    finally:
        client.__exit__(None, None, None)


def test_cleanup_removes_only_stopped_unmanaged(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        _service(client, "demo", ["web"])
        _gw(client).containers = [
            make_fake_container("c1", "old-app", project="p", service="app",
                                running=False),
            make_fake_container("c2", "still-running", project="p", service="app"),
            make_fake_container("c3", "demo-web", project="demo", service="web",
                                running=False),
            make_fake_container("hub1", "hub-backend", project="service-hub",
                                service="backend", running=False),
        ]
        _sync(client)

        r = _cleanup(client, ["c1", "c2", "c3", "hub1", "ghost"],
                     remove_dangling_images=False)
        assert r.status_code == 200, r.text
        data = r.json()
        assert [x["container_id"] for x in data["removed"]] == ["c1"]

        codes = {x["container_id"]: x["code"] for x in data["skipped"]}
        assert codes["c2"] == "container_running"
        assert codes["c3"] == "container_managed"
        assert codes["hub1"] == "protected_container"
        assert codes["ghost"] == "container_not_found"

        # 실제로 사라진 것은 c1뿐 — 나머지는 인벤토리에 남아 있다.
        ids = {c["container_id"]
               for c in client.get("/api/v1/containers").json()["items"]}
        assert "c1" not in ids
        assert {"c2", "c3", "hub1"} <= ids

        actions = [a["action"] for a in client.get("/api/v1/audit-logs").json()["items"]]
        assert "container.remove" in actions
        assert "cleanup.run" in actions
    finally:
        client.__exit__(None, None, None)


def test_cleanup_rejects_protected_patterns(app_factory, settings):
    client = _client(app_factory, settings, protected_containers="assetnest",
                     protected_projects="infra")
    try:
        _gw(client).containers = [
            make_fake_container("a1", "assetnest-server", project="other",
                                service="s", running=False),
            make_fake_container("a2", "some-db", project="infra", service="db",
                                running=False),
        ]
        _sync(client)

        r = _cleanup(client, ["a1", "a2"], remove_dangling_images=False)
        assert r.status_code == 200, r.text
        assert r.json()["removed"] == []
        assert {x["code"] for x in r.json()["skipped"]} == {"protected_container"}
        assert client.get("/api/v1/containers/a1").status_code == 200
    finally:
        client.__exit__(None, None, None)


def test_cleanup_removes_only_unused_dangling_images(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        gw = _gw(client)
        gw.containers = [
            make_fake_container("c1", "old-app", project="p", service="app",
                                running=False),
            make_fake_container("c2", "live-app", project="p", service="app",
                                image="sha256:live"),
        ]
        gw.images = [
            # 태그 없음 + 미사용 → 제거
            {"id": "sha256:dead", "short_id": "sha256:dead", "tags": [],
             "size_mb": 12.0, "created_at": None},
            # 태그 있음 → dangling이 아니므로 유지
            {"id": "sha256:tagged", "short_id": "sha256:tagged",
             "tags": ["unused:1"], "size_mb": 9.0, "created_at": None},
            # 실행 중 컨테이너가 사용 → 유지
            {"id": "sha256:live", "short_id": "sha256:live", "tags": [],
             "size_mb": 20.0, "created_at": None},
            # 허브 이미지 → 유지
            {"id": "sha256:hub", "short_id": "sha256:hub",
             "tags": ["n100-service-hub-backend:0.1.0"], "size_mb": 200.0,
             "created_at": None},
        ]
        _sync(client)

        r = _cleanup(client, ["c1"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert [x["image_id"] for x in data["images_removed"]] == ["sha256:dead"]
        assert data["freed_image_mb"] == 12.0
        # 사용 중 dangling 이미지는 건너뛴 사유가 남는다.
        assert any(x["image_id"] == "sha256:live" for x in data["images_skipped"])

        remaining = {i["id"] for i in client.get("/api/v1/images").json()["items"]}
        assert remaining == {"sha256:tagged", "sha256:live", "sha256:hub"}
    finally:
        client.__exit__(None, None, None)


def test_cleanup_can_remove_dangling_images_only(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        gw = _gw(client)
        gw.containers = []
        gw.images = [{"id": "sha256:dead", "short_id": "sha256:dead", "tags": [],
                      "size_mb": 3.5, "created_at": None}]
        r = _cleanup(client, [], remove_dangling_images=True)
        assert r.status_code == 200, r.text
        assert r.json()["removed"] == []
        assert [x["image_id"] for x in r.json()["images_removed"]] == ["sha256:dead"]
    finally:
        client.__exit__(None, None, None)


def test_container_list_reports_cleanup_eligibility(app_factory, settings):
    client = _client(app_factory, settings)
    try:
        _service(client, "demo", ["web"])
        _gw(client).containers = [
            make_fake_container("c1", "old-app", project="p", service="app",
                                running=False),
            make_fake_container("c2", "still-running", project="p", service="app"),
            make_fake_container("c3", "demo-web", project="demo", service="web",
                                running=False),
        ]
        _sync(client)

        items = {c["container_id"]: c
                 for c in client.get("/api/v1/containers").json()["items"]}
        assert items["c1"]["cleanup_eligible"] is True
        assert items["c1"]["cleanup_reason"] is None
        assert items["c2"]["cleanup_eligible"] is False
        assert items["c2"]["cleanup_reason"]
        assert items["c3"]["cleanup_eligible"] is False
    finally:
        client.__exit__(None, None, None)
