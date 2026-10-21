# IMPLEMENTATION STATUS

최종 갱신: 2026-10-21 (Phase 2 + Phase 3 apply — 로컬 검증 완료)

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
  - HTTPS: Tailscale Serve로 `https://n100-pve-dev.tail7d413d.ts.net` 노출
    (Let's Encrypt 인증서). 기존 평문 `http://100.85.245.79:8421` 유지.

## 테스트 결과 (2026-10-21, 로컬 macOS 개발 머신)

| 게이트 | 명령 | 결과 |
|---|---|---|
| 백엔드 | `cd backend && uv run pytest` | **107 passed** (Phase 1: 52) |
| §19.6 기존 서비스 보호 | `uv run pytest tests/test_protection.py -v` | **1 passed (실제 Docker 데몬 사용, skip 아님)** |
| CLI | `cd cli && uv run pytest` | **21 passed** (Phase 1: 14) |
| 프론트엔드 테스트 | `npm run test --prefix frontend` | **42 passed (8 files)** (Phase 1: 30) |
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

## 알려진 문제 / 확인 필요
- **N100 배포 검증 범위** — 2026-10-21 배포 후 인증/UI/WebAuthn/HTTPS 경로는 N100에서
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
- 배포 실행 검증은 `HUB_ENABLE_DEPLOY` 잠금 해제 승인 후, 사용하지 않는 테스트 서비스로
  `hub deploy plan → apply → status → 실제 상태 재조회` 순서로 수행한다.
- 남은 UX 요청: 컨테이너 수동 그룹핑(여러 컨테이너를 한 서비스로 묶기) — 현재는
  `POST /orphans/{id}/attach`로 1개씩 연결만 가능하다.
