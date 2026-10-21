"""수동 그룹핑(컨테이너 ↔ 서비스) 테스트.

핵심 회귀 방지:
  - 수동 연결이 15초 주기 sync_inventory 이후에도 유지된다(이름 매칭이 아님).
  - 다른 서비스에 연결된 컨테이너를 빼앗지 않는다.
  - 해제(detach)가 다음 동기화에서 자동매칭으로 되살아나지 않는다.
"""
from __future__ import annotations

from conftest import make_fake_container, mutate


def _service(client, sid: str = "grp", components: list[dict] | None = None) -> dict:
    r = mutate(client, "POST", "/api/v1/services", json={
        "id": sid, "name": sid, "description": "", "category": "infra",
        "components": components or [],
    })
    assert r.status_code == 201, r.text
    return r.json()


def _containers(*specs):
    return [make_fake_container(cid, name, project=proj, service=svc)
            for cid, name, proj, svc in specs]


def test_bulk_attach_groups_and_survives_sync(client, gateway):
    """여러 컨테이너를 한 번에 그룹핑하고, 주기 동기화 후에도 유지된다."""
    _service(client)
    gateway.containers = _containers(
        ("c1", "proj-web-1", "proj", "web"),
        ("c2", "proj-api-1", "proj", "api"),
        ("c3", "proj-db-1", "proj", "db"),
    )
    client.app.state.monitor.run_once()

    orphans = client.get("/api/v1/orphans").json()["items"]
    ids = [o["container_id"] for o in orphans]
    assert set(ids) == {"c1", "c2", "c3"}

    r = mutate(client, "POST", "/api/v1/orphans/attach", json={
        "service_id": "grp", "container_ids": ids})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["attached"] == 3 and body["skipped"] == 0
    assert body["runtime_unchanged"] is True

    detail = client.get("/api/v1/services/grp").json()
    assert {c["name"] for c in detail["components"]} == {"web", "api", "db"}

    # 주기 동기화를 한 번 더 돌려도 연결이 유지되어야 한다.
    client.app.state.monitor.run_once()
    items = client.get("/api/v1/services/grp/containers").json()["items"]
    assert len(items) == 3
    assert {i["component"] for i in items} == {"web", "api", "db"}
    assert all(i["manual"] for i in items)

    listed = client.get("/api/v1/containers").json()["items"]
    by_id = {c["container_id"]: c for c in listed}
    assert all(by_id[cid]["manual"] for cid in ("c1", "c2", "c3"))
    assert all(by_id[cid]["service_id"] == "grp" for cid in ("c1", "c2", "c3"))


def test_bulk_attach_can_use_one_component_name(client, gateway):
    """component_name을 지정하면 여러 컨테이너를 한 컴포넌트(replica)로 묶는다."""
    _service(client)
    gateway.containers = _containers(
        ("c1", "proj-web-1", "proj", "web"),
        ("c2", "proj-web-2", "proj", "web"),
    )
    client.app.state.monitor.run_once()

    r = mutate(client, "POST", "/api/v1/orphans/attach", json={
        "service_id": "grp", "container_ids": ["c1", "c2"], "component_name": "web"})
    assert r.json()["attached"] == 2
    detail = client.get("/api/v1/services/grp").json()
    assert [c["name"] for c in detail["components"]] == ["web"]
    items = client.get("/api/v1/services/grp/containers").json()["items"]
    assert {i["component"] for i in items} == {"web"}


def test_bulk_attach_does_not_steal_from_other_service(client, gateway):
    _service(client, "svc-a")
    _service(client, "svc-b")
    gateway.containers = _containers(("c1", "svc-a-web-1", "svc-a", "web"))
    client.app.state.monitor.run_once()

    mutate(client, "POST", "/api/v1/orphans/attach",
           json={"service_id": "svc-a", "container_ids": ["c1"]})
    r = mutate(client, "POST", "/api/v1/orphans/attach",
               json={"service_id": "svc-b", "container_ids": ["c1"]})
    body = r.json()
    assert body["attached"] == 0 and body["skipped"] == 1
    assert "이미 서비스 'svc-a'" in body["results"][0]["reason"]
    assert client.get("/api/v1/containers/c1").json()["service_id"] == "svc-a"


