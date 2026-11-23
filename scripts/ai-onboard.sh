#!/usr/bin/env bash
# 이 PC에서 N100 Service Hub MCP 사용 준비를 자동화한다.
#
#   ./scripts/ai-onboard.sh --dry-run
#   ./scripts/ai-onboard.sh --client opencode
#   ./scripts/ai-onboard.sh --client cursor --mode remote
#   ./scripts/ai-onboard.sh --client print
#
# 키: HUB_API_KEY 환경변수 또는 --key-file (기본 ~/.config/n100-hub/api-key)
#     HUB_ENROLL_TOKEN 이 있으면 /auth/enroll 로 1회 교환해 키 파일을 자동 생성한다.
#     키/토큰 값은 절대 출력하지 않는다.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -d "$REPO_DIR/mcp-server" ] || REPO_DIR=""   # 저장소 없이 내려받아 실행하는 경우
KEY_FILE="${HOME}/.config/n100-hub/api-key"
HUB_URL=""
HUB_HOST=""
MCP_URL=""
MODE="auto"
CLIENT="opencode"
DRY=0
VERIFY=1

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --key-file) KEY_FILE="$2"; shift ;;
    --hub-url) HUB_URL="$2"; shift ;;
    --hub-host) HUB_HOST="$2"; shift ;;
    --mcp-url) MCP_URL="$2"; shift ;;
    --mode) MODE="$2"; shift ;;
    --client) CLIENT="$2"; shift ;;
    --no-verify) VERIFY=0 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
  esac
  shift
done

log()  { printf '%s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------- 허브 주소 --
if [ -z "$HUB_URL" ]; then
  if [ -z "$HUB_HOST" ] && command -v tailscale >/dev/null 2>&1; then
    HUB_HOST="$(tailscale status --json 2>/dev/null | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    raise SystemExit(0)
for p in d.get("Peer",{}).values():
    if p.get("HostName")=="n100-pve-dev":
        ips=p.get("TailscaleIPs") or []
        print(next((ip for ip in ips if ":" not in ip), ""))
        break
' || true)"
  fi
  [ -n "$HUB_HOST" ] || fail "--hub-url 또는 --hub-host 를 지정하세요 (tailnet에서 n100-pve-dev를 찾지 못함)"
  HUB_URL="http://$HUB_HOST:8420/api/v1"
fi
if [ -z "$MCP_URL" ]; then
  MCP_HOSTPORT="$(printf '%s' "$HUB_URL" | sed -E 's#^https?://##; s#/api/v1/?$##')"
  MCP_HOSTPORT="$(printf '%s' "$MCP_HOSTPORT" | sed -E 's#:[0-9]+$##')"
  MCP_URL="http://$MCP_HOSTPORT:8422/mcp"
fi
HEALTH_URL="$(printf '%s' "$HUB_URL" | sed -E 's#/api/v1/?$##')/healthz"

# --------------------------------------------------- 등록 토큰 자동 교환 --
KEY=""
SKIP_AUTH=0
if [ -n "${HUB_ENROLL_TOKEN:-}" ] && [ -z "${HUB_API_KEY:-}" ] && [ ! -f "$KEY_FILE" ]; then
  if [ "$DRY" -eq 1 ]; then
    # 1회용 토큰을 dry-run 에서 소모하지 않는다.
    SKIP_AUTH=1
    log "== 등록 토큰 (dry-run) =="
    log "  note: 토큰을 소모하지 않도록 교환을 생략합니다 (실제 실행 시 1회 교환)"
  else
    log "== 등록 토큰 교환 (1회용) =="
    RESP=""
    for i in 1 2 3; do
      RESP="$(curl -fsS -m 15 -X POST "$HUB_URL/auth/enroll" \
        -H 'Content-Type: application/json' \
        -d "{\"token\":\"$HUB_ENROLL_TOKEN\"}" 2>/dev/null || true)"
      [ -n "$RESP" ] && break
      sleep 1
    done
    KEY="$(printf '%s' "$RESP" | python3 -c '
import json,sys
try:
    print(json.load(sys.stdin).get("api_key",""))
except Exception:
    print("")
' 2>/dev/null)"
    [ -n "$KEY" ] || fail "등록 토큰 교환 실패 — 만료/사용/폐기 또는 HUB_ENABLE_ENROLLMENT 확인"
    mkdir -p "$(dirname "$KEY_FILE")"
    printf '%s' "$KEY" > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    log "  ok: API 키 발급 → $KEY_FILE (값 미출력)"
    unset RESP
  fi
fi

# ------------------------------------------------------------------ 키 --
if [ "$SKIP_AUTH" -eq 0 ] && [ -z "$KEY" ]; then
  if [ -n "${HUB_API_KEY:-}" ]; then
    KEY="$HUB_API_KEY"
  else
    [ -f "$KEY_FILE" ] || fail "키 파일이 없습니다: $KEY_FILE — 대시보드 Settings → API 키에서 발급해 저장하세요."
    KEY="$(tr -d '\r\n' < "$KEY_FILE")"
  fi
fi
if [ "$SKIP_AUTH" -eq 0 ]; then
  case "$KEY" in hub_*) ;; *) fail "API 키 형식이 아닙니다(hub_...). 대시보드에서 재발급하세요." ;; esac
