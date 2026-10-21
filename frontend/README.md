# N100 Service Hub — Frontend

React 19 + TypeScript + Vite + Tailwind CSS 기반 운영 대시보드.
백엔드 API 계약은 `docs/ARCHITECTURE.md` §3 "API 계약 v1"을 따른다 (prefix `/api/v1`).

## 실행

```bash
cd frontend
npm install

# 개발 (백엔드 127.0.0.1:8420 로 /api 프록시)
npm run dev            # http://localhost:5173

# 백엔드가 아직 없을 때 로컬 목 데이터로 개발
npm run dev:mock       # VITE_API_MOCK=true

# 검증
npm run build          # tsc --noEmit + vite build (오류 0개 필수)
npm run test           # vitest run (전체 통과 필수)
npm run test:watch
npm run typecheck
```

Vite dev 서버는 `/api` 요청을 `http://127.0.0.1:8420`으로 프록시한다 (`vite.config.ts`).

## 구조

```
src/
├── lib/
│   ├── api.ts        # 모든 엔드포인트 타입드 fetch 클라이언트, CSRF/오류 처리
│   ├── mock.ts       # 개발용 목 어댑터 (계약과 동일한 경로/응답)
│   ├── format.ts     # ISO 8601 → 로컬 시각 + 상대 시간("3분 전")
│   ├── labels.ts     # 상태 한국어 라벨/뱃지 매핑
│   ├── theme.ts      # 다크(기본)/라이트 테마 저장
│   └── utils.ts
├── components/
│   ├── layout/       # Sidebar, Topbar(서버 상태/검색/알림/사용자), AppLayout
│   ├── ui/           # shadcn 호환 최소 컴포넌트 (Button/Card/Badge/Table/Tabs/Dialog/Input/Select/Skeleton/Tooltip)
│   ├── Gauge.tsx     # 반원형 자원 게이지 (SVG)
│   ├── LineChart.tsx # 라인/스파크라인 차트 (SVG 직접 구현, 차트 라이브러리 미사용)
│   ├── StatusBadge.tsx
│   └── feedback.tsx  # PageHeader/Loading/Error/Empty
├── context/AuthContext.tsx
└── pages/            # Setup, Login, Overview, Services, ServiceDetail, Containers,
                      # Ports, Deployments, DeploymentDetail, Resources, Events, Settings
```

## 백엔드가 맞춰야 할 계약 가정

`docs/ARCHITECTURE.md` §3을 그대로 따르되, 명시가 모호한 부분은 아래와 같이 가정했다.

1. **인증/CSRF**
   - `GET /auth/session` → `{authenticated, setup_required, user:{username,role}, csrf_token}`.
     `csrf_token`이 있으면 클라이언트가 저장하고, 모든 변경 메서드(POST/PUT/PATCH/DELETE)에
     `X-CSRF-Token` 헤더로 전송한다. 토큰이 없으면 변경 요청 전에 `/auth/session`을 1회 재조회한다.
   - `POST /auth/login` → 200 + 세션 객체 (본문 없이 204여도 클라이언트는 성공으로 처리).
   - `POST /setup/admin` → `{username, password}` (password 8자 이상), 201. 이후 로그인 상태로 진입.
   - 401/403 응답 시 클라이언트는 로그인 화면으로 되돌린다.
   - 최초 부팅 시 `setup_required: true`이면 `/setup`으로 강제 이동.
2. **오류 형식**: `{"detail": "...", "code": "..."}`. 필드 검증 오류는 선택적으로
   `{"errors": {"field": ["msg"]}}`를 지원하면 폼에 그대로 매핑된다. 포트 충돌은 `409`,
   클라이언트는 409를 "포트 충돌"로 특별 표시한다.
3. **`GET /ports/available`** 응답은 배열을 `ports` 키로 반환한다고 가정
   (`available`/`candidates` 키도 방어적으로 허용). 요청 파라미터: `count`, `range`(예 `8000-9000`), `protocol`.
4. **`POST /orphans/{cid}/attach`** 본문 키: `{service_id, component_name}`.
   `POST /orphans/{cid}/review` 본문 키: `{review_state}` (`pending|reviewing|accepted|ignored`).
5. **포트 상태 문자열**은 프론트가 한국어 배지로 매핑한다:
   `reserved→예약됨`, `in_use→점유 중`, `available→가용`, `conflict→충돌`,
   `unmanaged→미관리 점유`, `proxy→프록시`, `internal→내부 전용`.
6. **`DELETE /services/{id}?confirm=<id>`** 응답에 `runtime_unchanged: true`가 포함되어야 하며,
   UI는 삭제 확인 다이얼로그에서 "컨테이너/볼륨 미변경"을 명시한다.
7. **`GET /search?q=`** 는 `{services, containers, ports, domains, images}` 그룹을 반환한다고 가정.
   각 항목은 객체(권장: `{id, name, description, image, state, service_id, hostname, ...}`) 또는 문자열 모두 허용한다.
8. **`GET /services/{id}/logs?tail=N`** 응답은 `{lines: [{ts, stream, message}]}`.
9. **`GET /system/status`** 는 `monitor.{running,interval_seconds,last_ok_at,consecutive_errors}`,
   `docker.connected`, `hub.{name,deploy_enabled}`, `last_monitor_ok_at`을 포함한다고 가정.
   상단 상태 필은 이 값과 `last_monitor_ok_at`의 60초 경과 여부로 판정한다.
10. **값이 없는 지표는 `null`** 로 내려주면 UI가 `N/A`로 표시한다 (0으로 대체하지 않음).
11. 시간 값은 모두 ISO 8601이며, UI가 브라우저 로컬 시간으로 변환해 표시한다.

## 테스트

`npm run test` — Vitest + @testing-library/react:

- `src/lib/api.test.ts` — 오류 `{detail, code}` → `ApiError`, 네트워크 실패, CSRF 헤더 부착/미부착, 401 리스너
- `src/pages/Overview.test.tsx` — 카운트/게이지/서비스 상태/이벤트 렌더, N/A 처리, 오류 상태
- `src/pages/Services.test.tsx` — 검색/상태/카테고리 필터, 필터 해제, 등록 폼 검증, 오류 상태
- `src/pages/Ports.test.tsx` — 상태 배지(충돌/점유/미관리/예약), 충돌 강조, 예약 삭제 버튼 노출 규칙
- `src/pages/Login.test.tsx` — 폼 검증, 로그인 성공 경로, 401/네트워크 오류 메시지

## 디자인 규칙

- 다크 테마 기본, 상단바에서 라이트 모드 전환 (localStorage 저장).
- 상태 색상: 녹색 OK / 앰버 WARN / 적색 CRITICAL / 슬레이트 UNKNOWN.
- 과도한 그라데이션·애니메이션·장식 그래픽 미사용, 4px 스케일 간격, 상태 중심 시각화.
- 데스크톱 우선, 좁은 화면에서는 사이드바가 드로어로 전환된다.
