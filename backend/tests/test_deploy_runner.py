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
