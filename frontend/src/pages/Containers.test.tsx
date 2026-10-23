import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Containers from "./Containers";
import type { ContainerDetail, ContainerListItem } from "../lib/api";

const focusRef = { value: "hub1" };

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useSearchParams: () => [
    new URLSearchParams(focusRef.value ? { focus: focusRef.value } : {}),
    vi.fn(),
  ],
  useParams: () => ({}),
  Link: ({ children, to }: { children: React.ReactNode; to?: string }) => (
    <a href={to}>{children}</a>
  ),
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    fetchContainers: vi.fn(async () => []),
    fetchContainer: vi.fn(),
    fetchContainerResources: vi.fn(async () => []),
    fetchImages: vi.fn(async () => ({ items: [], actions_enabled: true })),
    fetchServices: vi.fn(async () => []),
    fetchOrphans: vi.fn(async () => []),
  };
});

import {
  fetchContainer,
  fetchContainers,
  fetchContainerResources,
  fetchImages,
  fetchServices,
} from "../lib/api";

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

function item(overrides: Partial<ContainerListItem> = {}): ContainerListItem {
  return {
    id: "c1",
    name: "flow-plan-ui",
    image: "flow-plan-ui:latest",
    state: "running",
    status: "Up 1 hour",
    management_state: "managed",
    service_id: "flow-plan",
    component_name: "ui",
    compose_project: "flow-plan",
    compose_service: "ui",
    ports: [],
    networks: [],
    started_at: null,
    created_at: null,
    restart_count: 0,
    health: null,
    observed_at: null,
    ...overrides,
  };
}

