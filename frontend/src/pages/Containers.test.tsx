import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import Containers from "./Containers";
import type { ContainerDetail } from "../lib/api";

const focusRef = { value: "hub1" };

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useSearchParams: () => [
    new URLSearchParams(focusRef.value ? { focus: focusRef.value } : {}),
    vi.fn(),
  ],
  useParams: () => ({}),
  Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    fetchContainers: vi.fn(async () => []),
    fetchContainer: vi.fn(),
    fetchImages: vi.fn(async () => ({ items: [], actions_enabled: true })),
    fetchServices: vi.fn(async () => []),
    fetchOrphans: vi.fn(async () => []),
  };
});

import { fetchContainer, fetchImages, fetchServices } from "../lib/api";

function detail(overrides: Partial<ContainerDetail> = {}): ContainerDetail {
  return {
    id: "hub1",
    name: "hub-backend",
    image: "n100-service-hub-backend:0.1.0",
    state: "running",
    status: "Up 2 hours",
    management_state: "managed",
    service_id: null,
    component_name: "hub-self",
    compose_project: "service-hub",
    compose_service: "backend",
    ports: [],
    networks: ["service-hub_default"],
    started_at: "2026-10-23T00:00:00+00:00",
    created_at: "2026-10-23T00:00:00+00:00",
    restart_count: 0,
    health: "healthy",
    observed_at: "2026-10-23T01:00:00+00:00",
    mounts: [],
    labels: { "com.hub.self": "true" },
    stats: null,
    protected_reason: "허브 자신의 컨테이너는 조작할 수 없습니다",
    actions_allowed: false,
    ...overrides,
  };
}

describe("Containers 상세 — 조작 버튼 보호", () => {
  beforeEach(() => {
    focusRef.value = "hub1";
    vi.mocked(fetchServices).mockResolvedValue([]);
    vi.mocked(fetchImages).mockResolvedValue({ items: [], actions_enabled: true });
  });

  afterEach(() => vi.clearAllMocks());

  it("허브 자신의 컨테이너는 시작/정지/제거 버튼이 비활성화되고 사유를 표시한다", async () => {
    vi.mocked(fetchContainer).mockResolvedValue(detail());

    render(<Containers />);
    const drawer = await screen.findByRole("dialog", { name: "컨테이너 상세" });

    expect(within(drawer).getByText("허브 자신의 컨테이너는 조작할 수 없습니다")).toBeInTheDocument();

    const stop = within(drawer).getByRole("button", { name: "정지" });
    expect(stop).toBeDisabled();
    expect(stop).toHaveAttribute("title", "허브 자신의 컨테이너는 조작할 수 없습니다");

    expect(within(drawer).getByRole("button", { name: "제거" })).toBeDisabled();
  });

  it("보호되지 않은 컨테이너는 조작 버튼이 활성화된다", async () => {
    focusRef.value = "c1";
    vi.mocked(fetchContainer).mockResolvedValue(
      detail({
        id: "c1",
        name: "flow-plan-ui",
        component_name: null,
        compose_project: "flow-plan",
        protected_reason: null,
        actions_allowed: true,
      }),
    );

    render(<Containers />);
    const drawer = await screen.findByRole("dialog", { name: "컨테이너 상세" });

    expect(within(drawer).getByRole("button", { name: "정지" })).toBeEnabled();
    // 실행 중이므로 제거는 상태 때문에 비활성
    expect(within(drawer).getByRole("button", { name: "제거" })).toBeDisabled();
    expect(
      within(drawer).queryByText("허브 자신의 컨테이너는 조작할 수 없습니다"),
    ).not.toBeInTheDocument();
  });

  it("게이트가 잠긴 경우(actions_allowed=false)에도 버튼이 비활성화된다", async () => {
    focusRef.value = "c2";
    vi.mocked(fetchContainer).mockResolvedValue(
      detail({
        id: "c2",
        name: "pianosync-web",
        state: "exited",
        component_name: null,
        protected_reason: null,
        actions_allowed: false,
      }),
    );

    render(<Containers />);
    const drawer = await screen.findByRole("dialog", { name: "컨테이너 상세" });
    const start = within(drawer).getByRole("button", { name: "시작" });
    expect(start).toBeDisabled();
    expect(start).toHaveAttribute("title", "HUB_ENABLE_DOCKER_ACTIONS=false");
  });
});
