# N100 Service Hub — 전체 개발 요구사항 (기준 문서)

AI 기반 개인 서버 통합 관리 플�랫폼 개발 명세서.
이 문서는 본 프로젝트의 요구사항 기준 문서다. 모든 설계·구현·테스트는 이 문서를 따른다.

---

## 1. 프로젝트 목표

N100 PC 한 대에서 운영하는 다양한 Docker 기반 서비스를 통합 관리하는 웹 플랫폼을 개발한다.

현재 및 향후 운영할 서비스 유형: 웹 프런트엔드, 백엔드 API, 데이터베이스, AI 애플리케이션, 자동화 서비스, 미디어 서버, 개발/테스트 환경, 기타 Docker Compose 기반 애플리케이션.

핵심 목표 — 서비스가 늘어도 다음 문제가 발생하지 않도록 한다.

1. 어떤 서비스가 설치되어 있는지 파악하기 어렵다.
2. 각 컨테이너가 어떤 서비스에 속하는지 알기 어렵다.
3. 포트 번호와 실제 서비스의 관계를 파악하기 어렵다.
4. 서비스의 목적, 배포 위치, 실행 방법을 시간이 지난 뒤에도 파악하기 어렵다.
5. 관리 시스템을 거치지 않고 생성된 컨테이너를 발견하기 어렵다.
6. 서버 자원이 얼마나 남아 있는지 판단하기 어렵다.
7. AI 코딩 도구가 기존 서버 구성을 모르고 임의로 포트를 할당하거나 배포할 수 있다.
8. 새로운 서비스를 배포할 때마다 서로 다른 방식으로 구성하게 된다.
9. 기존 서비스를 변경하거나 재배포할 때 다른 서비스에 영향을 줄 위험이 있다.

해결책: 서비스 등록, 컨테이너 관리, 포트 관리, 자원 모니터링, 표준 배포, AI 연동을 제공하는 통합 관리 플랫폼.

프로젝트 이름은 **N100 Service Hub**이며, 이름은 설정으로 변경 가능해야 한다.

## 2. 개발 원칙

### 2.1 기존 서비스 보호

기존 Docker 환경을 최우선으로 보호한다. 초기 설치 및 조사 과정에서는 기존 서비스의 상태를 변경하지 않는다.

명시적 승인 없이 금지되는 작업:
- 기존 컨테이너 삭제/재생성/재시작
- 기존 포트 변경
- 기존 Docker 네트워크 변경
- 기존 볼륨 삭제 또는 변경
- 기존 이미지 삭제
- Docker 시스템 정리 (`docker system prune`, `docker volume prune`, `docker compose down -v` 등)
- 기존 서비스 설정 파일 수정
- 기존 서비스 실행 방식 변경

초기 설치 시 기존 Docker 컨테이너/이미지/네트워크/볼륨/포트 매핑/Compose 프로젝트를 **읽기 전용**으로 조사한다.
관리 정보가 불완전하더라도 기존 컨테이너를 자동 재배포하지 않는다.

### 2.2 관리 시스템과 실제 상태의 분리

세 가지 정보를 분리해서 관리한다.
1. **Service Registry**: 서비스의 목적, 설명, 소속 컨테이너, 접속 주소, 배포 정보
2. **Docker Runtime**: 실제 컨테이너, 이미지, 실행 상태, 네트워크, 포트, 자원 사용량
3. **Port Registry**: 포트 예약, 서비스 연결, 공개 범위, 충돌 상태

등록 정보만으로 실제 서비스가 정상이라고 판단하지 않는다. Docker에 컨테이너가 있다는 이유만으로 관리 대상이라고 판단하지 않는다. 주기적으로 실제 상태를 조회해 등록 정보와 비교한다.

### 2.3 AI 친화적 설계

모든 주요 관리 기능은 웹 UI 외에도 CLI와 구조화된 API로 제공한다. AI 코딩 도구가 화면을 분석하거나 마우스를 조작하지 않아도 다음이 가능해야 한다.

- 현재 서버 상태 조회, 서비스 목록/상세 조회
- 사용 중인 포트 조회, 사용 가능한 포트 후보 조회
- 신규 서비스 등록 가능 여부 확인
- 배포 계획 생성, 배포 실행, 배포 결과 확인
- 로그 조회, 자원 상태 조회, 미관리 컨테이너 조회

