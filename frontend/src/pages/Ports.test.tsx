import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import Ports from "./Ports";
import type { PortEntry } from "../lib/api";

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
  Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    fetchPorts: vi.fn(),
    fetchServices: vi.fn(),
    fetchAvailablePorts: vi.fn(),
  };
});

import { fetchPorts, fetchServices } from "../lib/api";

const PORTS: PortEntry[] = [
  {
    reservation_id: "r-1",
    service_id: "ai-platform",
    service_name: "AI Platform",
    component: "frontend",
    protocol: "tcp",
    host_port: 3000,
    bind_addr: "127.0.0.1",
    container_port: 3000,
    exposure: "proxy",
    state: "in_use",
    occupied: true,
    occupied_by: "ai-frontend",
    last_checked_at: "2026-10-21T14:00:00+09:00",
  },
  {
    reservation_id: "r-2",
    service_id: "dev-playground",
    service_name: "Dev Playground",
    component: "web",
    protocol: "tcp",
    host_port: 5001,
    bind_addr: "0.0.0.0",
    container_port: 5000,
    exposure: "public",
    state: "conflict",
    occupied: true,
    occupied_by: "playground-web",
    last_checked_at: "2026-10-21T14:00:00+09:00",
  },
  {
    reservation_id: null,
    service_id: null,
    protocol: "tcp",
    host_port: 8081,
    bind_addr: "0.0.0.0",
    container_port: 80,
    exposure: "public",
    state: "unmanaged",
    occupied: true,
    occupied_by: "old-nginx",
    last_checked_at: "2026-10-21T14:00:00+09:00",
  },
  {
    reservation_id: "r-5",
    service_id: "sample-app",
    service_name: "샘플 애플리케이션",
    component: "backend",
    protocol: "tcp",
    host_port: 8010,
    bind_addr: "127.0.0.1",
    container_port: 8000,
    exposure: "internal",
    state: "reserved",
    occupied: false,
    last_checked_at: "2026-10-21T14:00:00+09:00",
  },
];

describe("Ports & Routing 페이지", () => {
  afterEach(() => vi.clearAllMocks());

  it("상태 배지를 한국어 라벨로 렌더링한다 (충돌/점유/미관리/예약)", async () => {
    vi.mocked(fetchPorts).mockResolvedValue(PORTS);
    vi.mocked(fetchServices).mockResolvedValue([]);

    render(<Ports />);

    expect(await screen.findByText("5001")).toBeInTheDocument();
    // 표 셀 배지 + 필터 칩이 모두 존재하므로 getAllByText 사용
    expect(screen.getAllByText("충돌").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("점유 중").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("미관리 점유").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("예약됨").length).toBeGreaterThanOrEqual(2);
  });

  it("충돌 포트의 포트 번호를 강조 클래스로 표시한다", async () => {
    vi.mocked(fetchPorts).mockResolvedValue(PORTS);
    vi.mocked(fetchServices).mockResolvedValue([]);

    render(<Ports />);

    const portCell = await screen.findByText("5001");
    expect(portCell.className).toContain("text-red-500");
  });

  it("예약된 항목에만 삭제 버튼을 제공한다", async () => {
    vi.mocked(fetchPorts).mockResolvedValue(PORTS);
    vi.mocked(fetchServices).mockResolvedValue([]);

    render(<Ports />);
    await screen.findByText("5001");

    expect(screen.getByRole("button", { name: "3000 예약 삭제" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "8010 예약 삭제" })).toBeInTheDocument();
    // 미관리 점유(8081)는 예약 레코드가 없으므로 삭제 버튼이 없다
    expect(screen.queryByRole("button", { name: "8081 예약 삭제" })).not.toBeInTheDocument();
  });
});
