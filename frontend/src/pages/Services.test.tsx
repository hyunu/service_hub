import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Services from "./Services";
import { ApiError, type ServiceListItem } from "../lib/api";

const navigate = vi.fn();

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigate,
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
  useParams: () => ({}),
  Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, fetchServices: vi.fn(), createService: vi.fn() };
});

import { fetchServices } from "../lib/api";

const ALL: ServiceListItem[] = [
  {
    id: "ai-platform",
    name: "AI Platform",
    description: "개인 AI 추론 플랫폼",
    category: "ai",
    status: "ok",
    containers: { total: 4, running: 4 },
    endpoints: [{ name: "frontend", type: "http", exposure: "proxy", hostname: "ai.home", container: "ai-frontend", container_port: 3000 }],
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
  {
    id: "dev-playground",
    name: "Dev Playground",
    description: "개발/테스트 환경",
    category: "dev",
    status: "critical",
    containers: { total: 2, running: 0 },
    endpoints: [],
    cpu_percent: null,
    memory_mb: null,
    last_deployed_at: null,
  },
];

describe("Services 페이지", () => {
  beforeEach(() => {
    vi.mocked(fetchServices).mockImplementation(async (query) => {
      const search = (query?.search ?? "").toLowerCase();
      return ALL.filter((s) => {
        if (query?.status && s.status !== query.status) return false;
        if (query?.category && s.category !== query.category) return false;
        if (
          search &&
          !s.name.toLowerCase().includes(search) &&
          !s.id.includes(search) &&
          !s.description.toLowerCase().includes(search)
        )
          return false;
        return true;
      });
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("전체 서비스를 이름/상태와 함께 표시한다", async () => {
    render(<Services />);
    expect(await screen.findByText("AI Platform")).toBeInTheDocument();
    expect(screen.getByText("Media Server")).toBeInTheDocument();
    expect(screen.getByText("Dev Playground")).toBeInTheDocument();
    expect(screen.getByText("등록 서비스 3개 · Service Registry (컨테이너와 별개의 관리 정보)")).toBeInTheDocument();
  });

  it("검색어로 목록이 필터링된다", async () => {
    const user = userEvent.setup();
    render(<Services />);
    await screen.findByText("AI Platform");

    await user.type(screen.getByLabelText("서비스 검색"), "media");

    await waitFor(() => {
      expect(screen.queryByText("AI Platform")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Media Server")).toBeInTheDocument();
    expect(fetchServices).toHaveBeenLastCalledWith(
      expect.objectContaining({ search: "media" }),
    );
  });

  it("상태 필터를 적용하면 해당 상태만 남는다", async () => {
    const user = userEvent.setup();
    render(<Services />);
    await screen.findByText("AI Platform");

    await user.selectOptions(screen.getByLabelText("상태 필터"), "warn");

    await waitFor(() => {
      expect(screen.queryByText("AI Platform")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Media Server")).toBeInTheDocument();
    expect(screen.queryByText("Dev Playground")).not.toBeInTheDocument();
    expect(fetchServices).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: "warn" }),
    );
  });

  it("카테고리 필터를 적용하면 해당 카테고리만 남는다", async () => {
    const user = userEvent.setup();
    render(<Services />);
    await screen.findByText("AI Platform");

    await user.selectOptions(screen.getByLabelText("카테고리 필터"), "dev");

    await waitFor(() => {
      expect(screen.queryByText("Media Server")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Dev Playground")).toBeInTheDocument();
  });

  it("필터 해제 버튼이 활성 필터 수를 표시하고 초기화한다", async () => {
    const user = userEvent.setup();
    render(<Services />);
    await screen.findByText("AI Platform");

    await user.selectOptions(screen.getByLabelText("상태 필터"), "ok");
    const clear = await screen.findByRole("button", { name: /필터 해제/ });
    expect(clear).toHaveTextContent("필터 해제 (1)");

    await user.click(clear);
    await waitFor(() => expect(screen.getByText("Media Server")).toBeInTheDocument());
    expect(screen.getByText("Dev Playground")).toBeInTheDocument();
  });

  it("조회 실패 시 오류와 다시 시도 버튼을 표시한다", async () => {
    vi.mocked(fetchServices).mockRejectedValueOnce(new ApiError("서비스 조회 실패", 500));
    render(<Services />);
    expect(await screen.findByText("서비스 조회 실패")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeInTheDocument();
  });

  it("등록 다이얼로그에서 입력해도 포커스가 유지된다", async () => {
    // 회귀 방지: onClose 가 렌더마다 새 함수여도 다이얼로그가 재포커스하지 않아야 한다.
    const user = userEvent.setup();
    render(<Services />);
    await screen.findByText("AI Platform");

    await user.click(screen.getByRole("button", { name: /서비스 등록/ }));
    const dialog = await screen.findByRole("dialog");
    const idInput = within(dialog).getByLabelText(/서비스 ID/);

    await user.click(idInput);
    await user.type(idInput, "my-app");

    expect(idInput).toHaveValue("my-app");
    expect(idInput).toHaveFocus();
  });

  it("등록 다이얼로그에서 필수값 검증 오류를 표시한다", async () => {
    const user = userEvent.setup();
    render(<Services />);
    await screen.findByText("AI Platform");

    await user.click(screen.getByRole("button", { name: /서비스 등록/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "등록" }));

    expect(await within(dialog).findByText(/id는 영문 소문자/)).toBeInTheDocument();
    expect(within(dialog).getByText("서비스 이름을 입력하세요.")).toBeInTheDocument();
    expect(within(dialog).getByText("설명을 입력하세요.")).toBeInTheDocument();
  });
});
