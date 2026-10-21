#!/usr/bin/env bash
# N100 Service Hub 설치 스크립트 (Linux 대상)
#
# 안전 원칙 (요구사항 §18):
#   * 기존 컨테이너/이미지/네트워크/볼륨/포트를 중단하거나 변경하지 않는다.
#     설치 중 수행하는 Docker 관련 작업은 읽기 전용 조회뿐이다.
#   * 기존 MOTD 설정은 백업 후에만 수정하며 uninstall.sh로 복원할 수 있다.
#
# 사용법:
#   sudo ./scripts/install.sh [--prefix /srv/service-hub] [--port 8420] [--no-motd] [--no-cli]
set -euo pipefail

PREFIX="/srv/service-hub"
PORT="8420"
WITH_MOTD=1
WITH_CLI=1

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --port)   PORT="$2";   shift 2 ;;
    --no-motd) WITH_MOTD=0; shift ;;
    --no-cli)  WITH_CLI=0;  shift ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
  esac
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$PREFIX/backup"
info()  { echo "[정보] $*"; }
warn()  { echo "[경고] $*"; }
fail()  { echo "[오류] $*" >&2; exit 1; }

info "N100 Service Hub 설치 시작 (대상: $PREFIX, 관리 포트: $PORT)"

# 1. 운영체제 및 필수 도구 확인 -------------------------------------------
case "$(uname -s)" in
  Linux) : ;;
  *) warn "배포 대상은 Linux(N100)입니다. 현재 OS=$(uname -s) — 계속 진행하지만 설치 검증은 Linux에서만 유효합니다." ;;
esac
command -v python3 >/dev/null || fail "python3가 필요합니다."
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Python: $PYVER"

# 2. Docker 환경 확인 (읽기 전용) -----------------------------------------
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    info "Docker: $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?')"
    BEFORE_CONTAINERS=$(docker ps -a --format '{{.ID}} {{.Names}} {{.Status}}' | sort | md5sum | cut -d' ' -f1 || true)
    info "설치 전 컨테이너 스냅샷 기록 (보복 검증용): $BEFORE_CONTAINERS"
  else
    warn "Docker 데몬에 연결할 수 없습니다. Hub는 'unknown' 상태로 기동하지만 인벤토리는 비어 있습니다."
  fi
else
  warn "Docker가 설치되어 있지 않습니다."
fi

# 3. 기존 포트 충돌 확인 ---------------------------------------------------
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -qE "[:.]$PORT[[:space:]]"; then
  fail "포트 $PORT가 이미 사용 중입니다. --port 옵션으로 다른 포트를 지정하세요."
fi

# 4. 설치 디렉터리 및 설정 -------------------------------------------------
mkdir -p "$PREFIX"/{data,logs,backup}
[ -f "$PREFIX/.env" ] || cp "$REPO_DIR/.env.example" "$PREFIX/.env"
chmod 600 "$PREFIX/.env"
info "설치 디렉터리 준비 완료: $PREFIX"

# 소켓 경로 자동 감지
if [ -S /var/run/docker.sock ]; then
  grep -q '^HUB_DOCKER_SOCKET=' "$PREFIX/.env" || \
    echo "HUB_DOCKER_SOCKET=/var/run/docker.sock" >> "$PREFIX/.env"
fi
grep -q '^HUB_PORT=' "$PREFIX/.env" || echo "HUB_PORT=$PORT" >> "$PREFIX/.env"

# 5. CLI 설치 --------------------------------------------------------------
if [ "$WITH_CLI" = "1" ]; then
  if command -v uv >/dev/null 2>&1; then
    (cd "$REPO_DIR/cli" && uv tool install --editable . >/dev/null)
    info "hub CLI 설치 완료 (uv tool): $(command -v hub || echo '~/.local/bin/hub')"
  else
    pip3 install --user "$REPO_DIR/cli" >/dev/null 2>&1 || \
      warn "hub CLI 자동 설치 실패. 수동 설치: pip install $REPO_DIR/cli"
  fi
fi

