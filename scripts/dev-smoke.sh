#!/usr/bin/env bash
# 로컬 스모크 테스트: 백엔드 기동 → CLI로 상태 조회 → 종료.
# 기존 Docker 컨테이너는 어떤 경우에도 건드리지 않는다 (인벤토리 읽기 전용).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${SMOKE_PORT:-8451}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; [ -n "${BACK_PID:-}" ] && kill "$BACK_PID" 2>/dev/null || true' EXIT

echo "[1/4] 백엔드 기동 (port $PORT, db=$TMP/hub.db)"
(cd "$REPO/backend" && \
  HUB_DB_PATH="$TMP/hub.db" HUB_STATUS_CACHE="$TMP/status.json" HUB_PORT="$PORT" \
  uv run uvicorn app.main:app --port "$PORT" --log-level warning) &
BACK_PID=$!

for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:$PORT/api/v1/system/status" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/api/v1/system/status" >/dev/null || {
  echo "[실패] 백엔드가 기동하지 않았습니다." >&2; exit 1; }
echo "  기동 확인"

echo "[2/4] CLI: hub status"
(cd "$REPO/cli" && HUB_URL="http://127.0.0.1:$PORT/api/v1" uv run hub status)

echo "[3/4] CLI: hub status --json (순수 JSON 검증)"
OUT=$(cd "$REPO/cli" && HUB_URL="http://127.0.0.1:$PORT/api/v1" uv run hub status --json)
python3 -c "import json,sys; json.loads(sys.argv[1])" "$OUT" && echo "  순수 JSON OK"

echo "[4/4] MOTD 캐시 렌더"
HUB_STATUS_CACHE="$TMP/status.json" bash "$REPO/scripts/motd.sh" | head -5 || true

echo "스모크 테스트 완료."