CLI 결과는 사람이 읽는 형식과 JSON 형식을 모두 지원한다. AI가 임의 Docker 명령을 실행하는 방식보다 표준 CLI/API 사용을 우선한다.

### 2.4 단순성과 유지보수성

N100의 제한된 자원을 고려한다. 불필요하게 무거운 마이크로서비스를 도입하지 않는다. 관리 시스템 자체는 모듈화된 단일 백엔드 애플리케이션으로 구현한다.
초기 버전에서 Kubernetes, Elasticsearch, 별도 메시지 브로커, 복잡한 분산 모니터링은 도입하지 않는다.
서비스 메타데이터는 SQLite에 저장한다. Docker Compose 기반으로 설치·운영한다.

## 3. 기술 스택

| 영역 | 기술 |
|---|---|
| 프런트엔드 | React + TypeScript |
| UI 빌드 | Vite |
| UI 스타일 | Tailwind CSS |
| UI 컴포넌트 | shadcn/ui |
| 아이콘 | Lucide |
| 백엔드 | Python + FastAPI |
| 데이터 검증 | Pydantic |
| 데이터베이스 | SQLite |
| DB 마이그레이션 | Alembic |
| Docker 제어 | Docker SDK for Python 또는 Docker Engine API |
| 컨테이너 실행 정의 | Docker Compose |
| 리버스 프록시 | Traefik |
| 시스템 자원 수집 | Linux /proc, 표준 시스템 정보, Docker Stats API |
| Python 테스트 | pytest |
| 프런트엔드 테스트 | Vitest |
| API 문서 | OpenAPI |
| 서비스 관리 CLI | Python 기반 CLI |
| 배포 | Docker Compose |

스택 변경 필요 시 이유와 장단점을 먼저 문서화한다. N100 자원 사용량, 설치 편의성, AI 도구 호환성을 기준으로 결정한다.

## 4. 시스템 구성

### 4.1 Web Dashboard
서버 현황, 서비스 목록/상세, 컨테이너 목록, 포트 관리, 미관리 컨테이너 관리, 자원 모니터링, 배포 관리, 이벤트/배포 이력, 시스템 설정.

### 4.2 Backend API
모듈: Service Registry, Docker Inventory, Port Registry, Deployment Manager, Resource Monitor, Health Monitor, Event Manager, Authentication/Authorization, Audit Log, AI Integration API.

### 4.3 Background Monitor
주기 수집: 컨테이너 실행 상태, 컨테이너-서비스 관계, 포트 매핑, Docker 이벤트, CPU/메모리/디스크/네트워크 사용량, 헬스체크 결과, 등록 정보와 실제 상태의 불일치.
기본 수집 주기 15초(설정 변경 가능). 모니터링 오류가 웹페이지 중단을 초래하지 않아야 한다. 마지막 정상 수집 시각과 데이터 최신성을 표시한다.

### 4.4 CLI (`hub`)
주요 명령:
```
hub status
hub service list
hub service show <service-id>
hub service validate <path>
hub port list
hub port available
hub orphan list
hub resource
hub logs <service-id>
hub deploy plan <path>
hub deploy apply <service-id>
hub deploy status <deployment-id>
```
각 명령은 도움말과 사용 예제를 제공한다. `--json` 옵션을 지원한다 (`hub status --json` 등).
JSON 출력에는 사람용 설명 문구나 로그를 섞지 않는다. 오류는 표준 오류 스트림, 종료 코드 구분.

## 5. 서비스 관리 모델

### 5.1 서비스와 컨테이너의 관계
서비스는 하나 이상의 컨테이너로 구성될 수 있고, 컨테이너가 없는 상태도 허용한다.
예: AI Platform → frontend, backend, worker, postgres.
소속은 관리 시스템 내부 고유 서비스 ID + 구성요소 이름 기준. Docker Label과 Compose 프로젝트 정보를 활용해 실제 컨테이너를 식별한다.

### 5.2 Service Registry 데이터 모델

