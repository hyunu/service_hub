"""서비스 매칭 회귀 테스트 — 일반적인 컴포넌트 이름(web/api) 오매칭 방지.

배경:
  컴포넌트 이름 하위문자열 매칭 때문에 `trade-console-web` 컨테이너가
  pianosync 서비스의 `web` 컴포넌트로 잘못 연결되어, trade-console 서비스가
  "missing"으로 표시되고 같은 이름의 인벤토리 행이 2개 생겼다.
"""
from __future__ import annotations

from conftest import make_fake_container, mutate


def _service(client, sid: str, components: list[str], project: str | None = None) -> None:
    r = mutate(client, "POST", "/api/v1/services", json={
        "id": sid, "name": sid, "description": "", "category": "web",
        "deployment_type": "docker-compose",
        "deployment_path": f"/srv/services/{sid}",
        "components": [{"name": c, "role": "other"} for c in components],
    })
    assert r.status_code == 201, r.text


def _rows_by_name(client) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for c in client.get("/api/v1/containers").json()["items"]:
        out.setdefault(c["name"], []).append(c)
    return out


def test_generic_component_name_does_not_steal_other_service(client, gateway):
    """`-web` 접미사만으로 다른 서비스 컴포넌트에 연결되지 않는다."""
    _service(client, "pianosync", ["web"])
    _service(client, "trade-console", ["console"])
    gateway.containers = [
        make_fake_container("p1", "pianosync-web", project="pianosync", service="web"),
        make_fake_container("t1", "trade-console-web", project="trade-console",
                            service="console"),
    ]
    client.app.state.monitor.run_once()

    rows = _rows_by_name(client)
    assert rows["trade-console-web"][0]["service_id"] == "trade-console"
    assert rows["trade-console-web"][0]["component"] == "console"
    assert rows["pianosync-web"][0]["service_id"] == "pianosync"

    detail = client.get("/api/v1/services/trade-console").json()
    assert detail["status"] == "healthy"


def test_same_component_name_in_two_services_uses_project(client, gateway):
    """두 서비스에 같은 컴포넌트 이름이 있어도 compose 프로젝트로 구분한다."""
    _service(client, "alpha", ["web"])
    _service(client, "beta", ["web"])
    # alpha가 먼저 등록되어도 프로젝트가 beta인 컨테이너는 beta로 가야 한다.
    gateway.containers = [
        make_fake_container("b1", "beta-web", project="beta", service="web"),
        make_fake_container("a1", "alpha-web", project="alpha", service="web"),
    ]
    client.app.state.monitor.run_once()

    rows = _rows_by_name(client)
    assert rows["beta-web"][0]["service_id"] == "beta"
    assert rows["alpha-web"][0]["service_id"] == "alpha"


def test_labeled_name_without_compose_labels_is_unmanaged(client, gateway):
    """compose 라벨이 없고 이름도 정확히 일치하지 않으면 unmanaged로 둔다.

    (하위문자열 추정으로 다른 서비스에 붙이지 않는다 — 검토 후 수동 연결)
    """
    _service(client, "alpha", ["web"])
    gateway.containers = [make_fake_container("x1", "legacy-alpha-web")]
    client.app.state.monitor.run_once()

    row = _rows_by_name(client)["legacy-alpha-web"][0]
    assert row["management_state"] == "unmanaged"
    assert row["service_id"] is None


def test_stale_row_is_removed_after_correct_match(client, gateway):
    """같은 컴포넌트의 살아있는 컨테이너가 있으면 과거 행(중복 이름)은 정리된다."""
    _service(client, "trade-console", ["console"])
    # 과거 컨테이너(서비스명 web) → 나중에 삭제됨
    gateway.containers = [make_fake_container("old", "trade-console-web",
                                              project="trade-console", service="web")]
    client.app.state.monitor.run_once()
    # 새 컨테이너(서비스명 console)가 뜨고 과거 컨테이너는 사라짐
    gateway.containers = [make_fake_container("new", "trade-console-web",
                                              project="trade-console", service="console")]
    client.app.state.monitor.run_once()

    rows = _rows_by_name(client)["trade-console-web"]
    assert [r["container_id"] for r in rows] == ["new"]
    assert rows[0]["management_state"] == "managed"
    assert client.get("/api/v1/services/trade-console").json()["status"] == "healthy"
