/**
 * 클립보드 복사 유틸.
 *
 * `navigator.clipboard`는 **보안 컨텍스트(HTTPS/localhost)** 에서만 동작하고,
 * 권한이 없으면 reject 된다. 또한 HTTP로 접속하면 아예 `undefined`다.
 * 그래서 실패 시 textarea + execCommand fallback 을 사용한다.
 */
export async function copyText(text: string): Promise<boolean> {
  if (!text) return false;

  // 1) 표준 API (HTTPS/localhost)
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* 아래 fallback 시도 */
  }

  // 2) 레거시 fallback — 비보안 컨텍스트에서도 동작
  try {
    const el = document.createElement("textarea");
    el.value = text;
    el.setAttribute("readonly", "");
    el.style.position = "fixed";
    el.style.top = "0";
    el.style.left = "0";
    el.style.opacity = "0";
    el.style.pointerEvents = "none";
    document.body.appendChild(el);
    const previous = document.activeElement as HTMLElement | null;
    el.select();
    el.setSelectionRange(0, el.value.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    previous?.focus?.();
    return ok;
  } catch {
    return false;
  }
}
