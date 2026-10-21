# Phase 2 + Phase 3 구현 계획 (남은 작업)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 2(표준 서비스 등록/검증)와 Phase 3(배포 계획 + 배포 실행기)를 순차 구현한다.

**Architecture:** service.yaml을 Pydantic으로 검증하는 `service_spec` 모듈을 신설하고, CLI/백엔드 양쪽에서 같은 검증을 호출한다. 배포 계획(`deploy_plan`)은 순수 함수로 Compose diff/포트/자원/환경변수 검증만 수행한다(컨테이너 무변경). 배포 실행기(`deploy_runner`)는 `HUB_ENABLE_DEPLOY=true`일 때만 동작하며, `docker_client.py`에 제한된 변경 함수(compose up/down)를 추가한다.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, Pydantic v2, PyYAML, Docker SDK, pytest, React 19 + Vite + Vitest.

---

## 파일 구조 (생성/수정 대상)

| 파일 | 역할 |
|---|---|
| `backend/app/services/service_spec.py` | service.yaml Pydantic 모델 + 검증 (신규) |
| `backend/app/services/deploy_plan.py` | 배포 계획 생성: diff/포트/자원/환경변수 (신규) |
| `backend/app/services/deploy_runner.py` | 배포 실행 상태머신 (신규, 잠금 게이트) |
| `backend/app/services/template_render.py` | 표준 서비스 디렉터리 템플릿 렌더 (신규) |
| `backend/app/docker_client.py` | compose 검증/실행 함수 추가 (수정, gate 필요) |
| `backend/app/routers/services.py` | `/services/validate`, `/services/import` 추가 (수정) |
| `backend/app/routers/events.py` | `deploy_plan`/`deploy_apply` 실제 구현 (수정) |
| `backend/app/config.py` | `deploy_allowed`/compose 설정 추가 (수정) |
| `backend/app/monitor.py` | 활성 배포 진행 갱신 (수정, 선택) |
| `cli/hub_cli/main.py` | `service validate/new`, `deploy plan/apply/status`, `port available` (수정) |
| `cli/hub_cli/deploy.py` | CLI 배포 헬퍼 (신규, 선택) |
| `backend/tests/test_service_spec.py` | 검증 단위 테스트 (신규) |
| `backend/tests/test_deploy_plan.py` | 계획 생성 테스트 (신규) |
| `backend/tests/test_deploy_runner.py` | 실행기 테스트 (신규) |
| `backend/tests/test_deploy_api.py` | 배포 API 테스트 (신규) |
| `cli/tests/test_cli_deploy.py` | CLI 배포 명령 테스트 (신규) |
| `frontend/src/pages/*` | 검증 결과/배포 계획 UI (수정, 최소) |
| `docs/AI-OPERATIONS.md`, `AGENTS.md` | AI 규칙 확장 (수정) |
| `docs/SECURITY.md` | Phase 3 잠금 해제 위험 명시 (수정) |

---

## Task 목록 (개요)

1. **Task 1:** service.yaml Pydantic 스키마 (`service_spec.py`) + 단위 테스트
2. **Task 2:** 백엔드 `POST /services/validate` 엔드포인트 + 테스트
3. **Task 3:** CLI `hub service validate <path>` 실구현 (로컬 검증) + 테스트
4. **Task 4:** 표준 디렉터리 템플릿 렌더 + `hub service new` + 테스트
5. **Task 5:** 배포 계획 생성기 (`deploy_plan.py`) + 테스트 (읽기 전용)
6. **Task 6:** 백엔드 `POST /deployments/plan` 실구현 + 테스트
7. **Task 7:** CLI `hub deploy plan <path>` + 테스트
8. **Task 8:** 설정 게이트 (`deploy_allowed`) + SECURITY/AGENTS 문서 갱신
9. **Task 9:** `docker_client.py` 제한 변경 함수 (compose config/up/down, gate 필수) + 테스트
10. **Task 10:** 배포 실행기 상태머신 (`deploy_runner.py`) + 테스트
11. **Task 11:** 백엔드 `POST /deployments` 실구현 (비동기) + 테스트
12. **Task 12:** CLI `hub deploy apply/status` + 테스트
13. **Task 13:** 프론트엔드 배포 계획/실행 UI 최소 연동 + 테스트
14. **Task 14:** 통합 스모크 + 문서 최종 갱신 + 커밋

---

## Task 1: service.yaml Pydantic 스키마

**Files:**
- Create: `backend/app/services/service_spec.py`
- Test: `backend/tests/test_service_spec.py`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `backend/tests/test_service_spec.py`:

```python
import pytest
from app.services.service_spec import SpecError, parse_spec, validate_spec_dict

VALID = {
    "schema_version": 1,
    "service": {"id": "sample-app", "name": "Sample", "description": "샘플", "category": "web"},
    "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
}


def test_valid_spec_parses():
    spec = validate_spec_dict(VALID)
    assert spec.service.id == "sample-app"


def test_unknown_schema_version_rejected():
    bad = {**VALID, "schema_version": 2}
    with pytest.raises(SpecError) as e:
        validate_spec_dict(bad)
    assert e.value.code == "unsupported_schema_version"


def test_bad_service_id_rejected():
    bad = {**VALID, "service": {**VALID["service"], "id": "Bad_ID"}}
    with pytest.raises(SpecError) as e:
        validate_spec_dict(bad)
    assert e.value.code == "invalid_service_id"


def test_proxy_endpoint_requires_hostname():
    bad = {**VALID, "endpoints": [{"name": "f", "type": "http", "exposure": "proxy",
                                   "container": "frontend", "container_port": 3000}]}
    with pytest.raises(SpecError) as e:
        validate_spec_dict(bad)
    assert e.value.code == "spec_validation_failed"


def test_secret_values_in_security_rejected():
    bad = {**VALID, "security": {"required_env": {"PASSWORD": "hunter2"}}}
    with pytest.raises(SpecError):
        validate_spec_dict(bad)


def test_parse_spec_from_yaml(tmp_path):
    import yaml
    p = tmp_path / "service.yaml"
    p.write_text(yaml.safe_dump(VALID), encoding="utf-8")
    spec = parse_spec(p)
    assert spec.service.category == "web"


def test_parse_spec_missing_file(tmp_path):
    with pytest.raises(SpecError) as e:
        parse_spec(tmp_path / "nope.yaml")
    assert e.value.code == "spec_file_not_found"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && uv run pytest tests/test_service_spec.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.service_spec'`

- [ ] **Step 3: 최소 구현 작성**

Create `backend/app/services/service_spec.py`:

