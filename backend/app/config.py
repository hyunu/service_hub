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