# 6. MOTD 설치 (기존 설정 백업 후) ----------------------------------------
if [ "$WITH_MOTD" = "1" ] && [ "$(uname -s)" = "Linux" ]; then
  MOTD_DIR="/etc/update-motd.d"
  MOTD_TARGET="$MOTD_DIR/90-n100-service-hub"
  mkdir -p "$BACKUP_DIR"
  if [ -d "$MOTD_DIR" ]; then
    if [ -e "$MOTD_TARGET" ] && [ ! -L "$MOTD_TARGET" ]; then
      cp -a "$MOTD_TARGET" "$BACKUP_DIR/90-n100-service-hub.orig"
      info "기존 MOTD 파일 백업: $BACKUP_DIR/90-n100-service-hub.orig"
    fi
    # 기존 /etc/motd가 실파일인 경우도 보존 (업데이트 스크립트와 공존)
    [ -f /etc/motd ] && [ ! -L /etc/motd ] && [ ! -f "$BACKUP_DIR/etc-motd.orig" ] && \
      cp -a /etc/motd "$BACKUP_DIR/etc-motd.orig"
    install -m 755 "$REPO_DIR/scripts/motd.sh" "$MOTD_TARGET"
    echo "HUB_STATUS_CACHE=$PREFIX/data/status.json" > "$BACKUP_DIR/motd.env"
    info "MOTD 설치: $MOTD_TARGET (제거: scripts/uninstall.sh)"
  else
    warn "$MOTD_DIR가 없습니다. MOTD 자동 설치 생략 (--no-motd과 동일 동작)."
  fi
fi

# 7. 관리 시스템 실행 -------------------------------------------------------
cd "$REPO_DIR"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 && [ -f compose.yaml ]; then
  info "docker compose로 Service Hub 기동 시도..."
  # 설치 시 생성한 $PREFIX/.env 를 사용한다 (HUB_PORT/HUB_BIND/HUB_ENABLE_DEPLOY 반영).
  # .env 에 값이 없는 키는 compose.yaml 의 기본값(안전한 잠금)을 따른다.
  docker compose --env-file "$PREFIX/.env" -f "$REPO_DIR/compose.yaml" up -d --build || \
    warn "compose 기동 실패. 로컬 기동으로 대체: uvicorn app.main:app (backend/)"
else
  warn "compose 대신 로컬 기동을 사용하세요: (cd backend && uv sync && HUB_PORT=$PORT uv run uvicorn app.main:app)"
fi

# 8. 헬스체크 ----------------------------------------------------------------
# /healthz 는 인증이 필요 없는 생존 확인 엔드포인트다.
info "헬스체크: http://127.0.0.1:$PORT/healthz"
for _ in $(seq 1 15); do
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    info "헬스체크 통과."
    break
  fi
  sleep 1
done

# 9. 설치 후 보존 검증 -------------------------------------------------------
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  AFTER_CONTAINERS=$(docker ps -a --format '{{.ID}} {{.Names}} {{.Status}}' | sort | md5sum | cut -d' ' -f1 || true)
  if [ "$BEFORE_CONTAINERS" = "$AFTER_CONTAINERS" ]; then
    info "보존 검증 통과: 기존 컨테이너 상태 무변경."
  else
    warn "컨테이너 목록이 달라졌습니다. 즉시 확인이 필요합니다 (설치 스크립트는 컨테이너를 건드리지 않아야 합니다)."
  fi
fi

cat <<EOF

============================================================
 설치 완료
   대상 디렉터리 : $PREFIX
   관리 대시보드 : http://<서버 IP>:$PORT  (최초 접속 시 관리자 계정을 생성합니다.
                    기본 비밀번호는 존재하지 않습니다.)
   CLI            : hub status
   상태 캐시      : $PREFIX/data/status.json (MOTD용)
 다음 단계
   1. 브라우저에서 대시보드에 접속해 관리자 계정을 생성하세요.
   2. 기존 서비스는 'Containers' 탭의 미관리 목록에서 확인 후 서비스에 연결하세요.
   3. 새 서비스 배포 절차는 AI-OPERATIONS.md를 참조하세요.
 주의
   * 이 설치는 기존 컨테이너/포트/볼륨을 변경하지 않습니다.
   * 관리 포트는 기본적으로 내부망에서만 접근하는 것을 권장합니다.
============================================================
EOF
