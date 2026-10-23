import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import Overview from "./Overview";
import type { ServiceListItem, SystemOverview } from "../lib/api";

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    fetchOverview: vi.fn(),
    fetchServices: vi.fn(),
    fetchResourceWarnings: vi.fn(),
    fetchHostResources: vi.fn(),
  };
});

import {
  fetchHostResources,
  fetchOverview,
  fetchResourceWarnings,
  fetchServices,
} from "../lib/api";

const OVERVIEW: SystemOverview = {
  server: {
    hostname: "n100-server",
    os: "Debian GNU/Linux 12",
    kernel: "6.1.0-25-amd64",
    uptime_seconds: 1_058_400,
    booted_at: "2026-10-08T09:00:00+09:00",
  },
  docker: { connected: true, server_version: "27.3.1" },
  resources: {
    cpu: { percent: 23.5, cores: 4 },
    memory: { total_mb: 16384, used_mb: 13440, available_mb: 2944, percent: 82 },
    disk: { total_gb: 500, used_gb: 320, percent: 64 },
  },
  counts: { services: 5, containers_running: 7, containers_stopped: 2, orphans: 2 },
  last_monitor_ok_at: new Date(Date.now() - 12_000).toISOString(),
  recent_events: [
    {
      id: "e-1",
      ts: new Date(Date.now() - 60_000).toISOString(),
      severity: "critical",
      kind: "container.mismatch",
      service_id: "dev-playground",
      container_id: "c-1",
      message: "포트 매핑 불일치: 등록 5000 → 실제 5001",
    },
  ],
};

const SERVICES: ServiceListItem[] = [
  {
    id: "ai-platform",
    name: "AI Platform",
    description: "개인 AI 추론 플랫폼",
    category: "ai",
    status: "ok",
    containers: { total: 4, running: 4 },
    endpoints: [],
    cpu_percent: 18.4,
    memory_mb: 3120,
    last_deployed_at: "2026-10-18T10:00:00+09:00",
  },
  {
    id: "media-server",
    name: "Media Server",
    description: "미디어 스트리밍",
    category: "media",
    status: "warn",
    containers: { total: 2, running: 1 },
    endpoints: [],
    cpu_percent: 6.2,
    memory_mb: 1450,
    last_deployed_at: null,
  },
];

describe("Overview 페이지", () => {
  beforeEach(() => {
    // 개별 테스트가 명시하지 않으면 폴링은 실패로 두어 개요 응답 값을 사용한다.
    vi.mocked(fetchHostResources).mockRejectedValue(new Error("poll disabled in test"));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("카운트/게이지/서비스 상태/최근 이벤트를 렌더링한다", async () => {
    vi.mocked(fetchOverview).mockResolvedValue(OVERVIEW);
    vi.mocked(fetchServices).mockResolvedValue(SERVICES);
    vi.mocked(fetchResourceWarnings).mockResolvedValue([
      { level: "warning", scope: "memory", message: "메모리 사용률 82% — 주의 임계값 초과" },
    ]);

    render(<Overview />);

    expect(await screen.findByText("n100-server · Debian GNU/Linux 12 · 커널 6.1.0-25-amd64")).toBeInTheDocument();

    // 카운트 카드
    expect(screen.getByText("등록 서비스")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("실행 컨테이너")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("미관리 컨테이너")).toBeInTheDocument();

    // 자원 게이지 (수치)
    expect(screen.getByRole("img", { name: "CPU 23.5%" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "메모리 82.0%" })).toBeInTheDocument();

    // 서비스별 상태
    expect(screen.getByText("AI Platform")).toBeInTheDocument();
    expect(screen.getByText("정상")).toBeInTheDocument();
    expect(screen.getByText("주의")).toBeInTheDocument();

    // 최근 이벤트
    expect(screen.getByText("포트 매핑 불일치: 등록 5000 → 실제 5001")).toBeInTheDocument();

    // 주요 경고
    expect(screen.getByText("메모리 사용률 82% — 주의 임계값 초과")).toBeInTheDocument();
  });

  it("값이 없는 자원은 N/A로 표시한다 (0으로 대체하지 않음)", async () => {
    vi.mocked(fetchOverview).mockResolvedValue({
      ...OVERVIEW,
      resources: {
        cpu: { percent: null, cores: null },
        memory: { total_mb: null, used_mb: null, available_mb: null, percent: null },
        disk: { total_gb: null, used_gb: null, percent: null },
      },
    });
    vi.mocked(fetchServices).mockResolvedValue([]);
    vi.mocked(fetchResourceWarnings).mockResolvedValue([]);

    render(<Overview />);

    await waitFor(() => expect(screen.getAllByText("N/A").length).toBeGreaterThanOrEqual(3));
  });

  it("조회 실패 시 오류 메시지를 보여준다", async () => {
    const { ApiError } = await vi.importActual<typeof import("../lib/api")>("../lib/api");
    vi.mocked(fetchOverview).mockRejectedValue(new ApiError("백엔드 연결 실패", 0, "network_error"));
    vi.mocked(fetchServices).mockResolvedValue([]);
    vi.mocked(fetchResourceWarnings).mockResolvedValue([]);

    render(<Overview />);

    expect(await screen.findByText("백엔드 연결 실패")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeInTheDocument();
  });

  it("호스트 자원 게이지를 1초마다 갱신한다", async () => {
    vi.useFakeTimers();
    const resources = {
      cpu: { percent: 23.5, cores: 4 },
      memory: { total_mb: 16384, used_mb: 13440, available_mb: 2944, percent: 82 },
      disk: { total_gb: 500, used_gb: 320, percent: 64 },
    };
    vi.mocked(fetchOverview).mockResolvedValue(OVERVIEW);
    vi.mocked(fetchServices).mockResolvedValue([]);
    vi.mocked(fetchResourceWarnings).mockResolvedValue([]);
    vi.mocked(fetchHostResources).mockResolvedValue(resources);

    render(<Overview />);
    await act(async () => {});
    expect(screen.getByRole("img", { name: "CPU 23.5%" })).toBeInTheDocument();
    expect(fetchHostResources).toHaveBeenCalledTimes(1);

    // 1초 후 새 값으로 갱신
    vi.mocked(fetchHostResources).mockResolvedValue({
      ...resources,
      cpu: { percent: 61.2, cores: 4 },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(fetchHostResources).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("img", { name: "CPU 61.2%" })).toBeInTheDocument();
  });
});
