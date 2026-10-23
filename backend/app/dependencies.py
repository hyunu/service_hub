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


def build_deploy_runner():
    """설정 기반 배포 실행기 생성 (Phase 3).

    잠금 게이트는 실행기 내부에서 다시 강제된다 (방어 심층).
    작업 디렉터리는 HUB_DEPLOY_WORKDIR 또는 서비스 경로 규칙을 따른다.
    """
    import os

    from .config import get_settings
    from .services.deploy_runner import DeployRunner

    settings = get_settings()

    def resolver(service_id: str) -> str:
        base = os.environ.get("HUB_DEPLOY_WORKDIR") or "./services-local"
        return f"{base.rstrip('/')}/{service_id}"

    gateway = get_gateway()
    # 실제 배포 경로에서만 변경 권한을 부여한다 (잠금 시에는 무의미).
    if hasattr(gateway, "_allow_mutations"):
        gateway._allow_mutations = bool(
            settings.enable_deploy or settings.enable_docker_actions)
    return DeployRunner(gateway=gateway, workdir_resolver=resolver,
                        enable_deploy=settings.enable_deploy,
                        snapshot_root=settings.deploy_snapshot_dir or None)
