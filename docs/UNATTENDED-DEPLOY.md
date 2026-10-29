# 무인 배포(Unattended Deployment) 운영 가이드

이 문서는 **사람이 개입하지 않고** AI 에이전트가 N100 Service Hub에 서비스를
등록·업로드·배포·검증·롤백하는 절차와 전제 조건을 정리한다.

- 작성: 2026-10-24
- 실서버 검증: `flow-plan` (N100, `dep-de5fb2c57f4f` succeeded)
- 관련 문서: [AI-OPERATIONS.md §8](../AI-OPERATIONS.md), [REQUIREMENTS §8.5·§13.4.1](REQUIREMENTS.md),
  [SECURITY](SECURITY.md), [MCP README](../mcp-server/README.md)

## 1. 전체 흐름

```text
[AI] hub_service_spec_guide          service.yaml 형식 확인
[AI] hub_service_scaffold            /srv/services/<id>/{service.yaml,compose.yaml} 생성 (신규)
[AI] hub_service_validate            스키마 검증
[AI] hub_service_register            서비스 레지스트리 등록
[AI] hub_service_sync_source         로컬 소스 → 서버 (tar.gz 업로드, SSH 불필요)
[AI] hub_deploy_plan                 계획 확인 (READY)
[AI] hub_deploy_apply                빌드 + compose up + 헬스체크
[AI] hub_deploy_status               단계/오류 확인
[AI] (실패 시) 자동 롤백 또는 hub_deploy_rollback
```

사람이 **한 번만** 수행하는 것: **API 키 발급**(대시보드 Settings → API 키)과
MCP 클라이언트 설정(`HUB_URL`, `HUB_API_KEY`). 그 외에는 개입이 필요 없다.

## 2. 서버 설정 (N100 현재 값)

| 설정 | 값 | 의미 |
|---|---|---|
| `HUB_ENABLE_DEPLOY` | `true` | 배포 허용 |
| `HUB_ENABLE_SOURCE_UPLOAD` | `true` | SSH 없이 소스 업로드 허용 |
| `HUB_DEPLOY_AUTO_ROLLBACK` | `true` | 배포 실패 시 직전 성공 배포로 자동 복구 |
| `HUB_DEPLOY_ALLOWED_SERVICES` | (비움) | 전체 서비스 허용 (제한하려면 콤마 목록) |
| `HUB_DEPLOY_WEBHOOK_URL` | (미설정) | 설정 시 성공/실패/롤백 JSON 통지 |
| `HUB_SOURCE_UPLOAD_MAX_MB` | `200` | 업로드 압축 파일 상한 |

변경은 `/srv/service-hub/.env` 수정 후 `docker compose up -d backend` 로 반영한다.

## 2.1 MCP 연결 방식 (환경 독립)

로컬(저장소 + uv)과 원격(HTTP) 두 가지가 있다. **어느 OpenCode 세션이든** 쓰려면 원격을 권장.

| 방식 | 클라이언트 요구 | 설정 |
|---|---|---|
| local | 저장소, uv | `"type": "local"`, command/env |
| **remote** | URL, API 키만 | `"type": "remote"`, url/headers |

원격 서버 설치(서버에서 1회): `sudo ./mcp-server/deploy/install-remote.sh`

```jsonc
"n100-service-hub": {
  "type": "remote",
  "url": "http://100.85.245.79:8422/mcp",
  "headers": { "X-API-Key": "hub_..." },
  "enabled": true
}
```

- 요청마다 키를 검증하며, 그 키로 허브를 호출한다(권한/폐기 정책 그대로).
- 서버에는 상시 키를 저장하지 않는다.

## 3. 소스 동기화 (SSH 불필요)

`hub_service_sync_source(service_id, path, exclude, dry_run, max_mb)`

- 로컬 디렉터리를 tar.gz로 묶어 `POST /api/v1/services/{id}/source` 로 전송
- 허브가 `<HUB_DEPLOY_WORKDIR>/<service_id>` 에 안전하게 기록
- 기본 제외: `.git`, `node_modules`, `.venv`, `__pycache__`, `.pytest_cache`, `.DS_Store`
- **덮어쓰기만** 수행하며 파일 삭제는 반영하지 않는다
- `.env`/`*.pem`/`*.key` 는 `0600` 으로 저장

