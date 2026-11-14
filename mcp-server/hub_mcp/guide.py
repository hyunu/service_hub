"""MCP 접속 AI가 배포 방식을 스스로 파악하도록 제공하는 가이드.

도구(hub_deployment_guide), 리소스(hub://guides/deployment),
프롬프트(deploy-service)가 같은 내용을 공유한다.

핵심: AI가 사람 개입 없이 **판단 → 포트 선택 → 정의 → 업로드 → 계획 → 배포 →
검증 → 접속 정보 확인**까지 수행할 수 있도록 필요한 정보를 모두 담는다.
"""
from __future__ import annotations

DEPLOYMENT_GUIDE = """# N100 Service Hub 배포 가이드 (AI 자율 배포)

## 0) 배포 전에 먼저 확인 — `hub_capabilities`
- `deploy.enabled` / `deploy.reason`
- `source_upload.enabled` / `max_mb`
- `auth.kind` / `auth.scopes` — `read`만 있으면 변경/배포 불가(403)
- `deploy.allowed_services` — 목록 밖이면 403 `service_not_allowed`
- `ports.host_range` — 현재 `50000-59999`
- `deploy.auto_rollback` — 실패 시 자동 복구 여부
- `deploy.workdir` — 서버 빌드 경로 (기본 `/srv/services`)

게이트가 꺼져 있으면 **AI가 임의로 켜지 말고** 사용자에게 보고한다.

## 1) 배포 모델
- 허브는 **N100 서버의 `/srv/services/<service-id>` 디렉터리**를 빌드한다
  (`docker compose up -d --build`).
- `service.yaml`과 `compose.yaml`이 그 디렉터리에 있어야 한다.
- 배포 = **정의 등록/갱신 → 소스 동기화 → 계획(plan) → 실행(apply) → 검증**.

## 2) 소스 동기화 — 실행 위치가 중요하다
`hub_service_sync_source`는 **MCP 서버 프로세스의 파일 시스템**을 읽는다.
- **로컬(stdio) MCP**: 호출자 프로젝트 경로를 그대로 올릴 수 있다. (권장)
- **원격(HTTP, N100) MCP**: N100 서버의 경로만 읽는다. 호출자 PC의 소스는
  올릴 수 없다. 이 경우:
  1) 로컬 MCP를 `HUB_URL`/`HUB_API_KEY`로 실행하거나,
  2) `POST /api/v1/services/<id>/source`에 tar.gz를 직접 업로드한다
     (`HUB_ENABLE_SOURCE_UPLOAD=true` 필요).
     ```bash
     tar -czf /tmp/svc.tgz -C /path/to/project .
     curl -X POST -H "X-API-Key: $HUB_API_KEY" \
       -H "Content-Type: application/gzip" \
       --data-binary @/tmp/svc.tgz \
       "$HUB_API_URL/services/<id>/source"
     ```
     `HUB_API_URL`은 `hub_capabilities.api_base_url`에서 확인한다.
- `dry_run=true`로 파일 수/크기를 먼저 확인한다.
- 기본 제외: `.git`, `node_modules`, `.venv`, `__pycache__`, `.pytest_cache`, `.DS_Store`
- 업로드는 **덮어쓰기만** 한다. 파일 삭제는 반영되지 않는다.
- `.env`/`*.pem`/`*.key`는 서버에 0600으로 저장된다.

## 3) 포트 정책 — `50000-59999`
- 공유기가 이 대역을 N100으로 포워딩하므로, `exposure: host`는 **이 대역의
  미할당 포트만** 허용한다. 다른 대역은 검증/계획/예약 단계에서 거부된다.
- 후보 조회: `hub_ports_available(count, range?, protocol?)`
- 충돌 방지를 위해 배포 전 예약 권장: `hub_port_reserve(...)`
- 예약 해제: `hub_port_release(reservation_id)`
- `exposure: proxy`는 `hostname`, `internal`은 호스트 포트 없이 사용한다.

## 4) 인증·접속 계약 (값이 아니라 참조)
`service.yaml`의 endpoint에 다음을 기록한다.
```yaml
endpoints:
  - name: api
    type: http
    exposure: host
    host_port: 50004
    container: api
    container_port: 8080
    api_base_path: /api/v1
    health_path: /healthz
    docs_url: https://example.com/docs
    bind_addr: 100.85.245.79
    auth:
      type: custom            # none|basic|bearer|api_key|mtls|custom
      header: X-User-Id       # bearer/api_key/custom만
      credentials_ref: operator://n100/app/api-key
      hint: 운영자에게 자격 증명 요청
```
- **비밀번호/토큰 값은 service.yaml·MCP 응답·로그에 넣지 않는다.**
- `hub_service_access(service_id)`가 `url`/`api_url`/`health_url`,
  `auth.type`/`auth.header`/`credentials_ref`, `url_available`/`verified`를 반환한다.
- `verified: false`는 URL을 계산했다는 뜻일 뿐 실제 HTTP 확인이 아니다.
  배포 후 소비자가 `health_url`을 직접 호출해 확인한다.
- 값은 `credentials_ref` 위치(운영자/비밀번호 관리 도구/서비스 `.env`)에서 얻는다.
  MCP는 값을 반환하지 않는다.

## 5) 워크플로 (도구 순서)
1. `hub_capabilities` — 권한/게이트/포트 대역 확인
2. `hub_service_spec_guide` — service.yaml 형식 확인
3. `hub_ports_available` → `hub_port_reserve` — 50000번대 미할당 포트 확보
4. `hub_service_scaffold`(신규) 또는 소스에 `service.yaml`/`compose.yaml` 작성
5. `hub_service_validate` — 스키마·포트·인증 검증 (변경 없음)
6. `hub_service_register`(신규) 또는 `hub_service_apply`(기존 갱신)
   - `hub_service_apply`는 레지스트리만 교체하며 런타임은 건드리지 않는다.
7. `hub_service_sync_source` — 소스 업로드 (또는 REST 업로드)
8. `hub_deploy_plan` — `result=READY`, `impact` 비어 있음 확인
9. `hub_deploy_apply(service_id, confirmed=true)` — 실제 배포
10. `hub_deploy_status` — 단계/오류 확인 (`succeeded`까지)
11. `hub_service_get` — 컨테이너 running/healthy 확인
12. `hub_service_access` — URL·인증·health 경로 확인
13. 실패 시 `hub_deploy_rollback(deployment_id, confirmed=true)`
    (자동 롤백이 켜져 있으면 응답에 `auto_rolled_back` 포함)

## 6) service.yaml 요약
- `schema_version: 1`만 지원
- `service.id/name/description/category` 필수
- `deployment.type: docker-compose`, `compose_file` 필수
- `containers[].name`은 **compose 서비스명과 동일**
- `exposure: host`는 `host_port` 필수(50000-59999), `proxy`는 `hostname` 필수
- **시크릿 값 금지**: `security.required_env`에는 **이름만** 적고, 실제 값은 서비스
  `.env`(600/660) 또는 운영자 비밀번호 관리 도구에 둔다.
- 허용되지 않은 필드는 거부된다(오타 방지)

## 7) 오류 코드와 대처
| 코드 | HTTP | 대처 |
|---|---|---|
| `unauthorized` | 401 | API 키 없음/폐기 → 운영자에게 키 요청 |
| `insufficient_scope` | 403 | read 키 → write/deploy scope 필요 |
| `deploy_disabled` | 503 | `HUB_ENABLE_DEPLOY=true` 필요 (AI가 켜지 말 것) |
| `source_upload_disabled` | 503 | `HUB_ENABLE_SOURCE_UPLOAD=true` 필요 |
| `service_not_allowed` | 403 | 허용 목록 확인 |
| `deployment_busy` | 409 | 같은 서비스 배포 중 → 잠시 후 재시도 |
| `plan_not_ready` | 409 | 포트/env/계획 문제 → `impact` 확인 |
| `already_exists` | 409 | 디렉터리 존재 → scaffold overwrite+confirm |
| `host_port_out_of_range` | 422 | 50000-59999의 미할당 포트로 변경 |
| `range_out_of_policy` | 422 | 가용 포트 조회 range를 50000-59999로 |
| `hostname_required` | 422 | proxy 노출에 hostname 필요 |
| `source_write_forbidden` | 409 | `/srv/services/<id>` 그룹 쓰기 권한 필요 |
| `source_too_large` | 413 | `max_mb` 이하로 줄이거나 제외 패턴 추가 |
| `source_path_traversal` | 422 | 아카이브를 루트 기준으로 다시 묶기 |
| `snapshot_missing` | 409 | 롤백 스냅샷 없음 → 재배포로 복구 |
| `confirmation_required` | 409 | `confirmed=true` 필요 |

## 8) 안전 규칙
- 임의 셸 실행 도구 없음 — 허브 REST API만 호출한다.
- 배포는 compose 화이트리스트(config/up/down)만 수행한다.
- 허브 자신(`service-hub`/`com.hub.self`)과 보호 대상은 조작할 수 없다.
- DB/볼륨 변경은 롤백 대상이 아니다.
- 기존 서비스의 컨테이너/볼륨/네트워크를 임의로 삭제하지 않는다.
- 자격 증명 값은 채팅/로그/커밋에 남기지 않는다.

## 9) 자율 배포 완료 기준 (스스로 확인)
- [ ] `hub_capabilities`에서 deploy/source_upload 허용, 필요한 scope 보유
- [ ] host_port가 50000-59999이며 미할당
- [ ] `hub_service_validate` 통과
- [ ] `hub_deploy_plan` = READY, impact 없음
- [ ] `hub_deploy_apply` = succeeded
- [ ] 필수 컨테이너 running/healthy
- [ ] `hub_service_access`의 `health_url`을 실제 호출해 2xx 확인
- [ ] 인증 필요 시 `credentials_ref`를 사용자에게 보고 (값은 요청/출력 금지)
"""


