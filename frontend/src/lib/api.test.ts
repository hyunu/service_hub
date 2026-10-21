import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  ApiError,
  createReservation,
  fetchContainers,
  fetchOrphans,
  fetchOverview,
  fetchPorts,
  fetchResourceWarnings,
  fetchServices,
  onUnauthorized,
  request,
  setCsrfToken,
} from "./api";

interface FetchCall {
  url: string;
  init: RequestInit;
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as unknown as Response;
}

describe("api 클라이언트", () => {
  let calls: FetchCall[] = [];
  let responder: (url: string, init: RequestInit) => Response | Promise<Response>;

  beforeEach(() => {
    calls = [];
    responder = () => jsonResponse({});
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        calls.push({ url, init });
        return responder(url, init);
      }),
    );
    setCsrfToken(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfToken(null);
  });

  it("성공 응답의 JSON을 파싱한다", async () => {
    responder = () =>
      jsonResponse({
        server: { hostname: "n100" },
        counts: { services: 3 },
      });
    const data = await fetchOverview();
    expect(data.counts.services).toBe(3);
    expect(calls[0].url).toBe("/api/v1/system/overview");
  });

  it("오류 응답을 {detail, code} 기반 ApiError로 변환한다", async () => {
    responder = () =>
      jsonResponse({ detail: "이미 사용 중인 포트입니다.", code: "port_conflict" }, 409);

    const err = await request("/ports/reservations", {
      method: "POST",
      body: { host_port: 8080 },
    }).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(409);
    expect(apiErr.code).toBe("port_conflict");
    expect(apiErr.message).toBe("이미 사용 중인 포트입니다.");
  });

  it("FastAPI 422 검증 오류(detail 배열)를 읽을 수 있는 메시지로 변환한다", async () => {
    responder = () =>
      jsonResponse(
        {
          detail: [
            { type: "missing", loc: ["body", "id"], msg: "Field required" },
            { type: "missing", loc: ["body", "name"], msg: "Field required" },
          ],
        },
        422,
      );

    const err = await request("/services", { method: "POST", body: {} }).catch(
      (e: unknown) => e,
    );
    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(422);
    expect(apiErr.message).toContain("입력값이 올바르지 않습니다");
    expect(apiErr.message).toContain("id: Field required");
    expect(apiErr.message).toContain("name: Field required");
  });

  it("body가 없는 오류 응답에서도 안전하게 실패한다", async () => {
    responder = () =>
      jsonResponse({ detail: "Internal Server Error" }, 500);
    const err = await fetchOverview().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
  });

  it("연결 실패 시 network_error ApiError를 던진다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    const err = await fetchOverview().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("network_error");
    expect((err as ApiError).status).toBe(0);
  });

  it("변경 메서드(POST)에 X-CSRF-Token 헤더를 붙인다", async () => {
    setCsrfToken("csrf-token-123");
    responder = () => jsonResponse({ id: "p1" }, 201);

    await createReservation({
      service_id: "svc",
      component: "web",
      host_port: 8080,
      protocol: "tcp",
      bind_addr: "0.0.0.0",
      container_port: 80,
      exposure: "internal",
    });

    expect(calls).toHaveLength(1);
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("csrf-token-123");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(calls[0].init.method).toBe("POST");
  });

  it("GET 요청에는 CSRF 헤더를 붙이지 않는다", async () => {
    setCsrfToken("csrf-token-123");
    await fetchOverview();
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBeUndefined();
  });

  it("CSRF 토큰이 없으면 요청 전에 세션에서 토큰을 가져온다", async () => {
    setCsrfToken(null);
    responder = (url) =>
      url.includes("/auth/session")
        ? jsonResponse({ authenticated: true, csrf_token: "session-csrf" })
        : jsonResponse({ ok: true }, 201);

    await request("/ports/reservations", {
      method: "POST",
      body: { host_port: 9000 },
    });

    const sessionCall = calls.find((c) => c.url.includes("/auth/session"));
    const mutationCall = calls.find((c) => c.url.includes("/ports/reservations"));
    expect(sessionCall).toBeDefined();
    expect(mutationCall).toBeDefined();
    const headers = mutationCall!.init.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("session-csrf");
  });

  it("401 응답 시 unauthorized 리스너를 호출한다", async () => {
    responder = () => jsonResponse({ detail: "로그인이 필요합니다.", code: "unauthorized" }, 401);
    const listener = vi.fn();
    const off = onUnauthorized(listener);

    await fetchOverview().catch(() => undefined);

    expect(listener).toHaveBeenCalledTimes(1);
    off();
  });
});

