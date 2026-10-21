"""service.yaml 스키마 v1 검증 (REQUIREMENTS §6).

Pydantic으로 검증한다. 시크릿 값은 service.yaml에 넣지 않는다 — 이름만 허용.
지원하지 않는 schema_version은 임의 해석하지 않고 거부한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_SCHEMA_VERSIONS = {1}
SERVICE_ID_RE = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"


class SpecError(Exception):
    def __init__(self, message: str, code: str = "spec_invalid", errors: list | None = None):
        super().__init__(message)
        self.code = code
        self.errors = errors or []


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ServiceMeta(_Strict):
    id: str = Field(pattern=SERVICE_ID_RE)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    category: Literal["web", "backend", "database", "ai", "automation",
                      "media", "dev", "infra", "other"]
    version: str | None = None
    documentation: str | None = None
    tags: list[str] = Field(default_factory=list)


class Source(_Strict):
    repository_url: str = ""
    branch: str = "main"


class DeploymentInfo(_Strict):
    type: Literal["docker-compose"]
    compose_file: str = Field(min_length=1)
    project_name: str | None = None


class Endpoint(_Strict):
    name: str = Field(min_length=1)
    type: Literal["http", "https", "tcp", "udp", "grpc"] = "http"
    exposure: Literal["proxy", "host", "internal"] = "internal"
    hostname: str | None = None
    host_port: int | None = Field(default=None, ge=1, le=65535)
    container: str = Field(min_length=1)
    container_port: int = Field(ge=1, le=65535)

    @model_validator(mode="after")
    def _check_exposure(self):
        if self.exposure == "proxy" and not self.hostname:
            raise ValueError("exposure=proxy에는 hostname이 필요합니다")
        if self.exposure == "host" and not self.host_port:
            raise ValueError("exposure=host에는 host_port가 필요합니다")
        return self


class ContainerSpec(_Strict):
    name: str = Field(min_length=1)
    role: Literal["frontend", "backend", "worker", "database", "cache",
                  "proxy", "other"] = "other"
    required: bool = True
    description: str = ""


class Resources(_Strict):
    memory_limit_mb: int | None = Field(default=None, ge=16)
    cpu_limit: float | None = Field(default=None, gt=0)


class VolumeSpec(_Strict):
    name: str
    purpose: str
    backup_required: bool = False


class Operations(_Strict):
    healthcheck_required: bool = True
    backup_required: bool = False
    restart_policy: Literal["no", "always", "unless-stopped", "on-failure"] = "unless-stopped"


class Security(_Strict):
    expose_database: bool = False
    required_env: list[str] = Field(default_factory=list)

    @field_validator("required_env", mode="before")
    @classmethod
    def _names_only(cls, v):
        """시크릿 '값'이 아니라 '이름'만 허용한다 (REQUIREMENTS §6)."""
        if isinstance(v, dict):
            raise ValueError("required_env는 환경 변수 이름 목록이어야 합니다 (값 금지)")
        for item in v or []:
            if not isinstance(item, str) or not item or not item[0].isupper():
                raise ValueError(f"환경 변수 이름이 올바르지 않습니다: {item!r}")
        return v


class ServiceSpec(_Strict):
    schema_version: int
    service: ServiceMeta
    source: Source = Field(default_factory=Source)
    deployment: DeploymentInfo
    endpoints: list[Endpoint] = Field(default_factory=list)
    containers: list[ContainerSpec] = Field(default_factory=list)
    resources: Resources = Field(default_factory=Resources)
    volumes: list[VolumeSpec] = Field(default_factory=list)
    operations: Operations = Field(default_factory=Operations)
    security: Security = Field(default_factory=Security)


def validate_spec_dict(data: Any) -> ServiceSpec:
    if not isinstance(data, dict):
        raise SpecError("service.yaml 최상위는 매핑이어야 합니다", "spec_invalid")
    version = data.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SpecError(
            f"지원하지 않는 schema_version입니다: {version!r} "
            f"(지원: {sorted(SUPPORTED_SCHEMA_VERSIONS)})",
            "unsupported_schema_version")
    try:
        return ServiceSpec.model_validate(data)
    except Exception as exc:  # pydantic ValidationError
        errors = getattr(exc, "errors", lambda: [])()
        detail = "; ".join(
            f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg')}" for e in errors[:8]
        ) or str(exc)
        code = "invalid_service_id" if "service.id" in detail else "spec_validation_failed"
        raise SpecError(f"service.yaml 검증 실패 — {detail}", code, errors) from exc


def parse_spec(path: str | Path) -> ServiceSpec:
    p = Path(path)
    if p.is_dir():
        p = p / "service.yaml"
    if not p.exists():
        raise SpecError(f"service.yaml을 찾을 수 없습니다: {p}", "spec_file_not_found")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecError(f"YAML 파싱 오류: {exc}", "spec_yaml_error") from exc
    return validate_spec_dict(data)
