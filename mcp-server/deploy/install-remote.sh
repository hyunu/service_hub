#!/usr/bin/env bash
# N100 Service Hub — 원격(HTTP) MCP 설치 스크립트 (AI 실행 가능)
#
#   ./mcp-server/deploy/install-remote.sh --dry-run     # 점검 + unit 출력 (권한 불필요)
#   sudo ./mcp-server/deploy/install-remote.sh          # 실제 설치/갱신
#   sudo ./mcp-server/deploy/install-remote.sh --uninstall
#
# 환경변수로 대상를 바꿀 수 있다 (기본값은 현재 호스트 기준):
#   REPO_DIR  MCP_USER  MCP_GROUP  MCP_HOST  MCP_PORT  HUB_URL  UNIT_PATH  UV_BIN
#
# 보안: 이 스크립트는 API 키를 다루지 않는다. 키는 대시보드에서 발급해
#       **클라이언트 설정**에만 넣는다(서버에 상주 키를 저장하지 않는다).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="$HERE/hub-mcp.service.tmpl"
UNIT_NAME="hub-mcp"

MODE="apply"
DRY=0
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "알 수 없는 옵션: $arg" >&2; exit 2 ;;
  esac
done
if [ "$UNINSTALL" -eq 1 ]; then MODE="uninstall"; elif [ "$DRY" -eq 1 ]; then MODE="dry-run"; fi

