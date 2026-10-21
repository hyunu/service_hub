# IMPLEMENTATION PLAN (Phase 0)

## 우선순위 원칙
- Phase 1은 **읽기 전용**이다. 배포/삭제/재시작 코드 경로는 존재하더라도 기본 잠금(`HUB_ENABLE_DEPLOY=false`)에 의해 차단된다.
- 각 단계는 테스트와 함께 완료한다.

## Phase 0 — 환경 조사 및 설계 ✅
- [x] 개발 환경/기존 Docker 읽기 전용 조사 → ENVIRONMENT-INVENTORY.md
- [x] 아키텍처 + API 계약 → ARCHITECTURE.md
- [x] 보안 → SECURITY.md
- [x] 요구사항 기준 문서 → REQUIREMENTS.md

## Phase 1 — 읽기 전용 관리 기능 (현재)
작업 순서와 담당:

1. **백엔드 코어** (backend/)
   - [x] 프로젝트 셋업(pyproject, uv), config, db(WAL), models, 스키마
   - [x] docker_client 래퍼 (연결 실패 격리)
   - [x] 인벤토리 서비스: 컨테이너 스냅샷 → containers 테이블, management_state 판정, 미관리 탐지
   - [x] 서비스 레지스트리 CRUD (자기 자신 보호, 컨테이너 매칭)
   - [x] 포트 레지스트리: 현재 매핑 집계, 예약 CRUD(트랜잭션), 가용 포트 후보
   - [x] 자원 모니터: 호스트(macOS/Linux 분리)/컨테이너/서비스 집계, 임계값 경고
   - [x] 백그라운드 모니터 루프 + status.json 캐시
   - [x] 이벤트/감사 로그, 전역 검색, 인증(최초 관리자 설정 + 세션)
   - [x] pytest: 보호 테스트(§19.6) 포함 — 기존 컨테이너 무변경 검증
2. **프론트엔드** (frontend/)
   - [x] Vite+React+TS+Tailwind+shadcn/ui 셋업
   - [x] 전역 레이아웃(사이드바/상단바/검색), Overview, Services(목록+상세 탭), Containers, Ports & Routing, Deployments(목록), Resources, Events, Settings, Setup 마법사
   - [x] Vitest 컴포넌트 테스트
3. **CLI + MOTD + 템플릿** (cli/, scripts/, templates/, schemas/)
   - [x] `hub` CLI: status, service list/show, port list/available, orphan list, resource, logs, --json, 종료 코드
   - [x] MOTD 스크립트(캐시 전용, STALE 표시) + install/uninstall(백업/복원)
   - [x] 서비스 템플릿 + service.schema.v1.json 내보내기

## Phase 2 — 표준 서비스 등록
- [ ] service.yaml 스키마 v1 Pydantic 검증 + `hub service validate`
- [ ] 표준 서비스 디렉터리 템플릿 생성 명령
- [ ] 포트 예약과 배포 연계, 서비스 검증 워크플로우
- [ ] AI-OPERATIONS.md + AI 규칙 파일(.cursor/rules, AGENTS.md)

## Phase 3 — 표준 배포
- [ ] 배포 계획 생성(Compose diff, 포트/자원 검증)
- [ ] 배포 실행기(runner): 제한 작업만, 비동기 작업 상태머신
- [ ] 헬스체크, 프록시(Traefik) 라우팅 자동 구성, 이력
- [ ] 실패 처리/기록 (자동 롤백 범위 문서화)

## Phase 4 — 안전성 및 운영 고도화
- [ ] 권한 강화, CSRF 완전 적용, 감사 로그 UI
- [ ] DB 백업/복구 스크립트, 롤백 정책
- [ ] 자원 추세 분석(5분 롤업), 보안 테스트, 운영 문서

## 테스트 게이트
- §19.6 보호 테스트: 신규 미관리 컨테이너 생성 후 hub 인벤토리 수집 → 삭제/상태/포트/볼륨/네트워크 무변경 검증. **미통과 시 N100 설치 금지.**
- Docker 미연결 상태에서 API/CLI/MOTD가 graceful하게 동작하는 테스트.