def deployment_guide() -> dict:
    """도구 응답용 구조화 가이드."""
    return {
        "model": {
            "build_context": "/srv/services/<service-id> (서버)",
            "mcp_role": "REST API 호출만 (임의 셸 없음)",
            "source_sync": "hub_service_sync_source — SSH 없이 로컬 MCP 머신의 파일을 업로드 "
                           "(원격 MCP는 N100 경로만 읽음)",
            "apply_behavior": "docker compose up -d --build (레이어 캐시)",
            "auto_rollback": "HUB_DEPLOY_AUTO_ROLLBACK=true 이면 실패 시 직전 성공 배포로 복귀",
        },
        "prerequisites": [
            "hub_capabilities로 deploy/source_upload/scope 확인",
            "호스트 포트는 50000-59999의 미할당 포트",
            "/srv/services/<id> 쓰기 권한 (uid 10001 / hubdeploy 그룹)",
            "시크릿은 .env (600/660), service.yaml에는 이름만",
            "원격 MCP면 sync_source 대신 로컬 MCP 또는 REST 업로드",
        ],
        "workflow": [
            "hub_capabilities",
            "hub_service_spec_guide",
            "hub_ports_available / hub_port_reserve",
            "hub_service_scaffold (신규) 또는 정의 파일 작성",
            "hub_service_validate",
            "hub_service_register (신규) / hub_service_apply (갱신)",
            "hub_service_sync_source (또는 REST 업로드)",
            "hub_deploy_plan (READY 확인)",
            "hub_deploy_apply(service_id, confirmed=true)",
            "hub_deploy_status / hub_service_get",
            "hub_service_access (URL·인증·health)",
            "hub_deploy_rollback(confirmed=true) if needed",
        ],
        "source_sync": {
            "local_mcp": "호출자 프로젝트 경로 업로드 가능",
            "remote_mcp": "N100 서버 경로만 가능 — 로컬 MCP 또는 REST 업로드 필요",
            "excludes": [".git", "node_modules", ".venv", "__pycache__", ".pytest_cache"],
            "delete_semantics": "덮어쓰기만, 삭제 미반영",
            "secret_files_0600": [".env", "*.pem", "*.key"],
        },
        "ports": {
            "host_range": "50000-59999",
            "require_unassigned": True,
            "tools": ["hub_ports_available", "hub_port_reserve", "hub_port_release"],
        },
        "access_contract": {
            "fields": ["url", "api_url", "health_url", "auth.type", "auth.header",
                       "credentials_ref", "url_available", "verified"],
            "secret_values": "MCP는 값을 반환하지 않는다",
            "verified_false": "URL 계산값일 뿐 실제 HTTP 확인 아님 → health_url 직접 확인",
        },
        "timings": {
            "source_sync": "~1s",
            "image_build_cached": "0.6~0.9s",
            "container_up": "~1s (간헐적 ~10s)",
            "first_build": "수 분 (MCP 타임아웃 600s)",
        },
        "error_codes": {
            "unauthorized": "401 — API 키 필요/폐기",
            "insufficient_scope": "403 — write/deploy scope 필요",
            "deploy_disabled": "503 — HUB_ENABLE_DEPLOY=true 필요",
            "source_upload_disabled": "503 — HUB_ENABLE_SOURCE_UPLOAD=true 필요",
            "service_not_allowed": "403 — 허용 목록 밖",
            "deployment_busy": "409 — 같은 서비스 배포 중",
            "plan_not_ready": "409 — 포트/env/계획 문제",
            "already_exists": "409 — overwrite+confirm 필요",
            "host_port_out_of_range": "422 — 50000-59999만 허용",
            "range_out_of_policy": "422 — range도 50000-59999",
            "hostname_required": "422 — proxy에 hostname 필요",
            "source_write_forbidden": "409 — /srv/services/<id> 권한",
            "source_too_large": "413 — max_mb 초과",
            "source_path_traversal": "422 — 아카이브 경로 오류",
            "snapshot_missing": "409 — 롤백 스냅샷 없음",
            "confirmation_required": "409 — confirmed=true 필요",
        },
        "docs": "docs/MCP.md",
        "markdown": DEPLOYMENT_GUIDE,
    }
