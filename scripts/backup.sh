#!/usr/bin/env bash
# 관리 레지스트리 DB 백업 (요구사항 §16)
#
# 현재 배포는 named volume(hub-data)을 쓰므로 /srv/service-hub/data/hub.db 가 없다.
# 이 스크립트는 다음 순서로 DB를 찾는다.
#   1) --db 로 명시한 경로
#   2) 레거시 바인드 경로: <prefix>/data/hub.db
#   3) Docker 볼륨 마운트 경로: $(docker volume inspect -f '{{ .Mountpoint }}' <volume>)/hub.db
#   4) 위 경로를 읽을 수 없으면 컨테이너 안에서 스냅샷을 만들어 docker cp 로 꺼낸다
#
# 사용법:
#   ./scripts/backup.sh                        # 자동 탐지, 기본 보관 14개
#   ./scripts/backup.sh --out /srv/backups --keep 30
#   ./scripts/backup.sh --db /path/to/hub.db
set -euo pipefail

PREFIX="/srv/service-hub"
OUT="${HUB_BACKUP_DIR:-$PREFIX/backup/db}"
VOLUME="${HUB_VOLUME:-service-hub_hub-data}"
CONTAINER="${HUB_BACKEND_CONTAINER:-hub-backend}"
DB=""
KEEP=14

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --volume) VOLUME="$2"; shift 2 ;;
    --container) CONTAINER="$2"; shift 2 ;;
    --keep) KEEP="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
  esac
done

case "$KEEP" in
  ''|*[!0-9]*) echo "--keep 은 0 이상의 정수여야 합니다: $KEEP" >&2; exit 2 ;;
esac

STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"
TARGET="$OUT/hub-$STAMP.db"

volume_mountpoint() {
  docker volume inspect -f '{{ .Mountpoint }}' "$VOLUME" 2>/dev/null || true
}

# 1) DB 경로 결정
DB_FROM_VOLUME=0
if [ -n "$DB" ]; then
  [ -f "$DB" ] || { echo "[오류] DB 파일이 없습니다: $DB" >&2; exit 1; }
else
  if [ -f "$PREFIX/data/hub.db" ]; then
    DB="$PREFIX/data/hub.db"
  else
    MP=$(volume_mountpoint)
    if [ -n "$MP" ] && [ -f "$MP/hub.db" ]; then
      DB="$MP/hub.db"
      DB_FROM_VOLUME=1
    fi
  fi
fi

# 2) 백업 생성
if [ -n "$DB" ] && [ -r "$DB" ]; then
  # 호스트에서 직접 읽을 수 있으면 SQLite online backup (WAL 포함 정합성)
  python3 - "$DB" "$TARGET" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
PY
  echo "백업 완료: $TARGET (원본: $DB)"
else
  # 컨테이너 안에서 스냅샷을 만들고 docker cp 로 꺼낸다 (호스트 권한 불필요)
  command -v docker >/dev/null 2>&1 || {
    echo "[오류] DB를 읽을 수 없고 docker도 없습니다. --db 로 경로를 지정하세요." >&2; exit 1; }
  docker inspect "$CONTAINER" >/dev/null 2>&1 || {
    echo "[오류] 컨테이너 '$CONTAINER'를 찾을 수 없습니다." >&2; exit 1; }
  TMP_IN_CONTAINER="/data/.hub-backup-$STAMP.db"
  docker exec "$CONTAINER" python - "$TMP_IN_CONTAINER" <<'PY'
import sqlite3, sys
src, dst = "/data/hub.db", sys.argv[1]
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
PY
  docker cp "$CONTAINER:$TMP_IN_CONTAINER" "$TARGET" >/dev/null
  docker exec "$CONTAINER" rm -f "$TMP_IN_CONTAINER" || true
  echo "백업 완료: $TARGET (컨테이너 $CONTAINER:/data/hub.db)"
fi

[ -s "$TARGET" ] || { echo "[오류] 백업 파일이 비었습니다: $TARGET" >&2; exit 1; }

# 3) 무결성 검증 + 요약
python3 - "$TARGET" <<'PY'
import sqlite3, sys
path = sys.argv[1]
with sqlite3.connect(path) as c:
    ok = c.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        raise SystemExit(f"integrity_check 실패: {ok}")
    tables = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    counts = {}
    for t in ("services", "containers", "settings", "api_keys"):
        if t in tables:
            counts[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
print("무결성 검사 통과:", ", ".join(f"{k}={v}" for k, v in counts.items()))
PY

# 4) 보관 개수 제한 (최신 KEEP개 유지)
if [ "$KEEP" -ge 0 ]; then
  ls -1t "$OUT"/hub-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f "$old"
  done
fi

echo "백업 위치: $OUT (최근 ${KEEP}개 보관)"
echo "복구: ./scripts/restore.sh --db '$TARGET' --yes"
echo "주의: 관리 DB만 백업합니다. 각 서비스의 데이터 볼륨은 개별 정책을 따릅니다."
