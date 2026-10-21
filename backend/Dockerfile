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
    HUB_STATUS_CACHE=/data/status.json

# 데이터 디렉터리 (compose 볼륨 마운트 지점)
RUN mkdir -p /data && chown -R 10001:10001 /data /app
USER 10001:10001

EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8420/healthz')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8420"]
