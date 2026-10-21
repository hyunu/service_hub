import * as React from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar, MobileSidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

/** 전역 레이아웃: 좌측 메뉴 + 상단바(상태/검색/알림/사용자) + 콘텐츠 */
export function AppLayout() {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const location = useLocation();

  // 경로 변경 시 스크롤 위치 초기화
  React.useEffect(() => {
    const el = document.getElementById("hub-main");
    if (el && typeof el.scrollTo === "function") el.scrollTo(0, 0);
  }, [location.pathname]);

  return (
    <div className="flex h-full min-h-0 w-full overflow-hidden">
      <Sidebar />
      <MobileSidebar open={menuOpen} onClose={() => setMenuOpen(false)} />
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