def test_detach_removes_manual_link_and_component(client, gateway):
    """해제 후 자동매칭으로 되살아나지 않아야 한다."""
    _service(client)
    gateway.containers = _containers(("c1", "proj-web-1", "proj", "web"))
    client.app.state.monitor.run_once()
    mutate(client, "POST", "/api/v1/orphans/attach",
           json={"service_id": "grp", "container_ids": ["c1"]})

    r = mutate(client, "POST", "/api/v1/containers/c1/detach")
    assert r.status_code == 200, r.text
    assert r.json()["detached"] is True

    client.app.state.monitor.run_once()      # 자동매칭 재연결 시도
    assert client.get("/api/v1/services/grp").json()["components"] == []
    c = client.get("/api/v1/containers/c1").json()
    assert c["service_id"] is None
    assert c["management_state"] == "unmanaged"
    assert c["manual"] is False


def test_declared_component_detach_is_expected_to_rematch(client, gateway):
    """사용자가 선언한 컴포넌트와 이름이 같으면 해제해도 자동 재연결된다(정상)."""
    _service(client, components=[{"name": "web", "role": "frontend", "required": True}])
    gateway.containers = _containers(("c1", "proj-web-1", "proj", "web"))
    client.app.state.monitor.run_once()

    assert client.get("/api/v1/containers/c1").json()["service_id"] == "grp"
    r = mutate(client, "POST", "/api/v1/containers/c1/detach")
    assert r.json()["detached"] is True
    client.app.state.monitor.run_once()
    # 선언된 컴포넌트이므로 이름 매칭으로 다시 연결된다 (컴포넌트는 보존)
    assert client.get("/api/v1/containers/c1").json()["service_id"] == "grp"
    assert [c["name"] for c in client.get("/api/v1/services/grp").json()["components"]] == ["web"]


def test_auto_attach_by_compose_project(client, gateway):
    """서비스 등록 직후 compose 프로젝트 단위로 한 번에 그룹핑한다."""
    _service(client, "proj")
    gateway.containers = _containers(
        ("c1", "proj-web-1", "proj", "web"),
        ("c2", "proj-api-1", "proj", "api"),
        ("c3", "other-x-1", "other", "x"),
    )
    client.app.state.monitor.run_once()

    r = mutate(client, "POST", "/api/v1/services/proj/auto-attach", json={})
    assert r.status_code == 200, r.text
    assert r.json()["attached"] == 2
    assert r.json()["compose_project"] == "proj"

    items = client.get("/api/v1/services/proj/containers").json()["items"]
    assert {i["container_id"] for i in items} == {"c1", "c2"}
    assert client.get("/api/v1/containers/c3").json()["service_id"] is None


def test_auto_attach_without_matching_containers(client):
    _service(client, "empty")
    r = mutate(client, "POST", "/api/v1/services/empty/auto-attach", json={})
    assert r.status_code == 200
    assert r.json()["attached"] == 0
    assert "없습니다" in r.json()["note"]


def test_manual_only_group_is_healthy(client, gateway):
    """필수 컴포넌트가 없어도(수동 그룹핑) 실행 중이면 healthy로 판정한다."""
    _service(client)
    gateway.containers = _containers(("c1", "proj-web-1", "proj", "web"))
    client.app.state.monitor.run_once()
    mutate(client, "POST", "/api/v1/orphans/attach",
           json={"service_id": "grp", "container_ids": ["c1"]})
    client.app.state.monitor.run_once()
    assert client.get("/api/v1/services/grp").json()["status"] == "healthy"


def test_bulk_attach_requires_csrf(client):
    _service(client)
    r = client.post("/api/v1/orphans/attach",
                    json={"service_id": "grp", "container_ids": ["c1"]},
                    headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    assert r.json()["code"] == "csrf"


def test_service_delete_clears_assignments(client, gateway):
    _service(client)
    gateway.containers = _containers(("c1", "proj-web-1", "proj", "web"))
    client.app.state.monitor.run_once()
    mutate(client, "POST", "/api/v1/orphans/attach",
           json={"service_id": "grp", "container_ids": ["c1"]})

    r = mutate(client, "DELETE", "/api/v1/services/grp?confirm=grp")
    assert r.status_code == 200, r.text
    client.app.state.monitor.run_once()
    c = client.get("/api/v1/containers/c1").json()
    assert c["service_id"] is None
    assert c["manual"] is False
