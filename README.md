# N100 Service Hub

N100 PC 한 대에서 운영하는 여러 Docker Compose 기반 서비스를 통합 관리하는 웹 플랫폼.
기존 Docker 환경을 **읽기 전용으로 보호**하면서 서비스 등록, 포트 관리, 자원 모니터링,
미관리 컨테이너 탐지, 표준 배포 인터페이스를 제공한다.

- 요구사항 기준 문서: [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md)
- AI 코딩 도구 배포 규칙: [AI-OPERATIONS.md](AI-OPERATIONS.md)
- 무인 배포 운영 가이드: [docs/UNATTENDED-DEPLOY.md](docs/UNATTENDED-DEPLOY.md)
- 설계/보안/현황: [docs/](docs/) — 구현 상태는 [docs/IMPLEMENTATION-STATUS.md](docs/IMPLEMENTATION-STATUS.md)

## 구성

| 경로 | 내용 |
|---|---|
| `backend/` | FastAPI + SQLite 백엔드 (Docker 인벤토리, 레지스트리, 모니터, API) |
| `frontend/` | React + TypeScript + Vite + Tailwind + shadcn/ui 대시보드 |
| `cli/` | `hub` CLI (사람용/JSON 출력, 종료 코드 구분) |
| `mcp-server/` | MCP 서버 — AI 에이전트가 서비스 등록·연결·배포 요청 |
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

비밀번호를 잊어 로그인이 안 되면 `hub admin reset --yes`로 관리자 자격 증명만 초기화한다
(서비스/포트/컨테이너 데이터는 유지, 기존 세션 무효화 → 설정 마법사가 다시 나타난다).
자세한 절차는 [AI-OPERATIONS.md §7](AI-OPERATIONS.md) 참고.

## AI 에이전트 연동 (MCP)

AI 코딩 도구가 개발 결과를 허브에 직접 등록·배포 요청할 수 있다.

```bash
# 1) 대시보드 Settings → API 키 에서 키 발급 (평문은 1회만 표시)
# 2) MCP 서버 실행 (stdio)
cd mcp-server && uv sync && uv run hub-mcp --print-config
```

```json
{
  "mcpServers": {
    "n100-service-hub": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/service_hub/mcp-server", "hub-mcp"],
      "env": { "HUB_URL": "http://127.0.0.1:8420/api/v1", "HUB_API_KEY": "hub_..." }
    }
  }
}
```

제공 도구: 상태/서비스/컨테이너/포트 조회, `service.yaml` 등록, 미관리 컨테이너 연결,
배포 계획/실행/상태. 배포는 기존 잠금(`HUB_ENABLE_DEPLOY`)을 그대로 따른다.
자세한 내용: [mcp-server/README.md](mcp-server/README.md), [AI-OPERATIONS.md §8](AI-OPERATIONS.md).

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
cd mcp-server && uv run pytest   # MCP 도구/변환 로직
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
