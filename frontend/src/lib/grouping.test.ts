import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { attachOrphans, autoAttachService, detachContainer, setCsrfToken } from "./api";

/** 수동 그룹핑 API 계약 — 경로/메서드/본문이 어긋나면 그룹핑이 조용히 실패한다. */

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as unknown as Response;
}

describe("그룹핑 API", () => {
  let calls: { url: string; init: RequestInit }[] = [];

  beforeEach(() => {
    calls = [];
    setCsrfToken("csrf-test");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        calls.push({ url, init });
        return jsonResponse({ attached: 2, skipped: 0, results: [], service_id: "grp" });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfToken(null);
  });

  it("attachOrphans 는 여러 컨테이너를 /orphans/attach 로 보낸다", async () => {
    const res = await attachOrphans({
      service_id: "grp",
      container_ids: ["c1", "c2"],
      component_name: "web",
    });
    expect(res.attached).toBe(2);
    const call = calls[0];
    expect(call.url).toContain("/api/v1/orphans/attach");
    expect(call.init.method).toBe("POST");
    expect(JSON.parse(String(call.init.body))).toEqual({
      service_id: "grp",
      container_ids: ["c1", "c2"],
      component_name: "web",
    });
    const headers = call.init.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("csrf-test");
  });

  it("detachContainer 는 POST /containers/{id}/detach", async () => {
    await detachContainer("abc123");
    expect(calls[0].url).toContain("/api/v1/containers/abc123/detach");
    expect(calls[0].init.method).toBe("POST");
  });

  it("autoAttachService 는 compose_project 를 전달한다", async () => {
    await autoAttachService("grp", "infra");
    expect(calls[0].url).toContain("/api/v1/services/grp/auto-attach");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ compose_project: "infra" });
  });
});
