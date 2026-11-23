# AI 온보딩 — 이 PC에서 Service Hub 사용 준비

> 최신본: `http://100.85.245.79:8421/docs/AI-ONBOARDING.md` (tailnet 전용)
> 설정 스크립트: `http://100.85.245.79:8421/scripts/ai-onboard.sh`
> 소스 업로더: `http://100.85.245.79:8421/scripts/hub-source-upload.sh`
>
> 이 문서와 스크립트는 허브 프런트엔드에서 **읽기 전용으로 제공**됩니다.
> 저장소가 없는 PC에서도 위 URL만으로 시작할 수 있습니다(tailnet 연결 필요).
>
> **이 문서를 받은 AI에게**
> 목표는 이 PC에서 **N100 Service Hub MCP를 사용할 수 있게 준비**하고, 이후 이 PC의
> 프로젝트를 허브로 **배포·운영**할 수 있게 만드는 것이다. 아래 절차를 끝까지 수행하고,
> 마지막 **완료 체크리스트**를 모두 통과했을 때만 "준비 완료"라고 보고하라.
> 실패하면 추측으로 우회하지 말고 **중단하고 사용자에게 정확한 명령/사유를 보고**하라.

---

## 0. 완료 조건 (Definition of Done)

- [ ] 허브 API health 200
- [ ] MCP 클라이언트 설정 파일에 `n100-service-hub` 등록 (키 포함, 파일 권한 600)
- [ ] MCP `initialize` 200 + `tools/list`에 `hub_*` 도구 노출 (현재 28개)
- [ ] `hub_capabilities` 호출 성공 (`ok: true`)
- [ ] (배포까지 할 경우) 소스 업로드 경로 확보 — 로컬 stdio MCP 또는 REST 업로드
- [ ] 키를 화면/로그/커밋에 출력하지 않음

---

## 1. 보안 모델 — 사람이 하는 일은 **단 하나**

| 항목 | 동작 |
|---|---|
| API 키 발급 | **대시보드 Settings → API 키** (평문 1회 표시) 또는 **AI 등록 토큰**(1회용) |
| 키 보관 | 이 PC의 `~/.config/n100-hub/api-key` (0600) — AI는 읽되 **출력 금지** |
| 서버 키 | 서버는 키를 저장하지 않음. 요청마다 `X-API-Key`로 전달 |
| 네트워크 | 허브/MCP는 **tailnet 전용** (공인 인터넷 노출 없음) |
| 권한 | `read`(조회) / `write`·`deploy`(변경·배포), 만료·폐기 가능 |
| 감사 | 변경 작업은 허브 감사 로그에 기록 |

**사람이 하는 일은 둘 중 하나** (권장: A)

**A. 일회용 등록 토큰 (키 복사 없음)**
1. 대시보드 `http://100.85.245.79:8421/settings` → **API 키** → **AI 등록 토큰** → 이름/권한/유효(분) → 발급
2. 표시된 `enroll_...` 토큰을 AI에 전달 (10분 후 자동 만료, 1회용)
3. AI가 자동 교환:
   ```bash
   HUB_ENROLL_TOKEN='enroll_...' ./scripts/ai-onboard.sh --client opencode
   # → /auth/enroll 로 API 키 발급 → ~/.config/n100-hub/api-key (0600) 저장
   ```

**B. API 키 직접 발급**
```bash
# 사용자(사람)가 실행 — 입력은 화면에 보이지 않는다
umask 077
mkdir -p ~/.config/n100-hub
read -rsp 'Service Hub API key: ' KEY; printf '%s' "$KEY" > ~/.config/n100-hub/api-key; unset KEY
chmod 600 ~/.config/n100-hub/api-key
```

> AI는 이 파일을 읽어 설정에 넣을 수 있지만, **값을 채팅/로그/커밋에 출력하면 안 된다.**
> 키가 노출됐다면 즉시 대시보드에서 폐기 후 재발급한다.
> 등록 토큰은 서버에서 `HUB_ENABLE_ENROLLMENT=true`일 때만 동작한다.

