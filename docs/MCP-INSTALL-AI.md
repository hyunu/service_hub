# MCP 설치 런북 (AI 실행용)

이 문서는 **AI 에이전트가 읽고 스스로 원격 MCP 서버를 설치·검증**하기 위한 절차서다.
사람이 읽어도 동일하게 따라 할 수 있다.

- 대상: N100 Service Hub의 원격(Streamable HTTP) MCP — 기본 `http://<tailnet-ip>:8422/mcp`
- 스크립트: `mcp-server/deploy/install-remote.sh` (사전 점검·렌더링·설치·제거)
- 단위 파일 템플릿: `mcp-server/deploy/hub-mcp.service.tmpl`
- 관련: `docs/MCP.md`, `AI-OPERATIONS.md §8`

---

## 0. 보안 모델 (먼저 이해할 것)

| 항목 | 현재 동작 |
|---|---|
| API 키 발급 | **대시보드 Settings → API 키** (평문 1회 표시, 서버에는 SHA-256 해시만 저장) |
| 키 전달 | **클라이언트가 요청마다 `X-API-Key` 헤더로 전달** (원격), 로컬 stdio는 `env.HUB_API_KEY` |
| 서버 상주 키 | **없음** — MCP 서버는 키를 저장하지 않고 요청 헤더의 키를 그대로 백엔드 호출에 사용 |
| 네트워크 | MCP는 **tailnet IP에만 바인드** (`0.0.0.0` 금지). tailnet이 신뢰 경계 |
| 권한 | 키 scope `read`(조회 전용) / `write`·`deploy`(변경·배포), 만료·폐기 가능 |
| 감사 | 키 사용 시 `last_used_at`, 변경 작업은 감사 로그 기록 |

**AI 금지사항**
- API 키를 채팅·로그·커밋·이 문서에 출력하지 않는다.
- 설치 스크립트에 키를 넘기지 않는다(키는 클라이언트에만).
- `MCP_HOST=0.0.0.0`으로 바꾸지 않는다.
- `sudo`가 필요한 단계를 승인 없이 우회하지 않는다(아래 Phase 2 핸드오프).

---

## 1. 입력값

| 변수 | 기본값 | 비고 |
|---|---|---|
| `REPO_DIR` | 스크립트 기준 저장소 루트 | 서버의 체크아웃 경로 |
| `MCP_USER` | `SUDO_USER` 또는 현재 사용자 | systemd 실행 사용자 |
| `MCP_GROUP` | 해당 사용자의 기본 그룹 | |
| `MCP_HOST` | `tailscale ip -4` 첫 IP, 없으면 `127.0.0.1` | **tailnet IP만** |
| `MCP_PORT` | `8422` | |
| `HUB_URL` | `http://$MCP_HOST:8420/api/v1` | 백엔드 API |
| `UNIT_PATH` | `/etc/systemd/system/hub-mcp.service` | |

필요 도구: `uv`, `curl`, `ss`, `systemctl`, `tailscale`.

---

## 2. 실행 모드

| 상황 | AI가 하는 일 |
|---|---|
| **A. 서버 SSH + sudo 가능** | Phase 0~5를 직접 수행(Phase 2만 승인 확인) |
| **B. SSH만 가능(무sudo)** | Phase 0~1 직접, Phase 2는 사람에게 명령 전달 |
| **C. 서버 접근 불가** | Phase 0~1을 로컬에서 수행할 수 없으므로, 사람에게 전체 스크립트와 절차를 출력 |

---

## Phase 0 — 사전 점검 (권한 불필요)

```bash
cd "$REPO_DIR"
./mcp-server/deploy/install-remote.sh --dry-run
```

스크립트가 자동으로 확인하는 것:
- `mcp-server/pyproject.toml` 존재
- `uv` 실행 가능 (`UV_BIN`)
- `MCP_USER`/`MCP_GROUP` 존재
- `HUB_HEALTH_URL` 200 (`http://<host>:8420/healthz`)
- `hub_mcp` 임포트 가능 (실패 시 `uv sync` 안내 후 중단)
- 포트 8422 사용 가능 또는 기존 `hub-mcp`가 점유 중

**판정**: 모든 줄이 `ok`/`note`여야 진행. `FAIL`이면 아래 표대로 조치 후 다시 Phase 0.

> `--dry-run`은 파일을 쓰지 않고, root도 필요 없다. 렌더링될 unit 전문을 출력한다.

---

## Phase 1 — unit 검토

`--dry-run` 출력의 `ExecStart`/`User`/`HUB_URL`/`--host`가 의도와 같은지 확인한다.

- `--host`는 **tailnet IP**여야 한다.
- `WorkingDirectory`/`--project`는 `$REPO_DIR/mcp-server`.
- `Restart=always`, `NoNewPrivileges=true` 유지.

---

## Phase 2 — 설치/갱신 (root 필요 · 승인 지점)

AI가 sudo를 쓸 수 있으면 승인 후 실행하고, 없으면 **아래 명령을 그대로 사람에게 전달**한다.

```bash
sudo REPO_DIR="/home/hyunu/projects/service_hub" \
     MCP_USER="hyunu" \
     MCP_HOST="<tailnet-ip>" \
     ./mcp-server/deploy/install-remote.sh
```

스크립트가 하는 일(요약):
1. 기존 unit 백업 `/etc/systemd/system/hub-mcp.service.bak-<ts>`
2. unit 렌더링 후 `install -m 644`
3. `daemon-reload` → `enable` → `restart`
4. `is-active` + 8422 LISTEN 확인(실패 시 journal 30줄 출력)

**중단 조건**: `is-active` 실패, 포트 미바인드, health 실패 → Phase 6.

