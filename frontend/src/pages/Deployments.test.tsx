import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import Deployments from "./Deployments";

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    fetchDeployments: vi.fn(),
    getDeployPlan: vi.fn(),
    applyDeploy: vi.fn(),
  };
});

import { fetchDeployments, getDeployPlan, applyDeploy, ApiError } from "../lib/api";

const DEPLOYMENT = {
  id: "dep-1",
  service_id: "sample-app",
  status: "succeeded",
  requested_by: "admin",
  error: null,
  started_at: "2026-10-21T00:00:00Z",
  finished_at: "2026-10-21T00:01:00Z",
};

const PLAN = {
  service: "sample-app",
  result: "READY" as const,
  changes: [{ name: "app", action: "create", detail: "새로 생성" }],
  ports: [{ name: "web", host_port: 8123, container_port: 3000 }],
  validation: [{ check: "Compose syntax", result: "PASS" }],
  impact: [],
  runtime_unchanged: true,
};

beforeEach(() => {
  vi.mocked(fetchDeployments).mockResolvedValue([DEPLOYMENT]);
  vi.mocked(getDeployPlan).mockReset();
  vi.mocked(applyDeploy).mockReset();
});

afterEach(() => vi.clearAllMocks());

const SPEC_JSON = JSON.stringify({
  schema_version: 1,
  service: { id: "sample-app", name: "Sample", description: "샘플", category: "web" },
  deployment: { type: "docker-compose", compose_file: "compose.yaml" },
});

function typeSpec() {
  fireEvent.change(screen.getByLabelText("서비스 정의(JSON)"), {
    target: { value: SPEC_JSON },
  });
}

describe("Deployments", () => {
  it("배포 목록을 렌더링한다", async () => {
    render(<Deployments />);
    expect(await screen.findByText("sample-app")).toBeTruthy();
  });

  it("배포 상태 안내 문구를 표시한다", async () => {
    render(<Deployments />);
    expect(await screen.findByText(/배포는 기본 잠금 상태입니다/)).toBeTruthy();
  });

  it("계획 미리보기 결과와 READY를 표시한다", async () => {
    vi.mocked(getDeployPlan).mockResolvedValue(PLAN);
    render(<Deployments />);
    const btn = await screen.findByRole("button", { name: /계획 미리보기/ });
    typeSpec();
    fireEvent.click(btn);
    await waitFor(() => expect(getDeployPlan).toHaveBeenCalled());
    expect(await screen.findByText(/Compose syntax/)).toBeTruthy();
    expect(await screen.findByText(/READY/)).toBeTruthy();
  });

  it("deploy_disabled(503) 시 잠금 안내를 표시한다", async () => {
    vi.mocked(applyDeploy).mockRejectedValue(
      new ApiError("배포 기능이 비활성화되어 있습니다", 503, "deploy_disabled"),
    );
    render(<Deployments />);
    const btn = await screen.findByRole("button", { name: /배포 실행/ });
    typeSpec();
    fireEvent.click(btn);
    expect(await screen.findByText(/배포 기능이 비활성화/)).toBeTruthy();
  });
});
