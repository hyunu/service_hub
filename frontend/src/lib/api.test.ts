import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  ApiError,
  createReservation,
  fetchOverview,
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
