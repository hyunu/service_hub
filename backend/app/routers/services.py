"""서비스 레지스트리 라우터 (REQUIREMENTS §5).

중요: DELETE는 관리 DB 레코드만 삭제한다 — 컨테이너/볼륨/이미지는 건드리지 않는다.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import (Container, ContainerAssignment, Endpoint, PortReservation,
                      Service, ServiceComponent)
from ..security import HubError, get_read_actor, require_auth
from ..services.events import record_audit, record_event
from ..services.grouping import bulk_attach

router = APIRouter(prefix="/services", tags=["services"],
                   dependencies=[Depends(require_auth)])

SERVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
CATEGORIES = {"web", "backend", "database", "ai", "automation", "media", "dev", "infra", "other"}


class ComponentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = "other"
    required: bool = True
    description: str = ""


class EndpointIn(BaseModel):
    name: str
    type: str = "http"
    exposure: str = "internal"
    hostname: str | None = None
    host_port: int | None = None
    container: str
    container_port: int


class ServiceCreate(BaseModel):
    id: str | None = None
    name: str | None = None
    description: str | None = None
    category: str = "other"
    repository_url: str | None = None
    branch: str | None = None
    deployment_type: str = "docker-compose"
    deployment_path: str | None = None
    compose_file: str | None = None
    version: str | None = None
    documentation: str | None = None
    tags: list[str] = []
    components: list[ComponentIn] = []
    endpoints: list[EndpointIn] = []

    @model_validator(mode="before")
    @classmethod
    def _accept_service_spec_shape(cls, data):
        """service.yaml(중첩) 형식도 받는다.

        대시보드 등록 폼과 JSON 붙여넣기는 schemas/service.schema.v1.json 형태
        ({service, source, deployment, containers, endpoints})로 보낸다.
        내부 표현(평탄 필드)으로 정규화해 두 형식을 모두 지원한다.
        """
        if not isinstance(data, dict):
            return data
        meta = data.get("service")
        if not isinstance(meta, dict):
            return data
        out = dict(data)
        for key in ("id", "name", "description", "category", "version",
                    "documentation", "tags"):
            if out.get(key) in (None, "") and meta.get(key) is not None:
                out[key] = meta[key]
        source = data.get("source")
        if isinstance(source, dict):
            for key in ("repository_url", "branch"):
                if not out.get(key) and source.get(key):
                    out[key] = source[key]
        deployment = data.get("deployment")
        if isinstance(deployment, dict):
            if deployment.get("type"):
                out["deployment_type"] = deployment["type"]
            if deployment.get("compose_file"):
                out["compose_file"] = deployment["compose_file"]
            if not out.get("deployment_path"):
                out["deployment_path"] = (deployment.get("deployment_path")
                                          or deployment.get("project_name"))
        # 스펙의 containers 는 서비스 컴포넌트 정의에 해당한다.
        if not out.get("components") and data.get("containers"):
            out["components"] = data["containers"]
        return out


class ServicePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    documentation: str | None = None
    tags: list[str] | None = None
    notes: str | None = None
    version: str | None = None


def _validate(body_id: str, category: str) -> None:
    if not SERVICE_ID_RE.match(body_id):
        raise HubError(status_code=422,
                            detail="서비스 ID는 영문 소문자/숫자/하이픈으로 구성되어야 합니다",
                            code="invalid_service_id")
    if category not in CATEGORIES:
        raise HubError(status_code=422,
                            detail=f"category는 {sorted(CATEGORIES)} 중 하나여야 합니다",
                            code="invalid_category")


def _service_or_404(db: Session, service_id: str) -> Service:
    svc = db.get(Service, service_id)
    if svc is None:
        raise HubError(status_code=404, detail=f"서비스 '{service_id}'를 찾을 수 없습니다",
                            code="service_not_found")
    return svc


def _container_rows(db: Session, service_id: str) -> list[Container]:
    return list(db.execute(select(Container).where(Container.service_id == service_id)).scalars())


def _cpu_mem_for(db: Session, service_id: str) -> tuple[float | None, float | None]:
    from ..models import ResourceSample
    row = db.execute(select(ResourceSample)
                     .where(ResourceSample.scope == "service",
                            ResourceSample.scope_id == service_id)
                     .order_by(ResourceSample.id.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        return None, None
    return row.cpu_percent, row.mem_used_mb


def _summary(db: Session, svc: Service) -> dict:
    rows = _container_rows(db, svc.id)
    cpu, mem = _cpu_mem_for(db, svc.id)
    return {
        "id": svc.id, "name": svc.name, "description": svc.description,
        "category": svc.category, "status": svc.status, "version": svc.version,
        "containers": {
            "total": len(rows),
            "running": sum(1 for r in rows if r.state == "running"),
            "stopped": sum(1 for r in rows if r.state != "running"),
        },
        "endpoints": [{"name": e.name, "type": e.type, "exposure": e.exposure,
                       "hostname": e.hostname, "host_port": e.host_port,
                       "container": e.container, "container_port": e.container_port}
                      for e in svc.endpoints],
        "cpu_percent": cpu, "memory_mb": mem,
        "last_deployed_at": svc.last_deployed_at,
    }


@router.get("")
def list_services(search: str | None = None, status: str | None = None,
                  category: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Service)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(or_(Service.id.ilike(term), Service.name.ilike(term),
                              Service.description.ilike(term)))
    if status:
        stmt = stmt.where(Service.status == status)
    if category:
        stmt = stmt.where(Service.category == category)
    items = [_summary(db, s) for s in db.execute(stmt.order_by(Service.id)).scalars()]
    return {"items": items, "count": len(items)}


@router.post("", status_code=201)
def create_service(body: ServiceCreate, db: Session = Depends(get_db),
                   actor: str = Depends(get_read_actor)):
    if not body.id or not body.name:
        raise HubError(status_code=422,
                       detail="서비스 ID와 이름은 필수입니다",
                       code="missing_fields")
    if body.description is None:
        body.description = ""
    _validate(body.id, body.category)
    if db.get(Service, body.id) is not None:
        raise HubError(status_code=409, detail=f"서비스 ID '{body.id}'는 이미 등록되어 있습니다",
                            code="duplicate_service_id")
    svc = Service(id=body.id, name=body.name, description=body.description,
                  category=body.category, repository_url=body.repository_url,
                  branch=body.branch, deployment_type=body.deployment_type,
                  deployment_path=body.deployment_path, compose_file=body.compose_file,
                  version=body.version, documentation=body.documentation, tags=body.tags)
    db.add(svc)
    for comp in body.components:
        db.add(ServiceComponent(service_id=body.id, name=comp.name, role=comp.role,
                                required=comp.required, description=comp.description))
    for ep in body.endpoints:
        if ep.exposure == "proxy" and not ep.hostname:
            raise HubError(status_code=422, detail="proxy 노출에는 hostname이 필요합니다",
                                code="hostname_required")
        db.add(Endpoint(service_id=body.id, name=ep.name, type=ep.type, exposure=ep.exposure,
                        hostname=ep.hostname, host_port=ep.host_port, container=ep.container,
                        container_port=ep.container_port))
    record_audit(db, actor, "service.create", target=body.id)
    db.commit()
    return _summary(db, svc)


@router.post("/{service_id}/source")
async def upload_source(service_id: str, request: Request,
                        db: Session = Depends(get_db),
                        actor: str = Depends(get_read_actor)):
    """로컬 소스 아카이브(tar.gz)를 받아 배포 디렉터리에 반영한다.

    MCP/AI 가 SSH 없이 소스를 동기화하는 경로다.
    - 컨테이너/이미지는 건드리지 않는다 (반영 후 배포는 별도 단계).
    - 아카이브는 프로젝트 루트 기준(`./`)으로 만든다.
    - 안전: 상대 경로만, 일반 파일/디렉터리만, 크기/개수 상한, 기존 파일 덮어쓰기(삭제 없음).
    """
    import os
    import tempfile
    from pathlib import Path as _Path

    from ..services.source_sync import SourceArchiveError, extract_source

    settings = get_settings()
    if not settings.enable_source_upload:
        raise HubError(status_code=503,
                       detail="소스 업로드가 비활성화되어 있습니다 "
                              "(HUB_ENABLE_SOURCE_UPLOAD=false)",
                       code="source_upload_disabled")
    _service_or_404(db, service_id)
    if not SERVICE_ID_RE.match(service_id):
        raise HubError(status_code=422, detail="서비스 ID 형식이 올바르지 않습니다",
                       code="invalid_service_id")

    ctype = (request.headers.get("content-type") or "").split(";")[0].strip()
    if ctype not in ("application/gzip", "application/x-gzip", "application/x-tar",
                     "application/octet-stream"):
        raise HubError(status_code=415,
                       detail="Content-Type 은 application/gzip 이어야 합니다",
                       code="unsupported_media_type")

    base = os.environ.get("HUB_DEPLOY_WORKDIR") or "./services-local"
    target = _Path(base) / service_id

    limit = max(1, settings.source_upload_max_mb) * 1024 * 1024
    fd, tmp_name = tempfile.mkstemp(prefix="hub-upload-", suffix=".tar.gz")
    total = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            async for chunk in request.stream():
                total += len(chunk)
                if total > limit:
                    raise HubError(status_code=413,
                                   detail=f"업로드가 너무 큽니다 (최대 {settings.source_upload_max_mb}MB)",
                                   code="source_too_large")
                fh.write(chunk)
        if total == 0:
            raise HubError(status_code=422, detail="빈 아카이브입니다",
                           code="source_archive_empty")
        try:
            result = extract_source(_Path(tmp_name), target,
                                    max_extract_mb=settings.source_upload_max_extract_mb)
        except SourceArchiveError as exc:
            raise HubError(status_code=422, detail=str(exc), code=exc.code) from exc
    finally:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass

    record_audit(db, actor, "service.source_upload", target=service_id,
                 detail={"files": result["files"], "bytes_received": total})
    db.commit()
    return {
        "ok": True,
        "service_id": service_id,
        **result,
        "bytes_received": total,
        "runtime_changed": False,
        "note": "소스만 반영했습니다. 컨테이너/이미지는 변경되지 않았습니다.",
    }


@router.post("/validate")
def validate_service_spec(payload: dict, db: Session = Depends(get_db)):
    """service.yaml(dict) 또는 파일 경로를 검증한다. DB에 아무것도 쓰지 않는다."""
    from ..services.service_spec import SpecError, parse_spec, validate_spec_dict

    try:
        if isinstance(payload.get("path"), str):
            spec = parse_spec(payload["path"])
        else:
            spec = validate_spec_dict(payload)
    except SpecError as exc:
        raise HubError(status_code=422, detail=str(exc), code=exc.code) from exc
    return {"valid": True, "spec": spec.model_dump(), "errors": []}


class ScaffoldRequest(BaseModel):
    service_yaml: str = Field(min_length=1, max_length=200_000)
    compose_yaml: str = Field(min_length=1, max_length=200_000)
    overwrite: bool = False
    confirm: str | None = Field(default=None, max_length=64)


@router.post("/{service_id}/scaffold", status_code=201)
def scaffold_service(service_id: str, body: ScaffoldRequest,
                     db: Session = Depends(get_db),
                     actor: str = Depends(get_read_actor)):
    """서비스 디렉터리에 service.yaml/compose.yaml을 생성한다 (배포 준비).

    AI 에이전트가 MCP로 배포까지 끝낼 수 있도록 하는 파일 생성 경로다.
    안전: 경로는 ``HUB_DEPLOY_WORKDIR/<service_id>``, 파일명은 2개로 고정한다.
    덮어쓰기는 ``overwrite=true`` + ``confirm=service_id``가 모두 필요하고,
    배포 게이트(`HUB_ENABLE_DEPLOY`)가 열려 있어야 한다.
    """
    import os
    from pathlib import Path

    import yaml

    from ..services.service_spec import SpecError, validate_spec_dict

    settings = get_settings()
    ok, reason = settings.deploy_gate()
    if not ok:
        raise HubError(status_code=503, detail=reason, code="deploy_disabled")
    if not SERVICE_ID_RE.match(service_id):
        raise HubError(status_code=422, detail="서비스 ID 형식이 올바르지 않습니다",
                       code="invalid_service_id")

    try:
        spec = validate_spec_dict(yaml.safe_load(body.service_yaml))
    except SpecError as exc:
        raise HubError(status_code=422, detail=str(exc), code=exc.code) from exc
    except yaml.YAMLError as exc:
        raise HubError(status_code=422, detail=f"service.yaml 파싱 오류: {exc}",
                       code="spec_yaml_error") from exc
    if spec.service.id != service_id:
        raise HubError(status_code=422,
                       detail=f"service.id({spec.service.id})와 경로 ID({service_id})가 다릅니다",
                       code="id_mismatch")

    try:
        compose = yaml.safe_load(body.compose_yaml)
    except yaml.YAMLError as exc:
        raise HubError(status_code=422, detail=f"compose.yaml 파싱 오류: {exc}",
                       code="compose_yaml_error") from exc
    if not isinstance(compose, dict) or not isinstance(compose.get("services"), dict) \
            or not compose["services"]:
        raise HubError(status_code=422, detail="compose.yaml에 services 매핑이 필요합니다",
                       code="compose_invalid")

    base = Path(os.environ.get("HUB_DEPLOY_WORKDIR") or "/srv/services") / service_id
    if base.exists() and any(base.iterdir()):
        if not (body.overwrite and body.confirm == service_id):
            raise HubError(
                status_code=409,
                detail=f"이미 존재합니다. 덮어쓰려면 overwrite=true 와 confirm='{service_id}'가 필요합니다",
                code="already_exists")
    try:
        base.mkdir(parents=True, exist_ok=True)
        (base / "service.yaml").write_text(body.service_yaml, encoding="utf-8")
        (base / "compose.yaml").write_text(body.compose_yaml, encoding="utf-8")
    except OSError as exc:
        raise HubError(status_code=409, detail=f"파일을 쓸 수 없습니다: {exc}",
                       code="scaffold_failed") from exc

    record_audit(db, actor, "service.scaffold", target=service_id,
                 detail={"path": str(base),
                         "files": ["service.yaml", "compose.yaml"],
                         "overwrite": body.overwrite})
    db.commit()
    return {"ok": True, "service_id": service_id, "path": str(base),
            "files": ["service.yaml", "compose.yaml"], "spec": spec.model_dump()}


@router.get("/spec/guide")
def service_spec_guide():
    """service.yaml 작성 안내(예시·필드·규칙) — UI/문서 공용, 읽기 전용.

    `/{service_id}` 보다 먼저 선언해 경로가 가려지지 않게 한다.
    """
    from ..services.spec_guide import guide
    return guide()


@router.get("/{service_id}")
def get_service(service_id: str, db: Session = Depends(get_db)):
    svc = _service_or_404(db, service_id)
    rows = _container_rows(db, service_id)
    summary = _summary(db, svc)
    missing = [c.name for c in svc.components if c.required
               and not any(r.component_name == c.name and r.state == "running" for r in rows)]
    return {
        **summary,
        "repository_url": svc.repository_url, "branch": svc.branch,
        "deployment_type": svc.deployment_type, "deployment_path": svc.deployment_path,
        "compose_file": svc.compose_file, "documentation": svc.documentation,
        "tags": svc.tags, "notes": svc.notes,
        "created_at": svc.created_at, "updated_at": svc.updated_at,
        "last_healthcheck_at": svc.last_healthcheck_at,
        "components": [{"name": c.name, "role": c.role, "required": c.required,
                        "description": c.description} for c in svc.components],
        "containers_detail": [{"container_id": r.container_id, "name": r.name,
                               "component": r.component_name, "state": r.state,
                               "management_state": r.management_state, "image": r.image}
                              for r in rows],
        "warnings": ([f"필수 컨테이너가 실행되지 않음: {', '.join(missing)}"] if missing else []),
    }


@router.patch("/{service_id}")
def patch_service(service_id: str, body: ServicePatch, db: Session = Depends(get_db),
                  actor: str = Depends(get_read_actor)):
    svc = _service_or_404(db, service_id)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    for key, value in updates.items():
        setattr(svc, key, value)
    from ..models import utcnow
    svc.updated_at = utcnow()
    record_audit(db, actor, "service.update", target=service_id, detail={"fields": list(updates)})
    db.commit()
    return _summary(db, svc)


@router.delete("/{service_id}")
def delete_service(service_id: str, confirm: str = Query(...),
                   db: Session = Depends(get_db), actor: str = Depends(get_read_actor)):
    """관리 레코드만 삭제한다. 컨테이너/볼륨/이미지는 변경하지 않는다 (runtime_unchanged=true)."""
    svc = _service_or_404(db, service_id)
    if confirm != service_id:
        raise HubError(status_code=422,
                            detail="confirm 파라미터에 서비스 ID를 정확히 입력하세요",
                            code="confirm_mismatch")
    db.execute(PortReservation.__table__.delete().where(
        PortReservation.service_id == service_id))
    db.execute(Container.__table__.delete().where(
        Container.service_id == service_id).where(
        Container.component_name == "hub-self"))  # no-op 안전 가드
    # 컨테이너 행의 service_id 참조는 레코드 삭제 대상이 아님 — 소속 해제만
    for row in _container_rows(db, service_id):
        row.service_id = None
        row.component_name = None
        row.management_state = "unmanaged"
    record_audit(db, actor, "service.delete", target=service_id,
                 detail={"runtime_unchanged": True})
    db.delete(svc)
    db.commit()
    return {"deleted": service_id, "runtime_unchanged": True,
            "note": "컨테이너/볼륨/이미지는 변경되지 않았습니다"}


@router.get("/{service_id}/containers")
def service_containers(service_id: str, db: Session = Depends(get_db)):
    _service_or_404(db, service_id)
    rows = _container_rows(db, service_id)
    manual_ids = {a.container_id for a in db.execute(
        select(ContainerAssignment).where(
            ContainerAssignment.service_id == service_id)).scalars()}
    return {"items": [{"container_id": r.container_id, "name": r.name, "image": r.image,
                       "state": r.state, "status_text": r.status_text,
                       "management_state": r.management_state,
                       "component": r.component_name, "health": r.health,
                       "restart_count": r.restart_count, "ports": r.ports,
                       "manual": r.container_id in manual_ids}
                      for r in rows]}


class AutoAttachRequest(BaseModel):
    compose_project: str | None = Field(default=None, max_length=256)


@router.post("/{service_id}/auto-attach")
def auto_attach(service_id: str, body: AutoAttachRequest | None = None,
                db: Session = Depends(get_db), actor: str = Depends(get_read_actor)):
    """compose 프로젝트 단위로 컨테이너를 한 번에 그룹핑한다.

    예: 서비스 등록 직후 compose_project="<서비스 ID>"로 호출하면, 그 프로젝트의
    여러 컨테이너가 compose 서비스명 기준 컴포넌트로 묶인다. DB 연결만 수행한다.
    """
    svc = _service_or_404(db, service_id)
    project = (body.compose_project if body and body.compose_project
               else service_id).strip()
    if not project:
        raise HubError(status_code=422, detail="compose_project가 비어 있습니다",
                            code="invalid_compose_project")
    rows = list(db.execute(select(Container)).scalars())
    ids = [r.container_id for r in rows
           if (r.compose_project or "").strip().lower() == project.lower()]
    if not ids:
        return {"service_id": service_id, "compose_project": project,
                "attached": 0, "skipped": 0, "results": [],
                "runtime_unchanged": True,
                "note": f"compose 프로젝트 '{project}'에 해당하는 컨테이너가 없습니다"}
    result = bulk_attach(db, svc, ids, None, actor)
    if result["attached"]:
        record_event(db, "containers_grouped",
                     f"compose 프로젝트 '{project}' 컨테이너 {result['attached']}개를 "
                     f"서비스 {service_id}에 그룹핑",
                     service_id=service_id,
                     detail={"compose_project": project,
                             "attached": result["attached"],
                             "skipped": result["skipped"]})
    db.commit()
    return {**result, "compose_project": project, "runtime_unchanged": True}


@router.get("/{service_id}/endpoints")
def service_endpoints(service_id: str, db: Session = Depends(get_db)):
    svc = _service_or_404(db, service_id)
    return {"items": [{"name": e.name, "type": e.type, "exposure": e.exposure,
                       "hostname": e.hostname, "host_port": e.host_port,
                       "container": e.container, "container_port": e.container_port}
                      for e in svc.endpoints]}


@router.get("/{service_id}/logs")
def service_logs(service_id: str, tail: int = 200, db: Session = Depends(get_db)):
    """서비스 소속 컨테이너 로그. Docker 게이트웨이를 통해서만 접근 (임의 셸 없음).

    프런트엔드 계약: ``lines``는 ``{ts, stream, message}`` 객체 목록이다.
    (과거에는 문자열 목록을 반환해 UI에서 시각이 "-"로 표시됐다.)
    """
    from ..dependencies import get_gateway
    _service_or_404(db, service_id)
    gateway = get_gateway()
    lines: list[dict] = []
    for row in _container_rows(db, service_id):
        items = gateway.container_log_items(row.container_id, tail=tail)
        if not items:
            continue
        for item in items:
            lines.append({
                "ts": item.get("ts"),
                "stream": item.get("stream") or "stdout",
                "message": f"[{row.name}] {item.get('message', '')}",
            })
    return {"lines": lines[-tail:], "truncated": len(lines) > tail}


@router.get("/{service_id}/events")
def service_events(service_id: str, limit: int = 50, db: Session = Depends(get_db)):
    from ..models import Event
    _service_or_404(db, service_id)
    rows = list(db.execute(select(Event).where(Event.service_id == service_id)
                           .order_by(Event.id.desc()).limit(limit)).scalars())
    return {"items": [{"id": e.id, "ts": e.ts, "severity": e.severity, "kind": e.kind,
                       "message": e.message} for e in rows]}
