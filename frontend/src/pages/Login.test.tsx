import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Login from "./Login";
import { ApiError } from "../lib/api";

const loginMock = vi.fn();
const navigate = vi.fn();

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    status: "anonymous",
    session: null,
    login: loginMock,
    logout: vi.fn(),
    refresh: vi.fn(),
    completeSetup: vi.fn(),
  }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigate,
  useLocation: () => ({ state: null, pathname: "/login" }),
  Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

describe("Login 페이지", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("아이디가 비어 있으면 검증 메시지를 표시하고 로그인을 호출하지 않는다", async () => {
    const user = userEvent.setup();
    render(<Login />);

    await user.click(screen.getByRole("button", { name: /로그인/ }));

    expect(await screen.findByText("아이디를 입력하세요.")).toBeInTheDocument();
    expect(screen.getByText("비밀번호를 입력하세요.")).toBeInTheDocument();
    expect(loginMock).not.toHaveBeenCalled();
  });

  it("비밀번호가 비어 있으면 검증 메시지를 표시한다", async () => {
    const user = userEvent.setup();
    render(<Login />);

    await user.type(screen.getByLabelText(/아이디/), "admin");
    await user.click(screen.getByRole("button", { name: /로그인/ }));

    expect(await screen.findByText("비밀번호를 입력하세요.")).toBeInTheDocument();
    expect(loginMock).not.toHaveBeenCalled();
  });

  it("정상 입력 시 로그인하고 이전 경로로 이동한다", async () => {
    loginMock.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<Login />);

    await user.type(screen.getByLabelText(/아이디/), "admin");
    await user.type(screen.getByLabelText(/비밀번호/), "s3cret-pass");
    await user.click(screen.getByRole("button", { name: /로그인/ }));

    await waitFor(() => expect(loginMock).toHaveBeenCalledWith("admin", "s3cret-pass"));
    expect(navigate).toHaveBeenCalledWith("/", { replace: true });
  });

  it("서버가 401을 반환하면 자격 증명 오류 메시지를 표시한다", async () => {
    loginMock.mockRejectedValue(new ApiError("unauthorized", 401, "invalid_credentials"));
    const user = userEvent.setup();
    render(<Login />);

    await user.type(screen.getByLabelText(/아이디/), "admin");
    await user.type(screen.getByLabelText(/비밀번호/), "wrong-password");
    await user.click(screen.getByRole("button", { name: /로그인/ }));

    expect(
      await screen.findByText("아이디 또는 비밀번호가 올바르지 않습니다."),
    ).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("네트워크 오류 메시지를 그대로 노출한다", async () => {
    loginMock.mockRejectedValue(
      new ApiError("백엔드 서버에 연결할 수 없습니다 (127.0.0.1:8420).", 0, "network_error"),
    );
    const user = userEvent.setup();
    render(<Login />);

    await user.type(screen.getByLabelText(/아이디/), "admin");
    await user.type(screen.getByLabelText(/비밀번호/), "s3cret-pass");
    await user.click(screen.getByRole("button", { name: /로그인/ }));

    expect(
      await screen.findByText("백엔드 서버에 연결할 수 없습니다 (127.0.0.1:8420)."),
    ).toBeInTheDocument();
  });
});
