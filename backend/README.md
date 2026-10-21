# backend/README.md — N100 Service Hub 백엔드

FastAPI + SQLite 기반 관리 API. Phase 1은 **읽기 전용**이며 배포 기능은 잠겨 있다
(`HUB_ENABLE_DEPLOY=false` 기본).

## 실행

```bash
cd backend
uv sync
HUB_DB_PATH=../data/hub.db HUB_STATUS_CACHE=../data/status.json \
  uv run uvicorn app.main:app --port 8420
```

- API 문서(OpenAPI): http://127.0.0.1:8420/docs , 스키마: `/openapi.json`
- 헬스체크: `/healthz`
- 최초 실행 시 `/api/v1/setup/status`가 `setup_required: true` → 관리자 생성 필요
  (기본 비밀번호 없음)

## 테스트

```bash
uv run pytest                 # 전체
uv run pytest tests/test_protection.py -v   # §19.6 기존 서비스 보호 테스트
```

보호 테스트는 실제 Docker 데몬에 `hubtest-protect` 컨테이너를 만들어 읽기 전용 수집이
컨테이너/포트/볼륨/네트워크를 변경하지 않음을 검증한다. 데몬이 없으면 skip된다 —
**skip은 서버 검증 성공이 아니다.**

## 구조

```
app/
├── main.py          앱 팩토리, 라우터 등록, lifespan(모니터)
├── config.py        HUB_* 설정
├── db.py            SQLite(WAL) 엔진/세션
├── models.py        §16 테이블
├── docker_client.py Docker 접근 단일 통로 (읽기 전용) + Fake 게이트웨이
├── dependencies.py  게이트웨이 주입
├── security.py      인증/세션/CSRF/마스킹
├── monitor.py       백그라운드 폴링 (15s) + status.json 캐시
├── services/        inventory, ports, resource, events
└── routers/         auth, system, services, containers, ports, resources, events
```

## 안전 제약

- 컨테이너 실행/중지/삭제/재시작 함수가 **없다** (Phase 1). 배포 실행기는 Phase 3에서
  별도 모듈로 추가되며 `HUB_ENABLE_DEPLOY`로 잠긴다.
- 임의 셸 실행 엔드포인트가 없다.
- 서비스 삭제는 DB 레코드만 지우고 `runtime_unchanged: true`를 반환한다.
