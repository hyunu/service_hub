# IMPLEMENTATION STATUS

최종 갱신: 2026-10-22 (N100 실서버 배포·관리자 초기화·인벤토리 정리·MCP/API 키·배포 잠금 해제 완료)

## 완료
- **Phase 0**: 환경 조사(개발 머신 macOS / Docker 29.4.3, 기존 컨테이너 19개),
  ARCHITECTURE / SECURITY / ENVIRONMENT-INVENTORY / IMPLEMENTATION-PLAN / REQUIREMENTS 문서.
- **Phase 1 (읽기 전용)**:
  - 백엔드 (FastAPI + SQLite/WAL): 서비스 레지스트리, 컨테이너 인벤토리, 미관리(orphan)
    탐지·연결, 포트 레지스트리·예약, 자원 모니터링, 이벤트/감사 로그, 인증(관리자 설정
    마법사·세션·CSRF·로그인 제한), 백그라운드 모니터 + status.json 캐시.
  - 프론트엔드 (React 19 + Vite + Tailwind v4): Setup/Login/Overview/Services/ServiceDetail/
    Containers/Ports/Deployments/DeploymentDetail/Resources/Events/Settings 12개 페이지.
  - CLI (`hub`): status, service validate 등. 스키마(`service.schema.v1.json`) 포함.
  - 스크립트: install/uninstall/backup/dev-smoke/motd.
  - 문서: README, AI-OPERATIONS, AGENTS, backend/README, frontend/README.
- **Phase 2 (표준 서비스 등록/검증)**:
  - `backend/app/services/service_spec.py`: service.yaml 스키마 v1 Pydantic 검증.
    미지원 schema_version 거부, 시크릿 값 금지(이름만), proxy/host 노출 규칙.
  - `POST /api/v1/services/validate`: 스펙 검증(읽기 전용, DB 무변경).
  - `backend/app/services/template_render.py` + `hub service new`: 표준 디렉터리 골격
    (시크릿 값 미생성, `.env.example`에는 이름만).
  - 기존 `hub service validate`(jsonschema) 유지 — 로컬 검증 경로.
- **Phase 3 (표준 배포 — 계획 + 실행기, 게이트 필수)**:
  - `backend/app/services/deploy_plan.py`: 컨테이너를 변경하지 않는 배포 계획
    (changes/ports/validation/impact/READY·BLOCKED, `runtime_unchanged=true`).
  - `POST /api/v1/deployments/plan`: 읽기 전용 계획 API (CLI `service_definition` 호환).
  - `backend/app/services/deploy_runner.py`: 상태머신
    queued→validating→running→verifying→succeeded/failed, 단계별 이력.
  - `POST /api/v1/deployments`: 배포 실행 — **기본 잠금**, 게이트 통과 시에만 동작.
  - `docker_client.py`: 화이트리스트 compose 변경 함수(config/up/down)만 추가.
    `allow_mutations=False`면 `PermissionError`, 임의 셸 경로 없음.
  - 프론트엔드 Deployments: 계획 미리보기 + 실행 버튼(잠금 시 안내).
- **인증/UI 확장 (2026-10-21)**:
  - 비밀번호 변경(`POST /api/v1/auth/change-password`): 현 비밀번호 재확인 + CSRF,
    감사 로그(`auth.password_change`). Settings > 보안 탭 UI.
  - 생체인식(WebAuthn 패스워드리스): 등록/로그인 begin·finish + 자격증명 목록/삭제.
    HTTPS + `HUB_WEBAUTHN_RP_ID`/`HUB_WEBAUTHN_ORIGIN` 설정 시에만 활성(기본 꺼짐).
    공개키만 저장, 챌린지 1회용 5분 TTL, 로그인 잠금(5회/5분) 공유.
    로그인 화면 "생체인식으로 로그인" + Settings > 보안 탭 키 관리.
  - 사이드바 접기 + 화면 세로 중앙 원형 토글 버튼(localStorage 유지).
- **컨테이너 인벤토리 정리 (2026-10-22)**:
  - `sync_inventory`가 스냅샷에 **없는 컨테이너의 옛 행을 정리**하도록 수정.
    이전에는 upsert만 해서 재기동/배포할 때마다 옛 ID 행이 남아 대시보드에
    `hub-backend`/`hub-frontend`가 여러 개로 중복 표시되었다.
  - 처리 규칙: 허브 자기 자신·미관리 컨테이너 → 행 삭제, 서비스 컴포넌트 →
    등록 정보 보존 후 `missing` 표시(동일 컴포넌트의 살아있는 컨테이너가 있으면 행 삭제),
    사라진 컨테이너를 가리키는 수동 연결(assignment)도 삭제.
  - Docker 연결 불가(snapshot=None) 시에는 어떤 행도 삭제하지 않는다.
  - DB 레코드만 변경하며 Docker는 건드리지 않는다(기존 서비스 보호 유지).
  - 테스트: `backend/tests/test_inventory_cleanup.py` 6건 추가.
