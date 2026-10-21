/**
 * 공통 시간/숫자 포맷 유틸.
 * 규칙: ISO 8601 원본을 받아 브라우저 로컬 시간 기준으로 표시하고,
 * 상대 시간은 한국어로 함께 표기한다. (예: "2026-10-21 14:03:12 · 3분 전")
 */

const KO_UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["second", 1000],
  ["minute", 60 * 1000],
  ["hour", 3600 * 1000],
  ["day", 24 * 3600 * 1000],
  ["month", 30 * 24 * 3600 * 1000],
  ["year", 365 * 24 * 3600 * 1000],
];

const relFormatter = new Intl.RelativeTimeFormat("ko", { numeric: "auto" });

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** 로컬 날짜+시각: "2026-10-21 14:03:12" */
export function formatDateTime(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

/** 로컬 날짜만: "2026-10-21" */
export function formatDate(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** 상대 시간: "3분 전", "방금 전", "2일 전" */
export function formatRelative(
  value: string | null | undefined,
  now: Date = new Date(),
): string {
  const d = parseDate(value);
  if (!d) return "—";
  const diff = d.getTime() - now.getTime();
  const abs = Math.abs(diff);
  if (abs < 45_000) return relFormatter.format(Math.round(diff / 1000), "second");
  for (const [unit, ms] of KO_UNITS) {
    if (abs < ms * 60) {
      return relFormatter.format(Math.round(diff / ms), unit);
    }
  }
  return relFormatter.format(Math.round(diff / KO_UNITS[4][1]), "month");
}

/** "2026-10-21 14:03:12 · 3분 전" — 화면용 결합 표기 */
export function formatDateTimeFull(
  value: string | null | undefined,
  now?: Date,
): string {
  const d = parseDate(value);
  if (!d) return "—";
  return `${formatDateTime(d.toISOString())} · ${formatRelative(value, now)}`;
}

/** "12일 4시간" 형태의 가동 시간 */
export function formatUptime(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return "—";
  const s = Math.floor(seconds);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  if (days > 0) return `${days}일 ${hours}시간`;
  if (hours > 0) return `${hours}시간 ${minutes}분`;
  if (minutes > 0) return `${minutes}분`;
  return `${s}초`;
}

export function formatPercent(
  value: number | null | undefined,
  digits = 1,
): string {
  if (value == null || Number.isNaN(value)) return "N/A";
  return `${value.toFixed(digits)}%`;
}

export function formatBytesMb(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "N/A";
  if (value >= 1024) return `${(value / 1024).toFixed(1)} GB`;
  // 1MB 미만을 0으로 반올림하면 실제 트래픽이 "0 MB"로 보인다 → KB로 표기
  if (value < 1) return `${Math.round(value * 1024)} KB`;
  return `${Math.round(value)} MB`;
}

export function formatCount(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "N/A";
  return value.toLocaleString("ko-KR");
}

/** 알 수 없는 값을 임의의 정상값으로 대체하지 않는다. */
export function display<T>(value: T | null | undefined, fallback = "—"): T | string {
  if (value === null || value === undefined || value === "") return fallback;
  return value;
}
