#!/usr/bin/env bash
# 프로젝트 디렉터리를 tar.gz 로 묶어 허브의 /services/<id>/source 로 업로드한다.
# 원격 MCP(HTTP)만 쓰는 PC에서 소스 배포를 가능하게 하는 헬퍼.
#
#   ./scripts/hub-source-upload.sh <service-id> <project-dir> [--dry-run] [--max-mb N]
#
# 키: HUB_API_KEY 또는 ~/.config/n100-hub/api-key (값은 출력하지 않는다)
set -euo pipefail

SERVICE_ID="${1:-}"
PROJECT_DIR="${2:-}"
shift $(( $# > 2 ? 2 : $# ))
DRY=0
MAX_MB=200
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --max-mb) MAX_MB="$2"; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
  esac
  shift
done

log()  { printf '%s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

[ -n "$SERVICE_ID" ] && [ -n "$PROJECT_DIR" ] || fail "사용법: $0 <service-id> <project-dir>"
printf '%s' "$SERVICE_ID" | grep -qE '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$' \
  || fail "service-id 형식 오류(소문자/숫자/하이픈)"
[ -d "$PROJECT_DIR" ] || fail "디렉터리가 없습니다: $PROJECT_DIR"
[ -f "$PROJECT_DIR/compose.yaml" ] || fail "compose.yaml 이 없습니다: $PROJECT_DIR"
[ -f "$PROJECT_DIR/service.yaml" ] || fail "service.yaml 이 없습니다: $PROJECT_DIR"

KEY="${HUB_API_KEY:-}"
if [ -z "$KEY" ]; then
  KEY_FILE="${HOME}/.config/n100-hub/api-key"
  [ -f "$KEY_FILE" ] || fail "키 파일이 없습니다: $KEY_FILE"
  KEY="$(tr -d '\r\n' < "$KEY_FILE")"
fi
case "$KEY" in hub_*) ;; *) fail "API 키 형식이 아닙니다(hub_...)" ;; esac

if [ -z "${HUB_URL:-}" ]; then
  HOST="$(tailscale status --json 2>/dev/null | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: raise SystemExit(0)
for p in d.get("Peer",{}).values():
    if p.get("HostName")=="n100-pve-dev":
        print(next((ip for ip in (p.get("TailscaleIPs") or []) if ":" not in ip),"")); break
' || true)"
  [ -n "$HOST" ] || fail "HUB_URL 을 지정하세요 (tailnet에서 n100-pve-dev를 찾지 못함)"
  HUB_URL="http://$HOST:8420/api/v1"
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ARCHIVE="$TMP/source.tar.gz"

tar -czf "$ARCHIVE" \
  --exclude='.git' --exclude='node_modules' --exclude='.venv' --exclude='venv' \
  --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.mypy_cache' \
  --exclude='.DS_Store' --exclude='dist' --exclude='build' --exclude='*.pyc' \
  -C "$PROJECT_DIR" .

SIZE_MB="$(du -m "$ARCHIVE" | awk '{print $1}')"
FILES="$(tar -tzf "$ARCHIVE" | wc -l | tr -d ' ')"
log "archive: ${SIZE_MB}MB, ${FILES} entries (limit ${MAX_MB}MB)"
[ "$SIZE_MB" -le "$MAX_MB" ] || fail "아카이브가 너무 큽니다(${SIZE_MB}MB > ${MAX_MB}MB). 제외 패턴을 늘리세요."

if [ "$DRY" -eq 1 ]; then
  log "[dry-run] 업로드하지 않았습니다."
  exit 0
fi

log "uploading to $HUB_URL/services/$SERVICE_ID/source ..."
CODE="$(curl -sS -o "$TMP/resp.json" -w '%{http_code}' -X POST \
  "$HUB_URL/services/$SERVICE_ID/source" \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/gzip' \
  --data-binary "@$ARCHIVE" || true)"
log "HTTP $CODE"
python3 - "$TMP/resp.json" <<'PY' || true
import json,sys
try:
    d=json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit(0)
if isinstance(d,dict):
    print(json.dumps({k:d[k] for k in ("ok","target","files","bytes","error","code") if k in d},
                     ensure_ascii=False, indent=2))
PY
case "$CODE" in 200|201) ;; *) fail "업로드 실패 (HTTP $CODE)" ;; esac
log "완료. 다음: hub_deploy_plan → READY → hub_deploy_apply(confirmed=true)"
