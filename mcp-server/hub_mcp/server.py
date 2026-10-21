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
import json
import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from .client import HubApiError, HubClient, normalize_base

server = MCPServer(
    "n100-service-hub",
    version="0.1.0",
    instructions=(
        "N100 Service Hub 관리 도구. 먼저 hub_status / hub_services_list 로 현재 상태를 "
        "확인하고, 서비스 등록은 service.yaml(schema_version 1) dict를 hub_service_register 로 "
        "전달한다. 배포는 hub_deploy_plan 으로 계획을 확인한 뒤 hub_deploy_apply(confirmed=true) "
        "로 요청한다. 허브가 HUB_ENABLE_DEPLOY=false 로 잠겨 있으면 배포는 거부된다."
    ),
)


def _client() -> HubClient:
    return HubClient()


def _run(fn, *args, **kwargs) -> dict:
    """도구 공통 래퍼 — 예외를 구조화된 결과로 바꾼다."""
    try:
        data = fn(*args, **kwargs)
        return {"ok": True, "data": data}
    except HubApiError as exc:
        return {"ok": False, "error": str(exc), "code": exc.code, "status": exc.status}


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
    return _run(lambda: _client().post("/deployments", payload))


# --------------------------------------------------------------------- 실행 --

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
        server.run("streamable-http", host=args.host, port=args.port)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
