# IMPLEMENTATION STATUS

최종 갱신: 2026-10-21 (Phase 1 — 로컬 검증 완료)

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
- 배포 실행 경로는 `HUB_ENABLE_DEPLOY=false`로 잠김 (Phase 3).

## 테스트 결과 (2026-10-21, 로컬 macOS 개발 머신)

| 게이트 | 명령 | 결과 |
|---|---|---|
| 백엔드 | `cd backend && uv run pytest` | **52 passed** |
| §19.6 기존 서비스 보호 | `uv run pytest tests/test_protection.py -v` | **1 passed (실제 Docker 데몬 사용, skip 아님)** |
| CLI | `cd cli && uv run pytest` | **14 passed** |
| 프론트엔드 테스트 | `npm run test --prefix frontend` | **30 passed (6 files)** |
| 프론트엔드 빌드 | `npm run build --prefix frontend` | **성공** (tsc 0 errors, 471 kB js / 34.6 kB css) |

### 실제 환경 기동 검증 (Mock 아님)
- 백엔드를 실 Docker 데몬과 함께 기동 → `/api/v1/system/status`가 Docker 29.4.3 연결,
  **9 running / 10 stopped / 19 orphan**을 정확히 보고 (ENVIRONMENT-INVENTORY와 일치).
- `/containers` 19건, `/orphans` 19건, `/ports` 실제 바인딩 6건, `/resources/host`·`/containers`
  실측 수집, status.json 캐시 생성, MOTD 렌더, `hub status` 및 `hub status --json`(순수 JSON) OK.
- 프론트엔드 Vite dev 서버 → `/api` 프록시 → 백엔드 → Docker 전 구간 연결 확인.
- 배포 엔드포인트(`/deployments/plan`, `/deployments`) → 인증 필요 + `deploy_disabled` 확인.

### 기존 서비스 보호 확인
- 검증 전/후 Docker 컨테이너 **19개 동일**(동일 이름/프로젝트), 네트워크/볼륨 무변경.
- 보호 테스트가 만든 `hubtest-*` 컨테이너/네트워크는 스스로 정리됨 (잔여 0).

## 알려진 문제 / 확인 필요
- **실제 N100(Linux) 서버 미검증** — 아래 모든 결과는 macOS 개발 머신의 로컬 검증이다.
  로컬/개발 검증 ≠ 서버 검증. N100 배포 후 재검증 필요.
- 온도 센서(`temperature_c`)는 Linux (`coretemp`/`cpu_thermal`)에서만 값이 나옴 — macOS는 `null`.
- Traefik 연동, 배포 실행기는 Phase 3 범위.
- MOTD 백업/복원 실기능은 Linux에서만 동작.
- 세션은 인메모리 저장 → 백엔드 재시작 시 로그아웃됨 (Phase 1 허용, 문서화됨).

## 남은 작업
- Phase 2: service.yaml 검증 워크플로우, AI 규칙 파일
- Phase 3: 배포 계획/실행기/헬스체크/Traefik
- Phase 4: 권한 강화, 백업/복구, 추세 분석

## 다음 실행 단계
- N100 서버 배포 후 `docs/SECURITY.md` 절차에 따라 실환경 재검증 (§19.6 포함).