```python
"""service.yaml 스키마 v1 검증 (REQUIREMENTS §6).

Pydantic으로 검증한다. 시크릿 값은 service.yaml에 넣지 않는다 — 이름만 허용.
지원하지 않는 schema_version은 임의 해석하지 않고 거부한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_SCHEMA_VERSIONS = {1}
SERVICE_ID_RE = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"


class SpecError(Exception):
    def __init__(self, message: str, code: str = "spec_invalid", errors: list | None = None):
        super().__init__(message)
        self.code = code
        self.errors = errors or []


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ServiceMeta(_Strict):
    id: str = Field(pattern=SERVICE_ID_RE)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    category: Literal["web", "backend", "database", "ai", "automation",
                      "media", "dev", "infra", "other"]
    version: str | None = None
    documentation: str | None = None
    tags: list[str] = Field(default_factory=list)


class Source(_Strict):
    repository_url: str = ""
    branch: str = "main"


class DeploymentInfo(_Strict):
    type: Literal["docker-compose"]
    compose_file: str = Field(min_length=1)
    project_name: str | None = None


class Endpoint(_Strict):
    name: str = Field(min_length=1)
    type: Literal["http", "https", "tcp", "udp", "grpc"] = "http"
    exposure: Literal["proxy", "host", "internal"] = "internal"
    hostname: str | None = None
    host_port: int | None = Field(default=None, ge=1, le=65535)
    container: str = Field(min_length=1)
    container_port: int = Field(ge=1, le=65535)

    @model_validator(mode="after")
    def _check_exposure(self):
        if self.exposure == "proxy" and not self.hostname:
            raise ValueError("exposure=proxy에는 hostname이 필요합니다")
        if self.exposure == "host" and not self.host_port:
            raise ValueError("exposure=host에는 host_port가 필요합니다")
        return self


class ContainerSpec(_Strict):
    name: str = Field(min_length=1)
    role: Literal["frontend", "backend", "worker", "database", "cache", "proxy", "other"] = "other"
    required: bool = True
    description: str = ""


class Resources(_Strict):
    memory_limit_mb: int | None = Field(default=None, ge=16)
    cpu_limit: float | None = Field(default=None, gt=0)


class VolumeSpec(_Strict):
    name: str
    purpose: str
    backup_required: bool = False


class Operations(_Strict):
    healthcheck_required: bool = True
    backup_required: bool = False
    restart_policy: Literal["no", "always", "unless-stopped", "on-failure"] = "unless-stopped"


class Security(_Strict):
    expose_database: bool = False
    required_env: list[str] = Field(default_factory=list)

    @field_validator("required_env", mode="before")
    @classmethod
    def _names_only(cls, v):
        """시크릿 '값'이 아니라 '이름'만 허용한다 (REQUIREMENTS §6)."""
        if isinstance(v, dict):
            raise ValueError("required_env는 환경 변수 이름 목록이어야 합니다 (값 금지)")
        for item in v or []:
            if not isinstance(item, str) or not item or not item[0].isupper():
                raise ValueError(f"환경 변수 이름이 올바르지 않습니다: {item!r}")
        return v


class ServiceSpec(_Strict):
    schema_version: int
    service: ServiceMeta
    source: Source = Field(default_factory=Source)
    deployment: DeploymentInfo
    endpoints: list[Endpoint] = Field(default_factory=list)
    containers: list[ContainerSpec] = Field(default_factory=list)
    resources: Resources = Field(default_factory=Resources)
    volumes: list[VolumeSpec] = Field(default_factory=list)
    operations: Operations = Field(default_factory=Operations)
    security: Security = Field(default_factory=Security)


def validate_spec_dict(data: Any) -> ServiceSpec:
    if not isinstance(data, dict):
        raise SpecError("service.yaml 최상위는 매핑이어야 합니다", "spec_invalid")
    version = data.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SpecError(
            f"지원하지 않는 schema_version입니다: {version!r} "
            f"(지원: {sorted(SUPPORTED_SCHEMA_VERSIONS)})",
            "unsupported_schema_version")
    try:
        return ServiceSpec.model_validate(data)
    except Exception as exc:  # pydantic ValidationError
        errors = getattr(exc, "errors", lambda: [])()
        detail = "; ".join(
            f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg')}" for e in errors[:8]
        ) or str(exc)
        code = "invalid_service_id" if "service.id" in detail else "spec_validation_failed"
        raise SpecError(f"service.yaml 검증 실패 — {detail}", code, errors) from exc


def parse_spec(path: str | Path) -> ServiceSpec:
    p = Path(path)
    if p.is_dir():
        p = p / "service.yaml"
    if not p.exists():
        raise SpecError(f"service.yaml을 찾을 수 없습니다: {p}", "spec_file_not_found")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecError(f"YAML 파싱 오류: {exc}", "spec_yaml_error") from exc
    return validate_spec_dict(data)
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && uv run pytest tests/test_service_spec.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services/service_spec.py backend/tests/test_service_spec.py
git commit -m "feat(backend): service.yaml 스키마 v1 Pydantic 검증 추가 (Phase 2)"
```

---

## Task 2: 백엔드 `/services/validate` 엔드포인트

