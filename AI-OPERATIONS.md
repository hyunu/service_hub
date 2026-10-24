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

## 7. 관리자 비밀번호 분실 복구 (`hub admin reset`)

비밀번호를 잊어 로그인이 안 되면 아래 순서로 복구한다. **기존 컨테이너/포트/볼륨은
건드리지 않는다** — 관리자 자격 증명(사용자명·비밀번호 해시·패스워드 키)만 지운다.

### 7.1 서버 로컬(루프백) — 권장

```bash
# 컨테이너 안에서 루프백 요청으로 초기화 (컨테이너 내 127.0.0.1 → 서버 루프백 규칙 충족)
docker exec hub-backend python - <<'PY'
import urllib.request
req = urllib.request.Request("http://127.0.0.1:8420/api/v1/auth/reset-admin",
                             data=b"{}", method="POST",
                             headers={"Content-Type": "application/json"})
print(urllib.request.urlopen(req).read().decode())
PY
```

또는 CLI(서버에 설치된 경우):
```bash
hub admin reset --yes --url http://127.0.0.1:8420/api/v1
```

### 7.2 원격 (복구 토큰) — tailnet 등

1. 서버의 `/srv/service-hub/.env`에 `HUB_ADMIN_RESET_TOKEN=<임의의 긴 값>`을 추가한다.
2. 백엔드를 재기동한다 (`docker compose up -d backend`).
3. 토큰을 헤더로 보내 초기화한다.

```bash
hub admin reset --yes --url https://n100-pve-dev.tail7d413d.ts.net/api/v1 \
     --token '<HUB_ADMIN_RESET_TOKEN 값>'
```

**복구 토큰은 1회 사용이다.** 성공하면 같은 토큰으로는 다시 초기화할 수 없다
(`403 reset_token_used`). 사용이 끝나면 `.env`에서 토큰을 제거하고 백엔드를 재기동한다.

### 7.3 오프라인 (DB 파일 직접) — API가 닿지 않을 때

```bash
sudo hub admin reset --yes --db /var/lib/docker/volumes/service-hub_hub-data/_data/hub.db
```

- DB 파일을 먼저 백업한다(`hub.db.bak-<날짜>` 사본 생성).
- `settings`의 `admin` 행과 해당 관리자의 `webauthn_credentials`만 삭제한다.
- 백엔드가 실행 중이어도 안전하다(관리자 행이 사라지므로 세션은 자동으로 무효가 된다).
- 백엔드가 DB를 캐시하지 않으므로 **재시작이 필요 없다**.

### 7.4 복구 후

