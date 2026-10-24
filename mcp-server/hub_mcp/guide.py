"""MCP 접속 AI가 배포 방식을 스스로 파악하도록 제공하는 가이드.

도구(hub_deployment_guide), 리소스(hub://guides/deployment),
프롬프트(deploy-service)가 같은 내용을 공유한다.
"""
from __future__ import annotations

DEPLOYMENT_GUIDE = """# N100 Service Hub 배포 가이드

## 1) 배포 모델 — 가장 중요
- 허브는 **서버(N100)의 `/srv/services/<service-id>` 디렉터리를 빌드**한다.
- 소스 동기화는 **`hub_service_sync_source`** 로 MCP가 직접 수행한다
  (로컬 디렉터리 → tar.gz → 허브가 `/srv/services/<id>` 에 안전하게 반영).
  **SSH 접속이나 git 자격증명이 필요 없다.** rsync/git pull 은 대안일 뿐이다.
  - `HUB_ENABLE_SOURCE_UPLOAD=true` 필요(기본 false). 꺼져 있으면 503.
  - 제외 기본값: `.git`, `node_modules`, `.venv`, `__pycache__` 등 (`exclude`로 추가)
- 배포 = **소스 동기화 → service.yaml 검증/등록 → 계획(plan) → 실행(apply)**.
- `hub_deploy_apply`는 내부적으로 `docker compose up -d --build`를 실행하므로
  동기화된 소스 변경이 이미지에 반영된다(레이어 캐시로 보통 1초 내외).
- 첫 배포/대용량 의존성 변경은 이미지 빌드로 **수 분** 걸릴 수 있다
  (MCP는 배포 호출에 600초 타임아웃을 사용한다).

## 2) 사전 조건
- 배포 게이트: `HUB_ENABLE_DEPLOY=true` (아니면 scaffold/plan/apply 모두 503)
- 소스 업로드: `HUB_ENABLE_SOURCE_UPLOAD=true` (아니면 503)
- (선택) `HUB_DEPLOY_ALLOWED_SERVICES=a,b` — 목록 밖 서비스는 403 `service_not_allowed`
- (선택) `HUB_DEPLOY_AUTO_ROLLBACK=true` — 배포 실패 시 직전 성공 배포로 자동 롤백
- (선택) `HUB_DEPLOY_WEBHOOK_URL` — 배포 결과를 JSON으로 POST (실패해도 배포엔 영향 없음)
- `/srv/services/<id>` 쓰기 권한: 백엔드 uid 10001(소유자) / `hubdeploy` 그룹
- 포트 충돌 없음: `hub_ports_list`로 확인
- 시크릿은 `.env`에만. `service.yaml`에는 **이름만**

## 3) 워크플로 (도구 순서)
1. `hub_status` — 허브/도커/모니터 상태
2. `hub_service_spec_guide` — service.yaml 예시·필드·규칙
3. `hub_service_sync_source(service_id, path)` — 로컬 소스 업로드 (SSH 불필요)
   (`dry_run=true`로 크기/파일 수 먼저 확인 가능)
4. `hub_service_scaffold` — `/srv/services/<id>/{service.yaml,compose.yaml}` 생성
   (이미 있으면 `overwrite=true` + `confirm=<id>`)
5. `hub_service_validate` — 스키마 검증 (변경 없음)
6. `hub_service_register` — `deployment_path=/srv/services/<id>`로 DB 등록
7. `hub_deploy_plan` — `result=READY` 확인 (`impact`가 비어야 함)
8. `hub_deploy_apply(service_id, confirmed=true)` — 실제 배포
9. `hub_deploy_status` / `hub_deployments_list` — 결과 확인
10. 실패 시: `HUB_DEPLOY_AUTO_ROLLBACK=true`면 응답에 `auto_rolled_back`/`auto_rollback`이 포함된다.
    자동 롤백이 없거나 실패했다면 `hub_deploy_rollback(deployment_id, confirmed=true)`

> **무인 운영**: 사람이 지켜보지 않아도 되도록
> ① 소스 업로드(sync_source) ② 계획 확인 ③ 실행 ④ 상태 확인 ⑤ 실패 시 자동/수동 롤백
> 순서를 에이전트가 끝까지 수행한다. 결과는 웹훅으로 통지할 수 있다.

## 4) 코드 수정 후 재배포
```
# 1) 소스 업로드 (SSH 불필요)
hub_service_sync_source(service_id="pianosync", path="/Users/me/proj/pianosync")

# 2) 배포
hub_deploy_apply(service_id="pianosync", confirmed=true)
```
- 파일 삭제는 반영되지 않는다(덮어쓰기만). 삭제가 필요하면 서버에서 직접 정리한다.
- 실측: 동기화 ~1초, `build` 0.6~0.9초(캐시), `up` ~1초 → **약 2~3초**
- 컨테이너 재생성 대기로 간헐적으로 ~10초 걸릴 수 있다.
- **정적 파일(CSS/HTML)만 바꾸는 경우**에도 현재는 이미지 재빌드가 필요하다.
  (원하면 compose에 `pianosync/web/static` 바인드 마운트를 추가해 새로고침만으로 반영 가능)

## 5) 포트 · 노출
- `exposure=host` → `host_port` 필수, 호스트(테일넷)에 게시
- `exposure=proxy` → `hostname` 필수 (프록시가 없는 서버에서는 내부용으로만)
- `exposure=internal` → 외부 접근 없음 (container:port로만 통신)
- 새 포트는 `hub_ports_list`로 사용/예약 여부를 먼저 확인

## 6) 시크릿
- `service.yaml`에 시크릿 **값 금지** — `security.required_env`에는 이름만
- 실제 값은 `/srv/services/<id>/.env` (600/660)에 두고 compose에서 `env_file`로 주입
- 응답/로그/커밋에 키를 출력하지 않는다

## 7) 오류 코드
| 코드 | 의미 / 대처 |
|---|---|
| `deploy_disabled`(503) | 게이트 꺼짐 → 관리자에게 `HUB_ENABLE_DEPLOY=true` 요청 |
| `service_not_allowed`(403) | `HUB_DEPLOY_ALLOWED_SERVICES` 목록에 없는 서비스 |
| `plan_not_ready`(409) | 포트 충돌/필수 env/계획 문제 → `impact` 확인 |
| `already_exists`(409) | 디렉터리 존재 → `overwrite=true` + `confirm` |
| `container_running`(409) | 제거 전 정지 필요 |
| `protected_container`/`protected_image`(403) | 허브 자신/보호 대상 |
| `confirm_mismatch`(422) | 확인 이름/태그 불일치 |
| `snapshot_missing`(409) | 롤백 스냅샷 없음 |
| `source_upload_disabled`(503) | `HUB_ENABLE_SOURCE_UPLOAD=true` 필요 |
| `source_path_traversal`(422) | 아카이브에 `..`/절대 경로 포함 → 루트 기준으로 다시 묶기 |
| `unauthorized`(401) | API 키 만료/폐기 |

## 8) 안전 규칙
- 임의 셸 실행 도구 없음 — REST API만 호출
- 배포는 compose 화이트리스트(config/up/down)만
- 허브 자신(`service-hub`/`com.hub.self`)과 보호 대상은 조작 불가
- DB/볼륨 변경은 자동 롤백 대상이 아니다
- 기존 서비스(예: assetnest)는 보호 설정으로 차단되어 있다
"""