- **AI/MCP 연동 + API 키 (2026-10-22)**:
  - `api_keys` 테이블(해시만 저장) + `GET/POST/DELETE /api/v1/apikeys`
    (발급/목록/폐기는 브라우저 세션 전용).
  - `require_auth`가 `X-API-Key` / `Authorization: Bearer`를 허용하고 scope를 강제한다
    (`read` 키의 변경 요청은 403). 감사 로그 주체는 `apikey:<이름>`.
  - 대시보드 **Settings → API 키** 탭: 발급(1회 표시) / 목록 / 폐기 / MCP 설정 스니펫.
  - CLI: `hub apikey create|list|revoke [--db <hub.db>]` (오프라인 발급 지원).
  - `mcp-server/` 추가 — MCP 2.x(`MCPServer`) 기반. 도구 12개(상태/서비스/컨테이너/포트
    조회, 서비스 등록, 미관리 컨테이너 연결, 배포 계획/실행/상태, 로그).
    임의 셸 실행 도구는 없고 기존 REST API만 호출한다.
  - 테스트: backend +6(API 키), CLI +4, MCP 12, frontend +4(Settings).
- **대시보드 회귀 수정 2건 (2026-10-22)**:
  - **서비스 등록 422 해소**: 등록 폼이 `{service, source, deployment, containers,
    endpoints}`(service.yaml 형식)를 보내는데 `POST /services`가 평탄 필드만 받아
    422가 발생했다. `ServiceCreate`에 `model_validator(before)`를 추가해 중첩 스펙을
    정규화하고(`containers`→컴포넌트, `endpoints`→엔드포인트), 평탄 형식도 계속 지원.
    필수값 누락은 `422 missing_fields`로 명확히 응답. 프론트는 FastAPI 422(detail 배열)를
    "입력값이 올바르지 않습니다 — id: Field required" 형태로 표시한다.
  - **다이얼로그 포커스 튕김**: `Dialog`의 effect 의존성에 인라인 `onClose`가 포함되어
    입력할 때마다 재실행되며 `panelRef.focus()`가 호출됐다(입력 불가). 최신 핸들러는 ref로
    유지하고 효과는 `open`에만 반응하도록 수정. Services 등록·ServiceDetail 삭제 다이얼로그 공통.
  - 테스트: backend +5(`test_service_create_shapes.py`), frontend +2(포커스 회귀, 422 메시지).
  - N100 배포 후 실서버에서 중첩 payload 등록 201 / 필수값 누락 422 / 삭제 404 확인.
- **관리자 비밀번호 분실 복구 (2026-10-21)**:
  - `POST /api/v1/auth/reset-admin`: 관리자 자격 증명(사용자명·비밀번호 해시·패스워드 키)
   만 삭제하고 설정 마법사를 다시 표시한다. 서비스/포트/컨테이너 데이터는 보존.
  - 허용 조건: **루프백 요청** 또는 `HUB_ADMIN_RESET_TOKEN` + `X-Hub-Admin-Reset-Token`
    헤더 일치. 그 외는 403 `reset_not_allowed` (인증 우회 경로 없음).
  - 복구 토큰은 **1회 사용** — 성공 후 해시가 DB에 기록되어 같은 토큰 재사용 불가.
  - 세션 epoch: 관리자 생성/초기화마다 값이 바뀌어 기존 세션이 자동 무효화
    (재시작 불필요, 세션 쿠키 소지 요청도 401).
  - CLI `hub admin reset`: API 모드(`--url`/`--token`) + 오프라인 모드(`--db`, 백업 후
    `settings`/`webauthn_credentials`만 삭제). `--yes` 없이는 실행하지 않는다.
  - N100 실서버에서 실제로 관리자 초기화 수행 완료(아래 배포 검증 참고).
- **MCP 서버 상주 배포·전체 워크플로 (2026-10-23)**:
  - `hub-mcp.service`(systemd)로 N100에 상주. 엔드포인트 `http://100.85.245.79:8422/mcp`(tailnet 전용).
  - API 키 `mcp-agents` 발급(서버 `/srv/service-hub/mcp.env`, root 600).
  - 도구 17개: spec_guide/validate/scaffold/register/plan/apply/status/list/rollback 등.
  - `POST /services/{id}/scaffold` 추가 — AI가 셸 없이 `/srv/services/<id>`에 정의 파일 생성(게이트/확인/감사).
  - `/srv/services` 소유권을 10001로 변경(백엔드가 scaffold/롤백 파일을 쓸 수 있도록).
  - **실서버 MCP e2e**: guide → scaffold → validate → register → plan(READY) → apply(succeeded)
    → 컨테이너 `mcp-demo-web` 기동(`mcp-deploy-ok` 로그) → deployments/status 확인 → 전부 정리.
  - OpenCode/Cursor에 원격 MCP 등록(백업 후). Claude Code는 `claude mcp add --transport http`.