1. 대시보드(https://<tailnet FQDN>)를 다시 열어 **설정 마법사**에서 관리자 계정을 새로 만든다.
2. 이전 비밀번호는 복구할 수 없다 — 새 비밀번호를 안전하게 정한다.
3. `hub status --json`로 정상 동작을 확인한다.
4. 초기화 전에 발급한 **API 키는 그대로 유효**하다. 필요 없으면
   대시보드 Settings → API 키에서 폐기한다.

## 7.5 현재 서버 잠금 상태 (2026-10-23 기준)

- N100 서버는 **배포 잠금이 열려 있다** (`HUB_ENABLE_DEPLOY=true`).
  즉 `hub deploy apply` / `hub_deploy_apply`가 실제 compose 작업을 수행할 수 있다.
- **컨테이너/이미지 조작도 열려 있다** (`HUB_ENABLE_DOCKER_ACTIONS=true`, 사용자 승인).
  단, `HUB_PROTECTED_PROJECTS=infra` / `HUB_PROTECTED_CONTAINERS=assetnest` 로
  기존 assetnest 스택은 보호되고, 허브 자신은 코드 수준에서 항상 차단된다.
  기존 서비스(assetnest 등)를 조작해야 한다면 보호 목록을 임의로 풀지 말고
  먼저 사용자 승인을 받는다.
- 실행기는 `HUB_DEPLOY_WORKDIR/<service_id>`(= `/srv/services/<service_id>`)의
  `compose.yaml`만 사용한다. 등록 시의 `deployment_path`는 표시용이며 실행 경로가 아니다.
- 따라서 배포 가능한 서비스의 전제: **호스트에 `/srv/services/<service-id>/compose.yaml`이 존재**.
- 잠금을 다시 닫으려면 `/srv/service-hub/.env`의 값을 `false`로 바꾸고 백엔드를 재기동한다.
- 열려 있더라도 §0의 절대 금지 작업과 §1의 절차(상태 조회 → 포트 예약 → 검증 → 계획 확인)는
  그대로 적용된다.

## 8. AI 에이전트의 허브 연동 (MCP)

AI 코딩 도구는 셸에서 `docker`/`hub`를 직접 호출하는 대신 **MCP 도구**로 허브에 요청할 수 있다.
MCP 서버(`mcp-server/`)는 기존 REST API만 호출하며, 임의 셸 실행 경로는 없다.

### 8.1 준비

1. 대시보드 **Settings → API 키**에서 키를 발급한다 (평문은 1회만 표시).
   - 조회만 필요하면 `읽기 전용`, 배포까지 필요하면 전체 권한.
2. AI 클라이언트 설정에 MCP 서버를 등록한다 (`mcp-server/README.md` §3).

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

### 8.2 작업 순서 (MCP)

1. `hub_status` → `hub_services_list` → `hub_ports_list` 로 현재 상태 확인 (§1.1과 동일한 목적)
2. `hub_service_register(spec, deployment_path=..., dry_run=true)` 로 등록 내용 검토
3. `hub_service_register(spec, deployment_path=...)` 로 등록 (컨테이너는 생성되지 않음)
4. `hub_deploy_plan(spec)` → 결과가 `READY` 인지 확인
5. `hub_deploy_apply(service_id=..., confirmed=true)` — **잠금이 열려 있을 때만** 실행된다
6. `hub_deploy_status` / `hub_service_logs` 로 확인

> 배포는 `/srv/services/<service_id>/compose.yaml`에서만 동작한다(§7.5).
> 등록만으로는 컨테이너가 생기지 않으며, 실제 배포는 이 디렉터리가 준비된 뒤에 수행한다.

### 8.2.1 소스 동기화 방식 (SSH 없이)

| 방식 | 자격증명 | 비고 |
|---|---|---|
| `hub_service_sync_source` (권장) | 허브 API 키만 | MCP가 로컬 tar.gz 업로드 → `/srv/services/<id>` |
| `rsync`/`scp` | SSH 키 | 수동. AI 세션에 SSH 정보를 노출해야 함 |
| 서버에서 `git pull` | 서버의 git 자격증명 | 디렉터리가 git repo여야 함 |

기본 제외 항목: `.git`, `node_modules`, `.venv`, `__pycache__`, `.pytest_cache`, `.DS_Store`.

### 8.2.2 무인 배포 (사람 개입 없음)

서버 설정이 아래와 같으면 AI가 **등록 → 소스 업로드 → 계획 → 배포 → 확인 → 롤백**까지
사람 없이 수행할 수 있다.

| 설정 | 값 | 역할 |
|---|---|---|
| `HUB_ENABLE_DEPLOY` | `true` | 배포 허용 |
| `HUB_ENABLE_SOURCE_UPLOAD` | `true` | 소스 업로드 허용 |
| `HUB_DEPLOY_AUTO_ROLLBACK` | `true` | 실패 시 자동 롤백 |
| `HUB_DEPLOY_ALLOWED_SERVICES` | (비우면 전체) | 무인 배포 허용 서비스 제한 |
| `HUB_DEPLOY_WEBHOOK_URL` | (선택) | 결과 통지 |

사람이 한 번만 해두면 되는 것: **API 키 발급**(대시보드)과 MCP 클라이언트 설정.
그 외 배포 과정에는 사람이 필요 없다.

### 8.3 금지/주의

- MCP로도 §0의 절대 금지 작업을 우회할 수 없다 (도구 자체가 없다).
- `confirmed=true` 없이 배포를 실행하지 않는다.
- 배포 경로는 **호스트 절대 경로**다. hub 컨테이너 내부 경로를 넣으면 실패한다.
- API 키를 채팅/로그/커밋에 남기지 않는다. 유출 시 즉시 폐기한다.
