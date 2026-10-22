#!/usr/bin/env bash
# 관리 레지스트리 DB 복구 (요구사항 §16)
#
# 안전장치:
#   - --yes 없이는 절대 실행하지 않는다
#   - 복구 전 현재 DB를 자동 스냅샷(pre-restore-*.db)한다
#   - 백업 파일 무결성(integrity_check)을 먼저 검사한다
#   - hub-backend 컨테이너만 중지/시작한다 (다른 컨테이너 무영향)
#   - DB는 named volume에서만 교체하며, 소유권을 10001:10001로 맞춘다
#
# 사용법:
#   ./scripts/restore.sh --db /srv/service-hub/backup/db/hub-YYYYmmdd-HHMMSS.db --yes
#   (필요 시 --volume, --container 로 이름 지정)
set -euo pipefail

BACKUP=""
VOLUME="${HUB_VOLUME:-service-hub_hub-data}"
CONTAINER="${HUB_BACKEND_CONTAINER:-hub-backend}"
YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --db) BACKUP="$2"; shift 2 ;;
    --volume) VOLUME="$2"; shift 2 ;;
    --container) CONTAINER="$2"; shift 2 ;;
    --yes) YES=1; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
  esac
done

die() { echo "[오류] $*" >&2; exit 1; }

[ -n "$BACKUP" ] || die "사용법: $0 --db <backup.db> --yes"
[ -f "$BACKUP" ] || die "백업 파일이 없습니다: $BACKUP"
if [ "$YES" -ne 1 ]; then
  echo "복구는 관리 DB를 교체합니다. 계속하려면 --yes 를 붙여 다시 실행하세요." >&2
  exit 4
fi

command -v docker >/dev/null 2>&1 || die "docker가 필요합니다"
docker inspect "$CONTAINER" >/dev/null 2>&1 || die "컨테이너 '$CONTAINER'를 찾을 수 없습니다"
SELF=$(docker inspect -f '{{ index .Config.Labels "com.hub.self" }}' "$CONTAINER" 2>/dev/null || true)
[ "$SELF" = "true" ] || die "'$CONTAINER'는 허브 컨테이너가 아닙니다 (com.hub.self != true)"
docker image inspect alpine:latest >/dev/null 2>&1 || die "alpine:latest 이미지가 필요합니다 (docker pull alpine)"

# 1) 백업 파일 무결성
python3 - "$BACKUP" <<'PY'
import sqlite3, sys
path = sys.argv[1]
with sqlite3.connect(path) as c:
    ok = c.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        raise SystemExit(f"integrity_check 실패: {ok}")
    tables = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "settings" not in tables:
        raise SystemExit("Service Hub DB가 아닙니다 (settings 테이블 없음)")
print("백업 파일 무결성 검사 통과")
PY

# 2) 복구 전 현재 DB 스냅샷 (온라인 백업)
STAMP=$(date +%Y%m%d-%H%M%S)
SAFETY_DIR="$(cd "$(dirname "$BACKUP")" && pwd)"
SAFETY="$SAFETY_DIR/pre-restore-$STAMP.db"
docker exec "$CONTAINER" python - /data/.pre-restore.db <<'PY'
import sqlite3, sys
with sqlite3.connect("/data/hub.db") as s, sqlite3.connect(sys.argv[1]) as d:
    s.backup(d)
PY
docker cp "$CONTAINER:/data/.pre-restore.db" "$SAFETY" >/dev/null
docker exec "$CONTAINER" rm -f /data/.pre-restore.db || true
echo "복구 전 스냅샷: $SAFETY"

# 3) 백엔드만 중지하고 DB 교체
echo "hub-backend 중지 중…"
docker stop "$CONTAINER" >/dev/null
BASE="$(basename "$BACKUP")"
docker run --rm \
  -v "$VOLUME":/data \
  -v "$SAFETY_DIR":/backup:ro \
  alpine:latest sh -c \
  "rm -f /data/hub.db /data/hub.db-wal /data/hub.db-shm && \
   cp '/backup/$BASE' /data/hub.db && \
   chown 10001:10001 /data/hub.db && chmod 644 /data/hub.db"
echo "DB 교체 완료: $VOLUME <- $BASE"

# 4) 시작 + 헬스체크
docker start "$CONTAINER" >/dev/null
STATUS="unknown"
for _ in $(seq 1 30); do
  STATUS=$(docker inspect -f '{{ if .State.Health }}{{ .State.Health.Status }}{{ else }}{{ .State.Status }}{{ end }}' "$CONTAINER")
  case "$STATUS" in
    healthy|running) break ;;
    unhealthy|exited|dead) break ;;
  esac
  sleep 2
done
docker start "$CONTAINER" >/dev/null 2>&1 || true

if [ "$STATUS" = "healthy" ] || [ "$STATUS" = "running" ]; then
  echo "복구 완료 — 컨테이너 상태: $STATUS"
  echo "확인: curl -fsS http://127.0.0.1:8420/healthz (컨테이너 내부)"
  echo "되돌리기: ./scripts/restore.sh --db '$SAFETY' --yes"
  exit 0
fi

echo "[경고] 복구 후 상태가 '$STATUS' 입니다. 로그를 확인하세요: docker logs $CONTAINER" >&2
echo "되돌리기: ./scripts/restore.sh --db '$SAFETY' --yes" >&2
exit 1
