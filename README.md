# N100 Service Hub

N100 PC 한 대에서 운영하는 여러 Docker Compose 기반 서비스를 통합 관리하는 웹 플랫폼.
기존 Docker 환경을 **읽기 전용으로 보호**하면서 서비스 등록, 포트 관리, 자원 모니터링,
미관리 컨테이너 탐지, 표준 배포 인터페이스를 제공한다.

- 요구사항 기준 문서: [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md)
- AI 코딩 도구 배포 규칙: [AI-OPERATIONS.md](AI-OPERATIONS.md)
- 설계/보안/현황: [docs/](docs/) — 구현 상태는 [docs/IMPLEMENTATION-STATUS.md](docs/IMPLEMENTATION-STATUS.md)

## 구성

| 경로 | 내용 |
|---|---|
| `backend/` | FastAPI + SQLite 백엔드 (Docker 인벤토리, 레지스트리, 모니터, API) |
| `frontend/` | React + TypeScript + Vite + Tailwind + shadcn/ui 대시보드 |
| `cli/` | `hub` CLI (사람용/JSON 출력, 종료 코드 구분) |
| `scripts/` | install.sh / uninstall.sh / backup.sh / motd.sh |
| `schemas/`, `templates/` | 표준 서비스 정의 스키마와 신규 서비스 템플릿 |
| `compose.yaml` | 관리 시스템 자체 배포 (Docker 소켓은 backend에만 마운트) |

## 개발 (로컬)

```bash
# 백엔드 (기본 127.0.0.1:8420, 배포 기능 잠금: HUB_ENABLE_DEPLOY=false)
cd backend && uv sync && HUB_DB_PATH=../data/hub.db HUB_STATUS_CACHE=../data/status.json \
  uv run uvicorn app.main:app --port 8420

# 프론트엔드 (개발 서버, /api → 8420 프록시)
cd frontend && npm install && npm run dev    # http://localhost:5173

# CLI (별도 터미널)
cd cli && uv sync && uv run hub status
```

최초 접속 시 관리자 계정을 생성한다. **기본 비밀번호는 존재하지 않는다.**

## 서버 설치 (N100, Linux)

```bash
sudo ./scripts/install.sh --prefix /srv/service-hub --port 8420
```

설치 스크립트는 다음만 수행한다: 환경 확인(읽기 전용), 포트 충돌 검사, 디렉터리/설정 생성,
CLI 설치, MOTD 설치(기존 설정 백업), 기동, 헬스체크, **설치 전후 컨테이너 스냅샷 보존 검증**.
기존 컨테이너/볼륨/네트워크/포트는 변경하지 않는다. 제거 시 `scripts/uninstall.sh`가
MOTD를 원래 상태로 복원한다.

## 테스트

```bash
cd backend  && uv run pytest     # 서비스/포트/컨테이너/자원/인증 + 기존 서비스 보호 테스트(§19.6)
cd frontend && npm run test && npm run build
cd cli      && uv run pytest
```

**게이트:** 기존 서비스 보호 테스트(신규 미관리 컨테이너 생성 → 인벤토리 수집 후
컨테이너/포트/볼륨/네트워크 무변경 검증)가 실패하면 실제 서버에 설치하지 않는다.

## 안전 정책 요약

- Docker 소켓은 백엔드에만 마운트. 프런트엔드/외부 서비스 금지.
- 임의 셸 실행 API 없음. 배포는 검증을 거친 제한 작업만 (Phase 3).
- 서비스 삭제 API는 관리 DB 레코드만 삭제하고 컨테이너/볼륨은 건드리지 않는다.
- 관리 UI 포트(8420)는 기본 루프백 바인드. 외부 노출 시 방화벽 필수.
- 상세 위험 모델과 통제: [docs/SECURITY.md](docs/SECURITY.md)

## 주의

현재까지의 검증은 개발 환경(macOS)에서 수행되었다. 실제 N100(Linux)에서의 검증은
별도로 수행되어야 하며, 로컬/Mock 검증 성공이 서버 검증 성공을 의미하지 않는다.