fi

# ----------------------------------------------------------------- 모드 --
case "$MODE" in
  auto)
    if command -v uv >/dev/null 2>&1 && [ -d "$REPO_DIR/mcp-server" ]; then
      MODE="local"
    else
      MODE="remote"
    fi
    ;;
  local|remote) ;;
  *) fail "--mode 는 auto|local|remote 중 하나" ;;
esac
if [ "$MODE" = "local" ] && ! command -v uv >/dev/null 2>&1; then
  fail "local 모드는 uv 가 필요합니다. uv 설치 또는 --mode remote"
fi
if [ "$MODE" = "local" ] && [ -z "$REPO_DIR" ]; then
  fail "local 모드는 저장소(mcp-server)가 필요합니다. --mode remote 또는 저장소 경로에서 실행"
fi

case "$CLIENT" in
  opencode) CONFIG="${HOME}/.config/opencode/opencode.jsonc" ;;
  cursor)   CONFIG="${HOME}/.cursor/mcp.json" ;;
  print)    CONFIG="" ;;
  *) fail "--client 는 opencode|cursor|print 중 하나" ;;
esac

log "== 온보딩 설정 =="
log "  repo   : ${REPO_DIR:-(없음 — remote 전용)}"
log "  hub    : $HUB_URL"
log "  mcp    : $MCP_URL"
log "  mode   : $MODE"
log "  client : $CLIENT${CONFIG:+ ($CONFIG)}"
if [ "$SKIP_AUTH" -eq 1 ]; then
  log "  key    : (dry-run — 교환 생략)"
else
  log "  key    : ${KEY_FILE} (length ${#KEY})"   # 값은 출력하지 않는다
fi

# -------------------------------------------------------------- 사전 점검 --
log "== 사전 점검 =="
for i in 1 2 3; do
  curl -fsS -m 10 "$HEALTH_URL" >/dev/null 2>&1 && break
  [ "$i" -eq 3 ] && fail "허브 health 실패: $HEALTH_URL (tailnet/주소 확인)"
  sleep 1
done
log "  ok: hub health"
CAPS=""
if [ "$SKIP_AUTH" -eq 1 ]; then
  log "  note: auth 점검 생략 (dry-run, 토큰 미소모)"
else
  for i in 1 2 3; do
    CAPS="$(curl -fsS -m 15 -H "X-API-Key: $KEY" "$HUB_URL/system/capabilities" 2>/dev/null || true)"
    [ -n "$CAPS" ] && break
    sleep 1
  done
  [ -n "$CAPS" ] || fail "API 키 인증 실패(401/403) 또는 허브 응답 없음. 대시보드에서 키 상태/scope 확인"
  printf '%s' "$CAPS" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("  ok: api key", d.get("auth",{}).get("scopes"), "| deploy:", d.get("deploy",{}).get("enabled"))
'
fi
if [ "$MODE" = "local" ]; then
  if [ "$DRY" -eq 1 ]; then
    # dry-run 은 환경을 변경하지 않는다 (uv sync 생략).
    (cd "$REPO_DIR/mcp-server" && uv run python -c "import hub_mcp" >/dev/null 2>&1) \
      || log "  warn: hub_mcp 임포트 실패 — 실제 실행 시 uv sync 가 수행됩니다"
  else
    (cd "$REPO_DIR/mcp-server" && uv sync --quiet) || fail "uv sync 실패"
    (cd "$REPO_DIR/mcp-server" && uv run python -c "import hub_mcp" >/dev/null) \
      || fail "hub_mcp 임포트 실패"
  fi
  log "  ok: local mcp 준비"
fi

# ------------------------------------------------------------ 설정 기록 --
if [ "$DRY" -eq 1 ]; then
  log "== [dry-run] 기록 예정 설정 (키는 플레이스홀더) =="
  python3 - "$MODE" "$HUB_URL" "$MCP_URL" "$REPO_DIR" <<'PY'
