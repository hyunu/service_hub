# service.yaml 작성 안내 (스키마 v1)

서비스의 **정의 파일**입니다. 허브 UI에서 서비스를 등록하는 것(DB 레코드)과는 별개이며,
**배포 실행기(`hub deploy plan/apply`)가 이 파일을 읽습니다.**

- 파일 위치: `/srv/services/<service.id>/service.yaml` (고정)
- 스키마: `schemas/service.schema.v1.json`
- 검증: `hub service validate /srv/services/<service-id>`
- UI 안내: **Services → service.yaml 안내** (같은 내용을 대시보드에서 확인)

## 1. 생성

```bash
sudo hub service new my-app --dir /srv/services
# service.yaml / compose.yaml / .env.example / README.md / config/ data/ logs/ 생성
```

템플릿 복사(`cp -r templates/sample-app /srv/services/my-app`)나 직접 작성도 가능합니다.

## 2. 최소 예시

```yaml
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
  - name: app          # compose의 서비스명과 동일하게
    role: backend
    required: true
```

## 3. 전체 예시

```yaml
schema_version: 1
service:
  id: my-app
  name: My App
  description: |
    서비스 목적, 주요 기능, 데이터 위치, 백업 방법, 운영 주의사항을 적습니다.
  category: web
  version: "0.1.0"
  documentation: README.md
  tags: [web]
source:
  repository_url: ""
  branch: main
deployment:
  type: docker-compose
  compose_file: compose.yaml
  # project_name: my-app       # 비우면 service.id 사용
endpoints:
  - name: frontend
    type: http
    exposure: internal          # proxy | host | internal
    container: app
    container_port: 3000
containers:
  - name: app
    role: backend
    required: true
    description: 애플리케이션 컨테이너
resources:
  memory_limit_mb: 512
volumes:
  - name: my-app-data
    purpose: 영속 데이터
    backup_required: false
operations:
  healthcheck_required: true
  backup_required: false
  restart_policy: unless-stopped
security:
  expose_database: false
  required_env:
    - EXAMPLE_VAR               # 이름만. 값은 .env에
```

## 4. 필드

| 경로 | 필수 | 타입 | 설명 / 허용값 |
|---|---|---|---|
| `schema_version` | ✅ | int | `1`만 지원 |
| `service.id` | ✅ | string | `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$` (3~64자) |
| `service.name` | ✅ | string | 1~120자 |
| `service.description` | ✅ | string | 1~2000자 |
| `service.category` | ✅ | string | web, backend, database, ai, automation, media, dev, infra, other |
| `service.version` |  | string | 서비스 버전 |
| `service.documentation` |  | string | 문서 경로 |
| `service.tags` |  | string[] | 검색용 태그 |
| `source.repository_url` / `source.branch` |  | string | 저장소 정보 |
| `deployment.type` | ✅ | string | `docker-compose` |
| `deployment.compose_file` | ✅ | string | 서비스 디렉터리 기준 경로 |
| `deployment.project_name` |  | string | 비우면 `service.id` |
| `endpoints[].name` |  | string | 엔드포인트 이름 |
| `endpoints[].type` |  | string | http, https, tcp, udp, grpc |
| `endpoints[].exposure` |  | string | proxy, host, internal |
| `endpoints[].hostname` |  | string | `proxy`일 때 필수 |
| `endpoints[].host_port` |  | int | `host`일 때 필수 |
| `endpoints[].container` |  | string | 대상 compose 서비스명 |
| `endpoints[].container_port` |  | int | 1~65535 |
| `containers[].name` |  | string | **compose 서비스명과 동일** |
| `containers[].role` |  | string | frontend, backend, worker, database, cache, proxy, other |
| `containers[].required` |  | bool | 배포 후 기동 필수 (기본 true) |
| `containers[].description` |  | string | 설명 |
| `resources.memory_limit_mb` |  | int | 16 이상 |
| `resources.cpu_limit` |  | float | 0 초과 |
| `volumes[].name` / `purpose` / `backup_required` |  | | 볼륨 정보 |
| `operations.healthcheck_required` |  | bool | 기본 true |
| `operations.backup_required` |  | bool | 기본 false |
| `operations.restart_policy` |  | string | no, always, unless-stopped, on-failure |
| `security.expose_database` |  | bool | 기본 false |
| `security.required_env` |  | string[] | **이름만** (값 금지) |

## 5. 규칙 (검증에서 거부되는 것)

1. 정의되지 않은 필드는 거부됩니다(오타 방지).
2. **시크릿 값을 service.yaml에 쓰면 거부**됩니다. `required_env`에는 이름만 적고 실제 값은 `.env`에 둡니다(Git 커밋 금지).
3. `schema_version`이 1이 아니면 거부합니다.
4. `exposure=proxy`에는 `hostname`, `host`에는 `host_port`가 필요합니다.
5. `containers[].name`이 compose 서비스명과 다르면 계획/배포 검증이 어긋납니다.
6. 배포 경로는 `/srv/services/<service.id>`로 고정입니다. `deployment_path`는 표시용 메타데이터입니다.

## 6. 검증·계획·배포

```bash
hub service validate /srv/services/my-app          # 스키마 검증
hub deploy plan /srv/services/my-app/service.yaml  # 계획 (READY 확인, 컨테이너 무변경)
hub deploy apply my-app --yes                      # 실제 배포 (게이트 필요)
```

> 계획이 `BLOCKED`면 `impact`에 사유가 표시됩니다(포트 충돌, 필수 env 누락, compose 오류 등).
> 계획의 `Compose syntax` 검사는 현재 실제 `docker compose config`를 실행하지 않는 한계가 있습니다
> (실제 검증은 apply의 `validating` 단계에서 수행).
