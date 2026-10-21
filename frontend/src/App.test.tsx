import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { setCsrfToken } from "./lib/api";

/**
 * 라우팅/가드 스모크 테스트.
 * VITE_API_MOCK 어댑터를 통해 백엔드 없이도 전체 페이지 모듈이 로드되는지 확인한다.
 */
vi.stubEnv("VITE_API_MOCK", "true");

describe("App 라우팅", () => {
  beforeEach(() => {
    setCsrfToken(null);
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.stubEnv("VITE_API_MOCK", "true");
    setCsrfToken(null);
  });

  it("세션이 인증 상태면 Overview를 렌더링한다", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument();
    });
    // 사이드바 내비게이션 항목
    expect(screen.getByRole("link", { name: "Ports & Routing" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Deployments" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Resources" })).toBeInTheDocument();
  });

  it("Services 경로에서 서비스 표를 렌더링한다", async () => {
    render(
      <MemoryRouter initialEntries={["/services"]}>
        <App />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Services" })).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText("AI Platform")).toBeInTheDocument();
    });
  });

  it("Ports 경로에서 충돌 배지를 렌더링한다", async () => {
    render(
      <MemoryRouter initialEntries={["/ports"]}>
        <App />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Ports & Routing" })).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getAllByText("충돌").length).toBeGreaterThan(0);
    });
  });

  it("Settings 경로에서 설정 폼을 렌더링한다", async () => {
    render(
      <MemoryRouter initialEntries={["/settings"]}>
        <App />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByLabelText("허브 이름")).toHaveValue("N100 Service Hub");
    });
  });
});
