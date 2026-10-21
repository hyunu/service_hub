import { cn } from "../lib/utils";
import { Badge } from "./ui/badge";

/**
 * 상태 중심 시각화 — 사양 §11: 녹색 OK, 앰버 WARN, 적색 CRITICAL, 슬레이트 UNKNOWN.
 * 텍스트가 필요하면 children, 점만 필요하면 dot 전용으로 사용한다.
 */

export type StatusLevel = "ok" | "warn" | "critical" | "unknown";

export const STATUS_DOT: Record<StatusLevel, string> = {
  ok: "bg-emerald-500",
  warn: "bg-amber-500",
  critical: "bg-red-500",
  unknown: "bg-slate-400",
};

export const STATUS_TEXT: Record<StatusLevel, string> = {
  ok: "text-emerald-600 dark:text-emerald-400",
  warn: "text-amber-600 dark:text-amber-400",
  critical: "text-red-600 dark:text-red-400",
  unknown: "text-slate-500 dark:text-slate-400",
};

export const STATUS_LABEL_KO: Record<StatusLevel, string> = {
  ok: "정상",
  warn: "주의",
  critical: "위험",
  unknown: "상태 불명",
};

export function normalizeStatus(raw: string | null | undefined): StatusLevel {
  switch (raw) {
    case "ok":
    case "healthy":
    case "running":
    case "succeeded":
      return "ok";
    case "warn":
    case "warning":
    case "degraded":
    case "unhealthy":
      return "warn";
    case "critical":
    case "error":
    case "failed":
    case "down":
      return "critical";
    default:
      return "unknown";
  }
}

export function StatusDot({
  level,
  className,
}: {
  level: StatusLevel;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn("inline-block h-2 w-2 shrink-0 rounded-full", STATUS_DOT[level], className)}
    />
  );
}

export function StatusBadge({
  status,
  label,
  className,
}: {
  status: string | null | undefined;
  label?: string;
  className?: string;
}) {
  const level = normalizeStatus(status);
  const badgeVariant: Record<StatusLevel, "ok" | "warn" | "critical" | "unknown"> = {
    ok: "ok",
    warn: "warn",
    critical: "critical",
    unknown: "unknown",
  };
  return (
    <Badge variant={badgeVariant[level]} className={className}>
      <StatusDot level={level} className="h-1.5 w-1.5" />
      {label ?? STATUS_LABEL_KO[level]}
    </Badge>
  );
}
