"""테스트 픽스처: 임시 DB + Fake Docker 게이트웨이 + 인증 헬퍼."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, set_settings
from app.db import init_db, reset_db_state
from app.dependencies import set_gateway
from app.docker_client import FakeContainer, FakeDockerGateway
from app.main import create_app
from app.routers.webauthn import reset_webauthn_state
from app.security import reset_security_state


def make_fake_container(cid: str, name: str, project: str | None = None,
                        service: str | None = None, running: bool = True,
                        host_port: int | None = None, container_port: int = 80,
                        image: str = "nginx:alpine") -> FakeContainer:
    labels = {}
    if project:
        labels["com.docker.compose.project"] = project
    if service:
        labels["com.docker.compose.service"] = service
    ports = {f"{container_port}/tcp": (
        [{"HostIp": "0.0.0.0", "HostPort": str(host_port)}] if host_port else None)}
    attrs = {
        "State": {"Status": "running" if running else "exited"},
        "Config": {"Labels": labels, "Image": image},
        "NetworkSettings": {"Ports": ports, "Networks": {"bridge": {}}},
        "HostConfig": {"RestartCount": 2},
        "Mounts": [],
        "Created": "2026-10-01T00:00:00Z",
    }
    return FakeContainer(id=cid, name=name, image=image,
                         status="Up 2 hours" if running else "Exited (0) 3 months ago",
                         attrs=attrs)


@pytest.fixture()
def settings(tmp_path) -> Settings:
    s = Settings(
        db_path=str(tmp_path / "hub.db"),
        status_cache=str(tmp_path / "status.json"),
        monitor_enabled=False,     # 테스트에서 수동 제어
        _env_file=None,
    )
    set_settings(s)
    reset_db_state()
    reset_security_state()
    reset_webauthn_state()
    yield s
    reset_db_state()
    reset_security_state()
    reset_webauthn_state()


@pytest.fixture()
def gateway() -> FakeDockerGateway:
    gw = FakeDockerGateway()
    set_gateway(gw)
    return gw


@pytest.fixture()
def app_factory(settings, gateway):
    def _make(gw: FakeDockerGateway | None = None, s: Settings | None = None,
              admin: bool = False, *, enable_deploy: bool = False,
              deploy_workdir: str | None = None,
              gateway_allow_mutations: bool = False) -> TestClient:
        # 배포 실행 테스트: 게이트 개방 + 변경 허용 게이트웨이 + 작업 디렉터리
        if enable_deploy and s is None:
            s = Settings(
                db_path=settings.db_path,
                status_cache=settings.status_cache,
                monitor_enabled=False,
                enable_deploy=True,
                _env_file=None,
            )
            set_settings(s)
        if gw is None and gateway_allow_mutations:
            gw = FakeDockerGateway(allow_mutations=True)
        if deploy_workdir is not None:
            os.environ["HUB_DEPLOY_WORKDIR"] = deploy_workdir
        application = create_app(s or settings, gateway=gw or gateway)
        init_db()
        # client 호스트를 루프백으로 고정한다 — 루프백 전용 경로(관리자 초기화 등)를
        # 실제 서버와 동일하게 검증하기 위함이다.
        client = TestClient(application, client=("127.0.0.1", 50000))
        client.__enter__()  # lifespan 실행 (init_db, 게이트웨이 주입)
        if admin:
            r = client.post("/api/v1/setup/admin",
                            json={"username": "admin", "password": "secure-pass-123"})
            assert r.status_code == 201, r.text
            client.csrf = r.json()["csrf_token"]
        else:
            client.csrf = ""
        return client
    return _make


@pytest.fixture()
def anon_client(app_factory):
    """관리자 설정도, 세션도 없는 완전 익명 클라이언트 (인증 테스트용)."""
    c = app_factory()
    yield c
    c.__exit__(None, None, None)


@pytest.fixture()
def client(app_factory):
    """관리자 설정 + 로그인 세션이 있는 기본 클라이언트.

    Phase 1의 모든 변경 작업은 인증을 요구하므로, 기능 테스트는 인증된 세션으로 수행한다.
    인증 자체를 검증하는 테스트는 ``anon_client``를 사용한다.
    """
    c = app_factory(admin=True)
    yield c
    c.__exit__(None, None, None)


@pytest.fixture()
def auth_client(client):
    """client와 동일 (하위 호환용 별칭)."""
    return client


def mutate(client: TestClient, method: str, url: str, **kwargs):
    """CSRF 토큰을 자동으로 첨부하는 변경 요청."""
    headers = kwargs.pop("headers", {})
    headers["X-CSRF-Token"] = getattr(client, "csrf", "")
    return client.request(method, url, headers=headers, **kwargs)


@pytest.fixture()
def fake_ctx():
    """배포 계획용 PlanContext 생성 헬퍼 (관찰된 환경을 순수 입력으로 주입)."""
    from app.services.deploy_plan import PlanContext

    def _make(*, available_env=None, conflicting_ports=None, mem_available_mb=4096,
              compose_ok=True, current_containers=None):
        return PlanContext(
            available_env=available_env if available_env is not None else set(),
            conflicting_ports=conflicting_ports or set(),
            mem_available_mb=mem_available_mb,
            compose_ok=compose_ok,
            current_containers=current_containers or {},
        )
    return _make
