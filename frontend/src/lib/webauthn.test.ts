import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { setCsrfToken } from "./api";
import {
  deletePasskey,
  fetchPasskeys,
  isWebAuthnSupported,
  loginWithPasskey,
  registerPasskey,
} from "./webauthn";

/**
 * 프론트엔드 WebAuthn 변환 로직 테스트.
 *
 * 핵심 위험: 서버는 base64url JSON, 브라우저는 ArrayBuffer를 요구한다.
 * challenge / credential id 디코딩과 응답 재인코딩이 틀어지면
 * 브라우저에서 "TypeError: Failed to convert value to 'ArrayBuffer'" 또는
 * 서버 검증 실패가 된다. 여기서 양방향 변환을 고정한다.
 */

const b64url = (bytes: number[]) => {
  const bin = String.fromCharCode(...bytes);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

const ab = (bytes: number[]) => new Uint8Array(bytes).buffer;

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as unknown as Response;
}

interface FetchCall {
  url: string;
  init: RequestInit;
}

describe("webauthn 변환", () => {
  let calls: FetchCall[] = [];
  let responder: (url: string, init: RequestInit) => Response | Promise<Response>;
  let credentials: { get: ReturnType<typeof vi.fn>; create: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    calls = [];
    setCsrfToken(null);
    responder = () => jsonResponse({});
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        calls.push({ url, init });
        return responder(url, init);
      }),
    );
    vi.stubGlobal("PublicKeyCredential", function PublicKeyCredential() {});
    credentials = { get: vi.fn(), create: vi.fn() };
    Object.defineProperty(window.navigator, "credentials", {
      value: credentials,
      configurable: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete (window.navigator as unknown as { credentials?: unknown }).credentials;
  });

  it("isWebAuthnSupported 는 보안 컨텍스트 밖(HTTP)에서 false", () => {
    vi.stubGlobal("PublicKeyCredential", undefined);
    expect(isWebAuthnSupported()).toBe(false);
  });

  it("loginWithPasskey 는 챌린지를 ArrayBuffer로 디코딩하고 응답을 base64url로 직렬화한다", async () => {
    // 1) begin 응답: challenge는 base64url
    responder = (url) => {
      if (url.endsWith("/webauthn/login/begin")) {
        return jsonResponse({
          publicKey: {
            challenge: b64url([1, 2, 3]),
            rpId: "example.test",
            timeout: 60000,
            allowCredentials: [{ id: b64url([9, 8, 7]), type: "public-key" }],
          },
        });
      }
      if (url.endsWith("/webauthn/login/finish")) {
        return jsonResponse({ ok: true, username: "admin", csrf_token: "csrf-123", method: "webauthn" });
      }
      return jsonResponse({});
    };

    // 2) 브라우저가 반환하는 assertion (ArrayBuffer)
    credentials.get.mockResolvedValue({
      id: b64url([1, 2, 3]),
      rawId: ab([1, 2, 3]),
      type: "public-key",
      authenticatorAttachment: "platform",
      getClientExtensionResults: () => ({}),
      response: {
        clientDataJSON: ab([4, 5]),
        authenticatorData: ab([6, 7]),
        signature: ab([8, 9]),
        userHandle: ab([10]),
      },
    });

    const session = await loginWithPasskey("admin");

    // challenge / allowCredentials id 가 ArrayBuffer 로 넘어갔는가
    const getArgs = credentials.get.mock.calls[0][0] as {
      publicKey: { challenge: ArrayBuffer; allowCredentials?: { id: ArrayBuffer }[] };
    };
    expect(Array.from(new Uint8Array(getArgs.publicKey.challenge))).toEqual([1, 2, 3]);
    expect(Array.from(new Uint8Array(getArgs.publicKey.allowCredentials![0].id))).toEqual([9, 8, 7]);

    // 응답 본문이 base64url + username 으로 직렬화됐는가
    const finish = calls.find((c) => c.url.endsWith("/webauthn/login/finish"))!;
    const body = JSON.parse(String(finish.init.body));
    expect(body.username).toBe("admin");
    expect(body.rawId).toBe(b64url([1, 2, 3]));
    expect(body.response.clientDataJSON).toBe(b64url([4, 5]));
    expect(body.response.authenticatorData).toBe(b64url([6, 7]));
    expect(body.response.signature).toBe(b64url([8, 9]));
    expect(body.response.userHandle).toBe(b64url([10]));

    // 세션/CSRF 갱신
    expect(session.authenticated).toBe(true);
    expect(session.user?.username).toBe("admin");
    expect(session.csrf_token).toBe("csrf-123");
  });

  it("registerPasskey 는 등록 옵션을 디코딩하고 attestation 을 base64url 로 보낸다", async () => {
    setCsrfToken("csrf-existing");
    responder = (url) => {
      if (url.endsWith("/webauthn/register/begin")) {
        return jsonResponse({
          publicKey: {
            challenge: b64url([11, 12]),
            rp: { id: "example.test", name: "N1 00" },
            user: { id: b64url([13]), name: "admin", displayName: "admin" },
            pubKeyCredParams: [{ type: "public-key", alg: -7 }],
            excludeCredentials: [{ id: b64url([14]), type: "public-key" }],
          },
        });
      }
      return jsonResponse({ ok: true, id: 1, label: "내 기기" });
    };

    credentials.create.mockResolvedValue({
      id: b64url([1, 2, 3]),
      rawId: ab([1, 2, 3]),
      type: "public-key",
      authenticatorAttachment: "platform",
      getClientExtensionResults: () => ({}),
      response: {
        clientDataJSON: ab([20]),
        attestationObject: ab([21]),
        getTransports: () => ["internal"],
      },
    });

    await registerPasskey("내 기기");

    const createArgs = credentials.create.mock.calls[0][0] as {
      publicKey: {
        challenge: ArrayBuffer;
        user: { id: ArrayBuffer };
        excludeCredentials?: { id: ArrayBuffer }[];
      };
    };
    expect(Array.from(new Uint8Array(createArgs.publicKey.challenge))).toEqual([11, 12]);
    expect(Array.from(new Uint8Array(createArgs.publicKey.user.id))).toEqual([13]);
    expect(Array.from(new Uint8Array(createArgs.publicKey.excludeCredentials![0].id))).toEqual([14]);

    const finish = calls.find((c) => c.url.endsWith("/webauthn/register/finish"))!;
    const body = JSON.parse(String(finish.init.body));
    expect(body.response.attestationObject).toBe(b64url([21]));
    expect(body.response.transports).toEqual(["internal"]);

    // 등록은 CSRF 토큰이 필요하다
    const headers = finish.init.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("csrf-existing");
  });

  it("fetchPasskeys 는 items 봉투를 벗겨 배열로 돌려준다", async () => {
    responder = () => jsonResponse({ items: [{ id: 1, label: "Touch ID", device_type: "singleDevice", backed_up: false, created_at: "2026-01-01T00:00:00Z", last_used_at: null }] });
    const items = await fetchPasskeys();
    expect(items).toHaveLength(1);
    expect(items[0].label).toBe("Touch ID");
  });

  it("deletePasskey 는 DELETE 로 id 를 보낸다", async () => {
    setCsrfToken("csrf-existing");
    responder = () => jsonResponse({ ok: true });
    await deletePasskey(7);
    const del = calls.find((c) => c.url.endsWith("/webauthn/credentials/7"))!;
    expect(del.init.method).toBe("DELETE");
  });
});
