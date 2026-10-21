import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Settings from "./Settings";
import type { ApiKeyInfo } from "../lib/api";

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
  useParams: () => ({}),
  Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    fetchSettings: vi.fn(),
    updateSettings: vi.fn(),
    changePassword: vi.fn(),
    fetchAuditLogs: vi.fn(),
    fetchApiKeys: vi.fn(),
    createApiKey: vi.fn(),
    revokeApiKey: vi.fn(),
  };
});

vi.mock("../lib/webauthn", async () => {
  const actual = await vi.importActual<typeof import("../lib/webauthn")>("../lib/webauthn");
  return {
    ...actual,
    fetchPasskeys: vi.fn(async () => []),
    deletePasskey: vi.fn(),
    registerPasskey: vi.fn(),
    isPlatformAuthenticatorAvailable: vi.fn(async () => true),
    isWebAuthnSupported: vi.fn(() => true),
  };
});

import { createApiKey, fetchApiKeys, fetchAuditLogs, fetchSettings, revokeApiKey } from "../lib/api";

const KEYS: ApiKeyInfo[] = [
  {
    id: "k1",
    name: "claude-code",
    username: "admin",
    scopes: ["*"],
    created_at: "2026-10-22T09:00:00+00:00",
    created_by: "admin",
    last_used_at: null,
    expires_at: null,
    revoked_at: null,
    active: true,
  },
];

describe("Settings — API 키", () => {
  beforeEach(() => {
    vi.mocked(fetchSettings).mockResolvedValue({
      hub_name: "N100 Service Hub",
      monitor_interval_seconds: 15,
      thresholds: {},
    });
    vi.mocked(fetchAuditLogs).mockResolvedValue([]);
    vi.mocked(fetchApiKeys).mockResolvedValue(KEYS);
  });

  afterEach(() => vi.clearAllMocks());

  it("API 키 탭에서 발급된 키 목록을 보여준다", async () => {
    const user = userEvent.setup();
    render(<Settings />);
    await user.click(screen.getByRole("tab", { name: "API 키" }));
    expect(await screen.findByText("claude-code")).toBeInTheDocument();
    expect(screen.getByText("전체 권한")).toBeInTheDocument();
  });

  it("키를 발급하면 평문 키를 한 번 표시하고 목록을 갱신한다", async () => {
    vi.mocked(createApiKey).mockResolvedValue({
      ...KEYS[0],
      id: "k2",
      name: "cursor",
      key: "hub_plain_secret_value",
    });
    const user = userEvent.setup();
    render(<Settings />);
    await user.click(screen.getByRole("tab", { name: "API 키" }));
    await screen.findByText("claude-code");

    await user.type(screen.getByLabelText(/키 이름/), "cursor");
    await user.click(screen.getByRole("button", { name: /키 발급/ }));

    expect(await screen.findByText("hub_plain_secret_value")).toBeInTheDocument();
    expect(createApiKey).toHaveBeenCalledWith({
      name: "cursor",
      scopes: ["*"],
      expires_in_days: null,
    });
    await waitFor(() => expect(fetchApiKeys).toHaveBeenCalledTimes(2));
  });

  it("이름 없이 발급하면 오류를 표시하고 API를 호출하지 않는다", async () => {
    const user = userEvent.setup();
    render(<Settings />);
    await user.click(screen.getByRole("tab", { name: "API 키" }));
    await screen.findByText("claude-code");

    await user.click(screen.getByRole("button", { name: /키 발급/ }));
    expect(await screen.findByText("키 이름을 입력하세요.")).toBeInTheDocument();
    expect(createApiKey).not.toHaveBeenCalled();
  });

  it("폐기 확인 시 revoke API를 호출한다", async () => {
    vi.mocked(revokeApiKey).mockResolvedValue({ ...KEYS[0], revoked: true });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<Settings />);
    await user.click(screen.getByRole("tab", { name: "API 키" }));
    await screen.findByText("claude-code");

    await user.click(screen.getByRole("button", { name: "claude-code 폐기" }));
    await waitFor(() => expect(revokeApiKey).toHaveBeenCalledWith("k1"));
    confirmSpy.mockRestore();
  });
});