| 필드 | 필수 | 설명 |
|---|---|---|
| id | 예 | 고유 서비스 ID (영문 소문자/숫자/하이픈, 중복 불가) |
| name | 예 | 서비스 이름 |
| description | 예 | 서비스 목적 및 설명 (한국어 지원) |
| category | 예 | 서비스 분류 |
| status | 자동 | 실제 운영 상태 |
| repository_url | 아니오 | Git 저장소 |
| repository_branch | 아니오 | 배포 브랜치 |
| deployment_type | 예 | Docker Compose 등 |
| deployment_path | 예 | 서비스 디렉터리 |
| compose_file | 예 | Compose 파일 위치 |
| version | 아니오 | 서비스 버전 |
| created_at / updated_at | 자동 | 생성/수정 시각 |
| last_deployed_at | 자동 | 마지막 배포 시각 |
| last_healthcheck_at | 자동 | 마지막 헬스체크 |
| documentation | 아니오 | 추가 문서 위치 |
| tags | 아니오 | 검색용 태그 |

예시 ID: `ai-platform`, `home-assistant`, `media-server`.
서비스 설명에는 목적, 주요 기능, 사용자, 외부 접속 방법, 주요 컨테이너 역할, 데이터 저장 위치, 백업 방법, 운영상 주의사항, 개발/수정 방법을 기록할 수 있다.
이미지/컨테이너 이름만으로 설명을 추측해서 확정하지 않는다. 추정 정보는 추정으로 표시한다.

## 6. 표준 서비스 정의 파일 (service.yaml)

모든 신규 관리 대상 서비스는 service.yaml을 사용한다.

```yaml
schema_version: 1
service:
  id: sample-app
  name: Sample Application
  description: 샘플 웹 애플리케이션
  category: web
  version: "1.0.0"
source:
  repository_url: ""
  branch: main
deployment:
  type: docker-compose
  compose_file: compose.yaml
endpoints:
  - name: frontend
    type: http
    exposure: proxy
    hostname: sample.home
    container: frontend
    container_port: 3000
  - name: backend
    type: http
    exposure: internal
    container: backend
    container_port: 8000
containers:
  - name: frontend
    role: frontend
    required: true
  - name: backend
    role: backend
    required: true
resources:
  memory_limit_mb: 1024
operations:
  healthcheck_required: true
  backup_required: false
  restart_policy: unless-stopped
```

Pydantic 모델로 검증한다. 누락/오류 시 배포하지 않고 구체적인 오류를 출력한다. `schema_version`으로 향후 변경을 지원하며 지원하지 않는 버전은 임의 해석하지 않는다.
추가 검토 필드: 헬스체크 정의, 데이터 볼륨, 서비스 의존성, 환경 변수 참조, 리소스 제한, 네트워크 정책, 백업 정책, 롤백 정책.
비밀번호/토큰/개인 키를 service.yaml에 저장하지 않는다.

## 7. 표준 서비스 디렉터리

```
/srv/services/<service-id>/
├── service.yaml
├── compose.yaml
├── .env.example
├── README.md
├── .gitignore
├── config/
├── data/
└── logs/
```
데이터 저장 위치와 백업 정책을 명시하는 것이 중요하다. Named Volume 사용 시 볼륨 이름과 목적도 관리 정보에 기록한다.
`.env`는 Git에 커밋하지 않는다. `.env.example`은 필드 이름과 설명만 포함한다.

## 8. Docker 컨테이너 조사 및 관리

### 8.1 초기 인벤토리 수집 (읽기 전용)
조사 항목: 모든 컨테이너, 실행/중지 상태, 이미지, 포트 매핑, Docker Label, Compose 프로젝트, Compose 서비스 이름, 네트워크, 볼륨 마운트, 헬스체크, 생성 시각, 최근 상태 변경, 재시작 횟수. 가능하면 기존 Compose 파일 위치도 파악. 찾을 수 없으면 "확인되지 않은 정보"로 기록.
초기 조사 단계에서 컨테이너를 자동 등록하거나 재시작하지 않는다.

### 8.2 컨테이너 관리 상태
`managed`, `unmanaged`, `mismatch`, `missing`, `stopped`, `unknown`.
`unknown`을 정상 상태로 취급하지 않는다.

