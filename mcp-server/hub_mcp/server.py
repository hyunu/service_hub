"""N100 Service Hub MCP 서버.

AI 에이전트(Claude Code, Cursor, Codex 등)가 이 허브에 **서비스를 등록하고
미관리 컨테이너를 연결하고 배포 계획/실행을 요청**할 수 있게 한다.

안전 원칙:
  - 기존 백엔드 REST API만 호출한다. 임의 셸 실행 경로는 없다.
  - 배포는 백엔드의 HUB_ENABLE_DEPLOY 잠금과 화이트리스트 검증을 그대로 따른다.
  - 인증은 API 키(X-API-Key / HUB_API_KEY). 발급/폐기는 대시보드 세션 전용이다.

실행:
  hub-mcp                     # stdio (로컬 AI 에이전트)
  hub-mcp --transport http    # Streamable HTTP (원격)
"""
from __future__ import annotations

import argparse
import fnmatch
import io
import json
import os
import tarfile
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from .client import HubApiError, HubClient, normalize_base
from .guide import DEPLOYMENT_GUIDE, deployment_guide

server = MCPServer(
    "n100-service-hub",
    version="0.1.0",
    instructions=(
        "N100 Service Hub 관리 도구. "
        "**배포 모델**: 허브는 서버의 /srv/services/<service-id> 를 빌드한다. "
        "MCP는 소스 업로드 도구가 아니므로, 소스는 먼저 SSH rsync 또는 서버 git pull 로 "
        "동기화해야 한다. 배포/재배포 전에 **hub_deployment_guide** 를 먼저 호출해 "
        "모델·사전조건·절차·시크릿·오류를 확인하라. "
        "워크플로: hub_service_spec_guide → (소스 동기화) → hub_service_scaffold → "
        "hub_service_validate → hub_service_register → hub_deploy_plan(READY) → "
        "hub_deploy_apply(service_id, confirmed=true) → hub_deploy_status. "
        "롤백은 hub_deploy_rollback(deployment_id, confirmed=true). "
        "HUB_ENABLE_DEPLOY=false 이면 scaffold/plan/apply 는 503 으로 거부된다."
    ),
)


# HTTP(원격) 모드에서 요청별 X-API-Key 를 도구 실행 컨텍스트로 전달한다.
_REQUEST_API_KEY: ContextVar[str | None] = ContextVar("hub_request_api_key", default=None)


def _client() -> HubClient:
    return HubClient(api_key=_REQUEST_API_KEY.get())


def _run(fn, *args, **kwargs) -> dict:
    """도구 공통 래퍼 — 예외를 구조화된 결과로 바꾼다."""
    try:
        data = fn(*args, **kwargs)
        return {"ok": True, "data": data}
    except HubApiError as exc:
        return {"ok": False, "error": str(exc), "code": exc.code, "status": exc.status}


# ------------------------------------------------------------ 배포 가이드 --

@server.tool()
def hub_deployment_guide() -> dict:
    """N100 허브의 **배포 방식**을 반환한다 (모델·사전조건·절차·시크릿·오류·안전).

    배포/재배포를 시작하기 전에 반드시 먼저 호출한다. 특히:
    - 허브는 서버의 /srv/services/<id> 를 빌드하며 MCP는 소스 업로드를 하지 않는다.
    - 소스는 SSH rsync 또는 서버 git pull 로 먼저 동기화해야 한다.
    - 시크릿은 .env(600/660)에 두고 service.yaml에는 이름만 넣는다.
    """
    return deployment_guide()


@server.resource("hub://guides/deployment", mime_type="text/markdown",
                 description="N100 Service Hub 배포 가이드 (Markdown)")
def deployment_guide_resource() -> str:
    """MCP 리소스로도 같은 배포 가이드를 제공한다."""
    return DEPLOYMENT_GUIDE


