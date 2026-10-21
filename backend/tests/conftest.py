"""테스트 픽스처: 임시 DB + Fake Docker 게이트웨이 + 인증 헬퍼."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, set_settings
from app.db import init_db, reset_db_state
from app.dependencies import set_gateway
from app.docker_client import FakeContainer, FakeDockerGateway
from app.main import create_app
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
    yield s
    reset_db_state()
    reset_security_state()


@pytest.fixture()
def gateway() -> FakeDockerGateway:
    gw = FakeDockerGateway()
    set_gateway(gw)
    return gw


@pytest.fixture()
def app_factory(settings, gateway):
    def _make(gw: FakeDockerGateway | None = None, s: Settings | None = None,
              admin: bool = False) -> TestClient:
        application = create_app(s or settings, gateway=gw or gateway)
        init_db()
        client = TestClient(application)
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
