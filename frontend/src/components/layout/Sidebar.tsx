import * as React from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Server, X } from "lucide-react";
import { cn } from "../../lib/utils";
import { NAV_ITEMS } from "./nav";

function NavList({ onNavigate, collapsed }: { onNavigate?: () => void; collapsed?: boolean }) {
  return (
    <nav className="flex flex-col gap-0.5 px-2">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          onClick={onNavigate}
          title={collapsed ? item.label : undefined}
          className={({ isActive }) =>
            cn(
              "group flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors",
              isActive
                ? "bg-primary/15 font-medium text-foreground"
                : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )
          }
        >
          <item.icon className="h-4 w-4 shrink-0" />
          {!collapsed ? <span className="truncate">{item.label}</span> : null}
        </NavLink>
      ))}
    </nav>
  );
}

function Brand({ compact }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2 px-4 py-3.5">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-primary text-primary-foreground">
        <Server className="h-4 w-4" />
      </span>
      {!compact ? (
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold leading-tight">N100 Service Hub</div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            server operations
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** 데스크톱 고정 사이드바 — ``collapsed`` 면 아이콘만 남는 좁은 폭으로 접힘 */
export function Sidebar({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <aside
      className={cn(
        "hidden shrink-0 flex-col border-r border-border bg-card lg:flex",
        "transition-[width] duration-200 ease-out",
        collapsed ? "w-14" : "w-60",
      )}
      aria-label="주 메뉴"
    >
      <Brand compact={collapsed} />
      <div className="flex-1 overflow-y-auto py-1">
        <NavList collapsed={collapsed} />
      </div>
      {!collapsed ? (
        <div className="border-t border-border px-4 py-3 text-[10px] leading-relaxed text-muted-foreground">
          내부망 전용 · Phase 1 (읽기 전용)
        </div>
      ) : (
        <div className="border-t border-border" />
      )}
    </aside>
  );
}

/** 태블릿/모바일용 드로어 사이드바 */
export function MobileSidebar({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const location = useLocation();
  React.useEffect(() => {
    if (open) onClose();
    // 라우트 변경 시 자동 닫기
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div className="absolute inset-0 bg-black/55" onClick={onClose} aria-hidden="true" />
      <div className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-border bg-card">
        <div className="flex items-center justify-between pr-2">
          <Brand />
          <button
            type="button"
            onClick={onClose}
            aria-label="메뉴 닫기"
            className="rounded p-1.5 text-muted-foreground hover:bg-accent"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          <NavList onNavigate={onClose} />
        </div>
      </div>
    </div>
  );
}