- **이벤트 확인(unread 뱃지, 2026-10-23)**:
  - 상단 뱃지를 "최근 100개 중 warning/critical"에서 **마지막 확인 이후 미읽음 수**로 변경.
  - `GET /events/unread-count`, `POST /events/acknowledge`(CSRF) 추가.
    확인 시각은 `settings.events_state.last_read_at`에 저장(서버 일관).
  - Events 화면 진입 시 자동 확인 → 뱃지 즉시 감소(폴링 15초 + 커스텀 이벤트).
  - 실서버 검증: 뱃지 1 → 이벤트 화면 클릭 → 0 확인.
- **trade-console 배포 실패·오매칭 수정 (2026-10-24)**:
  - **배포 실패**: `container name "/trade-console-web" is already in use`.
    compose 서비스명이 `web` → `console` 로 바뀌었는데 `container_name` 이 고정되어 있어,
    이전 서비스(web)의 컨테이너가 남은 상태에서 새 컨테이너 생성이 충돌했다.
    재시도에서 성공(`dep-f4185dec2008 succeeded`). `_compose` 실패 메시지에
    원인/해결 힌트를 추가했다.
  - **오매칭 버그**: `match_component` 의 이름 하위문자열 fallback 때문에
    `trade-console-web` 이 `pianosync` 의 `web` 컴포넌트로 연결되어
    trade-console 이 `missing`, 같은 이름 행 2개가 생겼다.
    → 정확 매칭(compose 서비스명/컨테이너 이름)만 사용하고, 애매하면 unmanaged.
    추가로 compose 프로젝트 == 서비스 ID 인 서비스를 우선 매칭한다.
  - 검증: 동기화 후 `trade-console-web` 행 1개(`trade-console/console`, managed),
    서비스 상태 **healthy** (asset-nest/flow-plan/pianosync/trade-console 모두 healthy).
  - trade-console compose/service.yaml 의 restart 정책도 `always` 로 맞추고 적용.
  - 테스트: `backend/tests/test_inventory_matching.py` 4건 추가 (backend 185 passed).
- **원격 MCP(HTTP) 상주 — OpenCode 프로필 독립 (2026-10-24)**:
  - 문제: MCP가 특정 Mac의 `~/.config/opencode/opencode.jsonc` 한 곳에만 등록되어,
    같은 Mac의 다른 OpenCode 런타임(v2.2.1, 별도 설정)이나 저장소가 없는 환경에서는
    `opencode mcp list`가 비어 있고 API는 401이었다.
  - 해결: N100에 MCP를 HTTP 모드로 상주(systemd `hub-mcp`,
    `--transport http --host 100.85.245.79 --port 8422`, `HUB_URL` 명시).
    `RequireApiKeyMiddleware`가 매 요청의 `X-API-Key`(또는 Bearer)를 검증하고,
    그 키를 ContextVar로 도구 컨텍스트에 전달해 허브 호출에 그대로 사용한다
    (서버에 상시 키 저장 없음, clients의 scope/폐기 정책 유지).
  - 클라이언트는 `"type": "remote"` + `url` + `headers.X-API-Key` 만으로 연결
    (uv·저장소·로컬 경로 불필요).
  - 실서버 검증: 키 없음 → 401, 키 포함 initialize 200, `tools/call hub_status` → ok,
    systemd active, 100.85.245.79:8422 LISTEN(tailnet 한정). 이 Mac에서도 원격 호출 확인.
  - 산출물: `mcp-server/deploy/hub-mcp.service`, `install-remote.sh`,
    MCP README·UNATTENDED-DEPLOY 원격 연결 절차, MCP 테스트 +4(`test_http_auth.py`).
  - 발급 키: `opencode-remote` (채팅 노출 → 필요 시 대시보드에서 폐기/재발급 권장).
- **무인 배포 실검증 (2026-10-24, flow-plan)**:
  - 로컬 `/Users/hyunu/project/flow_plan` 을 `deploy/sync.sh` 제외 규칙으로 스테이징
    (`/tmp/flow-plan-sync/app/`)한 뒤 MCP `hub_service_sync_source` 로 업로드.
    - dry_run: 139 files / 30.2MB / archive 15.3MB
    - 실제 업로드 성공 → `/srv/services/flow-plan/app/...` (mtime 08:16)
  - 최초 업로드는 `PermissionError`(500) → `/srv/services/<id>` 하위가 그룹 쓰기 불가였음.
    `sudo chmod -R g+rwX /srv/services` 로 해결(소유자 유지). 업로더는 이제
    `409 source_write_forbidden` + 해결 명령을 안내한다.
  - MCP `hub_deploy_apply(service_id=flow-plan, confirmed=true)` →
    `dep-de5fb2c57f4f` **succeeded** (108초, queued→validating→running→verifying→succeeded).
  - 결과: flow-plan-backend/ui 모두 healthy, `http://100.85.245.79:8780` **200**,
    다른 서비스(assetnest·pianosync·trade-engine·hub) 무변경.