### 8.3 미관리 컨테이너
표시: 컨테이너 이름/ID, 이미지, 실행 상태, 포트 매핑, 네트워크, 볼륨, 생성 시각, Compose 프로젝트, 추정 서비스, 미관리 사유.
기능: 서비스에 연결, 신규 서비스로 등록, 기존 서비스와 연결, 상세 정보, 로그, 검토 상태 지정.
연결 시 실제 컨테이너를 재생성하지 않는다. 발견했다는 이유로 자동 삭제하지 않는다.

## 9. 포트 관리

### 9.1 구분
1. Host Port: 호스트에 실제로 바인딩되는 포트
2. Container Port: 컨테이너 내부 포트
3. Proxy Endpoint: 리버스 프록시를 통한 도메인/경로
외부에 공개되지 않는 내부 서비스도 지원한다.

### 9.2 Port Registry
저장: 프로토콜(TCP/UDP), 호스트 포트, 바인딩 주소, 컨테이너 포트, 서비스 ID, 구성요소 이름, 공개 범위, 예약 상태, 실제 점유 상태, 프록시 연결 여부, 마지막 확인 시각.
포트 번호는 1~65535 검증.

### 9.3 포트 할당 절차
1. 입력값 검증 → 2. 기존 예약 확인 → 3. 실제 호스트 포트 점유 여부 확인 → 4. 기존 Docker 포트 매핑과 비교 → 5. IPv4/IPv6 바인딩 조건 확인 → 6. 공개 범위 확인 → 7. 서비스 정책 검사 → 8. 충돌 없으면 예약 → 9. 배포 시 실제 연결 → 10. 배포 후 실제 연결 확인 → 11. Port Registry 반영.
예약과 실제 점유를 구분한다. 예약은 트랜잭션/잠금으로 동시 배포 충돌을 방지한다. 예약 성공 ≠ 바인딩 성공.

### 9.4 기본 공개 정책
- 관리 웹 UI는 내부 네트워크에서만 접근 가능
- 데이터베이스는 외부 미노출
- 내부 서비스는 Docker 내부 네트워크 우선
- 공개 웹 서비스는 리버스 프록시 우선
- SSH 포트는 자동 할당 대상에서 제외
- 기존 사용 중인 포트는 자동 변경하지 않음

### 9.5 Traefik 연동
관리 시스템이 생성한 라우팅만 자동 관리하고 기존 프록시 설정을 덮어쓰지 않는다. 서비스별 네트워크 연결 검증, 내부 전용 서비스는 공개 라우팅 미생성, HTTPS 활성화 시 인증서/도메인 검증, 라우팅 변경 후 실제 접속 테스트.
내부 DNS가 없으면 `.home` 도메인이 자동 동작하지 않음을 사용자에게 안내한다.

## 10. 시스템 자원 모니터링

### 10.1 서버 자원
CPU(전체/논리 수/코어별/추이), 메모리(전체/사용/가용/캐시/스왑), 디스크(파일시스템별 + Docker 데이터 디렉터리), 네트워크(인터페이스별 송수신/누적/오류), 시스템(호스트명, OS, 커널, 부팅 시각, 가동 시간, CPU 온도 가능 시).
호스트 자원과 Docker 컨테이너 자원을 별도 표시.

### 10.2 컨테이너 자원
CPU 사용률, 메모리 사용량/제한, 네트워크 송수신, 블록 I/O, 재시작 횟수, 실행 상태, 헬스체크 결과.
미지원 지표는 0이 아니라 N/A로 표시.

### 10.3 서비스별 자원
서비스 컨테이너 자원 집계: CPU, 메모리, 컨테이너 수, 재시작 횟수, 상태.
집계값이 호스트 전체와 정확히 일치하지 않을 수 있음을 고려한다.

### 10.4 자원 여유도
임계값(기본, 사용자 설정 가능):
- 메모리 80% 주의 / 90% 위험
- 디스크 80% 주의 / 90% 위험
- CPU 80% 지속 시 주의 / 95% 지속 시 위험 (지속 시간 적용)
메모리 압박, 스왑 증가, OOM 이벤트, 디스크 증가 추세를 별도 고려.
배포 전 자원 상태 확인 및 경고. 예상 사용량은 추정치로 구분 표시.