describe("Containers 목록 — 서비스 그룹화", () => {
  beforeEach(() => {
    focusRef.value = "";
  });
  afterEach(() => vi.clearAllMocks());

  it("서비스에 묶인 컨테이너는 서비스 단위로 묶여 표시된다", async () => {
    vi.mocked(fetchContainers).mockResolvedValue([
      item({ id: "c1", name: "flow-plan-ui", component_name: "ui" }),
      item({ id: "c2", name: "flow-plan-backend", component_name: "backend" }),
      item({
        id: "c3", name: "stray-web", service_id: null, component_name: null,
        management_state: "unmanaged", compose_project: null, compose_service: null,
      }),
    ]);
    vi.mocked(fetchServices).mockResolvedValue([
      {
        id: "flow-plan", name: "Flow Plan", description: "", category: "web",
        status: "ok", containers: { total: 2, running: 2 }, endpoints: [],
        cpu_percent: null, memory_mb: null, last_deployed_at: null,
      },
    ]);

    render(<Containers />);

    // 서비스 그룹 헤더 — 이름/실행 상태만 (ID·개수·상세 링크는 노출하지 않음)
    expect(await screen.findByText("Flow Plan")).toBeInTheDocument();
    const groupRow = screen.getByText("Flow Plan").closest("tr")!;
    expect(within(groupRow).getByText("2/2 실행 중")).toBeInTheDocument();
    expect(within(groupRow).queryByText("flow-plan")).not.toBeInTheDocument();
    expect(within(groupRow).queryByText("2개")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /서비스 상세/ })).not.toBeInTheDocument();

    // 기본은 접힘 — 행은 보이지 않는다
    expect(screen.getByText("서비스 미지정")).toBeInTheDocument();
    expect(screen.queryByText("stray-web")).not.toBeInTheDocument();
    expect(screen.queryByText("flow-plan-ui")).not.toBeInTheDocument();

    // 펼치면 행이 나타난다
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "모두 펼치기" }));
    expect(await screen.findByText("flow-plan-ui")).toBeInTheDocument();
    expect(screen.getByText("stray-web")).toBeInTheDocument();
  });

  it("그룹을 접고 펼칠 수 있다", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchContainers).mockResolvedValue([
      item({ id: "c1", name: "flow-plan-ui", component_name: "ui" }),
      item({ id: "c2", name: "flow-plan-backend", component_name: "backend" }),
    ]);
    vi.mocked(fetchServices).mockResolvedValue([
      {
        id: "flow-plan", name: "Flow Plan", description: "", category: "web",
        status: "ok", containers: { total: 2, running: 2 }, endpoints: [],
        cpu_percent: null, memory_mb: null, last_deployed_at: null,
      },
    ]);

    render(<Containers />);
    // 기본은 접힘
    expect(await screen.findByText("Flow Plan")).toBeInTheDocument();
    expect(screen.queryByText("flow-plan-ui")).not.toBeInTheDocument();

    const expand = screen.getByRole("button", { name: "Flow Plan 그룹 펼치기" });
    expect(expand).toHaveAttribute("aria-expanded", "false");

    await user.click(expand);
    expect(screen.getByRole("button", { name: "Flow Plan 그룹 접기" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(await screen.findByText("flow-plan-ui")).toBeInTheDocument();
    // 헤더 요약은 그대로 보인다
    expect(
      within(screen.getByRole("button", { name: "Flow Plan 그룹 접기" }).closest("tr")!)
        .getByText("2/2 실행 중"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Flow Plan 그룹 접기" }));
    expect(screen.queryByText("flow-plan-ui")).not.toBeInTheDocument();
  });

  it("모두 접기/펼치기 버튼으로 전체 그룹을 제어한다", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchContainers).mockResolvedValue([
      item({ id: "c1", name: "flow-plan-ui", component_name: "ui" }),
      item({
        id: "c3", name: "stray-web", service_id: null, component_name: null,
        management_state: "unmanaged",
      }),
    ]);
    vi.mocked(fetchServices).mockResolvedValue([
      {
        id: "flow-plan", name: "Flow Plan", description: "", category: "web",
        status: "ok", containers: { total: 1, running: 1 }, endpoints: [],
        cpu_percent: null, memory_mb: null, last_deployed_at: null,
      },
    ]);

    render(<Containers />);
    expect(await screen.findByText("Flow Plan")).toBeInTheDocument();
    expect(screen.queryByText("flow-plan-ui")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "모두 펼치기" }));
    expect(await screen.findByText("flow-plan-ui")).toBeInTheDocument();
    expect(screen.getByText("stray-web")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "모두 접기" }));
    expect(screen.queryByText("flow-plan-ui")).not.toBeInTheDocument();
    expect(screen.queryByText("stray-web")).not.toBeInTheDocument();
    expect(screen.getByText("서비스 미지정")).toBeInTheDocument();
  });

  it("docker stats 값을 CPU/메모리 컬럼에 표시하고, 중지 컨테이너는 N/A로 둔다", async () => {
    vi.mocked(fetchContainers).mockResolvedValue([
      item({ id: "c1", name: "flow-plan-ui" }),
      item({ id: "c2", name: "flow-plan-backend", state: "exited", component_name: "backend" }),
    ]);
    vi.mocked(fetchContainerResources).mockResolvedValue([
      {
        container_id: "c1", name: "flow-plan-ui", service_id: "flow-plan", state: "running",
        cpu_percent: 12.3, mem_used_mb: 128, mem_limit_mb: 2048,
      },
    ]);
    vi.mocked(fetchServices).mockResolvedValue([]);

    render(<Containers />);

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "모두 펼치기" }));
    expect(await screen.findByText("12.3%")).toBeInTheDocument();
    expect(screen.getByText("128 MB")).toBeInTheDocument();
    // stats 가 없는(중지) 컨테이너는 N/A
    expect(screen.getByText("flow-plan-backend")).toBeInTheDocument();
    expect(screen.getAllByText("N/A").length).toBeGreaterThanOrEqual(2);
  });

  it("Images 섹션은 기본적으로 접혀 있고, 펼치면 목록이 보인다", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchContainers).mockResolvedValue([]);
    vi.mocked(fetchServices).mockResolvedValue([]);
    vi.mocked(fetchImages).mockResolvedValue({
      items: [
        {
          id: "sha256:abc123", short_id: "abc123", tags: ["nginx:alpine"],
          size_mb: 103, created_at: null,
        },
      ],
      actions_enabled: true,
    });

    render(<Containers />);

    const toggle = await screen.findByRole("button", { name: /Images/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("nginx:alpine")).not.toBeInTheDocument();
    // 접힌 상태에서도 요약은 보인다
    expect(within(toggle).getByText(/이미지 1개/)).toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("nginx:alpine")).toBeInTheDocument();
    expect(screen.queryByText(/펼쳐서 관리/)).not.toBeInTheDocument();

    await user.click(toggle);
    expect(screen.queryByText("nginx:alpine")).not.toBeInTheDocument();
  });

  it("연결된 서비스가 없으면 그룹 헤더 없이 평면 목록으로 보인다", async () => {
    vi.mocked(fetchContainers).mockResolvedValue([
      item({
        id: "c9", name: "stray", service_id: null, component_name: null,
        management_state: "unmanaged",
      }),
    ]);
    vi.mocked(fetchServices).mockResolvedValue([]);

    render(<Containers />);
    expect(await screen.findByText("stray")).toBeInTheDocument();
    expect(screen.queryByText("서비스 미지정")).not.toBeInTheDocument();
  });
});

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
