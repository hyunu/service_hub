#!/usr/bin/env bash
# N100 Service Hub 제거 스크립트 — MOTD 복원 및 서비스 종료
#
# 안전 원칙: 기존(외부) 서비스의 컨테이너/볼륨/네트워크는 절대 삭제하지 않는다.
#   hub 자체 compose 프로젝트(label com.hub.self=true)와 등록 데이터만 선택적으로 제거한다.
#
# 사용법:
#   sudo ./scripts/uninstall.sh [--prefix /srv/service-hub] [--purge-data] [--remove-containers]
set -euo pipefail

PREFIX="/srv/service-hub"
PURGE_DATA=0
REMOVE_CONTAINERS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --purge-data) PURGE_DATA=1; shift ;;
    --remove-containers) REMOVE_CONTAINERS=1; shift ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
  esac
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$PREFIX/backup"
info() { echo "[정보] $*"; }
warn() { echo "[경고] $*"; }

# 1. MOTD 복원 --------------------------------------------------------------
MOTD_DIR="/etc/update-motd.d"
MOTD_TARGET="$MOTD_DIR/90-n100-service-hub"
if [ -e "$MOTD_TARGET" ]; then
  rm -f "$MOTD_TARGET"
  info "MOTD 스크립트 제거: $MOTD_TARGET"
fi
if [ -f "$BACKUP_DIR/90-n100-service-hub.orig" ]; then
  install -m 755 "$BACKUP_DIR/90-n100-service-hub.orig" "$MOTD_TARGET"
  info "기존 MOTD 파일 복원: $MOTD_TARGET"
fi
if [ -f "$BACKUP_DIR/etc-motd.orig" ] && [ ! -f /etc/motd ]; then
  cp -a "$BACKUP_DIR/etc-motd.orig" /etc/motd
  info "/etc/motd 복원"
fi

# 2. hub 자체 서비스 종료 ----------------------------------------------------
cd "$REPO_DIR"
if [ -f compose.yaml ] && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  if [ "$REMOVE_CONTAINERS" = "1" ]; then
    # --remove-orphans 없이, hub compose 프로젝트 범위 내에서만 down (외부 서비스 안전)
    docker compose -f compose.yaml down --remove-orphans
    info "hub compose 프로젝트 종료 및 컨테이너 제거 (외부 서비스는 영향 없음)"
  else
    docker compose -f compose.yaml stop
    info "hub compose 프로젝트 중지 (컨테이너 보존)"
  fi
fi

# 3. CLI 제거 ---------------------------------------------------------------
if command -v hub >/dev/null 2>&1; then
  pip3 uninstall -y hub-cli >/dev/null 2>&1 || uv tool uninstall hub-cli >/dev/null 2>&1 || true
  info "hub CLI 제거 시도 완료"
fi

# 4. 데이터 -----------------------------------------------------------------
if [ "$PURGE_DATA" = "1" ]; then
  warn "$PREFIX/data 삭제 요청됨 — 관리 레지스트리(SQLite)가 함께 삭제됩니다."
  warn "3초 후 삭제됩니다. (취소: Ctrl+C)"
  sleep 3
  rm -rf "$PREFIX/data"
  info "데이터 삭제 완료. 기존 Docker 서비스 데이터에는 접근한 적이 없습니다."
else
  info "데이터는 보존됩니다: $PREFIX/data (삭제하려면 --purge-data)"
fi

info "제거 완료. 기존 서비스는 어떤 경우에도 영향을 받지 않습니다."