import json,sys,os
mode,hub,mcp,repo=sys.argv[1:5]
if mode=="local":
    entry={"type":"local","command":["uv","run","--project",os.path.join(repo,"mcp-server"),"hub-mcp"],
           "environment":{"HUB_URL":hub,"HUB_API_KEY":"<HUB_API_KEY>"}}
else:
    entry={"type":"remote","url":mcp,"oauth":False,"headers":{"X-API-Key":"<HUB_API_KEY>"}}
print(json.dumps({"n100-service-hub":entry},ensure_ascii=False,indent=2))
PY
  log "  (설정 파일은 변경하지 않았습니다)"
  exit 0
fi

write_json() {
  local path="$1" shape="$2"
  mkdir -p "$(dirname "$path")"
  [ -f "$path" ] && { cp -p "$path" "$path.bak-$(date +%Y%m%d-%H%M%S)"; log "  backup: $path.bak-*"; }
  KEY="$KEY" python3 - "$path" "$shape" "$MODE" "$HUB_URL" "$MCP_URL" "$REPO_DIR" <<'PY'
import json,os,sys,time
path,shape,mode,hub,mcp,repo=sys.argv[1:7]
key=os.environ["KEY"]
try:
    cfg=json.load(open(path)) if os.path.exists(path) else {}
except Exception:
    raise SystemExit(f"FAIL: {path} JSON 파싱 실패 — 수동으로 n100-service-hub 블록을 추가하세요.")
if shape=="opencode":
    if mode=="local":
        entry={"type":"local",
               "command":["uv","run","--project",os.path.join(repo,"mcp-server"),"hub-mcp"],
               "environment":{"HUB_URL":hub,"HUB_API_KEY":key}}
    else:
        entry={"type":"remote","url":mcp,"oauth":False,"headers":{"X-API-Key":key}}
    cfg.setdefault("mcp",{}).setdefault("servers",{})["n100-service-hub"]=entry
else:  # cursor mcp.json
    if mode=="local":
        entry={"command":"uv","args":["run","--project",os.path.join(repo,"mcp-server"),"hub-mcp"],
               "env":{"HUB_URL":hub,"HUB_API_KEY":key}}
    else:
        entry={"url":mcp,"headers":{"X-API-Key":key}}
    cfg.setdefault("mcpServers",{})["n100-service-hub"]=entry
with open(path,"w",encoding="utf-8") as fh:
    json.dump(cfg,fh,ensure_ascii=False,indent=2); fh.write("\n")
os.chmod(path,0o600)
print("  wrote:",path,"| mode:",mode,"| keylen:",len(key))
PY
}

case "$CLIENT" in
  opencode) write_json "$CONFIG" opencode ;;
  cursor)   write_json "$CONFIG" cursor ;;
  print)
    log "== 클라이언트 설정 (키는 플레이스홀더 — 직접 주입) =="
    python3 - "$MODE" "$HUB_URL" "$MCP_URL" "$REPO_DIR" <<'PY'
import json,sys,os
mode,hub,mcp,repo=sys.argv[1:5]
entry={"type":"local","command":["uv","run","--project",os.path.join(repo,"mcp-server"),"hub-mcp"],
       "environment":{"HUB_URL":hub,"HUB_API_KEY":"<HUB_API_KEY>"}} if mode=="local" else \
      {"type":"remote","url":mcp,"oauth":False,"headers":{"X-API-Key":"<HUB_API_KEY>"}}
print(json.dumps({"mcpServers":{"n100-service-hub":entry}},ensure_ascii=False,indent=2))
PY
    ;;
esac

# ---------------------------------------------------------------- 검증 --
if [ "$VERIFY" -eq 1 ]; then
  log "== 검증 =="
  if [ "$MODE" = "remote" ]; then
    CODE=""
    for i in 1 2 3; do
      CODE="$(curl -s -o /dev/null -w '%{http_code}' -m 15 -X POST "$MCP_URL" \
        -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
        -H 'Accept: application/json, text/event-stream' \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"onboard","version":"1"}}}' || true)"
      [ "$CODE" = "200" ] && break
      sleep 1
    done
    [ "$CODE" = "200" ] || fail "MCP initialize 실패 (HTTP ${CODE:-timeout}) — URL/키/tailnet 확인"
    log "  ok: mcp initialize 200"
  else
    (cd "$REPO_DIR/mcp-server" && uv run python -c "import hub_mcp" >/dev/null) \
      || fail "local MCP 임포트 실패"
    log "  ok: local MCP 실행 준비"
  fi
fi

log ""
log "완료. 클라이언트를 재시작한 뒤 도구 목록에 hub_* 가 보이는지 확인하세요."
log "다음: docs/AI-ONBOARDING.md §4 (서비스 생성 → 배포)"