## 11. 웹 UI 요구사항

전문적인 서버 운영 도구 품질. 과도한 그라데이션/애니메이션/카드 남발/장식 그래픽 지양. 일관된 간격, 타이포그래피, 명확한 정보 위계, 상태 중심 시각화. Lucide 아이콘. 데스크톱 우선, 태블릿/모바일 기본 조회 가능.

### 11.1 전역 레이아웃
좌측 메뉴: Overview, Services, Containers, Ports & Routing, Deployments, Resources, Events, Settings.
상단: 서버 상태, 마지막 데이터 갱신 시각, 알림, 사용자 메뉴. 전역 검색(서비스 이름/ID, 컨테이너 이름/ID, 포트, 도메인, 이미지).

### 11.2 Overview
등록 서비스 수, 실행/중지 컨테이너 수, 미관리 컨테이너 수, CPU/메모리/디스크, 가동 시간, 최근 이벤트, 서비스별 상태, 주요 경고.

### 11.3 Services
테이블 컬럼: 서비스 이름, 설명, 상태, 실행 컨테이너 수, 엔드포인트, CPU, 메모리, 마지막 배포 시각.
기능: 검색, 상태/카테고리 필터, 정렬, 등록, 상세 조회, 설명 수정.

### 11.4 Service Detail 탭
Overview, Containers, Endpoints, Deployment, Resources, Logs, Configuration, Events.
필수 컨테이너가 중지되면 서비스 전체 상태에 반영.

### 11.5 Containers
전체 컨테이너 조회. 필터: 실행 중, 중지, 미관리, 상태 불명, 구성 불일치.
상세: 이미지, 네트워크, 포트, 볼륨, 로그, 자원 사용량.

### 11.6 Ports & Routing
상태 구분: 예약됨, 실제 점유 중, 사용 가능, 충돌, 관리되지 않는 점유, 프록시 연결, 내부 전용.
포트 지정 시 충돌 검사 및 연결할 서비스/컨테이너 선택.

### 11.7 Deployments
배포 ID, 서비스, 시작/완료 시각, 결과, 변경 내용, 오류 메시지, 실행 사용자/요청 주체. 상세에서 단계별 진행과 로그.

### 11.8 Resources
CPU/메모리 그래프, 디스크, 네트워크, 서비스별/컨테이너별 순위, 경고 임계값.

### 11.9 Events
기록: 컨테이너 생성/중지/재시작, 서비스 등록/수정, 포트 예약/충돌, 배포 시작/성공/실패, 미관리 컨테이너 발견, 자원 경고, Docker 연결 오류.
포함: 발생 시각, 심각도, 관련 서비스, 관련 컨테이너, 상세 내용.

## 12. SSH 로그인 환영 메시지 (MOTD)

```
============================================================
                 N100 SERVICE HUB
============================================================
SYSTEM
  Hostname       : n100-server
  Uptime         : 12 days
  CPU            : 23%
  Memory         : 9.2 / 16.0 GB
  Disk           : 320 / 500 GB
DOCKER
  Running        : 28
  Stopped        : 3
  Unmanaged      : 2
SERVICES
  [OK] AI Platform       4 containers
  [OK] Media Server      2 containers
  [WARN] Test App        1 container
MANAGEMENT
  Dashboard      : http://<server-address>:<configured-port>
  CLI            : hub status
RECENT EVENTS
  - Unmanaged container detected
  - Last deployment succeeded
============================================================
```
실제 상태에 따라 동적으로 생성. SSH 로그인마다 무거운 Docker 조회 금지. 백그라운드 모니터링 결과 캐시 사용. 상태가 오래되면 마지막 갱신 시각 표시. Docker/Service Hub가 중단되어도 SSH 로그인 지연 없음. 기존 MOTD 설정을 백업/복원 가능해야 한다.

## 13. 표준 배포 시스템

### 13.1 배포 원칙 (순서)
서비스 정의 파일 읽기 → 스키마 검증 → 서비스 ID 중복 확인 → 포트 충돌 확인 → 리소스 제한 확인 → Compose 파일 검증 → 환경 변수 검증 → 보안 정책 검증 → 배포 계획 생성 → 승인 확인 → 배포 실행 → 헬스체크 → 포트/라우팅 검증 → 서비스 상태 갱신 → 배포 이력 기록.
검증 실패 시 기본적으로 배포 중단.

