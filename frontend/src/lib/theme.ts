const STORAGE_KEY = "hub-theme";

export type Theme = "dark" | "light";

export function getTheme(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch {
    /* localStorage 접근 불가 시 기본값 */
  }
  return "dark";
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.classList.toggle("light", theme === "light");
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* 저장 실패는 동작에 영향 없음 */
  }
}