---

## 2. 30초 요약 — 자동 스크립트

**저장소가 이 PC에 있는 경우**:

```bash
./scripts/ai-onboard.sh --dry-run          # 무엇을 바꿀지 미리 확인 (기록 없음)
./scripts/ai-onboard.sh --client opencode  # 실제 설정 (opencode 예시)
```

**저장소가 없는 PC(원격 전용)** — 허브에서 문서/스크립트를 받아 실행:

```bash
curl -fsS http://100.85.245.79:8421/docs/AI-ONBOARDING.md -o /tmp/AI-ONBOARDING.md
curl -fsS http://100.85.245.79:8421/scripts/ai-onboard.sh -o /tmp/ai-onboard.sh
bash /tmp/ai-onboard.sh --mode remote --client opencode \
  --hub-url http://100.85.245.79:8420/api/v1
```

- `--mode auto`(기본): 저장소+uv가 있으면 **local stdio**(소스 업로드 가능), 없으면 **remote HTTP**
- `--client opencode|cursor|print` : 설정 대상 / 출력만
- `--hub-url`, `--hub-host`, `--key-file`, `--mode`, `--dry-run`
- 설정 파일은 백업 후 600 권한으로 기록하고, 키 값은 출력하지 않는다.
- `HUB_ENROLL_TOKEN`이 있으면 키 파일이 없어도 자동 교환한다:
  ```bash
  HUB_ENROLL_TOKEN='enroll_...' ./scripts/ai-onboard.sh --client opencode
  ```
- 저장소가 없는 PC에서도 등록 토큰으로 시작할 수 있다:
  ```bash
  HUB_ENROLL_TOKEN='enroll_...' bash /tmp/ai-onboard.sh --mode remote \
    --client opencode --hub-url http://100.85.245.79:8420/api/v1
  ```

스크립트를 쓸 수 없으면 아래 수동 절차를 따른다.

---

## 3. 수동 절차

### 3.1 사전 확인

```bash
# tailnet + 허브 health
tailscale status | grep -i n100-pve-dev
curl -s -o /dev/null -w '%{http_code}\n' http://100.85.245.79:8420/healthz   # 200

# (local 모드용) 저장소와 uv
test -d mcp-server && uv --version
```

허브 IP가 다르면 이 문서의 `100.85.245.79`를 실제 tailnet IP로 바꾼다.

### 3.2 모드 선택

| 이 PC의 상황 | 모드 | 소스 업로드 |
|---|---|---|
| 저장소 + `uv` 있음 | **local stdio** (권장) | `hub_service_sync_source`로 **내 PC 소스 직접 업로드** |
| 저장소/uv 없음, 서버만 접근 | **remote HTTP** | REST `POST /services/{id}/source`에 tar.gz 업로드 |

> 원격 HTTP MCP는 **MCP 서버가 실행 중인 N100의 파일만** 읽는다. 이 PC 소스를 올리려면
> local 모드이거나 REST 업로드를 써야 한다.

### 3.3 키 확인 (AI)

```python
# 키 값을 출력하지 않고 존재/길이만 확인
import os
p = os.path.expanduser("~/.config/n100-hub/api-key")
key = open(p).read().strip() if os.path.exists(p) else ""
assert key.startswith("hub_"), "키 파일이 없거나 형식이 다릅니다. 사용자에게 발급을 요청하세요."
print("key ok, length:", len(key))
```

### 3.4 모드 A — local stdio (권장)

```bash
cd mcp-server
uv sync
uv run hub-mcp --print-config    # 설정 골격 확인 (키 플레이스홀더)
```

클라이언트 설정 예 (OpenCode는 `~/.config/opencode/opencode.jsonc`):

```jsonc
"n100-service-hub": {
  "type": "local",
  "command": ["uv", "run", "--project", "/ABS/PATH/service_hub/mcp-server", "hub-mcp"],
  "environment": {
    "HUB_URL": "http://100.85.245.79:8420/api/v1",
    "HUB_API_KEY": "<~/.config/n100-hub/api-key 값>"
  }
}
```

