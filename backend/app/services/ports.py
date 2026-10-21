"""포트 레지스트리 및 예약 (docs/ARCHITECTURE.md §6, REQUIREMENTS §9).

구분: Host Port(호스트 바인딩) / Container Port(내부) / Proxy Endpoint.
예약(DB 고유 인덱스)과 실제 점유(Docker 스냅샷/소켓 확인)를 분리해 관리한다.
"""
from __future__ import annotations

import socket
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Container, PortReservation, Service


class PortConflict(Exception):
    def __init__(self, message: str, code: str = "port_conflict") -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_port_free_on_host(host_port: int, bind_addr: str = "0.0.0.0",
                         protocol: str = "tcp") -> bool:
    """호스트에서 실제 바인딩 가능 여부를 시도로 확인한다 (읽기 전용 안전 확인)."""
    family = socket.AF_INET6 if ":" in bind_addr else socket.AF_INET
    sock_type = socket.SOCK_DGRAM if protocol == "udp" else socket.SOCK_STREAM
    try:
        with socket.socket(family, sock_type) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((bind_addr if bind_addr != "*" else "0.0.0.0", host_port))
        return True
    except OSError:
        return False


def build_registry(db: Session) -> list[dict]:
    """Docker 실제 바인딩 + DB 예약을 합쳐 포트 레지스트리 항목을 만든다."""
    actual: list[dict] = []
    for row in db.execute(select(Container)).scalars():
        for p in row.ports or []:
            if p.get("host_port"):
                actual.append({
                    "host_port": p["host_port"],
                    "protocol": p.get("proto", "tcp"),
                    "bind_addr": p.get("bind_addr") or "0.0.0.0",
                    "container_port": p.get("container_port"),
                    "service_id": row.service_id,
                    "component": row.component_name,
                    "container_name": row.name,
                    "container_id": row.container_id,
                })

    reservations = list(db.execute(select(PortReservation)).scalars())
    items: list[dict] = []

    for res in reservations:
        bound = any(a["host_port"] == res.host_port and a["protocol"] == res.protocol
                    and _addr_matches(a["bind_addr"], res.bind_addr) for a in actual)
        items.append({
            "host_port": res.host_port,
            "protocol": res.protocol,
            "bind_addr": res.bind_addr,
            "container_port": res.container_port,
            "service_id": res.service_id,
            "component": res.component,
            "exposure": res.exposure,
            "state": "bound" if bound else "reserved",
            "reserved": True,
            "in_use": bound,
            "proxy": res.exposure == "proxy",
            "internal": res.exposure == "internal",
            "reservation_id": res.id,
            "last_checked_at": _now(),
            "note": "" if bound else "예약됨 — 아직 바인딩되지 않음",
        })

    for a in actual:
        duplicate = any(i["host_port"] == a["host_port"] and i["protocol"] == a["protocol"]
                        and _addr_matches(a["bind_addr"], i["bind_addr"])
                        and i.get("container_id") == a["container_id"] for i in items)
        if duplicate:
            continue
        items.append({
            "host_port": a["host_port"],
            "protocol": a["protocol"],
            "bind_addr": a["bind_addr"],
            "container_port": a["container_port"],
            "service_id": a["service_id"],
            "component": a["component"],
            "exposure": "host",
            "state": "in_use_unreserved" if a["service_id"] else "in_use_unmanaged",
            "reserved": False,
            "in_use": True,
            "proxy": False,
            "internal": False,
            "reservation_id": None,
            "container_name": a["container_name"],
            "container_id": a["container_id"],
            "last_checked_at": _now(),
            "note": "예약 정보 없이 실제 점유 중" if a["service_id"]
                    else "미관리 컨테이너가 점유 중",
        })

    # 충돌 판정: 동일 proto/port를 서로 다른 컨테이너가 점유
    seen: dict[tuple, dict] = {}
    for item in items:
        k = (item["protocol"], item["host_port"])
        prev = seen.get(k)
        if prev is not None and prev["in_use"] and item["in_use"] \
                and prev.get("container_id") != item.get("container_id"):
            item["state"] = "conflict"
            item["note"] = "동일 포트를 서로 다른 컨테이너가 점유"
        seen.setdefault(k, item)
    return items