### 13.2 배포 계획
배포 전 변경 계획 표시. 예시:
```
Service: ai-platform
Changes:
  frontend: image update
  backend: recreate
  worker: unchanged
  database: unchanged
Ports:
  No host port changes
Data:
  No planned volume changes
Impact:
  Frontend and backend may restart.
Validation:
  Compose syntax: PASS
  Port conflicts: NONE
  Required variables: PASS
  Resource warnings: NONE
Result: READY
```
계획과 실제가 다를 수 있으므로 배포 후 실제 상태를 다시 조회한다.

### 13.3 배포 실행
허용 작업: Compose 구성 검증, 이미지 빌드/다운로드, Compose 프로젝트 배포, 헬스체크, 프록시 연결 확인, 결과 기록.
**임의의 셸 명령을 전달받아 실행하는 API는 제공하지 않는다.**
배포 요청은 작업 ID를 발급하고 비동기 실행. 상태: `queued`, `validating`, `running`, `verifying`, `succeeded`, `failed`, `cancelled`.
실행 중인 작업과 동일 서비스의 중복 배포를 제어한다.

### 13.4 실패 및 롤백
구분: 이전 이미지로 복구 가능한 변경 / 설정 파일 복구 필요 / 데이터 마이그레이션 포함 / 자동 복구가 위험한 변경.
DB 스키마 변경과 데이터 볼륨 변경은 자동 롤백 대상이 아니다.
배포 전 설정 파일과 이미지 버전을 기록한다. 백업이 필요한 서비스는 백업 여부를 확인한다.
롤백 불가/미검증 작업은 사전 경고 및 승인 요구.

## 14. AI 전용 관리 인터페이스

### 14.1 구조화된 출력
JSON 제공. 시간은 ISO 8601. 실제 조회 시각과 마지막 정상 수집 시각을 구분. 알 수 없는 값을 임의의 정상값으로 대체하지 않는다.

### 14.2 AI 배포 가이드
프로젝트 루트에 `AI-OPERATIONS.md` 제공. 규칙: 배포 전 반드시 서버 상태 조회, 표준 템플릿 사용, 포트는 관리 시스템에서 확인/예약, 서비스 정의 파일 작성, Compose 검증, DB 외부 미노출, 기존 볼륨/컨테이너 임의 삭제 금지, 배포 전 계획 확인, 배포 후 헬스체크, 결과 반영, 실패 시 오류/변경 기록, 기존 서비스 영향 작업은 사전 승인.
프로젝트별 AI 규칙 파일도 제공.
문서 규칙만으로는 안전하지 않다. API 권한과 배포 실행기에서 동일한 제한을 강제해야 한다.

## 15. 보안 요구사항

1. 웹 대시보드는 인증을 요구한다.
2. 초기 설정에서 관리자 인증을 구성한다.
3. 기본 비밀번호를 하드코딩하지 않는다.
4. 비밀 정보는 화면과 로그에서 마스킹한다.
5. Docker 소켓을 프런트엔드 컨테이너에 마운트하지 않는다.
6. 관리 API는 허용된 작업만 제공한다.
7. 임의의 셸 실행 API를 제공하지 않는다.
8. 위험 작업은 별도 승인을 요구한다.
9. 배포 및 설정 변경 이력을 기록한다.
10. 관리 웹 UI는 기본적으로 내부 네트워크에서만 접근한다.
11. CSRF, 인증 우회, 권한 상승, 명령 주입을 방지한다.
12. 서비스별 환경 변수를 다른 서비스에서 임의로 조회할 수 없다.
13. 인증 정보와 개인 키를 Git에 저장하지 않는다.
14. 기본 설치 시 외부 인터넷에 관리 포트를 공개하지 않는다.

Docker 소켓 접근 범위를 명확히 하고 가능하면 배포 전용 작업 실행기와 분리한다. 최소 권한을 보장할 수 없는 구성은 설치 문서에 위험을 명시한다.

## 16. 데이터베이스 및 백업

