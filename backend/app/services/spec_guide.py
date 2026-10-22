"""service.yaml 작성 안내 (UI/문서 공용).

정의의 단일 출처는 ``schemas/service.schema.v1.json`` 과 ``service_spec.py`` 이며,
이 모듈은 사람이 읽는 예시·필드 설명·규칙을 제공한다. UI( Services > 작성 안내 )와
``docs/SERVICE-YAML.md`` 가 같은 내용을 보여주도록 여기서 관리한다.
"""
from __future__ import annotations

from .template_render import SERVICE_YAML

EXAMPLE_ID = "my-app"

CATEGORIES = ["web", "backend", "database", "ai", "automation", "media", "dev",
              "infra", "other"]
CONTAINER_ROLES = ["frontend", "backend", "worker", "database", "cache", "proxy", "other"]
ENDPOINT_TYPES = ["http", "https", "tcp", "udp", "grpc"]
EXPOSURES = ["proxy", "host", "internal"]
RESTART_POLICIES = ["no", "always", "unless-stopped", "on-failure"]

MINIMAL_EXAMPLE = """\
schema_version: 1
service:
  id: my-app
  name: My App
  description: 무슨 일을 하는 서비스인지 한 줄로 적습니다.
  category: web
deployment:
  type: docker-compose
  compose_file: compose.yaml
containers:
  - name: app
    role: backend
    required: true
"""


def _full_example() -> str:
    return (SERVICE_YAML
            .replace("{{ID}}", EXAMPLE_ID)
            .replace("{{NAME}}", "My App")
            .replace("{{CATEGORY}}", "web"))


def _f(path: str, required: bool, typ: str, description: str,
       allowed: str | None = None) -> dict:
    return {"path": path, "required": required, "type": typ,
            "description": description, "allowed": allowed}


FIELDS: list[dict] = [
    _f("schema_version", True, "int", "스키마 버전. 현재 1만 지원", "1"),
    _f("service.id", True, "string",
       "서비스 고유 ID. 디렉터리 이름·compose 프로젝트 이름으로도 사용",
       "^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$ (3~64자, 소문자/숫자/하이픈)"),
    _f("service.name", True, "string", "표시 이름", "1~120자"),
    _f("service.description", True, "string", "목적·기능·주의사항", "1~2000자"),
    _f("service.category", True, "string", "분류", ", ".join(CATEGORIES)),
    _f("service.version", False, "string", "서비스 버전", None),
    _f("service.documentation", False, "string", "문서 경로", None),
    _f("service.tags", False, "string[]", "검색용 태그", None),
    _f("source.repository_url", False, "string", "저장소 URL", None),
    _f("source.branch", False, "string", "브랜치", None),
    _f("deployment.type", True, "string", "배포 방식", "docker-compose"),
    _f("deployment.compose_file", True, "string",
       "서비스 디렉터리 기준 compose 파일 경로", "예: compose.yaml"),
    _f("deployment.project_name", False, "string",
       "compose 프로젝트 이름(비우면 service.id)", None),
    _f("endpoints[].name", False, "string", "엔드포인트 이름", None),
    _f("endpoints[].type", False, "string", "프로토콜", ", ".join(ENDPOINT_TYPES)),
    _f("endpoints[].exposure", False, "string",
       "proxy=Traefik 도메인, host=직접 포트, internal=Docker 내부", ", ".join(EXPOSURES)),
    _f("endpoints[].hostname", False, "string", "exposure=proxy일 때 필수", None),
    _f("endpoints[].host_port", False, "int", "exposure=host일 때 필수", "1~65535"),
    _f("endpoints[].container", False, "string", "대상 컨테이너(compose 서비스명)", None),
    _f("endpoints[].container_port", False, "int", "컨테이너 내부 포트", "1~65535"),
    _f("containers[].name", False, "string",
       "**compose 서비스명과 동일**해야 상태/배포 검증이 맞음", None),
    _f("containers[].role", False, "string", "컨테이너 역할", ", ".join(CONTAINER_ROLES)),
    _f("containers[].required", False, "bool", "배포 후 기동 필수 여부", "기본 true"),
    _f("containers[].description", False, "string", "설명", None),
    _f("resources.memory_limit_mb", False, "int", "메모리 제한", "16 이상"),
    _f("resources.cpu_limit", False, "float", "CPU 제한", "0 초과"),
    _f("volumes[].name", False, "string", "볼륨 이름", None),
    _f("volumes[].purpose", False, "string", "용도", None),
    _f("volumes[].backup_required", False, "bool", "백업 필요 여부", "기본 false"),
    _f("operations.healthcheck_required", False, "bool", "헬스체크 요구", "기본 true"),
    _f("operations.backup_required", False, "bool", "백업 요구", "기본 false"),
    _f("operations.restart_policy", False, "string", "재시작 정책",
       ", ".join(RESTART_POLICIES)),
    _f("security.expose_database", False, "bool", "DB 외부 노출 여부", "기본 false"),
    _f("security.required_env", False, "string[]",
       "필수 환경변수 **이름만**. 값(dict)은 금지", "대문자로 시작하는 이름"),
]

RULES: list[str] = [
    "정의되지 않은 필드는 거부됩니다(오타 방지). 스키마에 있는 키만 사용하세요.",
    "시크릿 **값**을 service.yaml에 쓰지 마세요. `security.required_env`에는 이름만 적고,"
    " 실제 값은 서비스 디렉터리의 `.env`에 넣습니다(Git 커밋 금지).",
    "`schema_version`은 1만 지원합니다. 다른 값은 임의 해석하지 않고 거부합니다.",
    "`endpoints[].exposure=proxy`면 `hostname`이, `host`면 `host_port`가 필요합니다.",
    "`containers[].name`은 compose의 서비스명과 같아야 계획/배포 검증이 정확합니다.",
    "파일 위치는 `/srv/services/<service.id>/service.yaml` 고정입니다"
    " (배포 실행기가 이 경로만 읽습니다).",
    "`compose_file`은 서비스 디렉터리 기준 상대 경로입니다.",
    "배포 전 `hub service validate <경로>`로 스키마를 검증하세요.",
    "계획(`hub deploy plan`)이 READY여야 실행(`hub deploy apply <id> --yes`)할 수 있습니다.",
]


def guide() -> dict:
    """UI/문서가 함께 쓰는 작성 안내 데이터."""
    return {
        "schema_version": 1,
        "file_location": "/srv/services/<service.id>/service.yaml",
        "create_command": "hub service new <service-id> --dir /srv/services",
        "validate_command": "hub service validate /srv/services/<service-id>",
        "plan_command": "hub deploy plan /srv/services/<service-id>/service.yaml",
        "apply_command": "hub deploy apply <service-id> --yes",
        "minimal_example": MINIMAL_EXAMPLE,
        "full_example": _full_example(),
        "fields": FIELDS,
        "rules": RULES,
        "enums": {
            "category": CATEGORIES,
            "container_role": CONTAINER_ROLES,
            "endpoint_type": ENDPOINT_TYPES,
            "exposure": EXPOSURES,
            "restart_policy": RESTART_POLICIES,
        },
        "docs": "docs/SERVICE-YAML.md",
    }
