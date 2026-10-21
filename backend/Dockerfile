# N100 Service Hub 백엔드 이미지
#
# 보안 원칙 (docs/SECURITY.md):
#   * 이미지에는 시크릿을 넣지 않는다. 런타임 환경 변수/볼륨으로만 주입한다.
#   * Docker 소켓은 이 컨테이너에만 마운트한다 (compose에서 처리).
#   * 비루트 사용자로 실행한다.
#
# 빌드: docker build -t n100-service-hub-backend:0.1.0 ./backend
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS base

WORKDIR /app

# docker CLI + compose 플러그인.
# 배포 실행기(Phase 3)는 `docker compose ...` 를 subprocess로 호출한다.
# Docker SDK에는 compose up/down 동등 기능이 없어 CLI가 필요하다.
# (게이트가 잠겨 있으면 실행기 자체가 이 경로에 도달하지 못한다.)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && chmod a+r /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
 && apt-get purge -y curl gnupg \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# 의존성 레이어를 먼저 캐시한다.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 애플리케이션 코드
COPY app ./app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HUB_BIND=0.0.0.0 \
    HUB_PORT=8420 \
    HUB_DB_PATH=/data/hub.db \
    HUB_STATUS_CACHE=/data/status.json \
    HUB_DEPLOY_WORKDIR=/srv/services

# 데이터 디렉터리 (compose 볼륨 마운트 지점)
RUN mkdir -p /data && chown -R 10001:10001 /data /app
USER 10001:10001

EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8420/healthz')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8420"]
