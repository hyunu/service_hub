import * as React from "react";
import { useNavigate } from "react-router-dom";
import {
  Bell,
  ChevronDown,
  LogOut,
  Menu,
  Moon,
  RefreshCw,
  Search,
  Sun,
} from "lucide-react";
import { fetchEvents, fetchStatus, search, type SearchResults, type SystemStatus } from "../../lib/api";
import { formatRelative } from "../../lib/format";
import { cn } from "../../lib/utils";
import { useAuth } from "../../context/AuthContext";
import { getTheme, applyTheme, type Theme } from "../../lib/theme";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { StatusDot, type StatusLevel } from "../StatusBadge";

/* ------------------------- 서버 상태 필 ------------------------- */

function statusLevel(status: SystemStatus | null): StatusLevel {
  if (!status) return "unknown";
  if (status.docker?.connected === false) return "critical";
  if (status.monitor?.running === false) return "critical";
  if (status.monitor?.consecutive_errors && status.monitor.consecutive_errors > 0) return "warn";
  if (status.stale) return "warn";
  return "ok";
}

const LEVEL_TEXT: Record<StatusLevel, string> = {
  ok: "모니터 정상",
  warn: "데이터 지연",
  critical: "모니터 중단",
  unknown: "상태 확인 중",
};

/** 서버 상태 필 + 마지막 갱신 시각(오래되면 강조) */
function StatusPill() {
  const [status, setStatus] = React.useState<SystemStatus | null>(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const s = await fetchStatus();
        if (alive) {
          setStatus(s);
          setFailed(false);
        }
      } catch {
        if (alive) setFailed(true);
      }
    };
    void load();
    const timer = setInterval(load, 15_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const level: StatusLevel = failed ? "critical" : statusLevel(status);
  const lastOk = status?.last_monitor_ok_at ?? status?.monitor?.last_ok_at ?? null;
  const stale = !lastOk || Date.now() - new Date(lastOk).getTime() > 60_000;

  return (
    <div className="flex items-center gap-2 text-xs">
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border px-2 py-1 font-medium",
          level === "ok" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
          level === "warn" && "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400",
          level === "critical" && "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400",
          level === "unknown" && "border-border bg-muted text-muted-foreground",
        )}
        title={failed ? "백엔드 /system/status 조회 실패" : undefined}
      >
        <StatusDot level={level} className="h-1.5 w-1.5" />
        {failed ? "연결 끊김" : LEVEL_TEXT[level]}
      </span>
      <span className={cn("hidden text-muted-foreground sm:inline", stale && "text-amber-600 dark:text-amber-400")}>
        마지막 갱신 {lastOk ? formatRelative(lastOk) : "—"}
      </span>
    </div>
  );
}

/* --------------------------- 글로벌 검색 --------------------------- */

function SearchBox({ className }: { className?: string }) {
  const navigate = useNavigate();
  const [q, setQ] = React.useState("");
  const [results, setResults] = React.useState<SearchResults | null>(null);
  const [open, setOpen] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const boxRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const term = q.trim();
    if (term.length < 1) {
      setResults(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const r = await search(term);
        setResults(r);
      } catch {
        setResults(null);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  React.useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const go = (route?: string) => {
    if (!route) return;
    setOpen(false);
    setQ("");
    setResults(null);
    navigate(route);
  };

  const goFirst = () => {
    const first = results?.groups[0]?.items[0];
    if (first) go(first.route);
  };

  return (
    <div ref={boxRef} className={cn("relative", className)}>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
      <Input
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter") goFirst();
          if (e.key === "Escape") setOpen(false);
        }}
        placeholder="서비스/컨테이너/포트/도메인/이미지 검색"
        aria-label="전역 검색"
        className="h-8 w-full pl-8 text-sm sm:w-72"
      />
      {open && q.trim() && (
        <div className="absolute left-0 top-full z-50 mt-1 w-full min-w-72 overflow-hidden rounded-md border border-border bg-popover shadow-lg">
          {loading && !results ? (
            <div className="px-3 py-3 text-xs text-muted-foreground">검색 중…</div>
          ) : results && results.total > 0 ? (
            <div className="max-h-96 overflow-y-auto py-1">
              {results.groups.map((g) => (
                <div key={g.key} className="px-1 pb-1">
                  <div className="px-2 pt-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {g.title}
                  </div>
                  {g.items.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onMouseDown={(e) => {
                        e.preventDefault();
                        go(item.route);
                      }}
                      className="flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
                    >
                      <span className="truncate">{item.label}</span>
                      {item.detail ? (
                        <span className="shrink-0 truncate text-xs text-muted-foreground">{item.detail}</span>
                      ) : null}
                    </button>
                  ))}
                </div>
              ))}
            </div>
          ) : (
            <div className="px-3 py-3 text-xs text-muted-foreground">일치하는 항목이 없습니다.</div>
          )}
        </div>
      )}
    </div>
  );
}

/* ----------------------------- 알림 ----------------------------- */

function NotificationBell() {
  const navigate = useNavigate();
  const [count, setCount] = React.useState(0);

  React.useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const events = await fetchEvents({ limit: 100 });
        if (!alive) return;
        const n = events.filter((e) => e.severity === "warning" || e.severity === "critical").length;
        setCount(n);
      } catch {
        /* 알림 조회 실패는 무시 (페이지 중단 금지) */
      }
    };
    void load();
    const timer = setInterval(load, 60_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  return (
    <button
      type="button"
      aria-label={`알림 ${count}건`}
      onClick={() => navigate("/events?severity=warning")}
      className="relative rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
    >
      <Bell className="h-4 w-4" />
      {count > 0 ? (
        <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-500 px-1 text-[10px] font-semibold text-black">
          {count > 99 ? "99+" : count}
        </span>
      ) : null}
    </button>
  );
}

/* --------------------------- 사용자 메뉴 --------------------------- */

function UserMenu() {
  const { session, logout } = useAuth();
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  const username = session?.user?.username ?? "사용자";

  React.useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary text-[11px] font-semibold text-secondary-foreground">
          {username.slice(0, 1).toUpperCase()}
        </span>
        <span className="hidden max-w-24 truncate sm:inline">{username}</span>
        <ChevronDown className="h-3.5 w-3.5" />
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1 w-48 rounded-md border border-border bg-popover py-1 shadow-lg"
        >
          <div className="border-b border-border px-3 py-2">
            <div className="truncate text-sm font-medium">{username}</div>
            <div className="text-xs text-muted-foreground">{session?.user?.role ?? "admin"}</div>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              void logout();
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <LogOut className="h-3.5 w-3.5" />
            로그아웃
          </button>
        </div>
      ) : null}
    </div>
  );
}

/* ----------------------------- 톱바 ----------------------------- */

export function Topbar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const [theme, setTheme] = React.useState<Theme>(() => getTheme());

  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
  };

  return (
    <header className="flex h-13 shrink-0 items-center gap-3 border-b border-border bg-card px-3 sm:px-4">
      <Button
        variant="ghost"
        size="icon"
        className="lg:hidden"
        onClick={onOpenMenu}
        aria-label="메뉴 열기"
      >
        <Menu className="h-4 w-4" />
      </Button>

      <StatusPill />

      <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
        <SearchBox className="hidden sm:block" />
        <Button
          variant="ghost"
          size="icon"
          onClick={() => window.location.reload()}
          aria-label="새로고침"
          title="페이지 새로고침"
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
        <NotificationBell />
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환"}
          title={theme === "dark" ? "라이트 모드" : "다크 모드"}
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
        <UserMenu />
      </div>
    </header>
  );
}

export { SearchBox };