/**
 * 실서버 응답 계약 회귀 테스트.
 *
 * 개발용 mock(lib/mock.ts)은 목록을 맨 배열로 돌려주지만, 실제 백엔드는
 * `{"items": [...]}` 봉투로 감싸고 컨테이너는 `container_id`/`status_text`
 * 같은 다른 필드명을 쓴다. 이 차이 때문에 로그인 직후 대시보드가
 * `a.slice is not a function` 으로 깨진 적이 있다(빈 화면).
 *
 * 아래 픽스처는 실서버 응답을 그대로 옮긴 것이며, mock 을 쓰지 않는다.
 */
describe("api 클라이언트 — 실서버 응답 계약", () => {
  let responder: (url: string, init: RequestInit) => Response | Promise<Response>;

  beforeEach(() => {
    responder = () => jsonResponse({});
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => responder(url, init)),
    );
    setCsrfToken(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfToken(null);
  });

  it("목록 봉투 {items:[...]} 를 배열로 정규화한다", async () => {
    responder = () =>
      jsonResponse({
        items: [
          {
            container_id: "8e3d7b1",
            container_id_short: "8e3d7b1",
            name: "hub-frontend",
            image: "n100-service-hub-frontend:0.1.0",
            state: "running",
            status_text: "running",
            management_state: "managed",
            service_id: null,
            component: "hub-self",
            compose_project: "service-hub",
            compose_service: "frontend",
            ports: [{ proto: "tcp", host_port: 8421, bind_addr: "127.0.0.1", container_port: 80 }],
            health: null,
            restart_count: 0,
            observed_at: "2026-10-21T06:13:38.854578+00:00",
          },
        ],
        count: 1,
      });

    const rows = await fetchContainers();
    expect(Array.isArray(rows)).toBe(true);
    expect(rows).toHaveLength(1);
    // 실서버 필드명 → 프런트 필드명 매핑
    expect(rows[0].id).toBe("8e3d7b1");
    expect(rows[0].status).toBe("running");
    expect(rows[0].component_name).toBe("hub-self");
    expect(rows[0].ports[0]).toMatchObject({
      host_ip: "127.0.0.1",
      host_port: 8421,
      container_port: 80,
      protocol: "tcp",
    });
    // 예전 크래시 지점: id 가 없으면 undefined.slice 로 렌더가 깨졌다.
    expect(typeof rows[0].id.slice).toBe("function");
  });

  it("/resources/warnings 는 {warnings:[...]} 를 배열로 돌려준다", async () => {
    responder = () =>
      jsonResponse({
        warnings: [{ kind: "memory", severity: "warn", message: "메모리 사용률 높음" }],
        thresholds: { mem_warn_pct: 80.0, mem_crit_pct: 90.0 },
      });

    const warnings = await fetchResourceWarnings();
    expect(Array.isArray(warnings)).toBe(true);
    expect(warnings).toHaveLength(1);
    // 예전 크래시 지점: warnings.slice(0,5)
    expect(typeof warnings.slice).toBe("function");
  });

  it("목록이 비어 있어도 항상 배열을 반환한다", async () => {
    responder = () => jsonResponse({ items: [], count: 0 });
    expect(await fetchServices()).toEqual([]);
    expect(await fetchOrphans()).toEqual([]);
    expect(await fetchPorts()).toEqual([]);
  });
});