@server.prompt(description="N100 Service Hub 배포 절차를 안내한다")
def deploy_service(service_id: str = "<service-id>") -> str:
    """배포 절차 프롬프트 — 대화에 가이드를 주입한다."""
    return (f"'{service_id}' 서비스를 N100 Service Hub에 배포하세요.\n"
            f"아래 가이드의 모델·사전조건·절차를 반드시 따르세요.\n\n"
            f"{DEPLOYMENT_GUIDE}")


# ------------------------------------------------------------------ 읽기 --

@server.tool()
def hub_status() -> dict:
    """허브/도커/모니터의 현재 상태 요약과 경고를 반환한다."""
    return _run(lambda: _client().get("/system/status"))


@server.tool()
def hub_services_list(search: str | None = None, status: str | None = None,
                      category: str | None = None) -> dict:
    """등록된 서비스 목록을 반환한다.

    Args:
        search: 이름/ID/설명 부분 검색
        status: ok | warn | critical | missing | stopped 등
        category: web | backend | database | ai | automation | media | dev | infra | other
    """
    params = {k: v for k, v in
              {"search": search, "status": status, "category": category}.items() if v}
    return _run(lambda: _client().get("/services", params=params or None))


@server.tool()
def hub_service_get(service_id: str) -> dict:
    """서비스 상세(컴포넌트/엔드포인트/컨테이너/상태)를 반환한다."""
    return _run(lambda: _client().get(f"/services/{service_id}"))


@server.tool()
def hub_service_spec_guide() -> dict:
    """service.yaml 작성 안내(최소/전체 예시·필드·규칙)를 반환한다.

    배포 전에 먼저 호출해 스키마 v1 형식을 확인한다.
    """
    return _run(lambda: _client().get("/services/spec/guide"))


@server.tool()
def hub_service_validate(spec: dict) -> dict:
    """service.yaml dict를 스키마 검증한다 (DB/파일 변경 없음)."""
    return _run(lambda: _client().post("/services/validate", spec))


@server.tool()
def hub_service_scaffold(service_id: str, service_yaml: str, compose_yaml: str,
                         overwrite: bool = False, confirm: str | None = None) -> dict:
    """서비스 디렉터리에 service.yaml/compose.yaml을 생성한다 (배포 준비).

    파일은 ``/srv/services/<service_id>/`` 에 고정된 이름으로만 생성된다.
    이미 존재하면 ``overwrite=true`` 와 ``confirm=<service_id>`` 가 모두 필요하다.
    배포 게이트(HUB_ENABLE_DEPLOY)가 필요하다.

    Args:
        service_id: 서비스 ID (소문자/숫자/하이픈, 3~64자)
        service_yaml: service.yaml 전체 문자열
        compose_yaml: compose.yaml 전체 문자열 (services 매핑 필수)
        overwrite: 기존 디렉터리를 덮어쓸지
        confirm: overwrite 시 서비스 ID를 그대로 입력
    """
    payload: dict[str, Any] = {
        "service_yaml": service_yaml,
        "compose_yaml": compose_yaml,
        "overwrite": overwrite,
    }
    if confirm:
        payload["confirm"] = confirm
    return _run(lambda: _client().post(f"/services/{service_id}/scaffold", payload))


@server.tool()
def hub_containers_list(state: str | None = None, management: str | None = None) -> dict:
    """전체 Docker 컨테이너 인벤토리를 반환한다.

    Args:
        state: running | stopped | all
        management: managed | unmanaged | mismatch | missing | unknown
    """
    params = {k: v for k, v in
              {"state": state, "management": management}.items() if v}
    return _run(lambda: _client().get("/containers", params=params or None))


@server.tool()
def hub_orphans_list() -> dict:
    """미관리(어떤 서비스에도 속하지 않은) 컨테이너 목록을 반환한다."""
    return _run(lambda: _client().get("/orphans"))


@server.tool()
def hub_ports_list() -> dict:
    """포트 사용/예약 현황을 반환한다 (신규 서비스 포트 선택에 사용)."""
    return _run(lambda: _client().get("/ports"))