- **무인 배포 지원 (2026-10-24, N100 설정 적용)**:
  - 배포 허용 목록(`HUB_DEPLOY_ALLOWED_SERVICES`) 실제 강제, 실패 시 자동 롤백
    (`HUB_DEPLOY_AUTO_ROLLBACK`), 결과 웹훅(`HUB_DEPLOY_WEBHOOK_URL`, HMAC 서명).
  - 소스 업로드 시 `.env`/`*.pem`/`*.key` → 0600.
  - N100 설정: `HUB_ENABLE_DEPLOY=true`, `HUB_ENABLE_SOURCE_UPLOAD=true`,
    `HUB_DEPLOY_AUTO_ROLLBACK=true`, 허용 목록 비움(전체), 웹훅 미설정.
  - 사람이 한 번만 하는 것: API 키 발급 + MCP 클라이언트 설정.
  - 테스트: `test_unattended_deploy.py` 7건 (backend 199 passed / MCP 25 passed).
- **SSH 없는 소스 동기화 (2026-10-24, MCP)**:
  - `POST /api/v1/services/{id}/source` — tar.gz 업로드로 `/srv/services/<id>` 갱신.
    `HUB_ENABLE_SOURCE_UPLOAD`(기본 false) 게이트. 상대 경로/일반 파일만, 크기·개수 상한,
    경로 조작·심볼릭 링크 거부, 덮어쓰기만(삭제 없음), 감사 로그. 컨테이너/이미지 무변경.
  - MCP `hub_service_sync_source(service_id, path)`: 로컬 디렉터리를 tar.gz로 묶어 업로드.
    기본 제외 `.git`/`node_modules`/`.venv`/`__pycache__` 등, `dry_run` 지원.
  - N100 실서버 E2E: MCP로 2개 파일 업로드 → `/srv/services/src-probe/hello.txt` 확인
    (권한 664/775, uid 10001) → 테스트 서비스/키/디렉터리 정리 완료.
  - 이제 AI 워크플로: `sync_source` → `deploy_plan` → `deploy_apply` (SSH 불필요).
  - `.env`에 `HUB_ENABLE_SOURCE_UPLOAD=true` 적용(백업 `.env.bak-20261024-064100`).
- **Containers UI 정리 (2026-10-24)**:
  - 서비스 그룹을 **기본 접힘**으로 변경(`펼친 그룹`만 기억, 새 그룹도 자동 접힘).
  - 그룹 헤더 슬림화: 이름 + `n/m 실행 중`만. ID는 이름의 슬러그와 다를 때만,
    개수 칩·서비스 상세 링크는 제거(중복 정보 정리).
  - 서비스별 강조색(6색 팔레트, ID 해시로 고정) + 왼쪽 컬러 바 + 그룹 간 간격으로
    시각 구분 강화.
  - 하단 **Images 섹션을 기본 접힘**으로 변경. 접힌 상태에서 `이미지 N개 · 총 용량` 요약,
    펼치면 기존 표와 새로고침 버튼 노출(목록은 actions_enabled 확인을 위해 계속 선로딩).
- **재시작 정책 always 전환 (2026-10-24, N100)**:
  - 요구사항: "부팅 시 무조건 자동 시작" (`unless-stopped`는 수동 stop 후 재부팅 시 복귀하지 않음).
  - `docker update --restart always` 로 **11개 컨테이너 전체** 즉시 적용 +
    compose 파일 영구 반영: hub `compose.yaml`(2), `/srv/services/asset-nest`(6),
    `flow-plan`(2), `pianosync`(1) — 각 파일 백업 생성.
  - 발견/복구: `hub-frontend`가 네트워크 미연결 상태로 crash-loop(대시보드 502)
    → `compose up -d --force-recreate frontend` 로 복구.
    `flow-plan-ui`도 동일 증상(nginx `host not found in upstream "backend"`, 네트워크 없음)
    → flow-plan 스택 재생성으로 복구(8780 → HTTP 200).
  - 최종: 11개 모두 `running` + `restart: always`, 허브 대시보드 HTTP 200.
- **Containers 테이블 단순화 (2026-10-24)**:
  - 컬럼 10 → 8. **서비스 컬럼 제거**(그룹 헤더가 소속을 표시, 컴포넌트는 이름 옆 태그),
    **관리 상태 컬럼 제거**(상태 컬럼에 `managed`가 아닌 예외만 배지로 표시).
  - CPU/메모리가 항상 N/A였던 원인: 목록 API가 자원 값을 제공하지 않음.
    `GET /resources/containers`(docker stats)를 ID로 병합하되, 수집에 ~2초 걸리므로
    목록을 먼저 표시하고 도착 시 행만 갱신(점진 로딩, 시퀀스 토큰으로 역전 방지).
  - 재시작 횟수는 정상: `docker inspect .RestartCount`와 일치
    (assetnest-dashboard 3330, assetnest-mongo 13618, 나머지 0/1).