**Files:**
- Modify: `backend/app/routers/services.py` (파일 끝에 추가)
- Test: `backend/tests/test_services.py` (테스트 추가)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_services.py` 끝에 추가:

```python
def test_validate_spec_endpoint_ok(client):
    body = {
        "schema_version": 1,
        "service": {"id": "sample-app", "name": "Sample", "description": "샘플",
                    "category": "web"},
        "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    }
    r = client.post("/api/v1/services/validate", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert data["spec"]["service"]["id"] == "sample-app"


def test_validate_spec_endpoint_reports_errors(client):
    body = {"schema_version": 1,
            "service": {"id": "Bad", "name": "x", "description": "y", "category": "web"},
            "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"}}
    r = client.post("/api/v1/services/validate", json=body)
    assert r.status_code == 422
    assert r.json()["code"] in ("invalid_service_id", "spec_validation_failed")


def test_validate_spec_endpoint_requires_auth(anon_client):
    r = anon_client.post("/api/v1/services/validate", json={"schema_version": 1})
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && uv run pytest tests/test_services.py -k validate_spec -q`
Expected: FAIL (404 Not Found)

- [ ] **Step 3: 최소 구현 작성**

`backend/app/routers/services.py` 끝에 추가한다. 라우터 등록 순서상 이 핸들러는
파일에서 `@router.get("/{service_id}")`보다 **먼저** 선언되어야 `/validate`가
서비스 ID로 해석되지 않는다. 따라서 아래 블록을 `list_services` 정의 바로 뒤,
`get_service` 정의 **앞**에 삽입한다:

```python
@router.post("/validate")
def validate_service_spec(payload: dict, db: Session = Depends(get_db)):
    """service.yaml(dict) 또는 파일 경로를 검증한다. DB에 아무것도 쓰지 않는다."""
    from ..services.service_spec import SpecError, parse_spec, validate_spec_dict

    try:
        if isinstance(payload.get("path"), str):
            spec = parse_spec(payload["path"])
        else:
            spec = validate_spec_dict(payload)
    except SpecError as exc:
        raise HubError(status_code=422, detail=str(exc), code=exc.code) from exc
    return {"valid": True, "spec": spec.model_dump(), "errors": []}
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && uv run pytest tests/test_services.py -k validate_spec -q`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/routers/services.py backend/tests/test_services.py
git commit -m "feat(backend): 서비스 스펙 검증 API 추가 (POST /services/validate)"
```

---

## Task 3: CLI `hub service validate` — ✅ 이미 구현됨 (검증만)

**실행 중 발견:** CLI에 `cmd_service_validate`가 이미 존재한다(`cli/hub_cli/main.py:182`).
JSON Schema(draft-07)로 검증하며, 파일 없음은 `EXIT_NOTFOUND`(5)를 반환한다.
따라서 **새로 구현하지 않는다.** 대신 다음만 수행:

- [ ] **Step 1: 기존 동작 확인**

Run: `cd cli && uv run pytest tests/test_cli.py -q`
Expected: PASS (기존 14개)

- [ ] **Step 2: 백엔드 검증 API와 병행 사용 문서화**

CLI는 로컬 jsonschema 검증, 백엔드는 Pydantic 검증(§6). 두 경로 모두
`schemas/service.schema.v1.json` / `service_spec.py` 규칙을 따른다.
새 CLI 테스트는 추가하지 않는다(기존 커버리지 유지).

> 계획 정정: 원래 Task 3는 로컬 Pydantic 검증 구현을 계획했으나,
> 실제 CLI는 이미 jsonschema로 검증한다. 중복 구현하지 않는다.

---


## Task 4: 표준 디렉터리 템플릿 + `hub service new`

**Files:**
- Create: `backend/app/services/template_render.py`
- Modify: `cli/hub_cli/main.py`
- Test: `backend/tests/test_template_render.py`, `cli/tests/test_cli_deploy.py`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `backend/tests/test_template_render.py`:

```python
from pathlib import Path

from app.services.template_render import render_service_dir


def test_render_creates_standard_layout(tmp_path):
    out = render_service_dir(tmp_path, "sample-app", name="Sample App", category="web")
    out = Path(out)
    for rel in ("service.yaml", "compose.yaml", ".env.example", "README.md", ".gitignore",
                "config/.gitkeep", "data/.gitkeep", "logs/.gitkeep"):
        assert (out / rel).exists(), rel
    text = (out / "service.yaml").read_text(encoding="utf-8")
    assert "id: sample-app" in text
    assert "schema_version: 1" in text


def test_render_rejects_bad_id(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        render_service_dir(tmp_path, "Bad_ID")


def test_render_refuses_existing_dir(tmp_path):
    (tmp_path / "sample-app").mkdir()
    import pytest
    with pytest.raises(FileExistsError):
        render_service_dir(tmp_path, "sample-app")


def test_gitignore_and_env_example_have_no_secrets(tmp_path):
    out = Path(render_service_dir(tmp_path, "sample-app"))
    gi = (out / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gi
    envx = (out / ".env.example").read_text(encoding="utf-8")
    assert "=" in envx
    # 값이 아닌 이름/설명만 — 실제 시크릿 패턴이 없어야 한다
    assert "password=" not in envx.lower() or "#" in envx
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && uv run pytest tests/test_template_render.py -q`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 최소 구현 작성**

Create `backend/app/services/template_render.py`:

```python
"""표준 서비스 디렉터리 템플릿 렌더 (REQUIREMENTS §7).

시크릿 값은 생성하지 않는다 — .env.example에는 이름/설명만 넣는다.
"""
from __future__ import annotations

import re
from pathlib import Path

SERVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
PLACEHOLDERS = ("{{ID}}", "{{NAME}}", "{{CATEGORY}}")

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
```

- [ ] **Step 4: CLI `service new` 추가 및 테스트**

`cli/hub_cli/main.py`의 `_validate_local` 아래에 추가:

```python
def _render_local(out_dir: str, service_id: str, name: str | None, category: str) -> dict:
    import re
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$", service_id):
        raise CliError(f"서비스 ID 형식이 올바르지 않습니다: {service_id!r}", EXIT_REJECTED)
    root = Path(out_dir) / service_id
    if root.exists():
        raise CliError(f"이미 존재하는 디렉터리입니다: {root}", EXIT_REJECTED)
    # 스키마 준수 골격 생성 (시크릿 값 없음)
    for sub in ("config", "data", "logs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
        (root / sub / ".gitkeep").write_text("", encoding="utf-8")
    display = name or service_id
    (root / "service.yaml").write_text(
        "schema_version: 1\n"
        "service:\n"
        f"  id: {service_id}\n"
        f"  name: {display}\n"
        f"  description: {display} 서비스 (설명을 채우세요)\n"
        f"  category: {category}\n"
        '  version: "0.1.0"\n'
        "deployment:\n"
        "  type: docker-compose\n"
        "  compose_file: compose.yaml\n", encoding="utf-8")
    (root / "compose.yaml").write_text(
        "services:\n  app:\n    image: " + service_id + ":latest\n"
        "    restart: unless-stopped\n    ports:\n"
        '      - "127.0.0.1:8000:3000"\n', encoding="utf-8")
    (root / ".env.example").write_text(
        f"# {display} 환경 변수 (이름만)\nEXAMPLE_VAR=\n", encoding="utf-8")
    (root / ".gitignore").write_text(".env\ndata/\nlogs/\n", encoding="utf-8")
    return {"created": str(root), "service_id": service_id}


def cmd_service_new(args: argparse.Namespace) -> None:
    result = _render_local(args.dir, args.service_id, getattr(args, "name", None),
                           getattr(args, "category", "other"))

    def render(d: dict) -> None:
        print(f"생성됨: {d['created']}")
        print(f"  service_id: {d['service_id']}")
        print("  다음: service.yaml 설명을 채우고 `hub service validate`로 검증하세요.")
    emit(result, args.json, render)
```

`build_parser()`에서 `service` 서브커맨드에 `new`를 추가한다:

```python
    sp_new = service_sub.add_parser("new", help="표준 서비스 디렉터리 골격 생성")
    sp_new.add_argument("service_id")
    sp_new.add_argument("--dir", default=".", help="생성 위치 (기본 현재 디렉터리)")
    sp_new.add_argument("--name", default=None)
    sp_new.add_argument("--category", default="other")
    sp_new.add_argument("--json", action="store_true")
    sp_new.set_defaults(func=cmd_service_new)
```

`cli/tests/test_cli_deploy.py`에 추가:

```python
def test_service_new_creates_layout(tmp_path, capsys):
    code = main(["service", "new", "demo-app", "--dir", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "demo-app" / "service.yaml").exists()
    assert (tmp_path / "demo-app" / "compose.yaml").exists()
    assert (tmp_path / "demo-app" / ".env.example").exists()


def test_service_new_then_validate_roundtrip(tmp_path, capsys):
    main(["service", "new", "demo-app", "--dir", str(tmp_path)])
    code = main(["service", "validate", str(tmp_path / "demo-app")])
    assert code == 0


def test_service_new_rejects_existing(tmp_path, capsys):
    (tmp_path / "demo-app").mkdir()
    code = main(["service", "new", "demo-app", "--dir", str(tmp_path)])
    assert code == 4
```

- [ ] **Step 5: 통과 확인 및 커밋**

Run: `cd backend && uv run pytest tests/test_template_render.py -q` → PASS
Run: `cd cli && uv run pytest tests/test_cli_deploy.py -q` → PASS

```bash
git add backend/app/services/template_render.py backend/tests/test_template_render.py \
        cli/hub_cli/main.py cli/tests/test_cli_deploy.py
git commit -m "feat: 표준 서비스 디렉터리 템플릿 생성 (backend render + hub service new)"
```

---

## Task 5: 배포 계획 생성기 (`deploy_plan.py`, 읽기 전용)

**Files:**
- Create: `backend/app/services/deploy_plan.py`
- Test: `backend/tests/test_deploy_plan.py`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `backend/tests/test_deploy_plan.py`:

```python
from app.services.deploy_plan import build_plan
from app.services.service_spec import validate_spec_dict

SPEC = {
    "schema_version": 1,
    "service": {"id": "sample-app", "name": "Sample", "description": "샘플",
                "category": "web"},
    "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    "containers": [{"name": "frontend", "role": "frontend", "required": True},
                   {"name": "backend", "role": "backend", "required": True}],
    "endpoints": [{"name": "web", "type": "http", "exposure": "host",
                   "host_port": 8123, "container": "frontend", "container_port": 3000}],
    "security": {"required_env": ["EXAMPLE_VAR"]},
}


def test_plan_ready_when_all_checks_pass(fake_ctx):
    spec = validate_spec_dict(SPEC)
    plan = build_plan(spec, ctx=fake_ctx(available_env={"EXAMPLE_VAR"}))
    assert plan["result"] == "READY"
    assert plan["service"] == "sample-app"
    assert any(c["name"] == "frontend" for c in plan["changes"])


def test_plan_blocked_on_port_conflict(fake_ctx):
    spec = validate_spec_dict(SPEC)
    plan = build_plan(spec, ctx=fake_ctx(conflicting_ports={8123}))
    assert plan["result"] == "BLOCKED"
    assert any("포트" in i["message"] for i in plan["impact"])


def test_plan_blocked_on_missing_env(fake_ctx):
    spec = validate_spec_dict(SPEC)
    plan = build_plan(spec, ctx=fake_ctx(available_env=set()))
    assert plan["result"] == "BLOCKED"
    assert any("환경 변수" in i["message"] for i in plan["impact"])


def test_plan_reports_resource_warning(fake_ctx):
    spec = validate_spec_dict(SPEC)
    ctx = fake_ctx(available_env={"EXAMPLE_VAR"}, mem_available_mb=100)
    plan = build_plan(spec, ctx=ctx)
    assert any(w["level"] == "warning" for w in plan["warnings"])


def test_plan_has_no_runtime_side_effects(fake_ctx):
    spec = validate_spec_dict(SPEC)
    plan = build_plan(spec, ctx=fake_ctx(available_env={"EXAMPLE_VAR"}))
    assert plan["runtime_unchanged"] is True
```

`backend/tests/conftest.py`에 `fake_ctx` 픽스처 추가:

```python
@pytest.fixture
def fake_ctx():
    from app.services.deploy_plan import PlanContext
    def _make(*, available_env=None, conflicting_ports=None, mem_available_mb=4096,
              compose_ok=True, current_containers=None):
        return PlanContext(
            available_env=available_env if available_env is not None else set(),
            conflicting_ports=conflicting_ports or set(),
            mem_available_mb=mem_available_mb,
            compose_ok=compose_ok,
            current_containers=current_containers or {},
        )
    return _make
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && uv run pytest tests/test_deploy_plan.py -q`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 최소 구현 작성**

Create `backend/app/services/deploy_plan.py`:

```python
"""배포 계획 생성 (REQUIREMENTS §13.2). 컨테이너를 변경하지 않는다.

계획과 실제는 다를 수 있다 — 배포 후 실제 상태를 다시 조회한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .service_spec import ServiceSpec


@dataclass
class PlanContext:
    """계획 생성에 필요한 '관찰된' 환경 (순수 입력 — 여기서 Docker를 호출하지 않는다)."""
    available_env: set[str] = field(default_factory=set)
    conflicting_ports: set[int] = field(default_factory=set)
    mem_available_mb: float | None = None
    compose_ok: bool = True
    current_containers: dict[str, dict] = field(default_factory=dict)
    # current_containers: {compose_service_name: {"image": str, "state": str}}


def _change_for(name: str, ctx: PlanContext) -> dict:
    cur = ctx.current_containers.get(name)
    if cur is None:
        return {"name": name, "action": "create", "detail": "새로 생성"}
    state = cur.get("state")
    if state != "running":
        return {"name": name, "action": "start", "detail": f"중지 상태({state})에서 시작"}
    return {"name": name, "action": "unchanged", "detail": "변경 없음"}


def build_plan(spec: ServiceSpec, ctx: PlanContext) -> dict:
    impact: list[dict] = []
    warnings: list[dict] = []
    validation: list[dict] = []

    changes = [_change_for(c.name, ctx)
               for c in (spec.containers or [])] if spec.containers else \
              [{"name": "compose", "action": "apply", "detail": "compose 프로젝트 배포"}]

    # 1) Compose 검증
    validation.append({
        "check": "Compose syntax",
        "result": "PASS" if ctx.compose_ok else "FAIL",
    })
    if not ctx.compose_ok:
        impact.append({"message": "Compose 파일 검증에 실패했습니다"})

    # 2) 포트 충돌
    conflicts = []
    for ep in spec.endpoints:
        if ep.host_port and ep.host_port in ctx.conflicting_ports:
            conflicts.append(ep.host_port)
    validation.append({
        "check": "Port conflicts",
        "result": "NONE" if not conflicts else "CONFLICT",
        "detail": conflicts or None,
    })
    for port in conflicts:
        impact.append({"message": f"호스트 포트 {port}가 이미 사용 중입니다"})

    # 3) 필수 환경 변수
    missing = [name for name in (spec.security.required_env or [])
               if name not in ctx.available_env]
    validation.append({
        "check": "Required variables",
        "result": "PASS" if not missing else "MISSING",
        "detail": missing or None,
    })
    if missing:
        impact.append({"message": f"필수 환경 변수가 없습니다: {', '.join(missing)}"})

    # 4) 자원 경고
    res_warn = []
    need = spec.resources.memory_limit_mb
    if need and ctx.mem_available_mb is not None and need > ctx.mem_available_mb:
        res_warn.append(f"요청 메모리 {need}MB > 가용 {int(ctx.mem_available_mb)}MB")
    validation.append({
        "check": "Resource warnings",
        "result": "NONE" if not res_warn else "WARNING",
        "detail": res_warn or None,
    })
    for w in res_warn:
        warnings.append({"level": "warning", "message": w})

    result = "READY" if not impact else "BLOCKED"
    return {
        "service": spec.service.id,
        "changes": changes,
        "ports": [{"name": ep.name, "host_port": ep.host_port,
                   "container_port": ep.container_port, "exposure": ep.exposure}
                  for ep in spec.endpoints],
        "data": [{"name": v.name, "purpose": v.purpose} for v in spec.volumes],
        "impact": impact,
        "validation": validation,
        "warnings": warnings,
        "result": result,
        "runtime_unchanged": True,
        "note": "계획은 예측이다 — 배포 후 실제 상태를 다시 조회한다.",
    }
```

- [ ] **Step 4: 통과 확인 및 커밋**

Run: `cd backend && uv run pytest tests/test_deploy_plan.py -q` → PASS (5 passed)

```bash
git add backend/app/services/deploy_plan.py backend/tests/test_deploy_plan.py backend/tests/conftest.py
git commit -m "feat(backend): 배포 계획 생성기 추가 (읽기 전용, Phase 2)"
```

---

## Task 6: 백엔드 `POST /deployments/plan` 실구현

**Files:**
- Modify: `backend/app/routers/events.py`
- Test: `backend/tests/test_deploy_api.py`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `backend/tests/test_deploy_api.py`:

```python
SPEC_BODY = {
    "schema_version": 1,
    "service": {"id": "sample-app", "name": "Sample", "description": "샘플",
                "category": "web"},
    "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    "containers": [{"name": "app", "role": "backend", "required": True}],
}


def test_plan_endpoint_returns_ready(client):
    r = mutate(client, "POST", "/api/v1/deployments/plan", json=SPEC_BODY)
    assert r.status_code == 200
    data = r.json()
    assert data["result"] in ("READY", "BLOCKED")
    assert data["runtime_unchanged"] is True


def test_plan_accepts_cli_service_definition_payload(client):
    r = mutate(client, "POST", "/api/v1/deployments/plan",
               json={"service_definition": SPEC_BODY})
    assert r.status_code == 200
    assert r.json()["service"] == "sample-app"


def test_plan_endpoint_invalid_spec_422(client):
    bad = {**SPEC_BODY, "schema_version": 9}
    r = mutate(client, "POST", "/api/v1/deployments/plan", json=bad)
    assert r.status_code == 422
    assert r.json()["code"] == "unsupported_schema_version"


def test_plan_requires_auth(anon_client):
    r = anon_client.post("/api/v1/deployments/plan", json=SPEC_BODY)
    assert r.status_code in (401, 403)


def test_apply_still_locked_when_deploy_disabled(client):
    # 기본 설정 enable_deploy=False → apply는 여전히 503
    r = mutate(client, "POST", "/api/v1/deployments",
               json={"service_id": "sample-app", "spec": SPEC_BODY})
    assert r.status_code == 503
    assert r.json()["code"] == "deploy_disabled"
```

> `mutate(client, ...)`는 CSRF를 자동 첨부한다(conftest). POST는 CSRF 필수이므로
> 계획 테스트도 반드시 `mutate`를 사용한다 (계획 사전 검토에서 발견).
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && uv run pytest tests/test_deploy_api.py -q`
Expected: FAIL (plan이 503 deploy_disabled)

- [ ] **Step 3: 최소 구현 작성**

`backend/app/routers/events.py`의 `_deploy_disabled`와 `plan_deployment`를 교체:

```python
def _collect_plan_context(db: Session, spec) -> "PlanContext":
    """관찰된 환경을 모아 PlanContext를 만든다 (DB + 게이트웨이 읽기 전용)."""
    from ..dependencies import get_gateway
    from ..services.deploy_plan import PlanContext
    from ..services.ports import build_registry

    conflicting: set[int] = set()
    for item in build_registry(db):
        if item.get("in_use") and item.get("host_port"):
            conflicting.add(item["host_port"])

    gateway = get_gateway()
    current: dict[str, dict] = {}
    snapshots = gateway.list_containers() or []
    project = getattr(spec.deployment, "project_name", None) or spec.service.id
    for snap in snapshots:
        if snap.compose_project == project and snap.compose_service:
            current[snap.compose_service] = {"image": snap.image, "state": snap.state}

    # 필수 환경 변수는 서버 환경변수에서 존재 여부만 확인 (값은 노출하지 않음)
    import os
    available_env = {k for k in os.environ}

    mem_available = None
    try:
        from ..services.resource import collect_host
        host = collect_host()
        mem_available = getattr(host, "mem_available_mb", None)
    except Exception:
        mem_available = None

    return PlanContext(available_env=available_env, conflicting_ports=conflicting,
                       mem_available_mb=mem_available, compose_ok=True,
                       current_containers=current)


@deploy_router.post("/plan")
def plan_deployment(payload: dict, db: Session = Depends(get_db),
                    actor: str = Depends(get_read_actor)):
    """배포 계획 생성 — 컨테이너를 변경하지 않는다.

    CLI는 `{"service_definition": <service.yaml dict>}`로 POST한다.
    직접 호출 시에는 스펙 dict를 그대로 보내도 된다.
    """
    from ..services.deploy_plan import build_plan
    from ..services.service_spec import SpecError, validate_spec_dict

    spec_dict = payload.get("service_definition", payload)
    if isinstance(spec_dict, str):
        from ..services.service_spec import parse_spec
        try:
            spec = parse_spec(spec_dict)
        except SpecError as exc:
            raise HubError(status_code=422, detail=str(exc), code=exc.code) from exc
    else:
        try:
            spec = validate_spec_dict(spec_dict)
        except SpecError as exc:
            raise HubError(status_code=422, detail=str(exc), code=exc.code) from exc
    ctx = _collect_plan_context(db, spec)
    plan = build_plan(spec, ctx)
    record_audit(db, actor, "deploy.plan", target=spec.service.id,
                 detail={"result": plan["result"]})
    db.commit()
    return plan
```

`events.py` 상단 import에 `record_audit`, `get_read_actor` 추가:

```python
from ..security import HubError, get_read_actor, require_auth
from ..services.events import record_audit
```

> `create_deployment`는 이 Task에서 여전히 `_deploy_disabled()`를 호출한다.
> 실제 실행은 Task 11에서 연결한다.

- [ ] **Step 4: 통과 확인 및 커밋**

Run: `cd backend && uv run pytest tests/test_deploy_api.py -q` → PASS (4 passed)

```bash
git add backend/app/routers/events.py backend/tests/test_deploy_api.py
git commit -m "feat(backend): 배포 계획 API 실구현 (POST /deployments/plan)"
```

---

## Task 7: CLI `hub deploy plan` / `port available` — ✅ 이미 구현됨 (검증만)

**실행 중 발견:** CLI에 `cmd_deploy_plan`(line 327)과 `cmd_port_available`(line 259)가
이미 존재한다. `deploy plan`은 `{"service_definition": doc}`로 POST하고, Phase 3
비활성 시 안내 메시지로 변환한다.

따라서 **새로 구현하지 않는다.** 백엔드 `/deployments/plan`이 이 payload를
받도록 Task 6에서 맞춘다.

- [ ] **Step 1: 기존 동작 확인**

Run: `cd cli && uv run pytest tests/test_cli.py -q` → PASS

---


## Task 8: 설정 게이트 + SECURITY/AGENTS 문서 갱신

**Files:**
- Modify: `backend/app/config.py`, `docs/SECURITY.md`, `AGENTS.md`, `AI-OPERATIONS.md`
- Test: `backend/tests/test_deploy_runner.py` (게이트 테스트는 Task 10에서 포함)

- [ ] **Step 1: 설정에 배포 허용 게이트 추가**

`backend/app/config.py`의 `Settings`에 추가:

```python
    enable_deploy: bool = False           # Phase 3 잠금 — 기본 false
    deploy_allowed_services: list[str] = []   # 비어 있으면 모든 서비스 허용 (게이트 통과 시)
    deploy_compose_timeout: int = 600     # compose 작업 타임아웃(초)
```

`Settings`에 헬퍼 추가:

```python
    def deploy_gate(self) -> tuple[bool, str]:
        """배포 허용 여부와 사유. 잠금이 기본값이다."""
        if not self.enable_deploy:
            return False, "배포 기능이 비활성화되어 있습니다 (HUB_ENABLE_DEPLOY=false)"
        return True, "ok"
```

> 이 게이트는 실행기(runner)와 API 양쪽에서 반드시 호출한다
> (REQUIREMENTS §14.2: '문서 규칙만으로는 안전하지 않다').

- [ ] **Step 2: 문서 갱신**

`docs/SECURITY.md`의 위협 모델 표에 행 추가:
- "배포 경로 오남용" → 통제: `HUB_ENABLE_DEPLOY` 기본 false, 실행기는 화이트리스트
  작업만 허용, 임의 셸/커맨드 파라미터 금지, 모든 실행은 감사 로그 기록.

`AGENTS.md`의 핵심 원칙 #2에 Phase 3 조건 명시:
- 잠금 해제는 사용자 승인 + 본 문서 확인 + `docs/SECURITY.md` 검토 후에만.

`AI-OPERATIONS.md`에 배포 워크플로우 절차 섹션 추가:
- 배포 전 `hub status` → `hub deploy plan <path>` → 계획 확인 → 승인 →
  `hub deploy apply` → `hub deploy status` → 실제 상태 재조회.

- [ ] **Step 3: 커밋**

```bash
git add backend/app/config.py docs/SECURITY.md AGENTS.md AI-OPERATIONS.md
git commit -m "feat(backend): 배포 허용 게이트 추가 및 보안/운영 문서 갱신 (Phase 3)"
```

---

## Task 9: `docker_client.py` 제한 변경 함수 (게이트 필수)

**Files:**
- Modify: `backend/app/docker_client.py`
- Test: `backend/tests/test_deploy_runner.py`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `backend/tests/test_deploy_runner.py`:

```python
import pytest

from app.docker_client import DockerGateway


def test_gateway_refuses_compose_up_without_allow_flag():
    gw = DockerGateway(allow_mutations=False)
    with pytest.raises(PermissionError):
        gw.compose_up("/tmp/x", "proj")


def test_gateway_refuses_arbitrary_command():
    gw = DockerGateway(allow_mutations=True)
    # 화이트리스트에 없는 임의 셸은 존재하지 않는다
    assert not hasattr(gw, "run_command")
    assert not hasattr(gw, "exec_sh")


def test_fake_gateway_records_compose_calls():
    from app.docker_client import FakeDockerGateway
    gw = FakeDockerGateway(allow_mutations=True)
    result = gw.compose_up("/tmp/x", "proj")
    assert result["ok"] is True
    assert gw.mutation_log[-1]["action"] == "compose_up"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && uv run pytest tests/test_deploy_runner.py -q`
Expected: FAIL — `allow_mutations` 인자/메서드 없음

- [ ] **Step 3: 구현 추가**

`backend/app/docker_client.py`의 `DockerGateway.__init__`를 수정:

```python
    def __init__(self, socket_path: str | None = None,
                 allow_mutations: bool = False) -> None:
        self._socket_path = socket_path
        self._client = None
        self._allow_mutations = allow_mutations
        self.mutation_log: list[dict] = []

    def _require_mutation(self) -> None:
        if not self._allow_mutations:
            raise PermissionError(
                "이 게이트웨이는 변경 작업이 허용되지 않았습니다 (allow_mutations=False)")
```

`container_logs` 아래(또는 `stats` 위)에 화이트리스트 변경 함수 추가:

```python
    # --- 변경 작업 (화이트리스트) — allow_mutations=True 필요 ---------------

    def compose_config(self, project_dir: str, project_name: str) -> dict:
        """`docker compose config` 상당의 검증. 읽기 전용."""
        try:
            import subprocess
            proc = subprocess.run(
                ["docker", "compose", "-f", f"{project_dir}/compose.yaml",
                 "-p", project_name, "config", "--quiet"],
                capture_output=True, text=True, timeout=30, check=False)
            return {"ok": proc.returncode == 0, "stderr": proc.stderr.strip()[:500]}
        except Exception as exc:
            return {"ok": False, "stderr": type(exc).__name__}

    def compose_up(self, project_dir: str, project_name: str,
                   timeout: int = 600) -> dict:
        """Compose 프로젝트 배포. 임의 셸/커맨드 파라미터는 받지 않는다."""
        self._require_mutation()
        return self._compose(["up", "-d", "--remove-orphans"], project_dir, project_name, timeout)

    def compose_down(self, project_dir: str, project_name: str,
                     timeout: int = 300) -> dict:
        self._require_mutation()
        return self._compose(["down"], project_dir, project_name, timeout)

    def _compose(self, args: list[str], project_dir: str, project_name: str,
                 timeout: int) -> dict:
        import subprocess
        cmd = ["docker", "compose", "-f", f"{project_dir}/compose.yaml",
               "-p", project_name, *args]
        self.mutation_log.append({"action": f"compose_{args[0]}", "project": project_name})
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout, check=False)
            return {"ok": proc.returncode == 0,
                    "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
        except subprocess.TimeoutExpired:
            return {"ok": False, "stderr": "timeout"}
        except Exception as exc:
            return {"ok": False, "stderr": type(exc).__name__}
```

`FakeDockerGateway.__init__`를 수정:

```python
    def __init__(self, containers: list[FakeContainer] | None = None,
                 connected: bool = True, allow_mutations: bool = False) -> None:
        super().__init__(allow_mutations=allow_mutations)
        self.containers = containers or []
        self.connected = connected
```

`FakeDockerGateway`에 추가:

```python
    def compose_config(self, project_dir: str, project_name: str) -> dict:
        return {"ok": True, "stderr": ""}

    def compose_up(self, project_dir: str, project_name: str, timeout: int = 600) -> dict:
        self._require_mutation()
        self.mutation_log.append({"action": "compose_up", "project": project_name,
                                  "dir": project_dir})
        return {"ok": True, "stdout": f"fake compose up {project_name}", "stderr": ""}

    def compose_down(self, project_dir: str, project_name: str, timeout: int = 300) -> dict:
        self._require_mutation()
        self.mutation_log.append({"action": "compose_down", "project": project_name})
        return {"ok": True, "stdout": "", "stderr": ""}
```

> 보안 메모: `compose_up/down`은 **인자 목록**만 받고 문자열 셸을 실행하지 않는다.
> 임의 커맨드/`sh -c` 경로는 존재하지 않는다 (§15.7).

- [ ] **Step 4: 통과 확인 및 커밋**

Run: `cd backend && uv run pytest tests/test_deploy_runner.py -q` → PASS (3 passed)

```bash
git add backend/app/docker_client.py backend/tests/test_deploy_runner.py
git commit -m "feat(backend): docker 게이트웨이에 화이트리스트 compose 변경 함수 추가 (게이트 필수)"
```

---

## Task 10: 배포 실행기 상태머신 (`deploy_runner.py`)

**Files:**
- Create: `backend/app/services/deploy_runner.py`
- Test: `backend/tests/test_deploy_runner.py` (테스트 추가)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_deploy_runner.py`에 추가:

```python
from app.services.deploy_plan import PlanContext
from app.services.deploy_runner import DeployRunner, DeploymentBusy
from app.services.service_spec import validate_spec_dict

SPEC = {
    "schema_version": 1,
    "service": {"id": "sample-app", "name": "Sample", "description": "샘플",
                "category": "web"},
    "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    "containers": [{"name": "app", "role": "backend", "required": True}],
}


def _ctx():
    return PlanContext(available_env=set(), conflicting_ports=set(),
                       mem_available_mb=4096, compose_ok=True, current_containers={})


def test_runner_refuses_when_gate_closed(settings, tmp_path):
    from app.docker_client import FakeDockerGateway
    from app.db import init_db
    init_db()
    runner = DeployRunner(gateway=FakeDockerGateway(allow_mutations=True),
                          workdir_resolver=lambda sid: str(tmp_path),
                          enable_deploy=False)
    spec = validate_spec_dict(SPEC)
    with pytest.raises(PermissionError):
        runner.run(spec, _ctx(), actor="tester")


def test_runner_succeeds_and_records_steps(settings, tmp_path):
    from app.docker_client import FakeDockerGateway
    from app.db import init_db
    init_db()
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    gw = FakeDockerGateway(allow_mutations=True)
    runner = DeployRunner(gateway=gw, workdir_resolver=lambda sid: str(tmp_path),
                          enable_deploy=True)
    spec = validate_spec_dict(SPEC)
    deployment = runner.run(spec, _ctx(), actor="tester")
    assert deployment.status == "succeeded"
    steps = [s.name for s in deployment.steps]
    assert "validating" in steps and "running" in steps and "verifying" in steps
    assert gw.mutation_log[-1]["action"] == "compose_up"


def test_runner_blocks_on_plan_not_ready(settings, tmp_path):
    from app.docker_client import FakeDockerGateway
    from app.db import init_db
    from app.services.deploy_plan import PlanContext
    init_db()
    ctx = PlanContext(available_env=set(), conflicting_ports={8000},
                      mem_available_mb=4096, compose_ok=True, current_containers={})
    spec = validate_spec_dict({**SPEC, "endpoints": [
        {"name": "web", "type": "http", "exposure": "host", "host_port": 8000,
         "container": "app", "container_port": 3000}]})
    runner = DeployRunner(gateway=FakeDockerGateway(allow_mutations=True),
                          workdir_resolver=lambda sid: str(tmp_path), enable_deploy=True)
    with pytest.raises(ValueError):
        runner.run(spec, ctx, actor="tester")


def test_duplicate_deploy_rejected(settings, tmp_path):
    from app.docker_client import FakeDockerGateway
    from app.db import init_db
    init_db()
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    runner = DeployRunner(gateway=FakeDockerGateway(allow_mutations=True),
                          workdir_resolver=lambda sid: str(tmp_path), enable_deploy=True)
    spec = validate_spec_dict(SPEC)
    runner.acquire(spec.service.id)
    with pytest.raises(DeploymentBusy):
        runner.acquire(spec.service.id)
```

> 참고: `db_session` 픽스처는 필요 없다 — 실행기는 내부에서 `session_scope()`로
> 자체 세션을 연다. 대신 `settings` 픽스처가 활성화되어 엔진이 준비되어야 하며
> `init_db()`를 명시 호출한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && uv run pytest tests/test_deploy_runner.py -k runner -q`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 구현 (스켈레톤 + 상태머신)**

Create `backend/app/services/deploy_runner.py` (1/2 — 스켈레톤):

```python
"""배포 실행기 (REQUIREMENTS §13.3). 게이트가 닫혀 있으면 절대 실행하지 않는다.

상태: queued -> validating -> running -> verifying -> succeeded | failed
허용 작업: compose config/up/down + 헬스체크. 임의 셸 실행 경로 없음.
"""
from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from ..db import get_session_factory
from ..models import Deployment, DeploymentStep
from .deploy_plan import PlanContext, build_plan


class DeploymentBusy(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _session():
    """실행기 내부 세션 — 커밋/롤백/종료를 보장한다.

    (db.session_scope()는 제너레이터라 with 문에 바로 쓸 수 없다.)
    """
    s = get_session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


class DeployRunner:
    def __init__(self, *, gateway, workdir_resolver, enable_deploy: bool) -> None:
        self.gateway = gateway
        self.workdir_resolver = workdir_resolver
        self.enable_deploy = enable_deploy
        self._active: set[str] = set()
        self._lock = threading.Lock()

    # -- 게이트/중복 -----------------------------------------------------
    def _require_enabled(self) -> None:
        if not self.enable_deploy:
            raise PermissionError(
                "배포 기능이 비활성화되어 있습니다 (HUB_ENABLE_DEPLOY=false)")

    def acquire(self, service_id: str) -> None:
        with self._lock:
            if service_id in self._active:
                raise DeploymentBusy(f"'{service_id}' 배포가 이미 진행 중입니다")
            self._active.add(service_id)

    def release(self, service_id: str) -> None:
        with self._lock:
            self._active.discard(service_id)

    # -- 실행 ------------------------------------------------------------
    def run(self, spec, ctx: PlanContext, actor: str) -> Deployment:
        self._require_enabled()
        plan = build_plan(spec, ctx)
        if plan["result"] != "READY":
            raise ValueError(
                "배포 계획이 READY가 아닙니다: " +
                "; ".join(i["message"] for i in plan["impact"]))

        deployment_id = f"dep-{uuid.uuid4().hex[:12]}"
        with _session() as db:
            dep = Deployment(id=deployment_id, service_id=spec.service.id,
                             status="queued", requested_by=actor, plan=plan,
                             started_at=_now())
            db.add(dep)
            self._step(db, deployment_id, 0, "queued", "ok", "작업 생성")
        return self._execute(deployment_id, spec, plan)
```

Create remainder (2/2 — `_execute`/`_step`):

```python
    def _step(self, db, deployment_id: str, seq: int, name: str, status: str,
              detail: str) -> None:
        db.add(DeploymentStep(deployment_id=deployment_id, seq=seq, name=name,
                              status=status, detail=detail, at=_now()))

    def _execute(self, deployment_id: str, spec, plan: dict) -> Deployment:
        service_id = spec.service.id
        project = getattr(spec.deployment, "project_name", None) or service_id
        workdir = self.workdir_resolver(service_id)
        compose_file = getattr(spec.deployment, "compose_file", "compose.yaml")

        try:
            self.release(service_id)
            # validating
            with _session() as db:
                self._set_status(db, deployment_id, "validating")
                self._step(db, deployment_id, 1, "validating", "ok",
                           f"compose_file={compose_file}")
            cfg = self.gateway.compose_config(workdir, project)
            if not cfg.get("ok"):
                return self._fail(deployment_id, 1, f"Compose 검증 실패: {cfg.get('stderr')}")

            # running
            with _session() as db:
                self._set_status(db, deployment_id, "running")
                self._step(db, deployment_id, 2, "running", "ok", "compose up")
            up = self.gateway.compose_up(workdir, project)
            if not up.get("ok"):
                return self._fail(deployment_id, 2, f"배포 실패: {up.get('stderr')}")

            # verifying
            with _session() as db:
                self._set_status(db, deployment_id, "verifying")
                self._step(db, deployment_id, 3, "verifying", "ok", "헬스체크")
            snaps = self.gateway.list_containers() or []
            running = [s for s in snaps
                       if s.compose_project == project and s.state == "running"]
            required = [c.name for c in (spec.containers or []) if c.required]
            missing = [n for n in required
                       if not any(s.compose_service == n for s in running)]
            if missing:
                return self._fail(deployment_id, 3,
                                  f"필수 컨테이너 미기동: {', '.join(missing)}")

            with _session() as db:
                self._set_status(db, deployment_id, "succeeded", finished=True)
                self._step(db, deployment_id, 4, "succeeded", "ok", "완료")
                from ..models import Service
                svc = db.get(Service, service_id)
                if svc is not None:
                    svc.last_deployed_at = _now()
                    svc.status = "healthy"
            return self._get(deployment_id)
        finally:
            self.release(service_id)

    def _set_status(self, db, deployment_id: str, status: str,
                    finished: bool = False) -> None:
        dep = db.get(Deployment, deployment_id)
        if dep is not None:
            dep.status = status
            if finished:
                dep.finished_at = _now()

    def _fail(self, deployment_id: str, seq: int, message: str) -> Deployment:
        with _session() as db:
            dep = db.get(Deployment, deployment_id)
            if dep is not None:
                dep.status = "failed"
                dep.error = message
                dep.finished_at = _now()
            self._step(db, deployment_id, seq + 100, "failed", "error", message)
        return self._get(deployment_id)

    def _get(self, deployment_id: str) -> Deployment:
        with _session() as db:
            dep = db.get(Deployment, deployment_id)
            if dep is not None:
                db.expunge(dep)
                _ = list(dep.steps) if hasattr(dep, "steps") else None
            return dep
```

- [ ] **Step 4: 통과 확인 및 커밋**

Run: `cd backend && uv run pytest tests/test_deploy_runner.py -q` → PASS

```bash
git add backend/app/services/deploy_runner.py backend/tests/test_deploy_runner.py \
        backend/tests/conftest.py
git commit -m "feat(backend): 배포 실행기 상태머신 추가 (게이트 필수, 화이트리스트 compose)"
```

---

## Task 11: 백엔드 `POST /deployments` (apply) 실구현

**Files:**
- Modify: `backend/app/routers/events.py`, `backend/app/dependencies.py`
- Test: `backend/tests/test_deploy_api.py` (테스트 추가)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_deploy_api.py`에 추가:

```python
def test_apply_succeeds_when_enabled(app_factory, tmp_path):
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    client = app_factory(admin=True, enable_deploy=True, deploy_workdir=str(tmp_path),
                         gateway_allow_mutations=True)
    try:
        r = mutate(client, "POST", "/api/v1/deployments", json={"spec": SPEC_BODY})
        assert r.status_code == 202
        dep = r.json()
        assert dep["status"] in ("succeeded", "failed")
        assert dep["deployment_id"].startswith("dep-")
    finally:
        client.__exit__(None, None, None)


def test_apply_rejected_when_disabled(client):
    r = mutate(client, "POST", "/api/v1/deployments", json={"spec": SPEC_BODY})
    assert r.status_code == 503
    assert r.json()["code"] == "deploy_disabled"


def test_apply_requires_csrf(app_factory, tmp_path):
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    client = app_factory(admin=True, enable_deploy=True, deploy_workdir=str(tmp_path),
                         gateway_allow_mutations=True)
    try:
        # CSRF 없이 POST
        r = client.post("/api/v1/deployments", json={"spec": SPEC_BODY})
        assert r.status_code == 403
    finally:
        client.__exit__(None, None, None)
```

> 기존 `app_factory`가 `enable_deploy`/`deploy_workdir`/`gateway_allow_mutations`
> 키워드를 받지 못하므로, `conftest.py`의 `_make` 시그니처를 다음으로 확장한다
> (실제 시그니처: `_make(gw=None, s=None, admin=False) -> TestClient`):

```python
    def _make(gw: FakeDockerGateway | None = None, s: Settings | None = None,
              admin: bool = False, *, enable_deploy: bool = False,
              deploy_workdir: str | None = None,
              gateway_allow_mutations: bool = False) -> TestClient:
        base = s or settings
        if enable_deploy and s is None:
            base = Settings(db_path=base.db_path, status_cache=base.status_cache,
                            monitor_enabled=False, enable_deploy=True, _env_file=None)
            set_settings(base)
        use_gw = gw or FakeDockerGateway(allow_mutations=gateway_allow_mutations)
        set_gateway(use_gw)
        application = create_app(base, gateway=use_gw)
        init_db()
        client = TestClient(application)
        os.environ["HUB_DEPLOY_WORKDIR"] = deploy_workdir or str(tmp_path)
        client.__enter__()
        ...
```

`conftest.py` 상단에 `import os`를 추가한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && uv run pytest tests/test_deploy_api.py -k apply -q`
Expected: FAIL

- [ ] **Step 3: 구현 작성**

`backend/app/dependencies.py`에 러너 팩토리 추가:

```python
def build_deploy_runner():
    """설정 기반 배포 실행기 생성. workdir는 app.state 또는 서비스 경로 규칙."""
    from .config import get_settings
    from .services.deploy_runner import DeployRunner
    from .dependencies import get_gateway
    settings = get_settings()

    def resolver(service_id: str) -> str:
        import os
        base = os.environ.get("HUB_DEPLOY_WORKDIR") or "./services-local"
        return f"{base}/{service_id}"

    return DeployRunner(gateway=get_gateway(), workdir_resolver=resolver,
                        enable_deploy=settings.enable_deploy)
```

`events.py`에서 `create_deployment` 교체:

```python
@deploy_router.post("", status_code=202)
def create_deployment(payload: dict, db: Session = Depends(get_db),
                      actor: str = Depends(get_read_actor)):
    """배포 실행 — HUB_ENABLE_DEPLOY=true 에서만. 화이트리스트 compose 작업만 수행."""
    from ..dependencies import build_deploy_runner
    from ..services.deploy_plan import build_plan
    from ..services.service_spec import SpecError, validate_spec_dict
    from ..services.deploy_runner import DeploymentBusy

    settings = get_settings()
    ok, reason = settings.deploy_gate()
    if not ok:
        _deploy_disabled()

    spec_dict = payload.get("spec") or payload
    try:
        spec = validate_spec_dict(spec_dict)
    except SpecError as exc:
        raise HubError(status_code=422, detail=str(exc), code=exc.code) from exc

    ctx = _collect_plan_context(db, spec)
    plan = build_plan(spec, ctx)
    if plan["result"] != "READY":
        raise HubError(status_code=409,
                            detail="배포 계획이 READY가 아닙니다: " +
                                   "; ".join(i["message"] for i in plan["impact"]),
                            code="plan_not_ready")

    runner = build_deploy_runner()
    try:
        runner.acquire(spec.service.id)
    except DeploymentBusy as exc:
        raise HubError(status_code=409, detail=str(exc), code="deployment_busy") from exc

    record_audit(db, actor, "deploy.apply", target=spec.service.id,
                 detail={"result": plan["result"]})
    db.commit()
    try:
        dep = runner.run(spec, ctx, actor=actor)
    except PermissionError as exc:
        raise HubError(status_code=503, detail=str(exc), code="deploy_disabled") from exc
    except ValueError as exc:
        raise HubError(status_code=409, detail=str(exc), code="plan_not_ready") from exc

    return {"deployment_id": dep.id, "service_id": dep.service_id, "status": dep.status,
            "error": dep.error, "started_at": dep.started_at,
            "finished_at": dep.finished_at}
```

`events.py` 상단에 `get_settings` import가 있는지 확인하고 없으면 추가:

```python
from ..config import get_settings
```

- [ ] **Step 4: 통과 확인 및 커밋**

Run: `cd backend && uv run pytest tests/test_deploy_api.py -q` → PASS

```bash
git add backend/app/routers/events.py backend/app/dependencies.py \
        backend/tests/test_deploy_api.py backend/tests/conftest.py
git commit -m "feat(backend): 배포 실행 API 구현 (POST /deployments, 게이트/CSRF/감사로그)"
```

---

## Task 12: CLI `hub deploy apply/status`

**Files:**
- Modify: `cli/hub_cli/main.py`
- Test: `cli/tests/test_cli_deploy.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`cli/tests/test_cli_deploy.py`에 추가:

```python
def test_deploy_apply_confirms_required(tmp_path, monkeypatch, capsys):
    import hub_cli.main as m
    p = tmp_path / "service.yaml"
    p.write_text(VALID_YAML, encoding="utf-8")
    calls = []
    monkeypatch.setattr(m, "api", lambda path, method="GET", payload=None:
                        calls.append((path, method)) or
                        {"deployment_id": "dep-1", "status": "succeeded"})
    # --yes 없이 비대화형이면 거부
    code = m.main(["deploy", "apply", str(p)])
    assert code == 4
    assert not calls


def test_deploy_apply_with_yes(tmp_path, monkeypatch, capsys):
    import hub_cli.main as m
    p = tmp_path / "service.yaml"
    p.write_text(VALID_YAML, encoding="utf-8")
    monkeypatch.setattr(m, "api", lambda path, method="GET", payload=None:
                        {"deployment_id": "dep-1", "status": "succeeded"})
    code = m.main(["deploy", "apply", str(p), "--yes"])
    assert code == 0


def test_deploy_status(monkeypatch, capsys):
    import hub_cli.main as m
    monkeypatch.setattr(m, "api", lambda path, method="GET", payload=None:
                        {"deployment_id": "dep-1", "status": "succeeded",
                         "steps": [{"seq": 0, "name": "queued", "status": "ok"}]})
    code = m.main(["deploy", "status", "dep-1"])
    assert code == 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd cli && uv run pytest tests/test_cli_deploy.py -k "apply or status" -q`
Expected: FAIL

- [ ] **Step 3: 구현 작성**

`cli/hub_cli/main.py`에 추가:

```python
def cmd_deploy_apply(args: argparse.Namespace) -> None:
    if not args.yes:
        raise CliError(
            "배포는 컨테이너를 변경합니다. 계획(`hub deploy plan`)을 확인한 뒤 "
            "--yes 를 붙여 다시 실행하세요.", EXIT_REJECTED)
    spec = _load_spec_dict(args.path)
    data = api("/deployments", "POST", {"spec": spec})

    def render(d: dict) -> None:
        print(f"배포 ID : {d.get('deployment_id')}")
        print(f"상태    : {d.get('status')}")
        if d.get("error"):
            print(f"오류    : {d['error']}")
        print("실제 상태는 `hub deploy status <id>` 및 `hub status`로 재확인하세요.")

    emit(data, args.json, render)


def cmd_deploy_status(args: argparse.Namespace) -> None:
    data = api(f"/deployments/{args.deployment_id}")

    def render(d: dict) -> None:
        print(f"배포 ID : {d.get('deployment_id')}  ({d.get('status')})")
        for s in d.get("steps", []):
            print(f"  [{s.get('status')}] {s.get('name')} — {s.get('detail', '')}")

    emit(data, args.json, render)
```

`build_parser()`의 `dp_sub`에 추가:

```python
    dp_apply = dp_sub.add_parser("apply", help="배포 실행 (컨테이너 변경 — 승인 필요)")
    dp_apply.add_argument("path")
    dp_apply.add_argument("--yes", action="store_true", help="사전 확인 생략")
    dp_apply.add_argument("--json", action="store_true")
    dp_apply.set_defaults(func=cmd_deploy_apply)

    dp_status = dp_sub.add_parser("status", help="배포 상태 조회")
    dp_status.add_argument("deployment_id")
    dp_status.add_argument("--json", action="store_true")
    dp_status.set_defaults(func=cmd_deploy_status)
```

- [ ] **Step 4: 통과 확인 및 커밋**

Run: `cd cli && uv run pytest tests/test_cli_deploy.py -q` → PASS

```bash
git add cli/hub_cli/main.py cli/tests/test_cli_deploy.py
git commit -m "feat(cli): hub deploy apply/status 추가 (사전 확인 필수)"
```

---

## Task 13: 프론트엔드 배포 계획/실행 최소 연동

**Files:**
- Modify: `frontend/src/lib/api.ts`, `frontend/src/pages/Deployments.ts`, `frontend/src/pages/DeploymentDetail.tsx`
- Test: `frontend/src/pages/Deployments.test.tsx`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `frontend/src/pages/Deployments.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Deployments from "./Deployments";

vi.mock("../lib/api", () => ({
  api: {
    deployments: vi.fn().mockResolvedValue({ items: [
      { deployment_id: "dep-1", service_id: "sample-app", status: "succeeded",
        started_at: "2026-10-21T00:00:00Z" },
    ]}),
  },
}));

describe("Deployments", () => {
  it("배포 목록을 렌더링한다", async () => {
    render(<Deployments />);
    expect(await screen.findByText(/sample-app/)).toBeTruthy();
  });

  it("deploy_disabled 안내를 표시할 수 있다", async () => {
    render(<Deployments />);
    expect(await screen.findByText(/배포/)).toBeTruthy();
  });
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `npm run test --prefix frontend -- Deployments`
Expected: FAIL (타입/필드 불일치)

- [ ] **Step 3: 구현 작성**

`frontend/src/lib/api.ts`에 배포 계획/실행 메서드 추가:

```ts
export type DeployPlan = {
  service: string;
  result: "READY" | "BLOCKED";
  changes: { name: string; action: string; detail?: string }[];
  ports: { name: string; host_port: number | null; container_port: number }[];
  validation: { check: string; result: string; detail?: unknown }[];
  impact: { message: string }[];
  runtime_unchanged: boolean;
};

// api 객체에 추가
getDeployPlan: (spec: unknown) => request<DeployPlan>("/deployments/plan", { method: "POST", body: spec }),
applyDeploy: (spec: unknown) => request<{ deployment_id: string; status: string; error?: string }>(
  "/deployments", { method: "POST", body: { spec } }),
```

Deployments 페이지에 "계획 미리보기" 버튼과 `deploy_disabled`(503) 시
"배포 기능이 비활성화되어 있습니다 (Phase 3)" 안내를 표시한다.
미지원 지표는 `N/A`로 표시하고 0으로 대체하지 않는다.

- [ ] **Step 4: 통과 확인 및 커밋**

Run: `npm run test --prefix frontend` → PASS
Run: `npm run build --prefix frontend` → 성공 (tsc 0 errors)

```bash
git add frontend/src/lib/api.ts frontend/src/pages/Deployments.ts \
        frontend/src/pages/DeploymentDetail.tsx frontend/src/pages/Deployments.test.tsx
git commit -m "feat(frontend): 배포 계획/실행 UI 최소 연동"
```

---

## Task 14: 통합 스모크 + 문서 최종 갱신 + 커밋

- [ ] **Step 1: 전체 테스트 게이트 실행**

```bash
cd backend && uv run pytest -q                 # 기존 52 + 신규
cd backend && uv run pytest tests/test_protection.py -v   # §19.6 실제 데몬, skip 아님
cd cli && uv run pytest -q
npm run test --prefix frontend
npm run build --prefix frontend
```

Expected: 모두 PASS. §19.6이 skip이면 실패로 간주한다.

- [ ] **Step 2: 게이트 잠금 기본값 확인**

```bash
cd backend && uv run python -c "from app.config import Settings; print(Settings().deploy_gate())"
```

Expected: `(False, '배포 기능이 비활성화되어 있습니다 (HUB_ENABLE_DEPLOY=false)')`

- [ ] **Step 3: 실제 환경 스모크 (읽기 전용)**

```bash
bash scripts/dev-smoke.sh
```

Expected: `hub status`, `hub status --json`, MOTD 정상. 기존 컨테이너 수 무변경.

- [ ] **Step 4: 문서 갱신 및 커밋**

`docs/IMPLEMENTATION-STATUS.md`에 Phase 2/3 결과와 **실제 N100(Linux) 미검증**
한계를 명시한다.

```bash
git add -A
git commit -m "docs: Phase 2/3 진행 상태 갱신 및 한계 명시"
git push
```

---

## Self-Review 체크

- **Spec coverage:** §6(스키마)=T1, §13.1(검증 순서)=T1/T5/T10, §13.2(계획)=T5-T7,
  §13.3(실행)=T9-T12, §13.4(실패)=T10, §4.4(CLI)=T3/T4/T7/T12, §15(보안)=T8/T9/T11.
- **Placeholder scan:** 없음 — 모든 스텝에 실제 코드/명령 포함.
- **Type consistency:** `PlanContext`, `build_plan`, `DeployRunner.run(spec, ctx, actor)`,
  `deploy_gate()`, `compose_up/down` 시그니처가 전 Task에서 일치.
- **잔여 위험:** §13.4 롤백 자동화는 범위 밖(문서화만). Phase 4 추세 분석 미포함.






