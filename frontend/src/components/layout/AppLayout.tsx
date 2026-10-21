import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar, MobileSidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { cn } from "../../lib/utils";

const SIDEBAR_KEY = "hub.sidebar.collapsed";

/** 브라우저에 사이드바 접힘 상태를 유지한다 (없으면 펼침). */
function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_KEY) === "1";
  } catch {
    return false;
  }
}

/** 전역 레이아웃: 좌측 메뉴 + 상단바(상태/검색/알림/사용자) + 콘텐츠 */
export function AppLayout() {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [collapsed, setCollapsed] = React.useState<boolean>(readCollapsed);
  const location = useLocation();

  // 경로 변경 시 스크롤 위치 초기화
  React.useEffect(() => {
    const el = document.getElementById("hub-main");
    if (el && typeof el.scrollTo === "function") el.scrollTo(0, 0);
  }, [location.pathname]);

  const toggleSidebar = React.useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0");
      } catch {
        // localStorage 불가(프라이빗 모드 등) — 세션 동안만 유지
      }
      return next;
    });
  }, []);

  // 사이드바 오른쪽 경계(펼침 240px / 접힘 56px)에 걸치게, 세로 가운데에 둔다.
  const edgeLeft = collapsed ? 40 : 224;

  return (
    <div className="relative flex h-full min-h-0 w-full overflow-hidden">
      <Sidebar collapsed={collapsed} />
      <MobileSidebar open={menuOpen} onClose={() => setMenuOpen(false)} />

      {/* 화면 세로 중앙의 동그란 사이드바 토글 버튼 (데스크톱 전용) */}
      <button
        type="button"
        onClick={toggleSidebar}
        aria-label={collapsed ? "메뉴 펼치기" : "메뉴 접기"}
        aria-expanded={!collapsed}
        title={collapsed ? "메뉴 펼치기" : "메뉴 접기"}
        style={{ left: edgeLeft }}
        className={cn(
          "absolute top-1/2 z-30 hidden -translate-y-1/2 lg:flex",
          "h-8 w-8 items-center justify-center rounded-full",
          "border border-border bg-card text-muted-foreground shadow-md",
          "transition-[left] duration-200 ease-out hover:bg-accent hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
        )}
      >
        {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
      </button>

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenMenu={() => setMenuOpen(true)} />
        <main id="hub-main" className="min-h-0 flex-1 overflow-y-auto bg-background px-4 py-5 sm:px-6">
          <div className="mx-auto w-full max-w-7xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