- `HUB_API_KEY`는 AI가 키 파일에서 읽어 **무출력으로 주입**한다.
- 설정 파일 권한은 `600`.

### 3.5 모드 B — remote HTTP

```jsonc
"n100-service-hub": {
  "type": "remote",
  "url": "http://100.85.245.79:8422/mcp",
  "oauth": false,
  "headers": { "X-API-Key": "<~/.config/n100-hub/api-key 값>" }
}
```

소스 업로드(원격 모드) — 저장소의 헬퍼 사용:

```bash
./scripts/hub-source-upload.sh my-app /path/to/project --dry-run
./scripts/hub-source-upload.sh my-app /path/to/project
```

저장소가 없는 PC에서는 허브에서 받아 실행:

```bash
curl -fsS http://100.85.245.79:8421/scripts/hub-source-upload.sh -o /tmp/hub-source-upload.sh
HUB_URL=http://100.85.245.79:8420/api/v1 \
  bash /tmp/hub-source-upload.sh my-app /path/to/project
```

또는 직접:

```bash
KEY="$(cat ~/.config/n100-hub/api-key)"
tar -czf /tmp/svc.tgz -C /path/to/project .
curl -sS -X POST http://100.85.245.79:8420/api/v1/services/my-app/source \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/gzip' \
  --data-binary @/tmp/svc.tgz
```

### 3.6 검증 (필수)

```bash
KEY="$(cat ~/.config/n100-hub/api-key)"
API=http://100.85.245.79:8420/api/v1

# 1) 키/권한
curl -s -H "X-API-Key: $KEY" $API/system/capabilities \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('ok', d['auth']['scopes'], 'deploy', d['deploy']['enabled'])"

# 2) MCP initialize (remote)
curl -s -o /dev/null -w 'mcp initialize=%{http_code}\n' -X POST http://100.85.245.79:8422/mcp \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"onboard","version":"1"}}}'

# 3) 클라이언트에서 hub_capabilities / hub_status 호출 성공 확인
```

> `hub_capabilities.auth.scopes`가 `["read"]`뿐이면 배포/변경은 403이다.
> 배포까지 하려면 `write`/`deploy`(또는 `*`) scope로 재발급한다.

---

## 4. 서비스 생성 → 배포 플레이북

전체 규칙은 `docs/MCP.md §3`, 도구 안내는 `hub_deployment_guide`가 권위 문서다.
AI는 배포 전에 **항상** `hub_deployment_guide`를 먼저 호출한다.

### 4.1 프로젝트에 파일 2개 추가

`service.yaml` (schema v1):

```yaml
schema_version: 1
service:
  id: my-app                 # 소문자/숫자/하이픈 3~64자, compose 파일과 같은 디렉터리
  name: My App
  description: 무엇을 하는 서비스인지
  category: web
deployment:
  type: docker-compose
  compose_file: compose.yaml
containers:
  - name: web                # compose.yaml 의 services.web 과 동일
    role: frontend
    required: true
endpoints:
  - name: web
    type: http
    exposure: host           # host | proxy | internal
    host_port: 50021         # 50000-59999, hub_ports_available 로 확인
    container: web
    container_port: 3000
    health_path: /healthz
security:
  required_env: [APP_SECRET] # 값 금지 — 이름만
```

`compose.yaml` 의 서비스명은 `containers[].name`과 일치해야 한다.
시크릿은 `/srv/services/<id>/.env`(600/660)에 두고 `service.yaml`에는 이름만 적는다.

### 4.2 배포 순서 (MCP)

```
hub_capabilities
hub_service_spec_guide
hub_ports_available → (필요 시 hub_port_reserve)
hub_service_scaffold (신규) 또는 기존 디렉터리 사용
hub_service_validate
hub_service_register (신규) / hub_service_apply (갱신)
hub_service_sync_source (local)  또는  REST 업로드 (remote)
hub_deploy_plan   → result=READY, impact 비어 있음
hub_deploy_apply(service_id, confirmed=true)
hub_deploy_status → succeeded
hub_service_get / hub_service_access
```

