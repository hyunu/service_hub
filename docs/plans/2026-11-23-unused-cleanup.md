# 미사용 컨테이너 일괄 정리 Implementation Plan

**Goal:** 중지된 미관리 컨테이너와 dangling 이미지를 안전하게 한 번에 정리하는 API + 대시보드 UI를 추가한다.

**Architecture:** 기존 단일 제거(`POST /containers/{id}/remove`)의 게이트·보호·감사 규칙을 그대로 재사용하는 일괄 엔드포인트를 추가한다. 자동 전체 삭제는 없고, UI가 후보(`cleanup_eligible`)를 보여주고 사용자가 선택/확인한 것만 제거한다. Docker 접근은 `docker_client.py` 게이트웨이만 사용한다.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, pytest, React + Vitest.

**정책 (사용자 확정):**
- 후보: **중지된 미관리(unmanaged) 컨테이너만** (서비스 소속 제외)
- 실행 중 / 허브 자신 / `HUB_PROTECTED_*` 대상은 항상 제외
- dangling 이미지(태그 없음 + 미사용)도 함께 정리. **볼륨·네트워크·태그 이미지는 건드리지 않음**
- 노출: API + UI만 (MCP 삭제 도구는 추가하지 않음)

---

## File Structure

| 파일 | 역할 |
|---|---|
| `backend/app/routers/docker_actions.py` | `POST /containers/cleanup` + 이미지 정리 + 감사 |
| `backend/app/routers/containers.py` | 목록 응답에 `cleanup_eligible`/`cleanup_reason` 추가 |
| `backend/tests/test_container_cleanup.py` | 게이트·보호·확인·감사·이미지 테스트 |
| `frontend/src/lib/api.ts` | `cleanupUnusedContainers()` + 타입 |
| `frontend/src/pages/Containers.tsx` | 정리 버튼/확인/결과 표시 |
| `frontend/src/pages/Containers.test.tsx` | UI 동작 테스트 |
| `frontend/src/lib/mock.ts` | dev mock 엔드포인트 |
| `docs/REQUIREMENTS.md`, `docs/IMPLEMENTATION-STATUS.md` | 요구사항/이력 갱신 |

---

### Task 1: 백엔드 계약 + 테스트

- [ ] **Step 1: 실패하는 테스트 작성** (`backend/tests/test_container_cleanup.py`)

```python
def test_cleanup_is_gated_by_default(client):
    r = mutate(client, "POST", "/api/v1/containers/cleanup",
               json={"container_ids": ["c1"], "confirm": "cleanup"})
    assert r.status_code == 503
    assert r.json()["code"] == "docker_actions_disabled"
```

- [ ] **Step 2: 실패 확인**
  `cd backend && uv run pytest tests/test_container_cleanup.py -q` → 404/503 불일치

- [ ] **Step 3: 엔드포인트 구현** — `_require_enabled()` 재사용, `confirm == "cleanup"`,
  컨테이너별 `protection_reason`/`management_state`/실시간 상태 검사, 성공 시 DB 행+assignment 삭제,
  `container.remove`와 `cleanup.run` 감사 기록, dangling 이미지는 `list_containers()`로 사용 여부 확인 후 제거.

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_container_cleanup.py -q`

---

### Task 2: 목록 응답에 정리 가능 여부 노출

- [ ] **Step 1: 테스트** — unmanaged+중지 → `cleanup_eligible=true`, managed/실행 중/보호 → false + 사유
- [ ] **Step 2: 구현** — `containers._dict()`에 `cleanup_eligible`, `cleanup_reason` 추가
- [ ] **Step 3: 전체 백엔드 게이트** — `uv run pytest`

---

### Task 3: 프론트엔드 API + UI

- [ ] **Step 1: 테스트** — `Containers.test.tsx`에 "미사용 정리" 클릭 → `cleanupUnusedContainers` 호출 검증 (prompt mock)
- [ ] **Step 2: `api.ts`** — `cleanupUnusedContainers(ids, {removeDanglingImages})` (confirm은 "cleanup" 고정)
- [ ] **Step 3: `Containers.tsx`**
  - 필터 바: `미사용 정리 (N)` — 후보 없으면 비활성
  - 선택 바: `선택 정리` — 선택 항목이 모두 정리 가능할 때만 활성
  - Images 헤더: `dangling 정리`
  - 확인 prompt(`cleanup` 입력) → 결과/건너뜀 사유 표시 → 목록·이미지 새로고침
- [ ] **Step 4: 통과 확인** — `npm run test --prefix frontend`, `npm run build --prefix frontend`

---

### Task 4: mock + 문서

- [ ] **Step 1: `mock.ts`** — `POST /containers/cleanup` 처리(컨테이너/이미지 배열에서 제거, 결과 반환)
- [ ] **Step 2: `docs/REQUIREMENTS.md` §8.5** — 일괄 정리 정책(후보/금지 대상/이미지/감사) 명시
- [ ] **Step 3: `docs/IMPLEMENTATION-STATUS.md`** — 구현·검증 기록 추가
- [ ] **Step 4: 최종 게이트** — 백엔드/프론트엔드 테스트 + 빌드

---

## 검증 시나리오 (수동, 실서버 배포 후)

1. 후보 0개 → 버튼 비활성
2. `sentinel-permfix-permfix-1`, `sad_robinson`, `quizzical_shamir`(Exited) 선택 → 정리 →
   컨테이너 3개 사라지고 실행 중 컨테이너/볼륨/태그 이미지 무변경
3. 감사 로그에 `container.remove`(bulk) + `cleanup.run` 기록
4. `HUB_ENABLE_DOCKER_ACTIONS=false`로 내리면 503 (기본 잠금 회귀 확인)
