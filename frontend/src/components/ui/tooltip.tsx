import * as React from "react";
import { cn } from "../../lib/utils";

/**
 * 최소 툴팁 — hover/focus 시 표시되는 CSS 기반 툴팁.
 * 위치는 래퍼 relative 기준 상단 중앙이다.
 */
export function Tooltip({
  content,
  children,
  className,
  side = "top",
}: {
  content: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  side?: "top" | "bottom" | "left" | "right";
}) {
  const [open, setOpen] = React.useState(false);
  const pos =
    side === "top"
      ? "bottom-full left-1/2 -translate-x-1/2 mb-1.5"
      : side === "bottom"
        ? "top-full left-1/2 -translate-x-1/2 mt-1.5"
        : side === "left"
          ? "right-full top-1/2 -translate-y-1/2 mr-1.5"
          : "left-full top-1/2 -translate-y-1/2 ml-1.5";

  return (
    <span
      className={cn("relative inline-flex", className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open ? (
        <span
          role="tooltip"
          className={cn(
            "pointer-events-none absolute z-40 w-max max-w-xs rounded border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md",
            pos,
          )}
        >
          {content}
        </span>
      ) : null}
    </span>
  );
}
