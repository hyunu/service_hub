import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { copyText } from "./clipboard";

function setSecure(value: boolean) {
  Object.defineProperty(window, "isSecureContext", { value, configurable: true });
}

describe("copyText", () => {
  beforeEach(() => {
    setSecure(true);
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("보안 컨텍스트에서는 Clipboard API를 사용한다", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    await expect(copyText("http://host:20102")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("http://host:20102");
    // fallback(textarea)은 사용하지 않는다
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("Clipboard API가 거부되면 textarea fallback으로 복사한다", async () => {
    const writeText = vi.fn(async () => {
      throw new Error("NotAllowedError");
    });
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const exec = vi.fn(() => true);
    Object.defineProperty(document, "execCommand", { value: exec, configurable: true });

    await expect(copyText("x")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalled();
    expect(exec).toHaveBeenCalledWith("copy");
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("비보안 컨텍스트(HTTP)에서도 fallback으로 복사한다", async () => {
    setSecure(false);
    const exec = vi.fn(() => true);
    Object.defineProperty(document, "execCommand", { value: exec, configurable: true });

    await expect(copyText("http://100.85.245.79:20102")).resolves.toBe(true);
    expect(exec).toHaveBeenCalledWith("copy");
  });

  it("fallback도 실패하면 false를 반환한다", async () => {
    setSecure(false);
    Object.defineProperty(document, "execCommand", {
      value: vi.fn(() => false),
      configurable: true,
    });
    await expect(copyText("x")).resolves.toBe(false);
  });

  it("빈 문자열은 복사하지 않는다", async () => {
    await expect(copyText("")).resolves.toBe(false);
  });
});
