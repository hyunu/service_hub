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

## 2. 도구 (26개)

### 조회
| 도구 | 설명 |
|---|---|
| `hub_status` | 허브/도커/모니터 상태 요약 |
| `hub_capabilities` | **배포 게이트·API 키 scope·포트 대역·업로드 가능 여부** |
| `hub_services_list` | 서비스 목록(검색/상태 필터) |
| `hub_service_get` | 서비스 상세 |
| `hub_service_access` | **접속 URL·인증 방식·자격 증명 참조·health 경로** (비밀값 미반환) |
| `hub_containers_list` | 컨테이너 목록(상태/관리 필터) |
| `hub_orphans_list` | 미관리 컨테이너 |
| `hub_ports_list` | 포트 레지스트리/예약 |
| `hub_ports_available` | 50000-59999 미할당 포트 후보 |
| `hub_port_reserve` / `hub_port_release` | 포트 예약/해제 |
| `hub_service_logs` | 서비스 소속 컨테이너 로그 |
| `hub_service_spec_guide` | **service.yaml 예시·필드·규칙** |
| `hub_deployment_guide` | 배포 모델·사전조건·오류·안전 안내 |
| `hub_deployments_list` | 배포 이력 |
| `hub_deploy_status` | 배포 단계/상태 |

### 변경/배포
| 도구 | 설명 |
|---|---|
| `hub_service_validate` | service.yaml 스키마 검증 (변경 없음) |
| `hub_service_scaffold` | `/srv/services/<id>/{service.yaml,compose.yaml}` 생성 |
| `hub_service_sync_source` | 소스 디렉터리를 배포 디렉터리로 업로드 (SSH 불필요) |
| `hub_service_register` | 서비스 레지스트리(DB) 등록 |
| `hub_service_apply` | **service.yaml로 레지스트리 등록/갱신** (런타임 무변경) |
| `hub_service_set_endpoint_auth` | 엔드포인트 인증 메타데이터(참조) 기록 |
| `hub_orphans_attach` | 미관리 컨테이너 수동 그룹핑 |
| `hub_deploy_plan` | 배포 계획 (컨테이너 무변경) |
| `hub_deploy_apply` | 배포 실행 (`confirmed=true`, 게이트 필요) |
| `hub_deploy_rollback` | 성공 배포 시점으로 롤백 (`confirmed=true`) |

## 3. 배포 워크플로 (AI가 따르는 순서)

```
1) hub_capabilities                 # 게이트/scope/포트 대역/업로드 가능 여부
2) hub_service_spec_guide           # service.yaml 형식 학습
3) hub_ports_available [→ reserve]  # 50000-59999 미할당 포트 확보
4) hub_service_scaffold             # 신규: /srv/services/<id>/ 파일 생성
5) hub_service_validate             # 스키마·포트·인증 검증
6) hub_service_register             # 신규 등록
   hub_service_apply                # 기존 정의 갱신 (409 없이 교체)
7) hub_service_sync_source          # 소스 업로드 (로컬 MCP 필요)
8) hub_deploy_plan                  # READY 확인 (impact 비어 있어야 함)
9) hub_deploy_apply(service_id, confirmed=true)
10) hub_deploy_status / hub_service_get
11) hub_service_access              # URL·인증·health 경로 확인
12) 필요 시 hub_deploy_rollback(confirmed=true)
```

> `hub_service_sync_source`는 **MCP 서버 프로세스의 파일 시스템**을 읽습니다.
> 원격(HTTP, N100) MCP에서는 호출자 PC 경로를 읽을 수 없으므로, 로컬 MCP를 쓰거나
> `POST /services/{id}/source`로 tar.gz를 직접 업로드해야 합니다.

필수 전제:
- `HUB_ENABLE_DEPLOY=true` (배포 게이트) — false면 scaffold/plan/apply 모두 거부
- `HUB_ENABLE_SOURCE_UPLOAD=true` (소스 업로드)
- API 키에 `write`/`deploy` scope
- `/srv/services`는 백엔드(uid 10001) 소유여야 scaffold/롤백이 가능
  ```bash
  sudo chown 10001:10001 /srv/services
  ```
- `compose.yaml`의 서비스명 = `service.yaml`의 `containers[].name`

### 3.1 AI 자율 배포 모드 — 소스 업로드는 실행 위치를 따른다

`hub_service_sync_source`는 **MCP 서버 프로세스가 실행 중인 머신**의 파일만 읽습니다.

| 모드 | 소스 업로드 | 권장 상황 |
|---|---|---|
| **로컬 stdio MCP** | 호출자 프로젝트 경로 업로드 가능 | 다른 프로젝트의 AI가 자기 소스를 배포 |
| 원격 HTTP MCP (N100) | N100 서버 경로만 읽음 | 읽기/계획/배포/상태 조회 |
| 원격 + REST 업로드 | `POST /services/{id}/source`에 tar.gz | 로컬 MCP를 못 쓰는 경우 |

로컬 MCP 예시(프로젝트 AI가 소스까지 스스로 올리는 구성):
```jsonc
"n100-service-hub-local": {
  "type": "local",
  "command": ["uv", "run", "--project",
              "/Users/hyunu/project/service_hub/mcp-server", "hub-mcp"],
  "environment": {
    "HUB_URL": "http://100.85.245.79:8420/api/v1",
    "HUB_API_KEY": "hub_..."
  }
}
```

원격 MCP + REST 업로드:
```bash
tar -czf /tmp/svc.tgz -C /path/to/project .
curl -X POST -H "X-API-Key: $HUB_API_KEY" -H "Content-Type: application/gzip" \
  --data-binary @/tmp/svc.tgz "$HUB_API_URL/services/<id>/source"
```
`HUB_API_URL`은 `hub_capabilities.api_base_url`에서 확인합니다.

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

## 7. AI가 배포 방식을 스스로 파악하는 장치

MCP에 접속한 개발 AI가 별도 설명 없이 배포 모델을 이해하도록 세 가지를 제공합니다.

| 종류 | 이름 | 내용 |
|---|---|---|
| 도구 | `hub_deployment_guide` | 배포 모델·사전조건·절차·시크릿·오류·안전 (구조화 + Markdown) |
| 리소스 | `hub://guides/deployment` | 같은 가이드 (text/markdown) |
| 프롬프트 | `deploy_service(service_id)` | 대화에 배포 절차를 주입 |

서버 `instructions`에도 핵심 모델이 요약되어 있습니다:
> 허브는 **서버의 `/srv/services/<id>`를 빌드**하며, MCP는 소스 업로드를 하지 않는다.
> 소스는 SSH rsync 또는 서버 `git pull`로 먼저 동기화하고, 배포 전에
> `hub_deployment_guide`를 호출하라.

권장: AI는 배포/재배포를 시작할 때 **가장 먼저 `hub_deployment_guide`를 호출**하고,
그 절차(소스 동기화 → scaffold → validate → register → plan → apply)를 따른다.
