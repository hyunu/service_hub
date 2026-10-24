"""설정 — HUB_* 환경변수 기반 (docs/ARCHITECTURE.md §2)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HUB_", env_file=".env", extra="ignore")

    name: str = "N100 Service Hub"
    bind: str = "127.0.0.1"
    port: int = 8420
    db_path: str = "./data/hub.db"
    status_cache: str = "./data/status.json"
    monitor_interval: int = 15
    monitor_enabled: bool = True          # 테스트에서 비활성화
    enable_deploy: bool = False           # Phase 3 잠금 — 기본 false
    # 배포 허용 목록(콤마 구분). 비어 있으면 모든 서비스 허용 (게이트 통과 시)
    deploy_allowed_services: str = ""
    # 배포 실패 시 직전 성공 배포로 자동 롤백
    deploy_auto_rollback: bool = False
    # 배포 결과 웹훅 (POST JSON). 비어 있으면 비활성
    deploy_webhook_url: str = ""
    deploy_webhook_secret: str = ""
    deploy_compose_timeout: int = 600     # compose 작업 타임아웃(초)
    # 배포 시점 service.yaml/compose.yaml 스냅샷 위치 (롤백용). 빈 값이면 스냅샷 비활성.
    deploy_snapshot_dir: str = "/data/deploy-snapshots"

    # MCP/자동화가 로컬 소스를 /srv/services/<service-id> 로 업로드 (파괴적). 기본 잠금.
    enable_source_upload: bool = False
    source_upload_max_mb: int = 200       # 업로드 압축 파일 최대 크기
    source_upload_max_extract_mb: int = 1024   # 압축 해제 후 최대 크기
    # 컨테이너/이미지 시작·정지·제거 (파괴적). 기본 잠금.
    enable_docker_actions: bool = False
    # 보호 대상(콤마 구분). 이름 접두사/정확히 일치, compose 프로젝트명.
    protected_containers: str = ""
    protected_projects: str = ""
    docker_socket: str = "/var/run/docker.sock"

    # 자원 임계값 (%)
    mem_warn_pct: float = 80
    mem_crit_pct: float = 90
    disk_warn_pct: float = 80
    disk_crit_pct: float = 90
    cpu_warn_pct: float = 80
    cpu_crit_pct: float = 95
    cpu_sustain_seconds: int = 60

    # 포트 정책
    port_scan_min: int = 8000
    port_scan_max: int = 8999
    protected_ports: list[int] = [22]

    # WebAuthn (생체인식/패스워드리스) — 보안 컨텍스트(HTTPS)가 필요하다.
    # 비어 있으면 기능이 꺼진다 (평문 HTTP에서는 브라우저가 WebAuthn을 차단한다).
    webauthn_rp_id: str = ""        # 예: n100-pve-dev.tail7d413d.ts.net
    webauthn_origin: str = ""       # 예: https://n100-pve-dev.tail7d413d.ts.net
    webauthn_timeout_ms: int = 60000

    # 관리자 비밀번호 분실 복구 토큰 (hub admin reset).
    # 비어 있으면 루프백 요청만 초기화할 수 있다.
    # 설정하면 X-Hub-Admin-Reset-Token 헤더를 가진 요청도 허용한다 (1회 사용).
    admin_reset_token: str = ""

    # 컨테이너 안에서 platform.node()는 컨테이너 ID를 반환한다.
    # 호스트명을 정확히 표시하려면 배포 시 HUB_HOST_HOSTNAME을 주입한다.
    host_hostname: str = ""

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def db_url(self) -> str:
        p = Path(self.db_path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{p}"

    @property
    def status_cache_path(self) -> Path:
        p = Path(self.status_cache).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def loopback_only(self) -> bool:
        return self.bind in ("127.0.0.1", "localhost", "::1")

    @property
    def webauthn_enabled(self) -> bool:
        """rp_id와 origin이 모두 있어야 WebAuthn을 켠다 (HTTPS 전제)."""
        return bool(self.webauthn_rp_id and self.webauthn_origin)

    @property
    def deploy_allowed(self) -> list[str]:
        return [s.strip() for s in (self.deploy_allowed_services or "").split(",") if s.strip()]

    def deploy_gate(self) -> tuple[bool, str]:
        """배포 허용 여부와 사유. 잠금이 기본값이다 (AGENTS.md 규칙 #2)."""
        if not self.enable_deploy:
            return False, "배포 기능이 비활성화되어 있습니다 (HUB_ENABLE_DEPLOY=false)"
        return True, "ok"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def set_settings(s: Settings) -> None:
    """테스트/팩토리에서 설정을 주입할 때 사용."""
    global _settings
    _settings = s