log()  { printf '%s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 기본값 --
REPO_DIR="${REPO_DIR:-$(cd "$HERE/../.." && pwd)}"
MCP_USER="${MCP_USER:-${SUDO_USER:-$(id -un)}}"
MCP_HOME="${MCP_HOME:-$(getent passwd "$MCP_USER" | cut -d: -f6)}"
MCP_HOME="${MCP_HOME:-/home/$MCP_USER}"
if [ -z "${MCP_GROUP:-}" ]; then
  # 이 프로젝트의 배포 그룹(hubdeploy)이 있으면 기존 unit 동작을 유지한다.
  if id -nG "$MCP_USER" 2>/dev/null | tr ' ' '\n' | grep -qx hubdeploy; then
    MCP_GROUP="hubdeploy"
  else
    MCP_GROUP="$(id -gn "$MCP_USER")"
  fi
fi
MCP_PORT="${MCP_PORT:-8422}"
MCP_HOST="${MCP_HOST:-$(tailscale ip -4 2>/dev/null | head -n1 || true)}"
MCP_HOST="${MCP_HOST:-127.0.0.1}"
HUB_URL="${HUB_URL:-http://$MCP_HOST:8420/api/v1}"
HUB_HEALTH_URL="${HUB_HEALTH_URL:-$(printf '%s' "$HUB_URL" | sed -E 's#/api/v1/?$##')/healthz}"
UNIT_PATH="${UNIT_PATH:-/etc/systemd/system/$UNIT_NAME.service}"
UV_BIN="${UV_BIN:-$(command -v uv 2>/dev/null || true)}"
UV_BIN="${UV_BIN:-$MCP_HOME/.local/bin/uv}"

show_config() {
  cat <<EOF
설정:
  REPO_DIR   = $REPO_DIR
  MCP_USER   = $MCP_USER (home: $MCP_HOME, group: $MCP_GROUP)
  MCP_HOST   = $MCP_HOST:$MCP_PORT  (tailnet 바인드)
  HUB_URL    = $HUB_URL
  UNIT_PATH  = $UNIT_PATH
  UV_BIN     = $UV_BIN
EOF
}

render_unit() {
  [ -f "$TEMPLATE" ] || fail "템플릿이 없습니다: $TEMPLATE"
  sed -e "s|@REPO_DIR@|$REPO_DIR|g" \
      -e "s|@MCP_USER@|$MCP_USER|g" \
      -e "s|@MCP_GROUP@|$MCP_GROUP|g" \
      -e "s|@MCP_HOME@|$MCP_HOME|g" \
      -e "s|@MCP_HOST@|$MCP_HOST|g" \
      -e "s|@MCP_PORT@|$MCP_PORT|g" \
      -e "s|@HUB_URL@|$HUB_URL|g" \
      -e "s|@UV_BIN@|$UV_BIN|g" \
      "$TEMPLATE"
}

# ---------------------------------------------------------------- 사전 점검 --
preflight() {
  log "== 사전 점검 =="
  [ -f "$REPO_DIR/mcp-server/pyproject.toml" ] \
    || fail "mcp-server 를 찾을 수 없습니다: $REPO_DIR/mcp-server"
  [ -x "$UV_BIN" ] || fail "uv 실행 파일이 없습니다: $UV_BIN (UV_BIN 로 지정)"
  log "  ok: uv $("$UV_BIN" --version 2>/dev/null | awk '{print $2}')"
  getent passwd "$MCP_USER" >/dev/null || fail "사용자 없음: $MCP_USER"
  getent group "$MCP_GROUP" >/dev/null || fail "그룹 없음: $MCP_GROUP"
  log "  ok: user/group"

  if ! curl -fsS -m 5 "$HUB_HEALTH_URL" >/dev/null 2>&1; then
    fail "허브 백엔드 health 실패: $HUB_HEALTH_URL (HUB_URL/HUB_HEALTH_URL 확인)"
  fi
  log "  ok: hub health ($HUB_HEALTH_URL)"

  # 의존성/임포트 (실패 시 uv sync 안내만 하고 중단)
  if ! (cd "$REPO_DIR/mcp-server" && "$UV_BIN" run python -c "import hub_mcp" >/dev/null 2>&1); then
    fail "hub_mcp 임포트 실패 → 먼저 실행: (cd $REPO_DIR/mcp-server && $UV_BIN sync)"
  fi
  log "  ok: hub_mcp import"

  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE ":$MCP_PORT$"; then
    if systemctl is-active --quiet "$UNIT_NAME" 2>/dev/null; then
      log "  note: $UNIT_NAME 이미 실행 중 — 재시작으로 갱신됩니다"
    else
      fail "포트 $MCP_PORT 가 이미 사용 중입니다 (ss -ltnp | grep $MCP_PORT)"
    fi
  else
    log "  ok: 포트 $MCP_PORT 사용 가능"
  fi
}

# ------------------------------------------------------------------ 설치 --
apply_install() {
  [ "$(id -u)" -eq 0 ] || fail "실제 설치는 root 권한이 필요합니다. 먼저 --dry-run 후 sudo 로 실행하세요."
  preflight
  local tmp
  tmp="$(mktemp)"
  render_unit > "$tmp"
  log "== unit 렌더링 =="
  sed 's/^/  | /' "$tmp"

  if [ -f "$UNIT_PATH" ]; then
    local bak="$UNIT_PATH.bak-$(date +%Y%m%d-%H%M%S)"
    cp -p "$UNIT_PATH" "$bak"
    log "기존 unit 백업: $bak"
  fi
  install -m 644 "$tmp" "$UNIT_PATH"
  rm -f "$tmp"

  systemctl daemon-reload
  systemctl enable "$UNIT_NAME" >/dev/null
  systemctl restart "$UNIT_NAME"
  sleep 2

  systemctl is-active --quiet "$UNIT_NAME" \
    || { journalctl -u "$UNIT_NAME" -n 30 --no-pager >&2; fail "$UNIT_NAME 기동 실패"; }
  ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE ":$MCP_PORT$" \
    || fail "$UNIT_NAME 는 active지만 $MCP_PORT LISTEN 이 없습니다"

  log ""
  log "설치 완료: http://$MCP_HOST:$MCP_PORT/mcp"
  log "다음 단계(클라이언트): API 키를 대시보드에서 발급해 X-API-Key 헤더로 전달."
  log "검증: X-API-Key 없이 호출하면 401, 키가 있으면 initialize 200."
}

# ------------------------------------------------------------------ 제거 --
uninstall() {
  if [ "$DRY" -eq 1 ]; then
    log "[dry-run] 실행 예정:"
    log "  systemctl disable --now $UNIT_NAME"
    log "  rm -f $UNIT_PATH && systemctl daemon-reload"
    return
  fi
  [ "$(id -u)" -eq 0 ] || fail "제거는 root 권한이 필요합니다."
  systemctl disable --now "$UNIT_NAME" 2>/dev/null || true
  rm -f "$UNIT_PATH"
  systemctl daemon-reload
  log "제거 완료: $UNIT_NAME"
}

# ------------------------------------------------------------------ main --
show_config
case "$MODE" in
  dry-run)
    preflight
    log ""
    log "== 렌더링될 unit (기록하지 않음) =="
    render_unit | sed 's/^/  | /'
    log ""
    log "실제 적용: sudo REPO_DIR='$REPO_DIR' MCP_HOST='$MCP_HOST' ./mcp-server/deploy/install-remote.sh"
    ;;
  apply) apply_install ;;
  uninstall) uninstall ;;
esac