- **Overview 호스트 자원 1초 자동 갱신 (2026-10-24)**:
  - 개요 화면이 보이는 동안 `GET /resources/host`만 1초 간격으로 폴링해
    CPU/메모리/디스크 게이지를 갱신한다 (전체 개요 재조회 없음).
  - 중복 요청 방지(in-flight) + 탭 숨김 시 일시정지(`document.hidden`),
    언마운트/이탈 시 인터벌·리스너 정리. 첫 응답 전에는 개요 응답 값 사용(깜빡임 없음).
  - 카드에 "1초마다 자동 갱신 · 마지막 갱신 …" 표시, 실패 시 사유 표시.
  - 부하 절감: `collect_host()`가 CPU 샘플링을 2회(0.1s×2) → 1회로 통합.
    실서버 `/resources/host` 응답 시간 **263ms → 163ms**(평균, 5회 측정).
- **Containers 서비스 그룹화 (2026-10-23)**:
  - 목록을 `service_id` 기준으로 묶어 서비스별 헤더(이름·ID·`실행 중/전체` 배지·상세 링크) 아래에
    컨테이너를 표시. 미연결 컨테이너는 마지막 "서비스 미지정" 그룹.
  - 등록된 서비스가 없으면 기존과 동일한 평면 목록. 필터·선택·상세 드로어 동작 유지.
  - 실서버 데이터: flow-plan 2개, pianosync 1개, 미지정 8개로 그룹 표시 확인.
- **컨테이너/이미지 조작 (2026-10-23)**:
  - 시작/정지/제거 + 이미지 목록/제거. 기본 잠금(`HUB_ENABLE_DOCKER_ACTIONS=false`).
  - 허브 자신·보호 대상 차단, 제거는 실행 중 거부 + 정확한 이름 확인, 이미지는
    사용 중/허브 이미지 차단. 모든 조작 감사 로그.
  - UI: 컨테이너 상세의 작업 버튼, Containers 하단 Images 목록/제거.
  - 실서버 검증: stop/start/remove 200, 실행 중 제거 409, 확인 불일치 422,
    assetnest 보호 403, 허브 이미지 403, 사용 중 이미지 409. 검증 후 게이트 off로 복구.
  - **2026-10-23 사용자 승인으로 게이트 활성화**: `.env`에
    `HUB_ENABLE_DOCKER_ACTIONS=true`, `HUB_PROTECTED_PROJECTS=infra`,
    `HUB_PROTECTED_CONTAINERS=assetnest` 설정 후 backend 재생성
    (백업 `/srv/service-hub/.env.bak-20261023-133157`).
    활성화 후 재검증: `GET /images` → `actions_enabled=true`,
    `start assetnest-mongo` → 403 `protected_container`(project `infra`/접두사 `assetnest`),
    `stop assetnest-server` → 403, `stop hub-backend` → 403(허브 자신),
    `remove flow-plan-ui` → 409 `container_running`. 컨테이너 상태 변화 없음.
  - **UI 사전 차단 (2026-10-23)**: 백엔드는 403으로 막고 있었지만 대시보드는 전역
    게이트만 보고 버튼을 활성화해, 눌러야 거부를 알 수 있었다.
    `GET /containers[/{id}]`에 `protected_reason`·`actions_allowed`를 추가하고
    (판정은 `app/services/protection.py`로 단일화) 상세 화면이 사유와 함께 버튼을
    비활성화한다. 실서버 확인: 허브 2개·assetnest 2개 → `actions_allowed=false`,
    `flow-plan-ui`·`pianosync-web` → `true`.
- **배포 롤백 (2026-10-22)**:
  - 배포 시 `service.yaml`/`compose.yaml` 스냅샷(`HUB_DEPLOY_SNAPSHOT_DIR`,
    기본 `/data/deploy-snapshots`, `.env` 제외)을 남긴다.
  - `POST /deployments/{id}/rollback`: 성공한 배포 시점 파일을 복원해 재배포.
    롤백도 새 배포 레코드 + 감사 로그(`deploy.rollback`).
  - Deployments 목록에 성공 배포용 "롤백" 버튼.
  - 서비스 디렉터리 소유권(10001)이 필요 — `hub service new`(root)가 자동 설정,
    아니면 409와 함께 chown 명령 안내.
