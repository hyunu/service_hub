"""배포 실행기/게이트웨이 변경 함수 테스트 (REQUIREMENTS §13.3, §15)."""
from __future__ import annotations

import pytest

from app.docker_client import DockerGateway


def test_gateway_refuses_compose_up_without_allow_flag():
    gw = DockerGateway(socket_path="unix:///nonexistent.sock", allow_mutations=False)
    with pytest.raises(PermissionError):
        gw.compose_up("/tmp/x", "proj")


def test_gateway_has_no_arbitrary_command():
    gw = DockerGateway(allow_mutations=True)
    # 화이트리스트에 없는 임의 셸은 존재하지 않는다 (§15.7)
    assert not hasattr(gw, "run_command")
    assert not hasattr(gw, "exec_sh")
    assert not hasattr(gw, "shell")


def test_fake_gateway_records_compose_calls():
    from app.docker_client import FakeDockerGateway
    gw = FakeDockerGateway(allow_mutations=True)
    result = gw.compose_up("/tmp/x", "proj")
    assert result["ok"] is True
    assert gw.mutation_log[-1]["action"] == "compose_up"


def test_fake_gateway_refuses_mutation_when_not_allowed():
    from app.docker_client import FakeDockerGateway
    gw = FakeDockerGateway(allow_mutations=False)
    with pytest.raises(PermissionError):
        gw.compose_up("/tmp/x", "proj")


def test_fake_gateway_compose_config_is_readonly():
    from app.docker_client import FakeDockerGateway
    gw = FakeDockerGateway(allow_mutations=False)
    assert gw.compose_config("/tmp/x", "proj")["ok"] is True


# ---------------------------------------------------------------- runner ----

from app.services.deploy_plan import PlanContext
from app.services.deploy_runner import DeployRunner, DeploymentBusy
from app.services.service_spec import validate_spec_dict

RUNNER_SPEC = {
    "schema_version": 1,
    "service": {"id": "sample-app", "name": "Sample", "description": "샘플",
                "category": "web"},
    "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    "containers": [{"name": "app", "role": "backend", "required": True}],
}


def _ctx():
    return PlanContext(available_env=set(), conflicting_ports=set(),
                       mem_available_mb=4096, compose_ok=True, current_containers={})


def test_runner_refuses_when_gate_closed(settings, tmp_path):
    from app.db import init_db
    from app.docker_client import FakeDockerGateway
    init_db()
    runner = DeployRunner(gateway=FakeDockerGateway(allow_mutations=True),
                          workdir_resolver=lambda sid: str(tmp_path),
                          enable_deploy=False)
    spec = validate_spec_dict(RUNNER_SPEC)
    with pytest.raises(PermissionError):
        runner.run(spec, _ctx(), actor="tester")


def test_runner_succeeds_and_records_steps(settings, tmp_path):
    from app.db import init_db
    from app.docker_client import FakeDockerGateway
    from conftest import make_fake_container
    init_db()
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    # 배포 후 기동된 것으로 보이는 컨테이너 (프로젝트=sample-app, 서비스=app)
    gw = FakeDockerGateway(
        containers=[make_fake_container("c1", "sample-app-app", project="sample-app",
                                        service="app", running=True)],
        allow_mutations=True)
    runner = DeployRunner(gateway=gw, workdir_resolver=lambda sid: str(tmp_path),
                          enable_deploy=True)
    spec = validate_spec_dict(RUNNER_SPEC)
    deployment = runner.run(spec, _ctx(), actor="tester")
    assert deployment.status == "succeeded"
    steps = [s.name for s in deployment.steps]
    assert "validating" in steps and "running" in steps and "verifying" in steps
    assert gw.mutation_log[-1]["action"] == "compose_up"


def test_runner_blocks_on_plan_not_ready(settings, tmp_path):
    from app.db import init_db
    from app.docker_client import FakeDockerGateway
    init_db()
    ctx = PlanContext(available_env=set(), conflicting_ports={8000},
                      mem_available_mb=4096, compose_ok=True, current_containers={})
    spec = validate_spec_dict({**RUNNER_SPEC, "endpoints": [
        {"name": "web", "type": "http", "exposure": "host", "host_port": 8000,
         "container": "app", "container_port": 3000}]})
    runner = DeployRunner(gateway=FakeDockerGateway(allow_mutations=True),
                          workdir_resolver=lambda sid: str(tmp_path), enable_deploy=True)
    with pytest.raises(ValueError):
        runner.run(spec, ctx, actor="tester")


def test_duplicate_deploy_rejected(settings, tmp_path):
    from app.db import init_db
    from app.docker_client import FakeDockerGateway
    init_db()
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    runner = DeployRunner(gateway=FakeDockerGateway(allow_mutations=True),
                          workdir_resolver=lambda sid: str(tmp_path), enable_deploy=True)
    spec = validate_spec_dict(RUNNER_SPEC)
    runner.acquire(spec.service.id)
    with pytest.raises(DeploymentBusy):
        runner.acquire(spec.service.id)


def test_compose_up_forces_build(monkeypatch):
    """코드 변경이 반영되도록 compose up 은 --build 를 포함해야 한다."""
    from app import docker_client

    calls: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: (calls.append(cmd), _Proc())[1],
    )
    gw = docker_client.DockerGateway(allow_mutations=True)
    gw.compose_up("/tmp/proj", "proj")
    assert calls and "--build" in calls[0]
