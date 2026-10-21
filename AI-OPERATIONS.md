# AI-OPERATIONS.md — AI 코딩 도구를 위한 배포 운영 규칙

이 문서는 Cursor, OpenCode 등 AI 코딩 도구가 N100 서버에서 작업할 때 반드시 따르는 규칙이다.
문서에 규칙이 있다는 것만으로 안전하지 않다. **API/CLI가 같은 제한을 강제한다** — 예를 들어
배포 API는 임의 셸 명령을 받지 않고(`HUB_ENABLE_DEPLOY` 잠금), 포트 예약은 충돌 검사를 거친다.
규칙을 우회하는 시도(직접 docker 명령으로 관리 대상 컨테이너 조작 등)는 금지된다.

## 0. 절대 금지 (승인 없이)

- 기존 컨테이너의 삭제/재시작/재생성
- `docker system prune`, `docker volume prune`, `docker compose down -v`
- 기존 볼륨/이미지/네트워크/포트 매핑 변경
- 기존 서비스 설정 파일 수정
- 관리 웹 UI/포트를 외부 인터넷에 노출하는 변경
- `.env`, 개인 키, 토큰을 Git에 커밋

위 작업이 꼭 필요하면 작업 내용과 영향 범위를 사용자에게 제시하고 **명시적 승인**을 받는다.

## 1. 표준 배포 절차 (모든 신규 서비스)

1. **현재 서버 상태 조회** (배포 전 필수)
   ```
   hub status --json
   hub port list --json
   hub resource --json
   hub orphan list --json
   ```
2. **가용 포트 확인 및 예약** — 임의 포트 선택 금지
   ```
   hub port available --count 5 --range 8000-9000 --json
   ```
   웹 UI의 Ports & Routing 또는 API `POST /api/v1/ports/reservations`로 예약한다.
3. **표준 템플릿으로 서비스 디렉터리 생성**
   ```
   hub service new <service-id> --dir /srv/services --name "<서비스 이름>"
   ```
   또는 기존 예시를 복사한다: `cp -r templates/sample-app /srv/services/<service-id>`
   `service.id`는 소문자/숫자/하이픈. 디렉터리 구조는 §7(REQUIREMENTS)을 따른다.
4. **service.yaml 작성/수정** — 비밀값 절대 금지 (`security.required_env`에 이름만 기록)
5. **검증**
   ```
   hub service validate /srv/services/<service-id>
   ```
6. **배포 계획 확인**
   ```
   hub deploy plan /srv/services/<service-id> --json
   ```
   계획의 포트/영향 범위를 검토한다. 다른 서비스가 재시작되면 반드시 사용자에게 알린다.
7. **배포 실행** (사용자 승인 후)
   ```
   hub deploy apply <service-id> --yes
   ```
   배포는 `HUB_ENABLE_DEPLOY=true`에서만 동작한다(기본 잠금). 실행기는 화이트리스트
   compose 작업만 수행하며 임의 셸 명령을 받지 않는다. 실행 전 승인과 감사 로그를 남긴다.
8. **배포 후 검증**
   ```
   hub service show <service-id> --json
   hub status --json
   ```
   헬스체크, 포트 바인딩, 프록시 라우팅 접속을 확인한다. 확인 전에 성공으로 취급하지 않는다.
9. **실패 시**: 오류 로그와 변경된 파일 목록을 기록하고, 서비스가 손상되었으면 사용자에게 보고한다. DB 스키마/데이터 볼륨 변경은 자동 롤백하지 않는다.

## 2. 포트 규칙

- 데이터베이스/캐시는 `exposure: internal` (호스트 포트 미할당)
- 공개 웹 서비스는 `exposure: proxy` (Traefik 도메인) 우선
- SSH 22, 관리 UI 8420 및 이미 점유된 포트는 사용 금지
- 예약 성공 ≠ 실제 바인딩. 배포 후 반드시 확인한다.

## 3. 컨테이너 식별 규칙

- 관리 대상 컨테이너는 서비스 등록을 통해서만 연결한다. 미관리 컨테이너를 발견해도 자동 삭제/재생성하지 않는다.
- `hub orphan list`의 추정 서비스는 힌트일 뿐, 실제 확인 후에 연결한다.
- hub 자체 컨테이너(`hub-backend`, `hub-frontend`, label `com.hub.self/managed`)는 절대 조작하지 않는다.

## 4. 데이터 규칙

- 서비스 데이터는 Compose Named Volume 또는 명시적 호스트 경로로 관리하고 service.yaml의 `volumes`에 목적을 기록한다.
- 백업이 필요한 서비스(`operations.backup_required: true`)는 배포 전 백업 여부를 확인한다.
- 관리 DB(`hub.db`) 백업은 `scripts/backup.sh`. 관리 DB는 어떤 경우에도 서비스 데이터가 아니다.

## 5. 보안 규칙

- 시크릿은 서비스 `.env`(Git 제외)에서만 관리한다. service.yaml/CLI 인자/이벤트 로그에 시크릿을 넣지 않는다.
- API 응답의 `*_PASSWORD`/`*_TOKEN`/`*_KEY` 값은 마스킹되어야 한다 — 마스킹 해제 시도 금지.
- Docker 소켓을 프런트엔드/외부 서비스 컨테이너에 마운트하는 구성 금지.

## 6. 문제 발생 시

1. 즉시 작업을 중단하고 현재 상태(`hub status --json`)와 관련 로그를 수집한다.
2. 임의의 복구 명령을 실행하지 않고 사용자에게 상황을 보고한다.
3. 기존 서비스 영향 가능성이 있으면 영향받는 서비스 목록과 데이터 위험도를 명시한다.