SQLite 사용. 최소 테이블(또는 동등 모델): services, service_components, containers, endpoints, port_reservations, deployments, deployment_steps, resource_samples, events, audit_logs, settings.
필요한 인덱스와 외래 키 설정. SQLite 동시 쓰기 특성 고려해 트랜잭션 관리.
서비스 정의 파일과 실제 Docker 상태를 하나의 데이터로 혼합하지 않는다.
관리 데이터베이스 주기 백업 가능. 백업/복구 절차 문서화. 관리 DB 손상 시에도 기존 Docker 서비스 중단되지 않아야 한다.

## 17. API 설계 (초기 설계안)

```
GET    /api/v1/system/overview
GET    /api/v1/services
POST   /api/v1/services
GET    /api/v1/services/{service_id}
PATCH  /api/v1/services/{service_id}
DELETE /api/v1/services/{service_id}
GET    /api/v1/containers
GET    /api/v1/containers/{container_id}
GET    /api/v1/ports
GET    /api/v1/ports/available
POST   /api/v1/ports/reservations
DELETE /api/v1/ports/reservations/{reservation_id}
GET    /api/v1/orphans
GET    /api/v1/resources/host
GET    /api/v1/resources/services
POST   /api/v1/deployments/plan
POST   /api/v1/deployments
GET    /api/v1/deployments/{deployment_id}
GET    /api/v1/deployments/{deployment_id}/logs
GET    /api/v1/events
GET    /api/v1/audit-logs
```
REST 규칙, 인증, 권한, 오류 응답 형식을 통일한다.
서비스 삭제 API는 컨테이너와 볼륨을 자동 삭제하지 않는다. 관리 정보 삭제와 실제 실행 환경 삭제를 명확히 구분한다.
OpenAPI 문서 제공.

## 18. 설치 및 운영

Docker Compose로 설치. 최소 구성:
```
service-hub/
├── compose.yaml
├── .env.example
├── README.md
├── AI-OPERATIONS.md
├── backend/
├── frontend/
├── cli/
├── schemas/
├── templates/
├── scripts/
├── docs/
└── tests/
```
서비스 데이터와 관리 시스템 데이터를 분리한다. 관리 시스템 업데이트가 기존 서비스 데이터에 영향을 주지 않아야 한다.
설치 스크립트: OS/Docker 환경 확인 → 기존 포트 충돌 확인 → 기존 데이터 경로 확인 → 설치 디렉터리 생성 → 설정 파일 생성 → 관리자 초기 설정 안내 → 관리 시스템 실행 → 헬스체크 → 결과 출력.
설치 과정에서 기존 컨테이너 중단 금지, Docker 설정 임의 변경 금지. 기존 MOTD는 백업 후 추가, 제거 시 원래 상태 복구.

## 19. 테스트 요구사항

### 19.1 서비스 관리
정상 등록, 중복 ID 거부, 잘못된 스키마 거부, 설명 수정, 컨테이너 연결, 컨테이너 없는 서비스 등록.

### 19.2 포트 관리
가용 포트 예약, 예약된 포트 거부, 실제 점유 포트 감지, TCP/UDP 구분, 공개 범위 검증, 동시 예약 충돌 방지, 예약/실제 불일치 감지.

### 19.3 컨테이너 관리
실행/중지 컨테이너 조회, 미관리 탐지, 등록-실제 불일치, Docker 연결 실패, 볼륨/네트워크 정보 조회.

### 19.4 배포
정상 Compose 배포, 검증 실패, 포트 충돌 시 차단, 필수 환경 변수 누락, 헬스체크 실패, 중복 배포 방지, 실패 이력 기록, 데이터 보호 정책 검증.

### 19.5 자원 모니터링
정상 수집, Docker API 오류, 일부 지표 미지원, 오래된 데이터 표시, 경고 임계값 판정, 서비스별 집계.

### 19.6 기존 서비스 보호 (가장 중요)
테스트 환경에 관리되지 않는 컨테이너를 생성하고 초기 인벤토리 수집 후 검증:
삭제되지 않았는가, 실행 상태 미변경, 포트 매핑 미변경, 볼륨 미변경, 네트워크 미변경, 미관리로 정확히 표시되는가.
**이 테스트가 통과하지 않으면 기존 서버에 설치하지 않는다.**