@server.tool()
def hub_service_logs(service_id: str, tail: int = 200) -> dict:
    """서비스 컴포넌트 컨테이너의 최근 로그를 반환한다."""
    return _run(lambda: _client().get(f"/services/{service_id}/logs",
                                      params={"tail": max(1, min(tail, 2000))}))


@server.tool()
def hub_deploy_status(deployment_id: str) -> dict:
    """배포 작업의 상태/단계/오류를 반환한다."""
    return _run(lambda: _client().get(f"/deployments/{deployment_id}"))


# ------------------------------------------------------------ 등록/연결 --

def spec_to_service_payload(spec: dict, deployment_path: str | None = None) -> dict:
    """service.yaml(spec) dict를 POST /services 페이로드(평탄 형식)로 변환한다."""
    meta = spec.get("service") or {}
    source = spec.get("source") or {}
    deployment = spec.get("deployment") or {}
    payload: dict[str, Any] = {
        "id": meta.get("id"),
        "name": meta.get("name"),
        "description": meta.get("description", ""),
        "category": meta.get("category", "other"),
        "version": meta.get("version"),
        "documentation": meta.get("documentation"),
        "tags": meta.get("tags") or [],
        "repository_url": source.get("repository_url"),
        "branch": source.get("branch"),
        "deployment_type": deployment.get("type", "docker-compose"),
        "compose_file": deployment.get("compose_file", "compose.yaml"),
        "deployment_path": deployment_path,
        "components": spec.get("containers") or [],
        "endpoints": spec.get("endpoints") or [],
    }
    # None/빈 값은 보내지 않는다 (스펙 기본값이 빈 문자열인 경우 포함)
    return {k: v for k, v in payload.items() if v not in (None, "", [], {})}


@server.tool()
def hub_service_register(spec: dict, deployment_path: str | None = None,
                         dry_run: bool = False) -> dict:
    """service.yaml(schema_version 1) 내용으로 서비스를 등록한다.

    컨테이너는 생성/변경하지 않고 Service Registry(DB)에만 기록한다.

    Args:
        spec: service.yaml 과 동일한 dict. 예:
            {"schema_version": 1,
             "service": {"id": "my-app", "name": "My App",
                         "description": "설명", "category": "web"},
             "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
             "containers": [{"name": "web", "role": "frontend"}],
             "endpoints": [{"name": "web", "type": "http", "exposure": "host",
                            "host_port": 8080, "container": "web", "container_port": 80}]}
        deployment_path: 호스트에서 compose.yaml 이 있는 **절대 경로** (예: /srv/services/my-app).
            컨테이너 내부 경로가 아니라 Docker 데몬(호스트) 기준 경로다.
        dry_run: true 면 검증/변환 결과만 반환하고 등록하지 않는다.
    """
    client = _client()

    def _do() -> dict:
        validated = client.validate_spec(spec)
        normalized = validated.get("spec", spec)
        payload = spec_to_service_payload(normalized, deployment_path)
        if dry_run:
            return {"dry_run": True, "payload": payload}
        created = client.create_service(payload)
        return {"service": created, "payload": payload}

    return _run(_do)


SOURCE_SKIP_NAMES = {".git", "node_modules", ".venv", "venv", "__pycache__",
                     ".pytest_cache", ".mypy_cache", ".DS_Store"}


def build_source_archive(root: Path, excludes: list[str], max_mb: int) -> tuple[bytes, int, int]:
    """로컬 디렉터리를 루트 기준 tar.gz 로 묶는다.

    반환: (압축 바이트, 원본 바이트 합, 파일 수)
    """
    buf = io.BytesIO()
    total = 0
    count = 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in SOURCE_SKIP_NAMES
                and not any(fnmatch.fnmatch(d, pat) for pat in excludes)
            )
            for name in sorted(filenames):
                if name in SOURCE_SKIP_NAMES:
                    continue
                if any(fnmatch.fnmatch(name, pat) for pat in excludes):
                    continue
                full = Path(dirpath) / name
                if full.is_symlink() or not full.is_file():
                    continue
                try:
                    size = full.stat().st_size
                except OSError:
                    continue
                total += size
                if total > max_mb * 1024 * 1024:
                    raise ValueError(f"소스가 너무 큽니다 (>{max_mb}MB): {full}")
                rel = full.relative_to(root).as_posix()
                tf.add(full, arcname=f"./{rel}", recursive=False)
                count += 1
    return buf.getvalue(), total, count