def _normalize_addr(addr: str | None) -> str:
    if addr in (None, "", "*", "0.0.0.0", "::"):
        return "0.0.0.0"
    return addr


def _addr_matches(a: str | None, b: str | None) -> bool:
    return _normalize_addr(a) == _normalize_addr(b)


def find_available_ports(db: Session, settings: Settings, count: int = 5,
                         range_spec: str | None = None, protocol: str = "tcp") -> list[int]:
    """예약/실제 점유/정책 제외 포트를 뺀 가용 후보."""
    if range_spec and "-" in range_spec:
        lo, hi = (int(x) for x in range_spec.split("-", 1))
    else:
        lo, hi = settings.port_scan_min, settings.port_scan_max

    taken: set[int] = set()
    for item in build_registry(db):
        if item["protocol"] == protocol:
            taken.add(item["host_port"])
    protected = set(settings.protected_ports) | {settings.port}

    out: list[int] = []
    for port in range(lo, hi + 1):
        if port in taken or port in protected:
            continue
        if is_port_free_on_host(port, "0.0.0.0", protocol):
            out.append(port)
            if len(out) >= count:
                break
    return out


def create_reservation(db: Session, settings: Settings, *, service_id: str,
                       host_port: int, protocol: str = "tcp", bind_addr: str = "0.0.0.0",
                       container_port: int | None = None, component: str | None = None,
                       exposure: str = "host") -> PortReservation:
    """포트 예약 — §9.3 절차 중 1~8단계.

    예약 성공은 실제 바인딩 성공을 의미하지 않는다 (state=reserved로 시작).
    """
    if not (1 <= host_port <= 65535):
        raise PortConflict("포트는 1~65535 범위여야 합니다.", "invalid_port")
    if protocol not in ("tcp", "udp"):
        raise PortConflict("프로토콜은 tcp 또는 udp여야 합니다.", "invalid_protocol")
    if host_port in settings.protected_ports or host_port == settings.port:
        raise PortConflict(f"포트 {host_port}는 보호 포트로 예약할 수 없습니다.", "protected_port")
    if db.get(Service, service_id) is None:
        raise PortConflict(f"서비스 '{service_id}'가 등록되어 있지 않습니다.", "service_not_found")

    existing = db.execute(select(PortReservation).where(
        PortReservation.protocol == protocol,
        PortReservation.host_port == host_port,
        PortReservation.bind_addr == _normalize_addr(bind_addr),
    )).scalar_one_or_none()
    if existing is not None:
        raise PortConflict(
            f"포트 {host_port}/{protocol}은 이미 {existing.service_id}가 예약했습니다.",
            "already_reserved")

    for item in build_registry(db):
        if item["host_port"] == host_port and item["protocol"] == protocol \
                and _addr_matches(item["bind_addr"], bind_addr) and item["in_use"]:
            raise PortConflict(
                f"포트 {host_port}/{protocol}이 현재 "
                f"{item.get('container_name') or '다른 컨테이너'}에 의해 실제 점유되어 있습니다.",
                "in_use")

    if exposure == "host" and not is_port_free_on_host(host_port, bind_addr, protocol):
        raise PortConflict(f"호스트에서 포트 {host_port}/{protocol} 바인딩이 불가능합니다.",
                           "bind_failed")

    res = PortReservation(service_id=service_id, component=component, protocol=protocol,
                          host_port=host_port, bind_addr=_normalize_addr(bind_addr),
                          container_port=container_port, exposure=exposure,
                          state="reserved", created_at=_now())
    db.add(res)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise PortConflict(
            f"포트 {host_port}/{protocol} 예약이 충돌했습니다(동시 예약).", "race_conflict") from exc
    return res


def delete_reservation(db: Session, reservation_id: int) -> bool:
    res = db.get(PortReservation, reservation_id)
    if res is None:
        return False
    db.delete(res)
    db.flush()
    return True
