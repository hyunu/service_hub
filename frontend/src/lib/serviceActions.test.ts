import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { setCsrfToken, stopService, restartService } from "./api";

/** 서비스 단위 중지/재시작 API 계약 — 경로/메서드/확인 플래그가 어긋나면 조용히 실패한다. */

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as unknown as Response;
}

describe("서비스 조작 API", () => {
  let calls: { url: string; init: RequestInit }[] = [];

  beforeEach(() => {
    calls = [];
    setCsrfToken("csrf-test");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        calls.push({ url, init });
        const action = url.includes("/restart") ? "restart" : "stop";
        return jsonResponse({
          ok: true,
          service_id: "demo",
          action,
          stopped: 2,
          started: action === "restart" ? 2 : 0,
          results: { stopped: [], started: [], skipped: [], failed: [] },
          runtime_changed: true,
        });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfToken(null);
  });

  it("stopService 는 POST /services/{id}/stop 에 confirmed=true 를 보낸다", async () => {
    const res = await stopService("demo");
    expect(res.stopped).toBe(2);
    const call = calls[0];
    expect(call.url).toContain("/api/v1/services/demo/stop");
    expect(call.init.method).toBe("POST");
    expect(JSON.parse(String(call.init.body))).toEqual({ confirmed: true });
    const headers = call.init.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("csrf-test");
  });

  it("restartService 는 POST /services/{id}/restart 로 보낸다", async () => {
    const res = await restartService("demo");
    expect(res.started).toBe(2);
    expect(calls[0].url).toContain("/api/v1/services/demo/restart");
    expect(calls[0].init.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ confirmed: true });
  });
});