@server.tool()
def hub_service_sync_source(service_id: str, path: str,
                            exclude: list[str] | None = None,
                            dry_run: bool = False, max_mb: int = 200) -> dict:
    """로컬 디렉터리 소스를 허브의 배포 디렉터리로 업로드한다 (SSH/git 불필요).

    허브는 받은 tar.gz 를 `/srv/services/<service_id>` 에 안전하게 풀어 쓴다.
    컨테이너/이미지는 건드리지 않으므로, 이어서 `hub_deploy_apply` 로 배포한다.

    Args:
        service_id: 등록된 서비스 ID (= 배포 디렉터리 이름)
        path: 업로드할 로컬 디렉터리 경로 (절대/상대 모두 가능)
        exclude: 추가 제외 패턴 (fnmatch). 기본적으로 .git/node_modules/.venv/__pycache__ 제외
        dry_run: true 면 아카이브만 만들어 크기/파일 수를 반환하고 업로드하지 않는다
        max_mb: 원본 크기 상한(MB)
    """
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"디렉터리가 아닙니다: {root}", "code": "invalid_path"}

    try:
        archive, raw_bytes, count = build_source_archive(root, list(exclude or []), max_mb)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "code": "source_too_large"}
    except OSError as exc:
        return {"ok": False, "error": f"파일을 읽을 수 없습니다: {exc}", "code": "source_read_error"}

    meta = {"source": str(root), "files": count, "raw_bytes": raw_bytes,
            "archive_bytes": len(archive)}
    if dry_run:
        return {"ok": True, "data": {**meta, "dry_run": True}}

    def _do() -> dict:
        result = _client().post_raw(f"/services/{service_id}/source", archive,
                                    "application/gzip", timeout=300.0)
        return {**meta, "result": result}

    return _run(_do)


@server.tool()
def hub_orphans_attach(service_id: str, container_ids: list[str],
                       component_name: str | None = None) -> dict:
    """미관리 컨테이너를 기존 서비스에 **수동 연결**한다.

    컨테이너를 재생성/재시작하지 않고 DB 연결만 만든다.
    component_name 을 비우면 compose 서비스명(없으면 컨테이너 이름) 기준으로 묶는다.
    """
    payload: dict[str, Any] = {"service_id": service_id, "container_ids": container_ids}
    if component_name:
        payload["component_name"] = component_name
    return _run(lambda: _client().post("/orphans/attach", payload))


# --------------------------------------------------------------------- 배포 --

@server.tool()
def hub_deployments_list(service_id: str | None = None) -> dict:
    """배포 이력을 최신순으로 조회한다 (service_id 로 필터 가능)."""
    params = {"service_id": service_id} if service_id else None
    return _run(lambda: _client().get("/deployments", params=params))


@server.tool()
def hub_deploy_plan(spec: dict) -> dict:
    """배포 계획을 생성한다 (컨테이너를 변경하지 않음).

    결과의 result 가 READY 인지, impact 항목에 차단 사유가 있는지 확인한다.
    """
    return _run(lambda: _client().post("/deployments/plan", spec))


