# MCP 서버 (hub-mcp)

이 프로젝트는 **MCP(Model Context Protocol) 서버**를 제공합니다. AI 코딩 에이전트
(OpenCode, Cursor, Claude Code/Desktop 등)가 이 허브의 REST API를 통해
**조회 → 서비스 정의 생성 → 검증 → 등록 → 배포 계획/실행 → 롤백**을 수행할 수 있습니다.

- 코드: `mcp-server/` (패키지 `hub-mcp`)
- 전송: `stdio`(로컬 실행) 또는 **Streamable HTTP**(상주 서버)
- 안전: REST API만 호출하며 **임의 셸 실행 도구는 없습니다.**

## 1. 상주 서버 (N100)

| 항목 | 값 |
|---|---|
| 엔드포인트 | `http://100.85.245.79:8422/mcp` (**tailnet 전용**) |
| systemd | `hub-mcp.service` (User=hyunu, Restart=on-failure) |
| 환경 파일 | `/srv/service-hub/mcp.env` (root:root 600) |
| 허브 API | `HUB_URL=http://100.85.245.79:8420/api/v1` |
| 인증 | 허브 API 키 `X-API-Key` (서버 측 보관) |

> MCP HTTP 엔드포인트 자체에는 인증이 없습니다. **tailnet(100.x)에만 바인드**되어
> 있고, 키는 서버 프로세스 환경에만 있습니다. tailnet이 신뢰 경계입니다.

운영:

```bash
sudo systemctl status hub-mcp
sudo systemctl restart hub-mcp
sudo journalctl -u hub-mcp -n 50 --no-pager
```

## 2. 도구 (17개)

### 조회
| 도구 | 설명 |
|---|---|
| `hub_status` | 허브/도커/모니터 상태 요약 |
| `hub_services_list` | 서비스 목록(검색/상태 필터) |
| `hub_service_get` | 서비스 상세 |
| `hub_containers_list` | 컨테이너 목록(상태/관리 필터) |
| `hub_orphans_list` | 미관리 컨테이너 |
| `hub_ports_list` | 포트 레지스트리/예약 |
| `hub_service_logs` | 서비스 소속 컨테이너 로그 |
| `hub_service_spec_guide` | **service.yaml 예시·필드·규칙** |
| `hub_deployments_list` | 배포 이력 |
| `hub_deploy_status` | 배포 단계/상태 |

### 변경/배포
| 도구 | 설명 |
|---|---|
| `hub_service_validate` | service.yaml 스키마 검증 (변경 없음) |
| `hub_service_scaffold` | `/srv/services/<id>/{service.yaml,compose.yaml}` 생성 |
| `hub_service_register` | 서비스 레지스트리(DB) 등록 |
| `hub_orphans_attach` | 미관리 컨테이너 수동 그룹핑 |
| `hub_deploy_plan` | 배포 계획 (컨테이너 무변경) |
| `hub_deploy_apply` | 배포 실행 (`confirmed=true`, 게이트 필요) |
| `hub_deploy_rollback` | 성공 배포 시점으로 롤백 (`confirmed=true`) |

## 3. 배포 워크플로 (AI가 따르는 순서)

```
1) hub_service_spec_guide          # service.yaml 형식 학습
2) hub_service_scaffold            # /srv/services/<id>/ 파일 생성
3) hub_service_validate            # 스키마 검증
4) hub_service_register            # DB 등록 (deployment_path=/srv/services/<id>)
5) hub_deploy_plan                 # READY 확인 (impact 비어 있어야 함)
6) hub_deploy_apply(service_id, confirmed=true)
7) hub_deploy_status / hub_deployments_list
8) 필요 시 hub_deploy_rollback(confirmed=true)
```

필수 전제:
- `HUB_ENABLE_DEPLOY=true` (배포 게이트) — false면 scaffold/plan/apply 모두 거부
- `/srv/services`는 백엔드(uid 10001) 소유여야 scaffold/롤백이 가능
  ```bash
  sudo chown 10001:10001 /srv/services
  ```
- `compose.yaml`의 서비스명 = `service.yaml`의 `containers[].name`

## 4. 클라이언트 설정

### OpenCode
`~/.config/opencode/opencode.jsonc`
```jsonc
{
  "mcp": {
    "servers": {
      "n100-service-hub": {
        "type": "remote",
        "url": "http://100.85.245.79:8422/mcp",
        "oauth": false
      }
    }
  }
}
```

### Cursor
`~/.cursor/mcp.json`
```json
{
  "mcpServers": {
    "n100-service-hub": { "url": "http://100.85.245.79:8422/mcp" }
  }
}
```

### Claude Code
```bash
claude mcp add --transport http n100-service-hub http://100.85.245.79:8422/mcp
```

### 로컬 stdio (원격 HTTP를 못 쓰는 클라이언트)
```json
{
  "mcpServers": {
    "n100-service-hub": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/service_hub/mcp-server", "hub-mcp"],
      "env": {
        "HUB_URL": "https://n100-pve-dev.tail7d413d.ts.net/api/v1",
        "HUB_API_KEY": "hub_발급받은키"
      }
    }
  }
}
```

키는 **Settings → API 키**에서 발급합니다(평문은 1회만 표시).
서버 상주 키는 `/srv/service-hub/mcp.env`에서 확인할 수 있습니다(권한 필요).

## 5. 안전 / 제약

- **임의 셸 실행 도구 없음** — 허브 REST API만 호출합니다.
- 배포는 `HUB_ENABLE_DEPLOY` 게이트와 compose 화이트리스트(`config/up/down`)를 그대로 따릅니다.
- `hub_service_scaffold`는 경로/파일명이 고정(`/srv/services/<id>/{service.yaml,compose.yaml}`)이며,
  덮어쓰기에는 `overwrite=true` + `confirm=<id>`가 필요합니다.
- `hub_deploy_apply`/`hub_deploy_rollback`은 `confirmed=true` 없이는 실행되지 않습니다.
- DB/볼륨 변경은 롤백 대상이 아닙니다(요구사항 §13.4).
- MCP HTTP는 tailnet에만 바인드합니다. 외부 공개가 필요하면 방화벽/터널 정책을 먼저 검토하세요.

## 6. 트러블슈팅

| 증상 | 확인 |
|---|---|
| `401 unauthorized` | API 키 만료/폐기 여부, `X-API-Key` 전달 |
| `503 deploy_disabled` | `HUB_ENABLE_DEPLOY` 값 |
| `409 already_exists` | 이미 서비스 디렉터리 존재 → `overwrite+confirm` |
| `403/409 scaffold` | `/srv/services` 소유권(10001) |
| 도구가 안 보임 | 클라이언트 재시작, 엔드포인트 `/mcp` 경로, tailnet 연결 |
