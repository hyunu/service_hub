/** 사양 §11의 한국어 상태 라벨/뱃지 매핑 — 화면 공용 */

import type { BadgeProps } from "../components/ui/badge";

type BadgeVariant = NonNullable<BadgeProps["variant"]>;

/** 포트 상태 (사양 §11.6) */
export const PORT_STATE_LABEL: Record<string, string> = {
  reserved: "예약됨",
  in_use: "점유 중",
  available: "가용",
  conflict: "충돌",
  unmanaged: "미관리 점유",
  proxy: "프록시",
  internal: "내부 전용",
};

export const PORT_STATE_VARIANT: Record<string, BadgeVariant> = {
  reserved: "default",
  in_use: "ok",
  available: "unknown",
  conflict: "critical",
  unmanaged: "warn",
  proxy: "secondary",
  internal: "outline",
};

/** 노출 범위 */
export const EXPOSURE_LABEL: Record<string, string> = {
  public: "공개",
  proxy: "프록시",
  direct: "직접 노출",
  internal: "내부 전용",
  host: "호스트",
};

/** 이벤트 심각도 */
export const SEVERITY_LABEL: Record<string, string> = {
  info: "정보",
  warning: "주의",
  error: "오류",
  critical: "위험",
};

export const SEVERITY_VARIANT: Record<string, BadgeVariant> = {
  info: "unknown",
  warning: "warn",
  error: "critical",
  critical: "critical",
};

/** 배포 상태 (사양 §13.3) */
export const DEPLOYMENT_STATUS_LABEL: Record<string, string> = {
  queued: "대기",
  validating: "검증 중",
  running: "실행 중",
  verifying: "확인 중",
  succeeded: "성공",
  failed: "실패",
  cancelled: "취소됨",
};

export const DEPLOYMENT_STATUS_VARIANT: Record<string, BadgeVariant> = {
  queued: "unknown",
  validating: "warn",
  running: "default",
  verifying: "warn",
  succeeded: "ok",
  failed: "critical",
  cancelled: "secondary",
};

/** 컨테이너 관리 상태 (사양 §8.2) */
export const MANAGEMENT_LABEL: Record<string, string> = {
  managed: "관리됨",
  unmanaged: "미관리",
  mismatch: "구성 불일치",
  missing: "누락",
  unknown: "상태 불명",
};

export const MANAGEMENT_VARIANT: Record<string, BadgeVariant> = {
  managed: "ok",
  unmanaged: "warn",
  mismatch: "critical",
  missing: "critical",
  unknown: "unknown",
};

/** 미관리 컨테이너 검토 상태 */
export const REVIEW_LABEL: Record<string, string> = {
  pending: "검토 전",
  reviewing: "검토 중",
  accepted: "연결 승인",
  ignored: "무시함",
};

/** 컨테이너 실행 상태 → 표시용 */
export function containerStateLabel(state: string): string {
  switch (state) {
    case "running":
      return "실행 중";
    case "stopped":
    case "exited":
    case "created":
      return "중지";
    case "paused":
      return "일시 정지";
    case "restarting":
      return "재시작 중";
    case "dead":
      return "사망";
    default:
      return "상태 불명";
  }
}
