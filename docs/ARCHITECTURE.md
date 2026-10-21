# ARCHITECTURE (Phase 0)

## 1. 구성 요소

```
n100-service-hub/  (배포: docker compose, 개발: 로컬 프로세스)
├── backend/       FastAPI 애플리케이션 (단일 백엔드, 모듈화)
│   ├── app/main.py            앱 팩토리, 라우터 등록, 라이프사이클
│   ├── app/config.py          pydantic-settings (HUB_* 환경변수)
│   ├── app/db.py              SQLite(WAL) 엔진/세션
│   ├── app/models.py          SQLAlchemy 모델 (§16 테이블)
│   ├── app/schemas.py         Pydantic API/서비스정의 스키마
│   ├── app/docker_client.py   Docker SDK 래퍼 (연결 실패 → DockerUnavailable)
│   ├── app/monitor.py         백그라운드 폴링 루프 (기본 15s)
│   ├── app/routers/           system, services, containers, ports, orphans,
│   │                          resources, deployments, events, audit, settings
│   └── app/services/          inventory, portalloc, resource, deploy, events
├── cli/           hub CLI (FastAPI 백엔드에 HTTP로 접근, --json 지원)
├── frontend/      React + TS + Vite + Tailwind + shadcn/ui + Lucide
├── schemas/       service.schema.v1.json (Pydantic에서 내보냄)
├── templates/     신규 서비스 디렉터리 템플릿 (service.yaml 포함)
├── scripts/       install.sh, motd.sh (읽기 전용 캐시 사용), backup.sh
├── compose.yaml   hub 자체 배포 (backend + traefik 선택)
└── tests/         pytest (백엔드/CLI), Vitest (프론트)
```

## 2. 핵심 설계 결정

1. **자기 자신 보호**: hub 자신의 컨테이너는 compose label `hub.managed=true`로 식별하고 미관리 목록에서 제외하며, 어떤 경우에도 배포/삭제 대상에서 제외한다(하드 블록).
2. **Docker 래퍼 하나만**: 모든 Docker 접근은 `docker_client.py`를 통과. 컨테이너 실행/삭제/재시작 함수는 runner 모듈에만 존재하고 Phase 1에서는 비활성화 플래그(`HUB_ENABLE_DEPLOY=false` 기본)로 잠긴다.
3. **폴링 + 캐시**: Docker 이벤트 스트리밍 대신 폴링(15s)을 사용한다(안정성 우선). 마지막 정상 수집 시각은 `settings.last_monitor_ok_at`에 저장하고 API/CLI/MOTD에 노출한다.
4. **미관리 탐지 규칙**: 관리되는 컨테이너 = (서비스 컴포넌트에 등록된 매칭) ∪ (compose label 매칭). 나머지는 unmanaged. 추정 서비스는 compose project 이름과 이름 유사도로 힌트만 제시한다.
5. **포트 점유 확인**: Docker 포트 매핑(등록 vs 실제) + 소켓 바인딩 시도(127.0.0.1/0.0.0.0/::)의 교집합으로 판정. 예약은 DB 트랜잭션 + 고유 인덱스(proto, host_port, bind_addr)로 충돌 방지.
6. **MOTD**: `/var/run/hub/status.json` 캐시를 읽는 스크립트. Docker을 직접 호출하지 않는다. 캐시가 60초보다 오래되면 "STALE(마지막 갱신 시각)" 표시.
7. **트랜잭션**: SQLite WAL + `PRAGMA foreign_keys=ON`, 세션 단위 커밋.

## 3. API 계약 v1 (프론트/CLI 공통 기준)

기본 규칙: prefix `/api/v1`, JSON. 오류는 `{"detail": "...", "code": "..."}`. 시각은 전부 ISO 8601(로컬 오프셋 포함). `X-Request-Id` 헤더 응답.

### 시스템
- `GET /system/overview` → `{server:{hostname,os,kernel,uptime_seconds,booted_at},docker:{connected,server_version},resources:{cpu:{percent,cores},memory:{total_mb,used_mb,available_mb,percent},disk:{total_gb,used_gb,percent}},counts:{services,containers_running,containers_stopped,orphans},last_monitor_ok_at,recent_events:[Event]}`
- `GET /system/status` → 모니터 상태 + 데이터 최신성(CLI `hub status`용)
- `GET/PUT /system/settings` → 알림 임계값, 수집 주기, 허브 이름, bind 정책 등 (비밀 필드 미포함)

### 서비스
- `GET /services?search=&status=&category=` → 목록(각 항목: id, name, description, category, status, containers{total,running}, endpoints[], cpu_percent, memory_mb, last_deployed_at)
- `POST /services` (service.yaml 내용 또는 등록 폼) → 201
- `GET /services/{id}` → 상세(컴포넌트, 엔드포인트, 배포 정보, 경고)
- `PATCH /services/{id}` → 설명/문서/태그/임계값 수정
- `DELETE /services/{id}?confirm=<id>` → **DB 레코드만 삭제**, 컨테이너/볼륨 미변경 (응답에 `runtime_unchanged: true` 명시)
- `GET /services/{id}/containers|endpoints|logs?tail=200|events`

