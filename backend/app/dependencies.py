"""FastAPI 의존성 — Docker 게이트웨이 주입 (테스트에서 Fake로 교체)."""
from __future__ import annotations

from .docker_client import DockerGateway

_gateway: DockerGateway | None = None


def get_gateway() -> DockerGateway:
    global _gateway
    if _gateway is None:
        from ..config import get_settings
        settings = get_settings()
        sock = settings.docker_socket
        _gateway = DockerGateway(
            socket_path=sock if sock.startswith("unix://") else f"unix://{sock}")
    return _gateway


def set_gateway(gateway: DockerGateway | None) -> None:
    global _gateway
    _gateway = gateway
