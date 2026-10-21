"""표준 서비스 디렉터리 템플릿 렌더 (REQUIREMENTS §7).

시크릿 값은 생성하지 않는다 — .env.example에는 이름/설명만 넣는다.
"""
from __future__ import annotations

import re
from pathlib import Path

SERVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")

SERVICE_YAML = """\
schema_version: 1
service:
  id: {{ID}}
  name: {{NAME}}
  description: {{NAME}} 서비스 (설명을 채우세요)
  category: {{CATEGORY}}
  version: "0.1.0"
source:
  repository_url: ""
  branch: main
deployment:
  type: docker-compose
  compose_file: compose.yaml
endpoints:
  - name: frontend
    type: http
    exposure: internal
    container: app
    container_port: 3000
containers:
  - name: app
    role: backend
    required: true
resources:
  memory_limit_mb: 512
operations:
  healthcheck_required: true
  backup_required: false
  restart_policy: unless-stopped
security:
  expose_database: false
  required_env:
    - EXAMPLE_VAR
"""

COMPOSE_YAML = """\
services:
  app:
    image: {{ID}}:latest
    restart: unless-stopped
    env_file:
      - .env
    ports:
      - "127.0.0.1:8000:3000"
"""

ENV_EXAMPLE = """\
# {{NAME}} 환경 변수 (이름/설명만. 실제 값은 .env에 넣고 Git에 커밋하지 않는다)
EXAMPLE_VAR=        # 예시 변수 — 실제 값으로 대체
"""

GITIGNORE = """\
.env
data/
logs/
*.log
"""

README = """\
# {{NAME}}

ID: `{{ID}}` / category: `{{CATEGORY}}`

## 데이터/백업
- 데이터 저장 위치:
- 백업 방법:
"""


def render_service_dir(base: str | Path, service_id: str, *, name: str | None = None,
                       category: str = "other") -> str:
    if not SERVICE_ID_RE.match(service_id):
        raise ValueError(f"서비스 ID 형식이 올바르지 않습니다: {service_id!r}")
    root = Path(base) / service_id
    if root.exists():
        raise FileExistsError(f"이미 존재하는 디렉터리입니다: {root}")

    def sub(text: str) -> str:
        return (text.replace("{{ID}}", service_id)
                    .replace("{{NAME}}", name or service_id)
                    .replace("{{CATEGORY}}", category))

    for sub_dir in ("config", "data", "logs"):
        (root / sub_dir).mkdir(parents=True, exist_ok=True)
        (root / sub_dir / ".gitkeep").write_text("", encoding="utf-8")
    (root / "service.yaml").write_text(sub(SERVICE_YAML), encoding="utf-8")
    (root / "compose.yaml").write_text(sub(COMPOSE_YAML), encoding="utf-8")
    (root / ".env.example").write_text(sub(ENV_EXAMPLE), encoding="utf-8")
    (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (root / "README.md").write_text(sub(README), encoding="utf-8")
    return str(root)