## 20. 개발 진행 방식

- **Phase 0**: 환경 조사 및 설계 — OS, Docker 설치/실행 상태, Compose 버전, 컨테이너 목록, 포트 매핑, Compose 프로젝트, CPU/메모리, 디스크, 기존 리버스 프록시/웹 서버, MOTD, 관리 포트. 기존 서비스 변경 금지. 결과는 docs/ENVIRONMENT-INVENTORY.md, docs/ARCHITECTURE.md, docs/IMPLEMENTATION-PLAN.md, docs/SECURITY.md에 기록. 확인 불가 항목은 추측하지 말고 "확인 필요"로 기록.
- **Phase 1**: 읽기 전용 관리 기능 — Docker 인벤토리, 서비스 등록/설명 관리, 서비스별 컨테이너 그룹핑, 포트 현황 조회, 미관리 컨테이너 탐지, 호스트/컨테이너 자원 모니터링, 기본 대시보드, SSH 환영 메시지. 배포/재시작/삭제 기능 기본 비활성화.
- **Phase 2**: 표준 서비스 등록 — service.yaml 스키마, 표준 템플릿, CLI, 포트 예약, 서비스 등록/검증, AI 운영 문서.
- **Phase 3**: 표준 배포 — 배포 계획, Compose 검증, 배포 실행, 헬스체크, 프록시 연결, 배포 이력, 실패 처리.
- **Phase 4**: 안전성 및 운영 고도화 — 인증/권한, 감사 로그, 백업/복구, 롤백, 자원 추세 분석, 보안 테스트, 운영 문서.

각 Phase 완료 시 테스트 결과와 남은 작업을 문서화. 이전 단계 필수 테스트 통과 후 다음 단계로.

## 21. 완료 기준 (1차)

- 서비스 관리: 목적/설명 확인, 서비스별 컨테이너 목록, 포트/도메인 확인, 배포 경로 확인.
- Docker 관리: 전체 컨테이너 조회, 실행/중지 구분, 미관리 탐지, 등록-실제 불일치 탐지.
- 자원 관리: CPU/메모리/디스크, 서비스별 사용량, 부족 경고.
- 포트 관리: 충돌 탐지, 예약/실제 구분, 프록시/직접 포트 구분, 공개 범위 확인.
- AI 연동: CLI 상태 조회, 가용 포트 후보, 서비스 정의 파일 검증, 배포 계획 JSON 출력, AI 운영 규칙 문서.
- 운영: SSH 현황 표시, Docker 장애 시 SSH 지연 없음, 배포 이력, 관리 시스템 재시작 후 정보 유지, 업데이트 시 기존 서비스 무손상.

## 22. 개발 지시사항

1. 기존 작업 디렉터리와 파일을 조사한다.
2. 기존 코드/설정이 있으면 먼저 분석한다.
3. 실제 N100 환경 확인 가능하면 조사하되, 확인 불가 항목은 추정하지 않는다.
4. Phase 0 문서를 작성한다.
5. 기술 충돌/요구사항 누락을 식별한다.
6. 전체 구현 계획을 작성하고 Phase 1부터 실제로 코드를 구현한다.
7. 각 기능에 테스트를 작성하고 실행한다.
8. README와 운영 문서를 작성하고 설치/실행 절차를 검증한다.

계획만 작성하고 멈추지 않는다. 위험한 작업(기존 서비스 중단, 데이터 변경, 외부 노출)은 실행 전 승인을 받는다.
작업이 길어지면 docs/IMPLEMENTATION-STATUS.md에 완료/진행 중 기능, 테스트 결과, 알려진 문제, 남은 작업, 다음 실행 단계를 갱신한다.
실제 서버에 접근하지 못하면 테스트용 Docker 환경 또는 Mock으로 개발하되, Mock 성공을 실제 서버 검증 성공으로 표현하지 않는다.

최종 목표: 단순 데모가 아니라, 기존 Docker 환경을 보호하면서 여러 서비스를 장기 관리하고 AI가 표준 절차에 따라 신규 서비스를 배포할 수 있는 운영 가능한 시스템.
