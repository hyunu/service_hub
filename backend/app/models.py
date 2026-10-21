"""SQLAlchemy 모델 — docs/ARCHITECTURE.md §4 데이터 모델."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> str:
    """ISO 8601 UTC 타임스탬프 (REQUIREMENTS §6) — String 컬럼 기본값용."""
    return datetime.now(timezone.utc).isoformat()


class Service(Base):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="other")
    status: Mapped[str] = mapped_column(String(32), default="registered")
    repository_url: Mapped[str | None] = mapped_column(String(512))
    branch: Mapped[str | None] = mapped_column(String(120))
    deployment_type: Mapped[str] = mapped_column(String(32), default="docker-compose")
    deployment_path: Mapped[str | None] = mapped_column(String(512))
    compose_file: Mapped[str | None] = mapped_column(String(256))
    version: Mapped[str | None] = mapped_column(String(64))
    documentation: Mapped[str | None] = mapped_column(String(512))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    updated_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    last_deployed_at: Mapped[str | None] = mapped_column(String(40))
    last_healthcheck_at: Mapped[str | None] = mapped_column(String(40))

    components: Mapped[list[ServiceComponent]] = relationship(back_populates="service",
                                                              cascade="all, delete-orphan")
    endpoints: Mapped[list[Endpoint]] = relationship(back_populates="service",
                                                     cascade="all, delete-orphan")


class ServiceComponent(Base):
    __tablename__ = "service_components"
    __table_args__ = (UniqueConstraint("service_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(32), default="other")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(Text, default="")

    service: Mapped[Service] = relationship(back_populates="components")


class Container(Base):
    __tablename__ = "containers"

    container_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    image: Mapped[str | None] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(32), default="unknown")
    status_text: Mapped[str] = mapped_column(String(256), default="")
    management_state: Mapped[str] = mapped_column(String(32), default="unknown")
    service_id: Mapped[str | None] = mapped_column(ForeignKey("services.id", ondelete="SET NULL"))
    component_name: Mapped[str | None] = mapped_column(String(120))
    compose_project: Mapped[str | None] = mapped_column(String(256))
    compose_service: Mapped[str | None] = mapped_column(String(256))
    ports: Mapped[list] = mapped_column(JSON, default=list)
    networks: Mapped[list] = mapped_column(JSON, default=list)
    mounts: Mapped[list] = mapped_column(JSON, default=list)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    health: Mapped[str | None] = mapped_column(String(32))
    restart_count: Mapped[int] = mapped_column(Integer, default=0)
    container_created_at: Mapped[str | None] = mapped_column(String(40))
    started_at: Mapped[str | None] = mapped_column(String(40))
    observed_at: Mapped[str | None] = mapped_column(String(40))


class ContainerAssignment(Base):
    """수동 그룹핑: 컨테이너를 서비스 컴포넌트에 **명시적으로** 연결한다.

    이름 기반 자동 매칭(sync_inventory)은 이름이 바뀌거나 다른 서비스와 겹치면
    연결이 풀린다. 이 테이블의 명시적 연결은 주기 동기화보다 우선하며 유지된다.
    컨테이너 런타임은 건드리지 않는다(DB 연결만).
    """
    __tablename__ = "container_assignments"

    container_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    service_id: Mapped[str] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), index=True)
    component_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="")


class Endpoint(Base):
    __tablename__ = "endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(16), default="http")
    exposure: Mapped[str] = mapped_column(String(16), default="internal")
    hostname: Mapped[str | None] = mapped_column(String(256))
    host_port: Mapped[int | None] = mapped_column(Integer)
    container: Mapped[str] = mapped_column(String(120))
    container_port: Mapped[int] = mapped_column(Integer)

    service: Mapped[Service] = relationship(back_populates="endpoints")


class PortReservation(Base):
    __tablename__ = "port_reservations"
    __table_args__ = (UniqueConstraint("protocol", "host_port", "bind_addr"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    component: Mapped[str | None] = mapped_column(String(120))
    protocol: Mapped[str] = mapped_column(String(8), default="tcp")
    host_port: Mapped[int] = mapped_column(Integer)
    bind_addr: Mapped[str] = mapped_column(String(64), default="0.0.0.0")
    container_port: Mapped[int | None] = mapped_column(Integer)
    exposure: Mapped[str] = mapped_column(String(16), default="host")
    state: Mapped[str] = mapped_column(String(32), default="reserved")
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    service_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    requested_by: Mapped[str | None] = mapped_column(String(120))
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[str | None] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40))

    steps: Mapped[list[DeploymentStep]] = relationship(
        back_populates="deployment", cascade="all, delete-orphan",
        order_by="DeploymentStep.seq")


class DeploymentStep(Base):
    __tablename__ = "deployment_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deployment_id: Mapped[str] = mapped_column(ForeignKey("deployments.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    detail: Mapped[str | None] = mapped_column(Text)
    at: Mapped[str] = mapped_column(String(40), default=utcnow)

    deployment: Mapped[Deployment] = relationship(back_populates="steps")


class ResourceSample(Base):
    __tablename__ = "resource_samples"
    __table_args__ = (Index("ix_resource_scope", "scope", "scope_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(16))          # host | container | service
    scope_id: Mapped[str | None] = mapped_column(String(128))
    cpu_percent: Mapped[float | None] = mapped_column(Float)
    mem_used_mb: Mapped[float | None] = mapped_column(Float)
    mem_limit_mb: Mapped[float | None] = mapped_column(Float)
    net_rx_bytes: Mapped[int | None] = mapped_column(Integer)
    net_tx_bytes: Mapped[int | None] = mapped_column(Integer)
    extras: Mapped[dict] = mapped_column(JSON, default=dict)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_ts", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(16), default="info")   # info|warning|critical
    kind: Mapped[str] = mapped_column(String(64))
    service_id: Mapped[str | None] = mapped_column(String(64))
    container_id: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_ts", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(256))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class WebAuthnCredential(Base):
    """등록된 패스워드리스 자격 증명 (생체인식 로그인용).

    공개키만 저장한다 — 비밀키/생체 정보는 서버에 저장되지 않는다 (WebAuthn 규격).
    """
    __tablename__ = "webauthn_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    credential_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    public_key: Mapped[str] = mapped_column(Text)          # base64url
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    user_handle: Mapped[str] = mapped_column(String(128))  # base64url(user_id)
    label: Mapped[str] = mapped_column(String(120), default="패스워드 키")
    device_type: Mapped[str | None] = mapped_column(String(32))   # singleDevice/multiDevice
    backed_up: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    last_used_at: Mapped[str | None] = mapped_column(String(40))