---

## Phase 3 — 서버 검증 (키 불필요)

```bash
systemctl is-active hub-mcp
ss -ltn | grep ':8422'
curl -s -o /dev/null -w '%{http_code}\n' -X POST "http://<tailnet-ip>:8422/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"install-check","version":"1"}}}'
```

기대값:
- `active`
- `LISTEN 0 ... <tailnet-ip>:8422`
- HTTP **200** (헤더가 없으면 401 — 서버가 살아 있다는 증거)

---

## Phase 4 — API 키 발급·전달 (사람)

대시보드: `http://<tailnet-ip>:8421/settings` → **API 키** 탭
- 이름 예: `mcp-<host>-<agent>`
- scope: 배포까지 하면 `*`, 조회만이면 `read`
- 만료(일) 선택 가능
- **평문은 발급 직후 1회만 표시** → 바로 전달

전달 방법 (키를 채팅에 붙여넣지 않는다):

**방법 1 — 사람이 클라이언트 설정에 직접 입력 (AI가 키를 못 봐도 됨)**
- AI가 설정 파일 경로/JSON 골격을 준비 → 사람이 키만 붙여넣기

**방법 2 — 0600 파일로 전달 후 AI가 무출력 주입 (권장)**
```bash
# 사람이 실행 (입력은 화면에 보이지 않음)
umask 077
read -rsp 'API key: ' KEY; printf '%s' "$KEY" > ~/.config/n100-hub.key; unset KEY
chmod 600 ~/.config/n100-hub.key
```
AI는 파일을 **읽어서 설정에 주입**하되 값을 출력하지 않는다. 예(OpenCode):
```python
import json, os
key = open(os.path.expanduser("~/.config/n100-hub.key")).read().strip()
p = os.path.expanduser("~/.config/opencode/opencode.jsonc")
cfg = json.load(open(p))
cfg["mcp"]["servers"]["n100-service-hub"].setdefault("headers", {})["X-API-Key"] = key
json.dump(cfg, open(p, "w"), ensure_ascii=False, indent=2)
os.chmod(p, 0o600)
print("header set, key length:", len(key))   # 값은 출력하지 않는다
```

> 키가 채팅/로그에 노출됐다면 즉시 대시보드에서 **폐기**하고 재발급한다.

---

## Phase 5 — 클라이언트 검증

원격(OpenCode/Cursor/Claude 등) — `X-API-Key` 헤더 필요:
```bash
KEY="$(cat ~/.config/n100-hub.key)"
curl -s -X POST "http://<tailnet-ip>:8422/mcp" \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"verify","version":"1"}}}' \
  -o /dev/null -w 'initialize=%{http_code}\n'

# tools/list 로 실제 도구 노출 확인 (JSON-RPC id 2)
```
기대: `initialize=200`, `tools/list`에 `hub_capabilities`, `hub_deploy_apply`,
`hub_service_stop`, `hub_service_restart` 등 **28개** 포함.

AI 클라이언트에서 확인:
- 도구 목록에 `hub_*`가 보이는가
- `hub_capabilities` 호출 → `ok: true`, `auth.scopes` 확인
- `read` 키면 변경/배포 도구가 403 `insufficient_scope` (정상)

---

## Phase 6 — 업그레이드 / 제거 / 키 회전

**업그레이드**
```bash
cd "$REPO_DIR" && git pull --ff-only
sudo ./mcp-server/deploy/install-remote.sh      # unit 재렌더 + restart
# Phase 3~5 재검증
```

**제거**
```bash
sudo ./mcp-server/deploy/install-remote.sh --uninstall
./mcp-server/deploy/install-remote.sh --uninstall --dry-run   # 미리보기
```

**키 회전**
1. 대시보드에서 기존 키 폐기 → 새 키 발급
2. Phase 4 방법으로 교체
3. `initialize`/`tools/list` 재검증
4. `schedule: last_used_at`으로 구 키 사용 중지 확인

---

## 실패 매트릭스

| 증상 | 원인 | 조치 |
|---|---|---|
| `FAIL: uv 실행 파일이 없습니다` | PATH/설치 위치 | `UV_BIN=/path/to/uv` 지정 또는 uv 설치 |
| `FAIL: 허브 백엔드 health 실패` | 백엔드 다운/주소 오류 | `HUB_URL`, 8420 바인드 확인 |
| `FAIL: hub_mcp 임포트 실패` | 의존성 미설치 | `(cd mcp-server && uv sync)` |
| `FAIL: 포트 8422 가 이미 사용 중` | 다른 프로세스 | 점유 프로세스 확인, `MCP_PORT` 변경 |
| `unit 기동 실패` | user/path/uv 오류 | `journalctl -u hub-mcp -n 50` |
| `initialize=401` (키 없이) | 정상 | Phase 4로 키 전달 |
| `initialize=401` (키 있이) | 키 폐기/오타/만료 | 재발급 |
| 도구가 일부 안 보임 | 클라이언트 재시작 필요 | 앱 재시작 후 재확인 |
| `403 insufficient_scope` | `read` 키 | `write`/`*` 키로 재발급 |

---

## AI 체크리스트 (완료 선언 전)

- [ ] Phase 0 `--dry-run` 전 항목 ok
- [ ] Phase 2 `systemctl is-active` + 8422 LISTEN
- [ ] Phase 3 `initialize` 200
- [ ] Phase 5 키 포함 `initialize` 200 + `tools/list` 28개
- [ ] `hub_capabilities` 호출 성공
- [ ] 키를 출력/커밋하지 않음
- [ ] `--host`가 tailnet IP (0.0.0.0 아님)
