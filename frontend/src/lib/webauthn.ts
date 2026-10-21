/**
 * WebAuthn(생체인식/패스워드리스) 프론트엔드 헬퍼.
 *
 * 백엔드는 옵션을 JSON(base64url 문자열)으로 내려주지만, 브라우저 WebAuthn API는
 * `ArrayBuffer`(BufferSource)를 요구한다. 따라서 challenge / credential id /
 * user.id 를 ArrayBuffer로 변환해 넘기고, 응답(ArrayBuffer)은 다시 base64url
 * JSON으로 직렬화해 서버로 보낸다.
 *
 * 보안 컨텍스트(HTTPS 또는 localhost)에서만 동작한다. 평문 HTTP(IP 접속)에서는
 * `navigator.credentials`가 없으므로 UI에서 안내 문구를 보여준다.
 */
import { request, setCsrfToken, type SessionInfo } from "./api";

export interface PasskeyInfo {
  id: number;
  label: string;
  device_type: string | null;
  backed_up: boolean;
  created_at: string;
  last_used_at: string | null;
}

/* ------------------------------ base64url ------------------------------ */

function b64urlToBuf(value: string): ArrayBuffer {
  const b64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  const bin = atob(padded);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

function bufToB64url(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/* ------------------------------ 옵션 변환 ------------------------------ */

type RawOptions = Record<string, unknown>;

/** 서버 옵션(JSON) → 브라우저 create() 옵션 */
function toCreationOptions(raw: RawOptions): PublicKeyCredentialCreationOptions {
  const options = {
    ...raw,
    challenge: b64urlToBuf(String(raw.challenge)),
    user: {
      ...(raw.user as Record<string, unknown>),
      id: b64urlToBuf(String((raw.user as Record<string, unknown>)?.id ?? "")),
    },
  } as unknown as PublicKeyCredentialCreationOptions;

  const exclude = raw.excludeCredentials;
  if (Array.isArray(exclude) && exclude.length > 0) {
    options.excludeCredentials = exclude.map((c) => ({
      ...(c as Record<string, unknown>),
      id: b64urlToBuf(String((c as Record<string, unknown>).id ?? "")),
    })) as PublicKeyCredentialDescriptor[];
  }
  return options;
}

/** 서버 옵션(JSON) → 브라우저 get() 옵션 */
function toRequestOptions(raw: RawOptions): PublicKeyCredentialRequestOptions {
  const options = {
    ...raw,
    challenge: b64urlToBuf(String(raw.challenge)),
  } as unknown as PublicKeyCredentialRequestOptions;

  const allow = raw.allowCredentials;
  if (Array.isArray(allow) && allow.length > 0) {
    options.allowCredentials = allow.map((c) => ({
      ...(c as Record<string, unknown>),
      id: b64urlToBuf(String((c as Record<string, unknown>).id ?? "")),
    })) as PublicKeyCredentialDescriptor[];
  }
  return options;
}

/** 등록 응답(ArrayBuffer) → 서버가 검증할 JSON */
function creationCredentialToJSON(cred: PublicKeyCredential): RawOptions {
  const response = cred.response as AuthenticatorAttestationResponse;
  return {
    id: cred.id,
    rawId: bufToB64url(cred.rawId),
    type: cred.type,
    clientExtensionResults: cred.getClientExtensionResults(),
    authenticatorAttachment: cred.authenticatorAttachment ?? undefined,
    response: {
      clientDataJSON: bufToB64url(response.clientDataJSON),
      attestationObject: bufToB64url(response.attestationObject),
      transports:
        typeof response.getTransports === "function" ? response.getTransports() : undefined,
    },
  };
}

/** 로그인 응답(ArrayBuffer) → 서버가 검증할 JSON */
function assertionCredentialToJSON(cred: PublicKeyCredential): RawOptions {
  const response = cred.response as AuthenticatorAssertionResponse;
  return {
    id: cred.id,
    rawId: bufToB64url(cred.rawId),
    type: cred.type,
    clientExtensionResults: cred.getClientExtensionResults(),
    authenticatorAttachment: cred.authenticatorAttachment ?? undefined,
    response: {
      clientDataJSON: bufToB64url(response.clientDataJSON),
      authenticatorData: bufToB64url(response.authenticatorData),
      signature: bufToB64url(response.signature),
      userHandle: response.userHandle ? bufToB64url(response.userHandle) : null,
    },
  };
}

/* -------------------------------- 기능 감지 -------------------------------- */

/** 브라우저가 WebAuthn과 보안 컨텍스트를 지원하는가 */
export function isWebAuthnSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.PublicKeyCredential !== "undefined" &&
    typeof navigator !== "undefined" &&
    typeof navigator.credentials?.create === "function"
  );
}

/** 이 기기에 생체인식/플랫폼 인증기가 있는가 */
export async function isPlatformAuthenticatorAvailable(): Promise<boolean> {
  if (!isWebAuthnSupported()) return false;
  try {
    return await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
  } catch {
    return false;
  }
}

/* --------------------------------- API --------------------------------- */

export async function fetchPasskeys(): Promise<PasskeyInfo[]> {
  const res = await request<{ items?: PasskeyInfo[] }>("/webauthn/credentials");
  return res?.items ?? [];
}

export async function deletePasskey(id: number): Promise<void> {
  await request<unknown>(`/webauthn/credentials/${id}`, { method: "DELETE" });
}

/** 패스워드리스 등록 — 브라우저 프롬프트(지문/Face ID/PIN)를 띄운다. */
export async function registerPasskey(label: string): Promise<void> {
  const begin = await request<{ publicKey: RawOptions }>("/webauthn/register/begin", {
    method: "POST",
    body: { label },
  });
  const cred = await navigator.credentials.create({
    publicKey: toCreationOptions(begin.publicKey),
  });
  if (!cred) throw new Error("패스워드 키 생성이 취소되었습니다.");
  await request<unknown>("/webauthn/register/finish", {
    method: "POST",
    body: creationCredentialToJSON(cred as PublicKeyCredential),
  });
}

/** 패스워드리스 로그인 — 성공 시 세션/CSRF 토큰을 갱신한다. */
export async function loginWithPasskey(username: string): Promise<SessionInfo> {
  const begin = await request<{ publicKey: RawOptions }>("/webauthn/login/begin", {
    method: "POST",
    body: { username },
    refreshCsrf: false,
  });
  const cred = await navigator.credentials.get({
    publicKey: toRequestOptions(begin.publicKey),
  });
  if (!cred) throw new Error("생체인식 로그인이 취소되었습니다.");

  const result = await request<{ username: string; csrf_token: string }>(
    "/webauthn/login/finish",
    {
      method: "POST",
      body: {
        ...assertionCredentialToJSON(cred as PublicKeyCredential),
        username,
      },
      refreshCsrf: false,
    },
  );

  setCsrfToken(result.csrf_token);
  return {
    authenticated: true,
    setup_required: false,
    user: { username: result.username, role: "admin" },
    csrf_token: result.csrf_token,
  };
}
