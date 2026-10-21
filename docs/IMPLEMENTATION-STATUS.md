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
| 백엔드 | `cd backend && uv run pytest` | **128 passed, 1 skipped** (관리자 초기화 10건 추가. Phase 1: 52) |
| §19.6 기존 서비스 보호 | `uv run pytest tests/test_protection.py -v` | **skip** — 로컬 Docker Desktop 엔진 응답 없음 → **N100 서버에서 1 passed** (아래) |
| CLI | `cd cli && uv run pytest` | **28 passed** (관리자 초기화 7건 추가. Phase 1: 14) |
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
- **배포 실행(apply)은 어떤 환경에서도 실 컨테이너 생성까지 검증하지 않았다.** 테스트는
  Fake Docker 게이트웨이로 상태머신만 검증했고, 실 `docker compose up` 경로는 N100에서
  잠금 해제 후 최초 검증이 필요하다. 이 한계를 성공으로 보고하지 않는다.
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
- 배포 실행 검증은 `HUB_ENABLE_DEPLOY` 잠금 해제 승인 후, 사용하지 않는 테스트 서비스로
  `hub deploy plan → apply → status → 실제 상태 재조회` 순서로 수행한다.
- 다음 UX 후보: 서비스 상세에서 컴포넌트를 직접 편집(그룹핑 결과를 서비스 정의로 승격).
