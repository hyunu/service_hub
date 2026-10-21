import { cn } from "../lib/utils";
import { formatPercent } from "../lib/format";

export type GaugeLevel = "ok" | "warn" | "critical";

/** 임계값 기반 색상 판정 (사양 §10.4 기본: 80 주의 / 90 위험) */
export function gaugeLevel(
  percent: number | null | undefined,
  warn = 80,
  critical = 90,
): GaugeLevel {
  if (percent == null || Number.isNaN(percent)) return "ok";
  if (percent >= critical) return "critical";
  if (percent >= warn) return "warn";
  return "ok";
}

const LEVEL_STROKE: Record<GaugeLevel, string> = {
  ok: "stroke-emerald-500",
  warn: "stroke-amber-500",
  critical: "stroke-red-500",
};

const ARC_LEN = Math.PI * 50; // 반지름 50 반원

/**
 * 반원형 자원 게이지 — SVG만 사용 (차트 라이브러리 없음).
 * 값이 없으면 "N/A"와 회색 아치로 표시한다(임의 값 대체 금지).
 */
export function Gauge({
  label,
  percent,
  detail,
  warn = 80,
  critical = 90,
  size = 140,
  className,
}: {
  label: string;
  percent: number | null | undefined;
  detail?: string;
  warn?: number;
  critical?: number;
  size?: number;
  className?: string;
}) {
  const hasValue = percent != null && !Number.isNaN(percent);
  const p = hasValue ? Math.max(0, Math.min(1, (percent as number) / 100)) : 0;
  const level = gaugeLevel(percent, warn, critical);

  return (
    <div className={cn("flex flex-col items-center", className)}>
      <svg
        viewBox="0 0 120 70"
        width={size}
        height={(size * 70) / 120}
        role="img"
        aria-label={`${label} ${hasValue ? formatPercent(percent) : "N/A"}`}
      >
        <path
          d="M 10 60 A 50 50 0 0 1 110 60"
          fill="none"
          strokeWidth="9"
          strokeLinecap="round"
          className="stroke-muted"
        />
        {hasValue ? (
          <path
            d="M 10 60 A 50 50 0 0 1 110 60"
            fill="none"
            strokeWidth="9"
            strokeLinecap="round"
            strokeDasharray={ARC_LEN}
            strokeDashoffset={ARC_LEN * (1 - p)}
            className={LEVEL_STROKE[level]}
          />
        ) : null}
        <text
          x="60"
          y="52"
          textAnchor="middle"
          className="fill-foreground text-[17px] font-semibold"
        >
          {hasValue ? formatPercent(percent, 0) : "N/A"}
        </text>
      </svg>
      <div className="mt-0.5 text-xs font-medium">{label}</div>
      {detail ? <div className="text-[11px] text-muted-foreground">{detail}</div> : null}
    </div>
  );
}
