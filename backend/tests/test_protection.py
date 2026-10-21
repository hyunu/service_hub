"""기존 서비스 보호 테스트 (REQUIREMENTS §19.6) — 가장 중요한 테스트.

진짜 Docker 데몬 위에서 읽기 전용 수집이 무변경을 보장하는지 검증한다.
테스트용 컨테이너(hubtest-protect 라벨)만 생성/삭제하고, 그 외 컨테이너/네트워크/볼륨은
절대 건드리지 않는다. 데몬이 없으면 건너뛴다(skip) — 단, skip은 통과로 집계하지 않고
리포트에 표시한다.
"""
from __future__ import annotations

import uuid

import pytest

docker = pytest.importorskip("docker")


def _daemon_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _daemon_available(), reason="Docker 데몬을 사용할 수 없음")


TEST_NAME = "hubtest-protect"


def _full_snapshot(client):
    containers = sorted(
        (c.id, c.name, c.status, tuple(sorted((c.ports or {}).keys())))
        for c in client.containers.list(all=True))
    networks = sorted(n.name for n in client.networks.list())
    volumes = sorted(v.name for v in client.volumes.list())
    return containers, networks, volumes


def test_existing_environment_never_modified_by_inventory(client, app_factory, settings):
    dclient = docker.from_env()
    before = _full_snapshot(dclient)

    # 관리 시스템에 알 수 없는(미등록) 컨테이너 하나를 띄운다 — 실제 기존 서비스 모사
    test_net_name = f"hubtest-net-{uuid.uuid4().hex[:6]}"
    net = dclient.networks.create(test_net_name, driver="bridge",
                                  labels={"hubtest": "true"})
    try:
        container = dclient.containers.run(
            "alpine:latest", ["sleep", "60"], name=TEST_NAME,
            network=test_net_name, detach=True,
            labels={"hubtest": "true", "com.docker.compose.project": "rogue-project"})
        before = _full_snapshot(dclient)   # 테스트 컨테이너 생성 후 기준 스냅샷

        # 읽기 전용 수집을 여러 사이클 수행
        real_gw_app = app_factory(_real_gateway())
        for _ in range(2):
            real_gw_app.app.state.monitor.run_once()

        # 1) 컨테이너가 삭제되지 않았는가
        remaining = {c.name for c in dclient.containers.list(all=True)}
        assert TEST_NAME in remaining, "기존(미관리) 컨테이너가 삭제되었습니다!"

        # 2) 실행 상태가 변경되지 않았는가
        container.reload()
        assert container.status == "running", "컨테이너 실행 상태가 변경되었습니다!"

        # 3~5) 포트/볼륨/네트워크 무변경
        after = _full_snapshot(dclient)
        assert [c[0] for c in after[0]] == [c[0] for c in before[0]], "컨테이너 목록 변경됨"
        assert [c[3] for c in after[0]] == [c[3] for c in before[0]], "포트 매핑 변경됨"
        assert after[1] == before[1], "네트워크 변경됨"
        assert after[2] == before[2], "볼륨 변경됨"

        # 6) 미관리로 정확히 표시되는가
        items = real_gw_app.get("/api/v1/containers").json()["items"]
        mine = [i for i in items if i["name"] == TEST_NAME]
        assert mine, "테스트 컨테이너가 인벤토리에 나타나지 않음"
        assert mine[0]["management_state"] == "unmanaged"
        orphans = real_gw_app.get("/api/v1/orphans").json()["items"]
        assert any(o["name"] == TEST_NAME for o in orphans)
        assert any(o["reason"] for o in orphans)

        # 미관리 컨테이너에 대한 어떤 API도 삭제/재시작을 수행하지 않는다
        attach = real_gw_app.post(
            f"/api/v1/orphans/{container.id}/attach",
            headers={"X-CSRF-Token": ""}, json={"service_id": "x", "component_name": "y"})
        assert attach.status_code in (401, 403, 404), "미승인 attach가 통과됨"
        real_gw_app.__exit__(None, None, None)

        # attach 이후에도 컨테이너는 살아 있어야 한다 (DB 연결만 가능)
        container.reload()
        assert container.status == "running"
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass
        finally:
            net.remove()


def _real_gateway():
    from app.docker_client import DockerGateway
    return DockerGateway()