### 디렉터리 구조가 다른 경우 (예: flow-plan)

`flow-plan` 은 서버에서 `compose.yaml` 이 `./app/backend`, `./app/frontend` 를
빌드하므로, 로컬 저장소 루트를 `app/` 아래로 넣어야 한다.

```bash
rm -rf /tmp/flow-plan-sync && mkdir -p /tmp/flow-plan-sync/app
rsync -a \
  --exclude '.git' --exclude 'node_modules' --exclude 'dist' --exclude '.venv' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude 'backend/data' \
  --exclude 'desktop/build' --exclude '.DS_Store' \
  /Users/hyunu/project/flow_plan/ /tmp/flow-plan-sync/app/
# → hub_service_sync_source(service_id="flow-plan", path="/tmp/flow-plan-sync")
```

## 4. 권한 요구사항 (중요)

허브 백엔드는 **uid 10001 / gid 10001(hubdeploy)** 로 실행된다.
배포·업로드 대상 디렉터리가 그룹 쓰기 가능해야 한다.

```bash
sudo chmod -R g+rwX /srv/services            # 소유자는 그대로 유지
# 또는
sudo chown -R 10001:10001 /srv/services/<id>
```

권한이 없으면 업로드는 `409 source_write_forbidden` 과 함께 해결 명령을 안내한다.

## 5. 배포와 실패 처리

- `hub_deploy_apply(service_id, confirmed=true)` 는 내부에서 계획을 다시 만들고
  `READY` 인 경우에만 `docker compose up -d --build` 를 실행한다.
- 단계: `queued → validating(스냅샷) → running(compose up) → verifying(헬스체크) → succeeded`.
- 실패 시 `HUB_DEPLOY_AUTO_ROLLBACK=true` 이면 직전 **성공 배포 스냅샷**으로 자동 복구하며
  응답에 `auto_rolled_back`, `auto_rollback`, `auto_rollback_error` 가 포함된다.
- 자동 복구가 불가능하면 `hub_deploy_rollback(deployment_id, confirmed=true)`.
- DB/볼륨 데이터는 롤백 대상이 아니다.

## 6. 무인 운영을 위한 점검 체크리스트

- [ ] `HUB_ENABLE_DEPLOY=true`
- [ ] `HUB_ENABLE_SOURCE_UPLOAD=true`
- [ ] `HUB_DEPLOY_AUTO_ROLLBACK=true`
- [ ] `/srv/services` 그룹 쓰기 권한 (`g+rwX`)
- [ ] 서비스별 성공 배포 1회 이상 (스냅샷 존재 → 자동 롤백 가능)
- [ ] MCP API 키에 `write`(또는 `*`) scope
- [ ] (선택) `HUB_DEPLOY_WEBHOOK_URL` 로 결과 통지
- [ ] (선택) `HUB_DEPLOY_ALLOWED_SERVICES` 로 무인 배포 대상 제한

## 7. 실서버 검증 기록 (2026-10-24)

| 항목 | 결과 |
|---|---|
| 소스 | `/Users/hyunu/project/flow_plan` (139 files / 30.2MB → 15.3MB) |
| 업로드 | 성공 (`/srv/services/flow-plan/app`, mtime 08:16) |
| 배포 | `dep-de5fb2c57f4f` **succeeded** (108초) |
| 검증 | flow-plan-backend/ui healthy, `:8780` HTTP 200 |
| 보존 | assetnest·pianosync·trade-engine·hub 컨테이너 무변경 |

## 8. 알려진 한계

- 파일 **삭제**는 반영되지 않는다 (필요 시 서버에서 정리).
- 빌드는 서버(N100)에서 수행되므로 무거운 빌드는 느릴 수 있다. 필요하면
  로컬 빌드 산출물 또는 완성 이미지 방식(§"이미지 배포")을 사용한다.
- `container_name` 을 고정한 상태에서 compose 서비스명을 바꾸면 이름 충돌이 날 수 있다
  (`409`/`422` 안내 참고, 이전 컨테이너 정리 필요).
- 웹훅 미설정 시 결과는 대시보드/`hub_deploys_status` 로만 확인한다.