### 컨테이너/미관리
- `GET /containers?state=running|stopped|all&management=managed|unmanaged|mismatch|missing|unknown`
- `GET /containers/{id}` (상세: 이미지, 네트워크, 포트, 볼륨, stats, labels)
- `GET /orphans` → 미관리 목록(추정 서비스, 미관리 사유 포함)
- `POST /orphans/{cid}/attach` `{service_id, component_name}` → DB 연결만, 컨테이너 재생성 없음
- `POST /orphans/{cid}/review` `{review_state}`

### 포트
- `GET /ports` → PortRegistry 항목 전체(예약/실제/충돌/프록시 상태 포함)
- `GET /ports/available?count=5&range=8000-9000&protocol=tcp` → 후보 목록
- `POST /ports/reservations` `{service_id, component, host_port, protocol, bind_addr, container_port, exposure}` → 충돌 시 409
- `DELETE /ports/reservations/{id}`

### 자원
- `GET /resources/host` → CPU/메모리/디스크/네트워크/시스템 + 최근 추이(샘플)
- `GET /resources/containers` → 컨테이너별 stats
- `GET /resources/services` → 서비스별 집계
- `GET /resources/warnings` → 임계값 판정 경고

### 배포 (Phase 3)
- `POST /deployments/plan` (service.yaml 경로 또는 내용) → 검증 결과 + 변경 계획
- `POST /deployments` `{service_id, confirmed}` → `{deployment_id}` (비동기)
- `GET /deployments[?service_id=]`, `GET /deployments/{id}`, `GET /deployments/{id}/logs`

### 기타
- `GET /events?severity=&service_id=&limit=`
- `GET /audit-logs?limit=`
- `GET /search?q=` → 전역 검색(서비스/컨테이너/포트/도메인/이미지)
- `POST /auth/login`, `POST /auth/logout`, `GET /auth/session`
- `POST /setup/admin` (최초 1회 — 관리자 생성)

## 4. 데이터 모델 (요약)

services(id PK, name, description, category, status, repository_url, branch, deployment_type, deployment_path, compose_file, version, documentation, created_at, updated_at, last_deployed_at, last_healthcheck_at, tags_json, notes)
service_components(id PK, service_id FK, name, role, required, container_match_json, description) — UNIQUE(service_id, name)
containers(id PK=container_id, name, image, state, status, management_state, service_id FK nullable, component_name nullable, compose_project, compose_service, ports_json, networks_json, mounts_json, labels_json, started_at, created_at, restart_count, health, observed_at)
endpoints(id PK, service_id FK, name, type, exposure, hostname, container, container_port, enabled)
port_reservations(id PK, service_id FK, component, protocol, host_port, bind_addr, container_port, exposure, state, created_at) — UNIQUE(protocol, host_port, bind_addr)
deployments(id PK, service_id, status, requested_by, plan_json, error, started_at, finished_at)
deployment_steps(id PK, deployment_id FK, seq, name, status, detail, at)
resource_samples(id PK, ts, scope(host|container|service), scope_id, cpu_percent, mem_used_mb, mem_limit_mb, net_rx_bytes, net_tx_bytes, disk_used_gb, extras_json)
events(id PK, ts, severity, kind, service_id, container_id, message, detail_json)
audit_logs(id PK, ts, actor, action, target, detail_json)
settings(key PK, value_json, updated_at)

## 5. 모니터 파이프라인 (15s 주기)

1. Docker ping → 실패 시 `docker.connected=false`, 컨테이너 상태 unknown 처리, 이벤트 1회 기록(재발은 디바운스)
2. 컨테이너 목록 스냅샷 → management_state 판정 → containers 테이블 동기화
3. 포트 매핑 스냅샷 → port_reservations과 비교 → 충돌/불일치 플래그
4. 호스트 자원(1차: 현재값), 컨테이너 stats(별도 폴링 30s) → resource_samples
5. 임계값 판정 → 변경 시에만 events 기록(중복 경고 억제)
6. status.json 캐시 기록(MOTD/CLI용)

모니터 단계별 오류는 격리되어 다음 단계가 중단되지 않는다.

## 6. 포트 할당 절차 (§9.3 구현)

검증 → DB 예약 고유 인덱스(트랜잭션) → 소켓 바인딩 시도 확인 → Docker 매핑 비교 → 노출 정책 검사(DB: 포트 22, 8420 자기 자신 제외) → 예약 커밋. 배포 시(Phase 3) 실제 연결 확인 후 state 전이.
