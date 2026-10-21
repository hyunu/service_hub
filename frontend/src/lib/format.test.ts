import { describe, it, expect } from "vitest";
import { formatBytesMb } from "./format";

describe("formatBytesMb", () => {
  it("null/NaN 은 N/A (0으로 대체하지 않는다)", () => {
    expect(formatBytesMb(null)).toBe("N/A");
    expect(formatBytesMb(undefined)).toBe("N/A");
    expect(formatBytesMb(Number.NaN)).toBe("N/A");
  });

  it("1MB 미만은 KB 로 표기 (0 MB 반올림 방지)", () => {
    expect(formatBytesMb(0.004)).toBe("4 KB");
    expect(formatBytesMb(0.5)).toBe("512 KB");
    expect(formatBytesMb(0)).toBe("0 KB");
  });

  it("MB / GB 단위", () => {
    expect(formatBytesMb(1)).toBe("1 MB");
    expect(formatBytesMb(652.4)).toBe("652 MB");
    expect(formatBytesMb(1967.6)).toBe("1.9 GB");
  });
});