- 포트는 **50000-59999**만 host 노출 허용.
- `hub_deploy_apply`는 `confirmed=true` 필수이며, 실패 시 자동 롤백(`HUB_DEPLOY_AUTO_ROLLBACK=true`).
- 서비스 중지/재시작: `hub_service_stop`/`hub_service_restart` (`confirmed=true`).

### 4.3 운영 확인

```
hub_service_get(service_id)      # 컨테이너 running/healthy
hub_service_logs(service_id)     # 로그
hub_service_access(service_id)   # URL·인증 참조·health 경로
hub_deployments_list(service_id) # 이력, 롤백 대상 확인
```

---

## 5. 실패 매트릭스

| 증상 | 원인 | 조치 |
|---|---|---|
| `401 unauthorized` | 키 없음/오타/폐기/만료 | 대시보드에서 재발급 → 키 파일 교체 |
| `401 invalid_enrollment_token` | 토큰 만료/사용/폐기/오타 | 대시보드에서 새 토큰 발급(1회용) |
| `503 enrollment_disabled` | 서버 `HUB_ENABLE_ENROLLMENT=false` | 운영자가 `.env`에서 켜고 backend 재기동 |
| `403 insufficient_scope` | `read` 키 | `write`/`*` scope 재발급 |
| MCP 도구가 안 보임 | 클라이언트 재시작 필요 / URL 오류 | 앱 재시작, `/mcp` 경로 확인 |
| remote 모드에서 sync 실패 | 원격은 N100 파일만 읽음 | local 모드 또는 `hub-source-upload.sh` |
| `413 source_too_large` | 200MB 초과 | 제외 패턴 추가(`node_modules` 등) |
| `409 plan_not_ready` | 포트/env/계획 문제 | `impact` 확인, 포트 재선택 |
| `503 deploy_disabled` | 서버 게이트 꺼짐 | AI가 임의로 켜지 말고 사용자에게 보고 |
| `403 protected_container` | 보호 대상 서비스 | 사용자 승인 없이 보호 해제 금지 |
| `opencode.jsonc` 파싱 실패 | 기존 파일에 주석(`//`)이 있음 | `--client print`로 출력해 수동 병합(백업 후) |

---

## 6. 키 회수/정리

```bash
# 이 PC에서 제거
rm -f ~/.config/n100-hub/api-key
# 클라이언트 설정에서 n100-service-hub 블록 제거 (백업 후)
```

대시보드에서 키를 **폐기**하면 이 PC의 접근이 즉시 끊긴다.

---

## 7. AI 실행 규칙 (요약)

1. 키를 출력/커밋/채팅에 남기지 않는다. 길이/성공 여부만 보고한다.
2. `--dry-run` 없이 설정 파일을 덮어쓰지 않는다. 기존 파일은 백업한다.
3. 허브/MCP를 `0.0.0.0`에 노출하지 않는다(tailnet 전용 유지).
4. 보호 대상/기존 서비스는 사용자 승인 없이 중지·삭제·보호 해제하지 않는다.
5. 배포 전 `hub_deployment_guide` → `hub_deploy_plan(READY)` 확인.
6. 실패 시 추측으로 반복하지 말고, 마지막 오류 코드와 확인한 값을 보고한다.

---

## 8. 사용자용 프롬프트 템플릿

```
http://100.85.245.79:8421/docs/AI-ONBOARDING.md 를 읽고, 이 PC에서 N100 Service Hub MCP
사용 준비를 끝까지 수행해줘. API 키는 ~/.config/n100-hub/api-key 에 있어. 없으면 나에게
"대시보드 Settings → API 키에서 발급해서 파일로 넣어달라"고 요청해.
준비가 끝나면 완료 체크리스트 결과만 보고하고, 키 값은 절대 출력하지 마.
그 다음 내 프로젝트를 이 허브로 배포하는 것까지 도와줘.
```
