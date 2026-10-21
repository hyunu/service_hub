#!/usr/bin/env bash
# 관리 레지스트리 DB 및 상태 캐시 백업 (요구사항 §16)
# 사용법: ./scripts/backup.sh [--prefix /srv/service-hub] [--out /srv/backups]
set -euo pipefail

PREFIX="/srv/service-hub"
OUT="${HUB_BACKUP_DIR:-$PREFIX/backup/db}"
STAMP=$(date +%Y%m%d-%H%M%S)

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$OUT"
DB="$PREFIX/data/hub.db"

if [ ! -f "$DB" ]; then
  echo "[오류] DB를 찾을 수 없습니다: $DB" >&2
  exit 1
fi

# SQLite 온라인 백업: WAL 포함 정합성 보장
python3 - "$DB" "$OUT/hub-$STAMP.db" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
print(f"백업 완료: {dst}")
PY

# 유효성 검증
python3 - "$OUT/hub-$STAMP.db" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as c:
    c.execute("PRAGMA integrity_check")
    row = c.execute("PRAGMA integrity_check").fetchone()
    assert row[0] == "ok", f"integrity_check 실패: {row[0]}"
print("무결성 검사 통과")
PY

echo "복구 방법: systemctl/env로 백엔드 중지 후 백업 파일을 ${PREFIX}/data/hub.db로 복사."
echo "주의: 관리 DB만 백업하며, 각 서비스의 데이터 볼륨은 개별 백업 정책을 따릅니다."
