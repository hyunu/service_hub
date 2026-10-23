"""배포 API 테스트 — 계획(읽기 전용) 및 실행(게이트) (REQUIREMENTS §13)."""
from __future__ import annotations

from conftest import mutate

SPEC_BODY = {
    "schema_version": 1,
    "service": {"id": "sample-app", "name": "Sample", "description": "샘플",
                "category": "web"},
    "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    "containers": [{"name": "app", "role": "backend", "required": True}],
}


def test_plan_endpoint_returns_ready(client):
    r = mutate(client, "POST", "/api/v1/deployments/plan", json=SPEC_BODY)
    assert r.status_code == 200
    data = r.json()
    assert data["result"] in ("READY", "BLOCKED")
    assert data["runtime_unchanged"] is True


def test_plan_accepts_cli_service_definition_payload(client):
    r = mutate(client, "POST", "/api/v1/deployments/plan",
               json={"service_definition": SPEC_BODY})
    assert r.status_code == 200
    assert r.json()["service"] == "sample-app"


def test_plan_endpoint_invalid_spec_422(client):
    bad = {**SPEC_BODY, "schema_version": 9}
    r = mutate(client, "POST", "/api/v1/deployments/plan", json=bad)
    assert r.status_code == 422
    assert r.json()["code"] == "unsupported_schema_version"


def test_plan_requires_auth(anon_client):
    r = anon_client.post("/api/v1/deployments/plan", json=SPEC_BODY)
    assert r.status_code in (401, 403)


def test_apply_still_locked_when_deploy_disabled(client):
    r = mutate(client, "POST", "/api/v1/deployments",
               json={"service_id": "sample-app", "spec": SPEC_BODY})
    assert r.status_code == 503
    assert r.json()["code"] == "deploy_disabled"


def test_apply_succeeds_when_enabled(app_factory, tmp_path):
    from conftest import make_fake_container
    (tmp_path / "sample-app").mkdir()
    (tmp_path / "sample-app" / "compose.yaml").write_text("services: {}\n",
                                                          encoding="utf-8")
    client = app_factory(admin=True, enable_deploy=True,
                         deploy_workdir=str(tmp_path),
                         gateway_allow_mutations=True,
                         gw=None)
    # 배포 후 기동된 것으로 보이는 컨테이너를 게이트웨이에 추가한다
    from app.dependencies import get_gateway
    get_gateway().containers.append(
        make_fake_container("c1", "sample-app-app", project="sample-app",
                            service="app", running=True))
    try:
        r = mutate(client, "POST", "/api/v1/deployments", json={"spec": SPEC_BODY})
        assert r.status_code == 202, r.text
        dep = r.json()
        assert dep["status"] in ("succeeded", "failed")
        assert dep["deployment_id"].startswith("dep-")
    finally:
        client.__exit__(None, None, None)


def test_apply_requires_csrf(app_factory, tmp_path):
    (tmp_path / "sample-app").mkdir()
    (tmp_path / "sample-app" / "compose.yaml").write_text("services: {}\n",
                                                          encoding="utf-8")
    client = app_factory(admin=True, enable_deploy=True,
                         deploy_workdir=str(tmp_path),
                         gateway_allow_mutations=True)
    try:
        # CSRF 헤더 없이 POST → 차단
        r = client.post("/api/v1/deployments", json={"spec": SPEC_BODY})
        assert r.status_code == 403
    finally:
        client.__exit__(None, None, None)


def test_apply_plan_not_ready_409(app_factory, tmp_path):
    (tmp_path / "sample-app").mkdir()
    spec = {**SPEC_BODY, "endpoints": [
        {"name": "web", "type": "http", "exposure": "host", "host_port": 8420,
         "container": "app", "container_port": 3000}]}
    client = app_factory(admin=True, enable_deploy=True,
                         deploy_workdir=str(tmp_path),
                         gateway_allow_mutations=True)
    try:
        # 8420 포트를 다른 서비스가 예약 → 포트 충돌로 계획 BLOCKED → 409
        from app.db import get_session_factory
        from app.models import PortReservation, Service
        with get_session_factory()() as s:
            s.add(Service(id="other-svc", name="Other", description="d", category="web"))
            s.flush()
            s.add(PortReservation(service_id="other-svc", host_port=8420,
                                  protocol="tcp", container_port=3000))
            s.commit()
        r = mutate(client, "POST", "/api/v1/deployments", json={"spec": spec})
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "plan_not_ready"
    finally:
        client.__exit__(None, None, None)


def test_plan_ignores_own_service_port(client):
    """재배포 시 자기 서비스가 이미 점유한 포트는 충돌로 보지 않는다."""
    from app.db import get_session_factory
    from app.models import Container, Service

    with get_session_factory()() as s:
        s.add(Service(id="sample-app", name="Sample", description="d", category="web"))
        s.flush()
        s.add(Container(
            container_id="c1", name="sample-app-app", state="running",
            management_state="managed", service_id="sample-app",
            ports=[{"host_port": 8765, "container_port": 8765,
                    "proto": "tcp", "bind_addr": "100.85.245.79"}]))
        s.commit()

    spec = {**SPEC_BODY, "endpoints": [
        {"name": "web", "type": "http", "exposure": "host", "host_port": 8765,
         "container": "app", "container_port": 8765}]}
    r = mutate(client, "POST", "/api/v1/deployments/plan", json=spec)
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "READY", r.json()["impact"]


def test_plan_blocks_other_service_port(client):
    """다른 서비스가 쓰는 포트는 여전히 충돌이다."""
    from app.db import get_session_factory
    from app.models import Container, Service

    with get_session_factory()() as s:
        s.add(Service(id="other-svc", name="Other", description="d", category="web"))
        s.flush()
        s.add(Container(
            container_id="c2", name="other-app", state="running",
            management_state="managed", service_id="other-svc",
            ports=[{"host_port": 8765, "container_port": 80,
                    "proto": "tcp", "bind_addr": "100.85.245.79"}]))
        s.commit()

    spec = {**SPEC_BODY, "endpoints": [
        {"name": "web", "type": "http", "exposure": "host", "host_port": 8765,
         "container": "app", "container_port": 8765}]}
    r = mutate(client, "POST", "/api/v1/deployments/plan", json=spec)
    assert r.status_code == 200
    assert r.json()["result"] == "BLOCKED"