def deployment_guide() -> dict:
    """도구 응답용 구조화 가이드."""
    return {
        "model": {
            "build_context": "/srv/services/<service-id> (서버)",
            "mcp_role": "REST API 호출만 (임의 셸 없음)",
            "source_sync": "hub_service_sync_source (MCP가 소스 업로드, SSH 불필요)",
            "apply_behavior": "docker compose up -d --build (레이어 캐시)",
            "auto_rollback": "HUB_DEPLOY_AUTO_ROLLBACK=true 이면 실패 시 직전 성공 배포로 복귀",
            "notification": "HUB_DEPLOY_WEBHOOK_URL 로 결과 JSON POST (선택)",
        },
        "prerequisites": [
            "HUB_ENABLE_DEPLOY=true",
            "/srv/services/<id> 쓰기 권한 (uid 10001 / hubdeploy 그룹)",
            "포트 충돌 없음 (hub_ports_list)",
            "시크릿은 .env (600/660), service.yaml에는 이름만",
        ],
        "workflow": [
            "hub_status",
            "hub_service_spec_guide",
            "hub_service_sync_source (local dir → /srv/services/<id>)",
            "hub_service_scaffold (overwrite+confirm if exists)",
            "hub_service_validate",
            "hub_service_register (deployment_path=/srv/services/<id>)",
            "hub_deploy_plan (READY 확인)",
            "hub_deploy_apply(service_id, confirmed=true)",
            "hub_deploy_status / hub_deployments_list",
            "hub_deploy_rollback(confirmed=true) if needed",
        ],
        "timings": {
            "source_sync": "~1s",
            "image_build_cached": "0.6~0.9s",
            "container_up": "~1s (간헐적 ~10s)",
            "first_build": "수 분 (MCP 타임아웃 600s)",
        },
        "error_codes": {
            "deploy_disabled": "503 — 게이트 꺼짐",
            "plan_not_ready": "409 — 포트/env/계획 문제",
            "already_exists": "409 — overwrite+confirm 필요",
            "protected_container": "403 — 허브 자신/보호 대상",
            "confirm_mismatch": "422 — 확인 값 불일치",
            "snapshot_missing": "409 — 롤백 스냅샷 없음",
        },
        "docs": "docs/MCP.md",
        "markdown": DEPLOYMENT_GUIDE,
    }
