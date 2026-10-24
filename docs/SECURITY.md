# SECURITY (Phase 0)

## 위험 모델

관리 시스템은 Docker 소켓에 접근한다. Docker 소켓 접근은 사실상 root 권한이므로, 소켓 접근 주체를 최소화하는 것이 핵심 방어다.

## 권한 분리 구조

```
[브라우저/CLI/AI 도구]
        │ HTTPS(내부망) + 세션
        ▼
[backend (FastAPI)] ── 소켓 접근 주체 #1 (모니터링/인벤토리 전용, 읽기 우선)
        │
        ▼ (검증된 배포 작업만, 내부 IPC)
[runner (배포 실행기)] ── 소켓 접근 주체 #2 (compose up/down 제한 작업만)
        │
        ▼
[기존 서비스 컨테이너들 — 절대 소켓 미마운트]
```

- 프런트엔드 정적 파일은 backend가 서빙. 별도 프런트엔드 컨테이너에 소켓을 마운트하지 않는다.
- runner는 `docker compose up -d --remove-orphans`(범위 제한), `compose config` 검증, `compose pull`만 허용. 임의 셸 명령 API 없음.

## 통제 목록 (§15 대응)

| # | 통제 | 구현 위치 | Phase |
|---|---|---|---|
| 1 | 대시보드 인증 | 세션 쿠키(HttpOnly, SameSite=Strict) + bcrypt | 1 |
| 2 | 초기 관리자 구성 | 최초 기동 시 설정 마법사. 기본 비밀번호 없음 | 1 |
| 3 | 하드코딩 비밀번호 금지 | 환경변수/DB 해시만. 문서화된 기본값 없음 | 1 |
| 4 | 비밀 마스킹 | API/CLI/로그 응답에서 `*_PASSWORD`, `*_TOKEN`, `*_KEY` 형태 값 마스킹 | 1 |
| 5 | 소켓 미마운트(프런트엔드) | 단일 백엔드 구조로 구조적 보장 | 1 |
| 6 | 허용 작업만 API | Deployment Manager 화이트리스트 | 3 |
| 7 | 임의 셸 API 금지 | API에 shell 엔드포인트 존재하지 않음 (코드 리뷰 체크) | 1~3 |
| 8 | 위험 작업 승인 | destructive=false 기본, `confirm` 토큰 required | 3 |
| 9 | 감사 로그 | audit_logs 테이블, 모든 변경 작업 기록 | 1~4 |
| 10 | 내부망 기본 | bind 127.0.0.1 기본, `HUB_BIND_ADDR`로 변경. compose에 방화벽 안내 | 1 |
| 11 | CSRF/주입 방어 | SameSite 쿠키 + CSRF 토큰, Pydantic 검증, 매개변수화 | 1 |
| 12 | env 격리 | 서비스 env 조회 API 미제공. `.env` 직접 읽기 금지(파일 이름만 노출) | 1~2 |
| 13 | Git에 시크릿 금지 | .gitignore, pre-commit 안내 (문서화) | 1 |
| 14 | 외부 미노출 | 설치 시 바인드 주소/포트 경고, publish 정책 검사 | 1~2 |
| 15 | 비밀번호 변경 | `POST /auth/change-password` — 세션+CSRF+현 비밀번호 재확인, 감사 로그 | 2~3 |
| 16 | 패스워드리스 | WebAuthn — HTTPS 컨텍스트 전용, 공개키만 저장, 1회용 챌린지 | 2~3 |
| 17 | 관리자 초기화 | `POST /auth/reset-admin` — 루프백 또는 1회용 복구 토큰만, 감사 로그 | 3 |
| 18 | API 키(MCP) | `X-API-Key`/`Bearer` — SHA-256 해시만 저장, 발급 응답에서 1회만 평문 노출 | 3 |
| 19 | API 키 권한 제한 | scope(read/write/deploy/*) — read 키는 변경 요청 403, 발급/폐기는 세션 전용 | 3 |
| 20 | API 키 감사/폐기 | `apikey:<이름>` 주체로 감사 로그 기록, 폐기 즉시 인증 거부 | 3 |

## 추가 통제

- 로그인 실패 제한(분당 5회, 잠금 5분).
- 비밀번호 변경(`POST /auth/change-password`)은 인증 세션 + CSRF를 요구하고 현 비밀번호를
  재확인한다. 현 비밀번호 오류는 세션 만료(401)가 아니라 입력 오류(400)로 응답한다 —
  401은 프런트엔드의 전역 세션 만료 처리와 충돌한다.
- 생체인식(WebAuthn)은 `HUB_WEBAUTHN_RP_ID`와 `HUB_WEBAUTHN_ORIGIN`이 모두 설정된
  HTTPS 환경에서만 켜진다. 미설정(기본값) 시 모든 엔드포인트가 `503 webauthn_disabled`다.
- WebAuthn 자격증명은 **공개키만** 저장한다(비밀키/생체 정보 미저장). 챌린지는 1회용 +
  5분 TTL로 메모리에만 두며, `sign_count` 역전(자격증명 복제 의심) 시 인증을 거부한다.
- WebAuthn 인증 실패는 비밀번호 로그인과 **동일한 잠금 카운터**(5회/5분)를 공유한다.
- 컨테이너/이미지 조작(시작/정지/제거)은 `HUB_ENABLE_DOCKER_ACTIONS`(기본 false)로 잠근다.
  허브 자신과 보호 대상(`HUB_PROTECTED_CONTAINERS`/`HUB_PROTECTED_PROJECTS`)은 차단하고,
  제거는 실행 중 거부 + 정확한 이름 확인을 요구하며 모든 조작을 감사 로그에 남긴다.
  이미지는 사용 중이거나 허브 이미지면 제거할 수 없다.
- ES256 서명은 사용 중인 검증 스택(py-webauthn 3.0.1 + cryptography 50)이 DER만
  검증에 통과시키므로 raw(r‖s) → DER로 인코딩을 정규화한다. r·s 값 자체는 바꾸지 않아
  검증 강도는 동일하며, EdDSA(-8)·RS256(-257)은 형식이 달라 변환하지 않는다.
- 모든 API 오류 응답에 Docker 소켓 경로, 호스트 파일 경로 등 내부 정보 미포함.
- 배포 실행기는 작업 디렉터리 외 경로 접근 불가(경로 정규화 + 서비스 루트 제한).
- service.yaml에 시크릿 필드 자체를 금지(스키마 검증 단계에서 차단).
- 배포 실행 경로는 `HUB_ENABLE_DEPLOY` 기본 `false`로 잠긴다. 잠금 시 `POST /deployments`
  는 항상 `503 deploy_disabled`이며, 실행기 자체도 게이트를 재확인한다(방어 심층).
- `docker_client.py`의 변경 함수(`compose_up`/`compose_down`)는 `allow_mutations=True`가
  아니면 `PermissionError`를 낸다. 인자는 리스트로만 전달되며 `shell=True`/`sh -c` 경로가 없다.
- 관리자 초기화(`POST /auth/reset-admin`, CLI `hub admin reset`)는 인증 우회 경로가 될 수
  있으므로 다음 조건을 **모두** 만족해야 한다.
  - 요청이 루프백에서 왔거나, `HUB_ADMIN_RESET_TOKEN` 설정 + `X-Hub-Admin-Reset-Token`
    헤더가 일치해야 한다. 둘 다 아니면 `403 reset_not_allowed`다.
  - 복구 토큰은 **1회 사용**이다 — 성공 후 토큰 해시가 DB에 기록되어 같은 토큰으로
    다시 초기화할 수 없다(`403 reset_token_used`). 재사용하려면 .env의 토큰을 새로
    설정하고 백엔드를 재기동해야 한다.
  - 초기화는 관리자 행(사용자명/비밀번호 해시)과 그 관리자의 WebAuthn 자격 증명만
    삭제한다. 서비스/포트/컨테이너/이벤트 등 다른 데이터는 건드리지 않는다.
  - 초기화하면 관리자 `session_epoch`이 사라지므로 **기존 세션이 모두 무효**가 된다
    (세션 쿠키를 가진 요청도 401). 사용자는 설정 마법사에서 새 계정을 만든다.
  - 초기화는 감사 로그(`auth.admin_reset`)에 남는다.
  - 오프라인 모드(`hub admin reset --db <경로>`)는 DB 파일을 직접 다루므로 백업 사본을
    먼저 남기고, 테이블을 직접 쿼리하지 않고 `settings`/`webauthn_credentials`만 건드린다.
- API 키(MCP/AI 클라이언트)는 다음 통제를 적용한다.
  - 서버에는 **SHA-256 해시만** 저장한다. 평문 키는 발급 응답에서 한 번만 반환하며
    목록/감사 로그/오류 메시지에 다시 나타나지 않는다.
  - 발급·목록·폐기는 **브라우저 세션 전용**(`require_session_auth`)이다. API 키로는
    새 키를 만들 수 없어 권한 상승 경로가 없다. 폐기는 `revoked_at`만 기록한다.
  - scope(`read`/`write`/`deploy`/`*`)를 강제한다. `read` 키의 변경 요청은
    `403 insufficient_scope`로 거부한다. 키 생성 시 미지의 scope는 422로 거절한다.
  - API 키 인증은 CSRF 토큰을 요구하지 않는다(비브라우저 헤더 클라이언트). 대신
    쿠키를 쓰지 않으므로 CSRF 대상이 아니며, 키 자체가 인증 비밀이다.
  - 인증 사용은 감사 로그에 `apikey:<이름>` 주체로 기록된다.
  - API 키도 배포 잠금(`HUB_ENABLE_DEPLOY`)·화이트리스트·`confirmed=true` 검증을
    우회하지 못한다 — 권한은 "누가 요청했는가"만 바꾼다.
  - MCP 서버(`mcp-server/`)는 기존 REST API만 호출하며 셸/파일 실행 도구를 노출하지 않는다.
- 소스 업로드(`POST /services/{service_id}/source`)는 배포 디렉터리를 덮어쓸 수 있으므로
  다음을 강제한다.
  - 기본 `HUB_ENABLE_SOURCE_UPLOAD=false` (잠금). 인증된 세션/쓰기 권한 API 키 필요.
  - 대상은 `<HUB_DEPLOY_WORKDIR>/<service_id>` 하나로 고정 (서비스 ID 정규식 재검증).
  - tar.gz 멤버는 **상대 경로 + 일반 파일/디렉터리**만 허용. `..`/절대 경로/심볼릭 링크/
    하드 링크/장치·파이프는 거부. 파일 수·압축 해제 크기·파일 크기 상한.
  - 임시 디렉터리에서 검증 후 복사하며, 기존 파일을 삭제하지 않는다(prune 없음).
  - 업로드는 감사 로그(`service.source_upload`)에 기록된다.
  - `.env`/`*.pem`/`*.key` 는 업로드 시 **0600** 으로 저장한다(`.env.example` 제외).
- 무인 배포(`HUB_DEPLOY_AUTO_ROLLBACK`, `HUB_DEPLOY_ALLOWED_SERVICES`, 웹훅)
  - 허용 목록이 설정되면 목록 밖 서비스의 계획/실행/롤백은 `403 service_not_allowed`.
  - 자동 롤백은 **직전 성공 배포의 스냅샷**만 사용하며, DB/볼륨은 되돌리지 않는다.
  - 웹훅은 `HUB_DEPLOY_WEBHOOK_SECRET`이 있으면 HMAC 서명을 붙인다. 실패해도 배포는 계속된다.

## 수용 불가 구조 (명시)

Docker SDK가 backend 프로세스에 직접 연결하므로, backend 취약점은 Docker 전체 권한으로 이어질 수 있다. 최소 권한 달성은 별도의 rootless Docker 또는 cgroup 격리로만 가능하며, 이 단계(개인 서버, 단일 운영자)에서는 **위험을 수용하고 문서화**한다. N100 운영 시 방화벽으로 관리 포트를 외부 차단할 것.
