"""포트 레지스트리 라우터 (REQUIREMENTS §9)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..security import HubError, get_read_actor, require_auth
from ..services import ports as portsvc
from ..services.events import record_audit
from ..services.ports import PortConflict

router = APIRouter(prefix="/ports", tags=["ports"], dependencies=[Depends(require_auth)])


@router.get("")
def list_ports(db: Session = Depends(get_db)):
    return {"items": portsvc.build_registry(db)}


@router.get("/available")
def available_ports(count: int = 5, range: str | None = None, protocol: str = "tcp",
                    db: Session = Depends(get_db)):
    settings = get_settings()
    if protocol not in ("tcp", "udp"):
        raise HubError(status_code=422, detail="protocol은 tcp/udp만 가능합니다",
                            code="invalid_protocol")
    candidates = portsvc.find_available_ports(db, settings, count=count,
                                              range_spec=range, protocol=protocol)
    return {"candidates": candidates, "protocol": protocol, "range": range or "default",
            "note": "이 목록은 조회 시점 기준이며 예약과 동시에 충돌할 수 있습니다"}


class ReservationRequest(BaseModel):
    service_id: str
    host_port: int = Field(ge=1, le=65535)
    protocol: str = "tcp"
    bind_addr: str = "0.0.0.0"
    container_port: int | None = Field(default=None, ge=1, le=65535)
    component: str | None = None
    exposure: str = "host"


@router.post("/reservations", status_code=201)
def create_reservation(body: ReservationRequest, db: Session = Depends(get_db),
                       actor: str = Depends(get_read_actor)):
    try:
        res = portsvc.create_reservation(
            db, get_settings(), service_id=body.service_id, host_port=body.host_port,
            protocol=body.protocol, bind_addr=body.bind_addr,
            container_port=body.container_port, component=body.component,
            exposure=body.exposure)
    except PortConflict as exc:
        record_audit(db, actor, "port.reservation.rejected", target=str(body.host_port),
                     detail={"code": exc.code, "reason": str(exc)})
        db.commit()
        raise HubError(status_code=409, detail=str(exc), code=exc.code)
    record_audit(db, actor, "port.reserve", target=f"{body.host_port}/{body.protocol}",
                 detail={"service_id": body.service_id, "component": body.component,
                         "exposure": body.exposure})
    db.commit()
    return {"reservation_id": res.id, "service_id": res.service_id,
            "host_port": res.host_port, "protocol": res.protocol,
            "bind_addr": res.bind_addr, "state": res.state,
            "note": "예약되었습니다. 실제 바인딩은 배포 후 확인됩니다."}


@router.delete("/reservations/{reservation_id}")
def delete_reservation(reservation_id: int, db: Session = Depends(get_db),
                       actor: str = Depends(get_read_actor)):
    ok = portsvc.delete_reservation(db, reservation_id)
    if not ok:
        raise HubError(status_code=404, detail="예약을 찾을 수 없습니다",
                            code="reservation_not_found")
    record_audit(db, actor, "port.reserve.delete", target=str(reservation_id))
    db.commit()
    return {"deleted": reservation_id}