- **컨테이너 수동 그룹핑 (2026-10-21)**:
  - `container_assignments` 테이블: 명시적 연결을 주기 동기화(이름 자동 매칭)보다 우선 적용.
  - `POST /orphans/attach`(다중 일괄), `POST /containers/{id}/detach`,
    `POST /services/{id}/auto-attach`(compose 프로젝트 단위). 모두 DB 연결만, 런타임 무변경.
  - 수동 컴포넌트는 required=False, 해제 시 자동 생성 컴포넌트를 정리해 자동매칭 부활 방지.
  - UI: Containers 다중 선택 툴바, ServiceDetail 수동/자동 배지·해제·프로젝트 일괄 연결.
  - HTTPS: Tailscale Serve로 `https://n100-pve-dev.tail7d413d.ts.net` 노출
    (Let's Encrypt 인증서). 기존 평문 `http://100.85.245.79:8421` 유지.

## 테스트 결과 (2026-10-21, 로컬 macOS 개발 머신)

| 게이트 | 명령 | 결과 |
|---|---|---|
| 백엔드 | `cd backend && uv run pytest` | **175 passed** (Phase 1: 52) |
| §19.6 기존 서비스 보호 | `uv run pytest tests/test_protection.py -v` | **skip** — 로컬 Docker Desktop 엔진 응답 없음 → **N100 서버에서 1 passed** (아래) |
| CLI | `cd cli && uv run pytest` | **36 passed** (Phase 1: 14) |
| 프론트엔드 테스트 | `npm run test --prefix frontend` | **48 passed (10 files)** (Phase 1: 30) |
| 프론트엔드 빌드 | `npm run build --prefix frontend` | **성공** (tsc 0 errors) |
| 배포 게이트 기본값 | `Settings().deploy_gate()` | **`(False, ...)` — 기본 잠금 확인** |

### 실제 환경 기동 검증 (Mock 아님)
- 백엔드를 실 Docker 데몬과 함께 기동 → `/api/v1/system/status`가 Docker 29.4.3 연결,
  **9 running / 10 stopped / 19 orphan**을 정확히 보고 (ENVIRONMENT-INVENTORY와 일치).
- `/containers` 19건, `/orphans` 19건, `/ports` 실제 바인딩 6건, `/resources/host`·`/containers`
  실측 수집, status.json 캐시 생성, MOTD 렌더, `hub status` 및 `hub status --json`(순수 JSON) OK.
- 프론트엔드 Vite dev 서버 → `/api` 프록시 → 백엔드 → Docker 전 구간 연결 확인.
- 배포 엔드포인트: 계획(`/deployments/plan`)은 동작, 실행(`/deployments`)은 기본 잠금으로
  `503 deploy_disabled` 확인.

### 기존 서비스 보호 확인
- 검증 전/후 Docker 컨테이너 **19개 동일**(동일 이름/프로젝트), 네트워크/볼륨 무변경.
- 보호 테스트가 만든 `hubtest-*` 컨테이너/네트워크는 스스로 정리됨 (잔여 0).
- 배포 실행기는 기본 잠금이므로 위 검증에서 어떤 컨테이너도 생성/재시작되지 않았다.

### N100 서버 배포 검증 (2026-10-21)
- 대상: `n100-pve-dev` (Ubuntu 24.04, tailnet 100.85.245.79), 브랜치 `phase2-3-deploy`
  (HEAD `0261d98`). 배포는 `docker compose ... up -d --build --force-recreate backend frontend`.
- 접속: HTTPS `https://n100-pve-dev.tail7d413d.ts.net` (Tailscale Serve → `:8421` nginx →
  `backend:8420`), Let's Encrypt 인증서(만료 2027-01-19). 평문 `http://100.85.245.79:8421` 유지.
- 헤드리스 Chrome 검증(모두 통과): 비밀번호 로그인, 사이드바 접기/펼치기 + 새로고침 유지
  (240px ↔ 56px), 원형 토글이 화면 세로 중앙(450/450), WebAuthn API 사용 가능,
  보안 탭의 비밀번호 변경/패스워드리스 카드, 잘못된 현재 비밀번호 거부(400, 세션 유지),
  7개 라우트 렌더, 콘솔 오류 0.
- **CDP CTAP2 가상 인증기로 패스키 등록 → 로그아웃 → 패스키 로그인 → 세션 발급**까지 검증.
  검증용 자격증명은 삭제해 잔여 0으로 정리했다.
- 기존 assetnest 컨테이너 4개 ID는 배포 전후 동일(무변경).
- 수동 그룹핑 실서버 검증: UI에서 미관리 컨테이너 2개 선택 → 서비스 연결 → 상세에서
  수동 배지 확인 → 1건 해제. **15초 모니터 동기화 후에도 연결 유지** 확인.
  검증용 서비스/연결은 모두 삭제해 레지스트리·미관리 수(7)를 원상복구했다.

### 최종 상태 배포 (2026-10-23, N100 — `b5a93d6`)
- 저장소 최신 커밋(`b5a93d6`) 기준으로 `docker compose up -d --build --force-recreate` 수행.
- 게이트: backend 177 passed / CLI 36 / MCP 22 / frontend 55 (build OK).
- 결과: `hub-backend` healthy, `hub-frontend` Up, 대시보드 HTTP 200,
  `/services/spec/guide`·`/images` → 401(인증 요구 = 라우터 배포 확인).
- 설정: `enable_deploy=true`(배포 가능), `enable_docker_actions=false`(컨테이너 조작 잠김),
  `deploy_snapshot_dir=/data/deploy-snapshots`.
- 데이터: services 4 / containers 12 / api_keys 3 / deployments 19 / events 34 / audit_logs 90.
- **기존 서비스 보존**: assetnest 컨테이너 6개 ID 전부 동일(재생성 없음)
  (`0658bb58ed30` mongo, `281a5ffa17c0` trade-api, `b97010895241` collector,
  `e6a755b025ae` trade-rule-server, `f64e1ca4f4cb` server, `fe9f09aaabef` dashboard).
  볼륨 `assetnest-mongo-data`·`assetnest-certbot-www` 유지.
- 참고: 볼륨/네트워크 **목록 md5는 변경**됐다 — 허브 배포가 아니라 신규 서비스
  (`flow-plan`, `pianosync`)의 볼륨/네트워크가 추가된 결과다. assetnest 자원은 그대로다.

### 배포 잠금 해제 (2026-10-22, N100)
- 사용자 승인 후 `/srv/service-hub/.env`의 `HUB_ENABLE_DEPLOY=false` → `true`로 변경하고
  백엔드를 재기동했다. 백업: `/srv/service-hub/.env.bak-20261021-172317`.
- 컨테이너 내부 env 확인: `HUB_ENABLE_DEPLOY=true`.
- API 검증 (임시 API 키, 검증 후 삭제):
  - `POST /deployments/plan` → `200 READY` (변경 1건, DB 쓰기 없음)
  - `POST /deployments {"service_id": ...}` (존재하지 않는 디렉터리) →
    `422 spec_file_not_found` — **503 deploy_disabled가 아님 = 게이트 통과 확인**
  - 배포 레코드 증가 없음, 감사 로그 주체 `apikey:<이름>` 기록 확인
- 기존 컨테이너/볼륨/네트워크 무변경 (md5 동일). hub-backend healthy.
- **주의(배포 경로 규칙)**: 실행기는 `HUB_DEPLOY_WORKDIR/<service_id>`
  (= `/srv/services/<service_id>`)에서 `compose.yaml`을 찾는다. 등록 시 입력한
  `deployment_path`는 표시용 메타데이터이며 실행 경로를 바꾸지 않는다.
  따라서 실제 배포가 되려면 호스트에 `/srv/services/<service-id>/compose.yaml`이 있어야 한다.

### N100 서버 배포 검증 (2026-10-22, MCP/API 키 포함)
- 커밋 `be24ece` 배포: `api_keys` 테이블 자동 생성 확인, 대시보드 200, `GET /apikeys`
  무인증 → `401 unauthorized` 확인.
- MCP 서버를 tailnet URL로 실제 서버에 연결해 검증:
  - `hub_status` → `n100-pve-dev` / Linux 6.8 정상 응답
  - `hub_containers_list` → 8개 (assetnest 6 + hub 2)
  - `hub_orphans_list` → 6개 (서비스 미등록 상태)
  - `hub_service_register(dry_run)` → 페이로드 변환 확인 (DB 미변경)
  - `hub_deploy_apply` → `503 deploy_disabled` (잠금 정상 동작)
  - 검증용 키는 폐기 후 `401 unauthorized` 재확인 완료
- 기존 서비스 보존: assetnest-* 컨테이너 6개 무변경, 볼륨 md5 `1d98df79…` /
  네트워크 md5 `0e96287e…` 동일.

### N100 서버 배포 검증 (2026-10-22, 인벤토리 정리 포함)
- 커밋 `5faa01d` 배포 후 인벤토리가 **자동 정리**되어 컨테이너 행이 40 → **8**로 줄었다
  (실제 Docker 컨테이너 수와 일치: assetnest 6 + hub 2). 이전 인스턴스/테스트 컨테이너
  행( hubtest-* 등 )이 모두 제거됨.
- 배포 전/후 assetnest-* 6개 컨테이너 스냅샷 diff 없음, 볼륨 md5 `1d98df79…` /
  네트워크 md5 `0e96287e…` 동일.
- **주의(표기 차이)**: `docker ps`는 `assetnest-server`·`assetnest-trade-api`를
  "Up 12 hours"로 표시하지만, `docker inspect` 기준 실제로는 `exited`(ExitCode 255,
  기동 0.6초 후 종료)다. 허브 인벤토리는 **inspect 기준**을 저장하므로 대시보드에는
  "exited"로 정상 표시된다(허브 쪽 오류 아님).

### 실제 배포 실행 검증 (2026-10-22, 최초)
- `HUB_ENABLE_DEPLOY=true` 상태에서 **실제 컨테이너 생성까지** 검증했다.
  - 준비: `/srv/services/hubtest-deploy/{service.yaml,compose.yaml}` (alpine 1개, 포트 없음)
  - `POST /deployments/plan` → **READY** (changes: `web` create, Compose syntax PASS)
  - `POST /deployments {"service_id":"hubtest-deploy","confirmed":true}` →
    `202` **status=succeeded** (`finished_at` 기록)
  - 서버 확인: `hubtest-deploy-web` **Up**, compose project `hubtest-deploy` / service `web`
  - 인벤토리 판정: `managed`, component `web`, 서비스 상태 **healthy** (1/1 running)
- 이 과정에서 **라벨 오분류 버그**를 발견해 수정(`ab7b1fd`): `com.hub.managed`만 붙은
  일반 컨테이너가 허브 자신(hub-self)으로 분류되어 서비스가 `missing`으로 표시됐다.
  자기 식별을 `com.hub.self`로 한정하고 회귀 테스트를 추가했다.
- 검증 후 `compose down` + 서비스 레코드/디렉터리/임시 API 키 삭제. assetnest 컨테이너
  ID 불변, `/srv/services` 원상복구.
- **롤백 실서버 검증(2026-10-22)**: v1 배포 → compose를 v2로 수정·배포 → v1 배포 시점으로
  롤백 → 파일(`compose.yaml`)이 v1로 복원되고 컨테이너 로그도 `version-v1`로 재기동 확인.
  롤백도 새 배포 레코드(`dep-*`)로 남았다. 검증 데이터는 모두 정리.
- CLI 원격 인증도 검증: `HUB_API_KEY` 없으면 401 안내, 키 사용 시
  `HUB_URL=http://<tailnet-ip>:8420/api/v1 hub status` 정상(`n100-pve-dev`, Docker connected).

### N100 서버 배포 검증 (2026-10-21, 관리자 초기화 포함)
- 브랜치 `phase2-3-deploy` HEAD `1c82ae4` → 서버 `git pull --ff-only` →
  `docker compose --env-file /srv/service-hub/.env up -d --build` 성공
  (hub-backend healthy, hub-frontend up).
- **기존 서비스 보호**: 배포 전/후 assetnest-* 6개 컨테이너 스냅샷(이름·상태·포트·이미지)
  diff 없음, 볼륨 md5 `1d98df79…` / 네트워크 md5 `0e96287e…` 동일(배포 전과 동일).
- **§19.6 보호 테스트를 N100 서버에서 실제 Docker 데몬으로 실행 → 1 passed**
  (테스트 컨테이너/네트워크 잔여 0). 서버 이미지에는 `HUB_BIND=0.0.0.0`이 baked-in
  되어 있어 테스트 실행 시 `HUB_BIND=127.0.0.1`로 맞춰 실행해야 한다(로컬/CI와 동일).
- **관리자 초기화 실행**: 컨테이너 내부 루프백(`docker exec hub-backend` → 127.0.0.1)으로
  `POST /api/v1/auth/reset-admin` → `{"ok":true,"reset":true,"username":"admin",
  "setup_required":true}`. 공개 URL `GET /api/v1/setup/status` → `{"setup_required":true}`
  (설정 마법사 표시), 감사 로그 `auth.admin_reset`(actor `loopback:127.0.0.1`) 기록 확인,
  admin 행/WebAuthn 자격 증명 삭제 확인.
- 서버 CLI(`hub`, uv tool 편집 가능 설치) 확인: `hub admin reset --help` 정상,
  API 모드는 비루프백+무토큰에서 `403 reset_not_allowed`(종료 코드 4)로 거절,
  오프라인 모드(`--db`)는 실제 볼륨 DB를 읽어 "관리자 없음"(종료 코드 5)을 보고.

## 알려진 문제 / 확인 필요- **N100 배포 검증 범위** — 2026-10-21 배포 후 인증/UI/WebAuthn/HTTPS 경로는 N100에서
  재검증했다(위 "N100 서버 배포 검증"). 아래 배포 실행(apply) 관련 한계는 그대로 남아 있다.
- 배포 실행(apply)은 2026-10-22 N100에서 **실제 컨테이너 생성까지 검증 완료**
  (위 "실제 배포 실행 검증"). 실제 사용자 서비스 배포는 아직 수행하지 않았다.
- 온도 센서(`temperature_c`)는 Linux (`coretemp`/`cpu_thermal`)에서만 값이 나옴 — macOS는 `null`.
- Traefik 연동, 배포 롤백 자동화, 헬스체크 고도화는 미구현(문서화만).
- MOTD 백업/복원 실기능은 Linux에서만 동작.
- 세션은 인메모리 저장 → 백엔드 재시작 시 로그아웃됨 (Phase 1 허용, 문서화됨).

## 남은 작업
- Phase 3 잔여: Traefik 프록시 연결, 배포 롤백, 실환경 헬스체크 강화.
- Phase 4: 권한 강화, 백업/복구, 추세 분석.

## 다음 실행 단계
- **N100 관리자 계정 생성 대기** — 관리자 초기화로 서버에 관리자가 없다.
  `https://n100-pve-dev.tail7d413d.ts.net` 접속 → 설정 마법사에서 관리자 계정 생성
  (비밀번호 8자 이상). 원격 `hub admin reset`이 필요하면 `.env`에
  `HUB_ADMIN_RESET_TOKEN`을 설정하고 백엔드를 재기동한 뒤 사용(1회 사용).
- 배포 실행 검증은 완료됐다. 다음은 **실제 사용자 서비스 1건**을 `/srv/services/<id>`에
  준비해 plan → apply → 상태 확인 순으로 배포하는 것.
- 다음 UX 후보: 서비스 상세에서 컴포넌트를 직접 편집(그룹핑 결과를 서비스 정의로 승격).