@server.tool()
def hub_deploy_apply(service_id: str | None = None, spec: dict | None = None,
                     confirmed: bool = False) -> dict:
    """배포를 실행한다 (compose config/up/down + 헬스체크 화이트리스트만).

    HUB_ENABLE_DEPLOY=false 면 거부된다. 반드시 hub_deploy_plan 으로 READY 를
    확인한 뒤 호출하고, confirmed=true 를 명시해야 한다.

    Args:
        service_id: 기존 서비스 ID (서버 작업 디렉터리의 service.yaml 사용)
        spec: service.yaml dict (service_id 대신 전달 가능)
        confirmed: true 여야 실행한다
    """
    if not confirmed:
        return {"ok": False, "error": "배포를 실행하려면 confirmed=true 를 명시해야 합니다.",
                "code": "confirmation_required"}
    payload: dict[str, Any] = {"confirmed": True}
    if spec:
        payload["spec"] = spec
    elif service_id:
        payload["service_id"] = service_id
    else:
        return {"ok": False, "error": "service_id 또는 spec 중 하나가 필요합니다.",
                "code": "spec_required"}
    # 빌드가 포함되면 수 분 걸릴 수 있다 — 기본 60초 타임아웃으로는 실패로 보인다.
    return _run(lambda: _client().post("/deployments", payload, timeout=600))


@server.tool()
def hub_deploy_rollback(deployment_id: str, confirmed: bool = False) -> dict:
    """성공한 배포 시점의 스냅샷으로 되돌려 재배포한다.

    배포 게이트가 필요하고, 롤백도 새 배포 레코드로 남는다.
    DB/볼륨 변경은 자동 롤백되지 않는다.
    """
    if not confirmed:
        return {"ok": False,
                "error": "롤백을 실행하려면 confirmed=true 를 명시해야 합니다.",
                "code": "confirmation_required"}
    return _run(lambda: _client().post(
        f"/deployments/{deployment_id}/rollback", {"confirmed": True}, timeout=600))


# --------------------------------------------------------------------- 실행 --

class RequireApiKeyMiddleware:
    """원격(HTTP) 모드에서 요청마다 X-API-Key(또는 Bearer)를 요구한다.

    키는 그대로 허브 API 호출에 사용되므로, 클라이언트(API 키)의 scope/폐기 정책이
    그대로 적용된다 — 서버에 별도 상시 시크릿을 두지 않는다.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in (scope.get("headers") or [])}
        key = headers.get("x-api-key")
        if not key:
            auth = headers.get("authorization") or ""
            if auth.lower().startswith("bearer "):
                key = auth[7:].strip()
        if not key:
            body = b'{"error":"X-API-Key header required"}'
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        token = _REQUEST_API_KEY.set(key)
        try:
            await self.app(scope, receive, send)
        finally:
            _REQUEST_API_KEY.reset(token)


def run_http(host: str, port: int) -> None:
    import uvicorn

    app = server.streamable_http_app(streamable_http_path="/mcp",
                                     stateless_http=True, host=host)
    app.add_middleware(RequireApiKeyMiddleware)
    uvicorn.run(app, host=host, port=port, log_level="info")


def main() -> None:
    parser = argparse.ArgumentParser(prog="hub-mcp", description="N100 Service Hub MCP 서버")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                        help="stdio(기본) 또는 Streamable HTTP")
    parser.add_argument("--host", default=os.environ.get("HUB_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HUB_MCP_PORT", "8422")))
    parser.add_argument("--url", default=None, help="허브 API 베이스 URL (기본 HUB_URL)")
    parser.add_argument("--print-config", action="store_true",
                        help="AI 클라이언트용 MCP 설정 JSON을 출력하고 종료")
    args = parser.parse_args()

    if args.url:
        os.environ["HUB_URL"] = args.url

    if args.print_config:
        if args.transport == "http":
            # 원격(Streamable HTTP) 클라이언트용 — MCP 서버 주소만 지정한다.
            print(json.dumps({
                "mcpServers": {
                    "n100-service-hub": {
                        "url": f"http://{args.host}:{args.port}/mcp",
                    }
                }
            }, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({
                "mcpServers": {
                    "n100-service-hub": {
                        "command": "hub-mcp",
                        "env": {
                            "HUB_URL": normalize_base(os.environ.get("HUB_URL", "")),
                            "HUB_API_KEY": "<발급받은 API 키>",
                        },
                    }
                }
            }, ensure_ascii=False, indent=2))
        return

    if args.transport == "http":
        run_http(args.host, args.port)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
