import { cn } from "../lib/utils";

export interface ChartPoint {
  ts: string;
  value: number | null;
}

/**
 * 가벼운 SVG 라인/스파크라인 차트 (차트 라이브러리 없이 직접 구현).
 * null 값은 선을 끊어 표시한다 — 알 수 없는 값을 0으로 대체하지 않는다.
 */
export function LineChart({
  points,
  height = 120,
  color = "stroke-blue-500",
  fill = "fill-blue-500/10",
  unit = "",
  minLabel,
  maxLabel,
  warnAt,
  criticalAt,
  ariaLabel,
  className,
}: {
  points: ChartPoint[];
  height?: number;
  color?: string;
  fill?: string;
  unit?: string;
  minLabel?: string;
  maxLabel?: string;
  warnAt?: number | null;
  criticalAt?: number | null;
  ariaLabel: string;
  className?: string;
}) {
  const W = 300;
  const H = height;
  const PAD = { top: 8, right: 6, bottom: 6, left: 6 };

  const values = points.map((p) => p.value).filter((v): v is number => v != null && !Number.isNaN(v));
  const dataMin = values.length ? Math.min(...values) : 0;
  const dataMax = values.length ? Math.max(...values) : 1;
  const lo = Math.min(0, dataMin);
  const hi = dataMax === dataMin ? dataMax + 1 : dataMax;

  const x = (i: number) =>
    PAD.left + (points.length <= 1 ? 0 : (i / (points.length - 1)) * (W - PAD.left - PAD.right));
  const y = (v: number) =>
    PAD.top + (1 - (v - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);

  // 세그먼트 분리 (null 경계에서 선 끊김)
  const segments: Array<Array<{ x: number; y: number }>> = [];
  let current: Array<{ x: number; y: number }> = [];
  points.forEach((p, i) => {
    if (p.value == null || Number.isNaN(p.value)) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push({ x: x(i), y: y(p.value) });
    }
  });
  if (current.length) segments.push(current);

  const thresholdLine = (v: number | null | undefined, dash: string, cls: string) =>
    v == null || v < lo || v > hi ? null : (
      <line
        x1={PAD.left}
        x2={W - PAD.right}
        y1={y(v)}
        y2={y(v)}
        strokeWidth="1"
        strokeDasharray={dash}
        className={cls}
      />
    );

  return (
    <div className={cn("w-full", className)}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ height }}
        preserveAspectRatio="none"
        role="img"
        aria-label={ariaLabel}
      >
        {thresholdLine(criticalAt, "4 3", "stroke-red-500/60")}
        {thresholdLine(warnAt, "4 3", "stroke-amber-500/60")}
        {segments.map((seg, i) => {
          const d = seg.map((pt, j) => `${j === 0 ? "M" : "L"} ${pt.x} ${pt.y}`).join(" ");
          const area =
            seg.length > 1
              ? `${d} L ${seg[seg.length - 1].x} ${H - PAD.bottom} L ${seg[0].x} ${H - PAD.bottom} Z`
              : null;
          return (
            <g key={i}>
              {area ? <path d={area} className={fill} /> : null}
              <path d={d} fill="none" strokeWidth="1.5" className={color} vectorEffect="non-scaling-stroke" />
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>{minLabel ?? `${dataMin.toFixed(1)}${unit}`}</span>
        <span>{maxLabel ?? `${dataMax.toFixed(1)}${unit}`}</span>
      </div>
    </div>
  );
}

/** 사이드바/테이블용 미니 스파크라인 */
export function Sparkline({
  values,
  className,
  color = "stroke-blue-500",
}: {
  values: Array<number | null>;
  className?: string;
  color?: string;
}) {
  const W = 90;
  const H = 22;
  const nums = values.filter((v): v is number => v != null && !Number.isNaN(v));
  if (nums.length < 2) {
    return (
      <span className={cn("text-[11px] text-muted-foreground", className)}>추이 데이터 부족</span>
    );
  }
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  const span = hi - lo || 1;
  const pts: string[] = [];
  let idx = 0;
  values.forEach((v, i) => {
    if (v == null) return;
    const px = (i / (values.length - 1)) * W;
    const py = H - 2 - ((v - lo) / span) * (H - 4);
    pts.push(`${idx === 0 ? "M" : "L"} ${px.toFixed(1)} ${py.toFixed(1)}`);
    idx++;
  });
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className={cn("inline-block", className)} aria-hidden="true">
      <path d={pts.join(" ")} fill="none" strokeWidth="1.5" className={color} />
    </svg>
  );
}
