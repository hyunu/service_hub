# hub-mcp — N100 Service Hub MCP 서버

AI 코딩 에이전트(Claude Code, Claude Desktop, Cursor, Codex 등)가 이 허브에
**서비스 등록 · 컨테이너 연결 · 배포 계획/실행**을 요청할 수 있게 하는 MCP 서버입니다.

- 기존 백엔드 REST API만 호출합니다. 임의 셸 실행 도구는 없습니다.
- 배포는 백엔드의 `HUB_ENABLE_DEPLOY` 잠금과 compose 화이트리스트 검증을 그대로 따릅니다.
- 인증은 API 키입니다. 키 발급/폐기는 **대시보드 Settings → API 키**에서만 가능합니다.

## 1. API 키 발급

대시보드 **Settings → API 키**에서 이름(예: `claude-code`)을 입력하고 발급합니다.
평문 키는 발급 직후 한 번만 표시되므로 바로 복사하세요.

서버 셸에서 발급하려면(오프라인):

```bash
# 서버에서 (DB 볼륨 경로는 실제 값으로 바꾸세요)
sudo hub apikey create --name claude-code \
  --db /var/lib/docker/volumes/service-hub_hub-data/_data/hub.db

# 읽기 전용 키
sudo hub apikey create --name read-only --scope read --db <hub.db>

# 폐기 / 목록
sudo hub apikey revoke <key-id> --db <hub.db>
sudo hub apikey list --db <hub.db>
```

## 2. 설치

```bash
cd mcp-server
uv sync
uv run hub-mcp --help
```

## 3. AI 클라이언트 설정

### Claude Code / Claude Desktop

```json
{
  "mcpServers": {
    "n100-service-hub": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/service_hub/mcp-server", "hub-mcp"],
      "env": {
        "HUB_URL": "http://127.0.0.1:8420/api/v1",
        "HUB_API_KEY": "hub_발급받은키"
      }
    }
  }
}
```

서버에 원격으로 붙는 경우 `HUB_URL`을 Tailscale 주소로 바꿉니다.

```bash
uv run hub-mcp --print-config     # 위 형식의 설정을 출력
```

### Streamable HTTP로 상주 실행

```bash
HUB_URL=http://127.0.0.1:8420/api/v1 HUB_API_KEY=hub_... \
  uv run hub-mcp --transport http --host 127.0.0.1 --port 8422
```

기본 바인드는 루프백입니다. 외부에 열어야 한다면 방화벽/터널 정책을 먼저 확인하세요.

## 4. 제공 도구

| 도구 | 설명 |
|---|---|
| `hub_status` | 허브/도커/모니터 상태 요약 |
| `hub_services_list` | 서비스 목록 (검색/상태/카테고리) |
| `hub_service_get` | 서비스 상세(컴포넌트·엔드포인트·컨테이너) |
| `hub_containers_list` | 전체 컨테이너 인벤토리 |
| `hub_orphans_list` | 미관리 컨테이너 목록 |
| `hub_ports_list` | 포트 사용/예약 현황 |
| `hub_service_logs` | 서비스 로그 |
| `hub_service_register` | service.yaml로 서비스 등록 (`dry_run` 지원) |
| `hub_service_sync_source` | **로컬 소스 디렉터리를 허브로 업로드** (SSH 불필요) |
| `hub_orphans_attach` | 미관리 컨테이너를 서비스에 수동 연결 |
| `hub_deploy_plan` | 배포 계획 생성 (변경 없음) |
| `hub_deploy_apply` | 배포 실행 (`confirmed=true` 필요) |
| `hub_deploy_status` | 배포 작업 상태 |

모든 도구는 `{"ok": true, "data": ...}` 또는
`{"ok": false, "error": ..., "code": ..., "status": ...}` 형태로 응답합니다.

## 4.1 소스 동기화 (SSH 없이)

배포 디렉터리는 서버에 있어야 합니다. MCP가 로컬 소스를 tar.gz로 묶어 업로드합니다.

```text
hub_service_sync_source(service_id="pianosync", path="/Users/me/proj/pianosync")
→ { ok: true, data: { files: 42, raw_bytes: ..., result: {...} } }
```

- 서버 설정 필요: `HUB_ENABLE_SOURCE_UPLOAD=true` (기본 false, `.env`)
- 기본 제외: `.git`, `node_modules`, `.venv`, `__pycache__`, `.pytest_cache`, `.DS_Store`
- 덮어쓰기만 하고 **파일 삭제는 반영하지 않습니다**
- 안전: 상대 경로·일반 파일만, `..`/절대 경로/심볼릭 링크 거부, 크기·개수 상한, 감사 로그

## 5. 사용 예 (AI에게 이렇게 말하면 됩니다)

- "이 폴더의 service.yaml을 허브에 `my-app`으로 등록해줘. 배포 경로는 `/srv/services/my-app`."
- "미관리 컨테이너 목록 보여주고, `assetnest-*`는 `assetnest` 서비스에 연결해줘."
- "배포 계획 먼저 보여주고, READY면 실행해줘."

배포 경로(`deployment_path`)는 **호스트 기준 절대 경로**입니다.
Docker 데몬이 `compose.yaml`을 찾을 수 있는 디렉터리여야 하며, hub 컨테이너 내부 경로가 아닙니다.

## 6. 보안 메모

- 키는 SHA-256 해시로만 저장되고 목록/로그에 평문이 남지 않습니다.
- API 키로는 새 API 키를 발급할 수 없습니다 (세션 전용).
- `read` scope 키는 조회만 가능합니다.
- 배포 실행은 `HUB_ENABLE_DEPLOY=true`(기본 false)일 때만 동작하며, 모든 시도는 감사 로그에
  `apikey:<이름>` 주체로 기록됩니다.
- 키가 유출되면 대시보드에서 즉시 폐기하고 새로 발급하세요.

## 7. 상주 서버 (N100, Streamable HTTP)

N100에는 systemd로 상주 실행 중이다.

| 항목 | 값 |
|---|---|
| 엔드포인트 | `http://100.85.245.79:8422/mcp` (tailnet 전용) |
| 유닛 | `hub-mcp.service` (`systemctl status hub-mcp`) |
| 환경 | `/srv/service-hub/mcp.env` (root 600, `HUB_URL`/`HUB_API_KEY`) |

```bash
sudo systemctl status hub-mcp
sudo journalctl -u hub-mcp -n 50 --no-pager
```

전체 사용법(도구 17개, 배포 워크플로, 클라이언트 설정)은 `docs/MCP.md`를 참고하세요.

## 8. 배포 방식 자문 (AI용)

접속한 AI가 배포 방식을 스스로 알 수 있도록 제공한다.
- 도구 `hub_deployment_guide` — 모델·사전조건·절차·시크릿·오류·안전
- 리소스 `hub://guides/deployment` — 동일 가이드(Markdown)
- 프롬프트 `deploy_service` — 대화에 절차 주입

핵심: 허브는 서버의 `/srv/services/<id>`를 빌드하며, MCP는 소스 업로드를 하지 않는다.
소스는 먼저 SSH rsync / git pull로 동기화한다.
