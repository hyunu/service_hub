# N100 Service Hub — AI 에이전트 규칙

프로젝트 전체 요구사항: `docs/REQUIREMENTS.md`
배포/운영 규칙(반드시 따를 것): `AI-OPERATIONS.md`

## 핵심 원칙

1. **기존 Docker 서비스 보호 최우선.** 컨테이너/볼륨/이미지/네트워크/포트를 승인 없이 변경하지 않는다. `docker system prune` 등 정리 명령 금지.
2. 코드베이스에서 배포 실행 경로는 `HUB_ENABLE_DEPLOY=false` 잠금 상태가 기본이다. 잠금을 해제하려면 사용자 승인과 docs/SECURITY.md 확인 필요하다. 잠금이 열려 있어도 배포 실행기는 화이트리스트 작업(compose config/up/down + 헬스체크)만 수행하며, 임의 셸 실행 경로는 없다. 모든 배포는 감사 로그에 기록된다.
3. 관리 시스템의 Docker 접근은 `backend/app/docker_client.py` 하나로 통제된다. 다른 위치에서 Docker SDK/CLI 직접 호출을 추가하지 않는다.
4. 임의 셸 실행 API/엔드포인트를 추가하지 않는다.
5. 서비스 정의는 `schemas/service.schema.v1.json` (schema_version 1)을 따른다. 시크릿 값은 service.yaml에 넣지 않는다.
6. 시각 값은 ISO 8601로 출력한다. 알 수 없는 값을 임의의 정상값(0 등)으로 대체하지 않는다 — `null`과 N/A를 사용한다.
7. 문서만으로 안전해지지 않는다. 새로운 위험 작업 API를 추가할 때는 권한/승인 강제와 테스트를 함께 추가한다.

## 디렉터리Ownership

- `backend/` — FastAPI 백엔드
- `frontend/` — React 대시보드
- `cli/` — hub CLI
- `scripts/` — 설치/제거/백업/MOTD
- `schemas/`, `templates/` — 표준 서비스 정의
- `docs/` — 설계·상태 문서 (요구사항 변경 시 REQUIREMENTS.md부터 갱신)

## 테스트 게이트

- 백엔드: `cd backend && uv run pytest` — 특히 기존 서비스 보호 테스트(§19.6)가 실패하면 어떤 배포도 진행하지 않는다.
- 프론트엔드: `npm run test --prefix frontend`, `npm run build --prefix frontend`
- CLI: `cd cli && uv run pytest`
