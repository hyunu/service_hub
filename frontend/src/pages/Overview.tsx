import * as React from "react";
import { useNavigate } from "react-router-dom";
import { Cpu, HardDrive, MemoryStick, Clock, AlertTriangle, Server } from "lucide-react";
import {
  fetchHostResources,
  fetchOverview,
  fetchResourceWarnings,
  fetchServices,
  isApiError,
  type HostResources,
  type ResourceWarning,
  type ServiceListItem,
  type SystemOverview,
} from "../lib/api";
import { formatDateTime, formatRelative, formatUptime } from "../lib/format";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../components/feedback";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Gauge } from "../components/Gauge";
import { StatusBadge, StatusDot, type StatusLevel } from "../components/StatusBadge";

function StatCell({
  label,
  value,
  sub,
  level = "unknown",
  onClick,
}: {
  label: string;
  value: number | string;
  sub?: string;
  level?: StatusLevel;
  onClick?: () => void;
}) {
  return (
    <div
      className={`flex flex-col gap-0.5 px-4 py-3 ${onClick ? "cursor-pointer hover:bg-muted/50" : ""}`}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => e.key === "Enter" && onClick() : undefined}
    >
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <StatusDot level={level} />
        {label}
      </div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      {sub ? <div className="text-[11px] text-muted-foreground">{sub}</div> : null}
    </div>
  );
}

const SEVERITY_BADGE: Record<string, "ok" | "warn" | "critical" | "unknown"> = {
  info: "unknown",
  warning: "warn",
  error: "critical",
  critical: "critical",
};

/** 개요 대시보드 (사양 §11.2) */
export default function Overview() {
  const navigate = useNavigate();
  const [overview, setOverview] = React.useState<SystemOverview | null>(null);
  const [services, setServices] = React.useState<ServiceListItem[]>([]);
  const [warnings, setWarnings] = React.useState<ResourceWarning[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  // 호스트 자원은 별도로 1초 주기 갱신한다 (전체 개요 재조회는 하지 않음).
  const [host, setHost] = React.useState<HostResources | null>(null);
  const [hostError, setHostError] = React.useState<string | null>(null);
  const [hostUpdatedAt, setHostUpdatedAt] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const ov = await fetchOverview();
      setOverview(ov);
      const [svc, warn] = await Promise.all([
        fetchServices().catch(() => [] as ServiceListItem[]),
        fetchResourceWarnings().catch(() => [] as ResourceWarning[]),
      ]);
      setServices(svc);
      setWarnings(warn);
    } catch (e) {
      setError(isApiError(e) ? e.message : "개요 데이터를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  // 화면이 보이는 동안 1초마다 호스트 자원(CPU/메모리/디스크)만 갱신한다.
  // 탭이 숨겨지면 요청을 보내지 않고, 중복 요청도 막는다.
  React.useEffect(() => {
    let cancelled = false;
    let inFlight = false;

    const tick = async () => {
      if (cancelled || inFlight || document.hidden) return;
      inFlight = true;
      try {
        const h = await fetchHostResources();
        if (cancelled) return;
        setHost(h);
        setHostError(null);
        setHostUpdatedAt(new Date().toISOString());
      } catch (e) {
        if (!cancelled) {
          setHostError(isApiError(e) ? e.message : "호스트 자원 갱신에 실패했습니다.");
        }
      } finally {
        inFlight = false;
      }
    };

    void tick();
    const id = window.setInterval(() => void tick(), 1000);
    const onVisibility = () => {
      if (!document.hidden) void tick();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  if (loading && !overview) return <LoadingState label="시스템 상태를 불러오는 중…" />;
  if (error && !overview) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!overview) return <EmptyState message="표시할 데이터가 없습니다." />;

  const { server, docker, resources, counts, recent_events: recentEvents, last_monitor_ok_at } = overview;
  // 1초 폴링 결과가 있으면 그 값을, 없으면 개요 응답 값을 쓴다 (동일 스키마).
  const live = host ?? resources;
  const cpu = live.cpu;
  const mem = live.memory;
  const disk = live.disk;
  const topWarnings = warnings.slice(0, 5);

  return (
    <div>
      <PageHeader
        title="Overview"
        description={`${server.hostname} · ${server.os} · 커널 ${server.kernel}`}
        actions={
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            새로고침
          </button>
        }
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      {/* 카운트 */}
      <Card className="mb-4">
        <div className="grid grid-cols-2 divide-border sm:grid-cols-4 sm:divide-x">
          <StatCell
            label="등록 서비스"
            value={counts.services}
            level={services.some((s) => s.status === "critical") ? "critical" : "ok"}
            sub="Service Registry"
            onClick={() => navigate("/services")}
          />
          <StatCell
            label="실행 컨테이너"
            value={counts.containers_running}
            level="ok"
            sub={`전체 ${counts.containers_running + counts.containers_stopped}개`}
            onClick={() => navigate("/containers?state=running")}
          />
          <StatCell
            label="중지 컨테이너"
            value={counts.containers_stopped}
            level={counts.containers_stopped > 0 ? "warn" : "ok"}
            sub="stopped / exited"
            onClick={() => navigate("/containers?state=stopped")}
          />
          <StatCell
            label="미관리 컨테이너"
            value={counts.orphans}
            level={counts.orphans > 0 ? "warn" : "ok"}
            sub="미관리 컨테이너 검토 필요"
            onClick={() => navigate("/containers?management=unmanaged")}
          />
        </div>
      </Card>

      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        {/* 자원 게이지 */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-1">
            <CardTitle>호스트 자원</CardTitle>
            <CardDescription>
              1초마다 자동 갱신
              {hostUpdatedAt ? ` · 마지막 갱신 ${formatRelative(hostUpdatedAt)}` : ""}
              {" · "}모니터 수집 {last_monitor_ok_at ? formatRelative(last_monitor_ok_at) : "—"}
              {hostError ? ` · 갱신 실패: ${hostError}` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-start justify-around gap-4">
              <Gauge
                label="CPU"
                percent={cpu.percent}
                detail={cpu.cores != null ? `코어 ${cpu.cores}개` : "코어 수 확인 불가"}
                warn={80}
                critical={95}
              />
              <Gauge
                label="메모리"
                percent={mem.percent}
                detail={
                  mem.used_mb != null && mem.total_mb != null
                    ? `${(mem.used_mb / 1024).toFixed(1)} / ${(mem.total_mb / 1024).toFixed(1)} GB`
                    : "N/A"
                }
              />
              <Gauge
                label="디스크"
                percent={disk.percent}
                detail={
                  disk.used_gb != null && disk.total_gb != null
                    ? `${Math.round(disk.used_gb)} / ${Math.round(disk.total_gb)} GB`
                    : "N/A"
                }
              />
              <div className="min-w-44 space-y-2 text-xs">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <Clock className="h-3.5 w-3.5" /> 가동 시간
                  </span>
                  <span className="font-medium tabular-nums">{formatUptime(server.uptime_seconds)}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <Server className="h-3.5 w-3.5" /> Docker
                  </span>
                  <span className="font-medium">
                    {docker.connected
                      ? `연결됨${docker.server_version ? ` · ${docker.server_version}` : ""}`
                      : "연결 안 됨"}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <Cpu className="h-3.5 w-3.5" /> CPU 임계값
                  </span>
                  <span className="tabular-nums">80% / 95%</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <MemoryStick className="h-3.5 w-3.5" /> 메모리 임계값
                  </span>
                  <span className="tabular-nums">80% / 90%</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <HardDrive className="h-3.5 w-3.5" /> 디스크 임계값
                  </span>
                  <span className="tabular-nums">80% / 90%</span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* 주요 경고 */}
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="flex items-center gap-1.5">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              주요 경고
            </CardTitle>
            <CardDescription>자원 임계값 판정 결과</CardDescription>
          </CardHeader>
          <CardContent>
            {topWarnings.length === 0 ? (
              <EmptyState message="현재 경고가 없습니다." className="py-6" />
            ) : (
              <ul className="space-y-2">
                {topWarnings.map((w, i) => (
                  <li
                    key={i}
                    className={`flex items-start gap-2 rounded-md border px-2.5 py-2 text-xs ${
                      w.level === "critical"
                        ? "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400"
                        : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400"
                    }`}
                  >
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>{w.message}</span>
                  </li>
                ))}
              </ul>
            )}
            <button
              type="button"
              onClick={() => navigate("/resources")}
              className="mt-3 w-full rounded-md border border-border py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              자원 상세 보기
            </button>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 서비스별 상태 */}
        <Card>
          <CardHeader className="pb-1">
            <CardTitle>서비스별 상태</CardTitle>
            <CardDescription>등록 서비스 {services.length}개</CardDescription>
          </CardHeader>
          <CardContent>
            {services.length === 0 ? (
              <EmptyState message="등록된 서비스가 없습니다." className="py-6" />
            ) : (
              <ul className="divide-y divide-border">
                {services.map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      onClick={() => navigate(`/services/${s.id}`)}
                      className="flex w-full items-center justify-between gap-3 px-1 py-2 text-left hover:bg-muted/40"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">{s.name}</span>
                        <span className="block truncate text-[11px] text-muted-foreground">
                          {s.id} · 컨테이너 {s.containers.running}/{s.containers.total} 실행
                        </span>
                      </span>
                      <StatusBadge status={s.status} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        {/* 최근 이벤트 */}
        <Card>
          <CardHeader className="pb-1">
            <CardTitle>최근 이벤트</CardTitle>
            <CardDescription>
              {last_monitor_ok_at
                ? `마지막 갱신 ${formatRelative(last_monitor_ok_at)}`
                : "갱신 시각 확인 불가"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {recentEvents.length === 0 ? (
              <EmptyState message="최근 이벤트가 없습니다." className="py-6" />
            ) : (
              <ul className="divide-y divide-border">
                {recentEvents.map((ev) => (
                  <li key={ev.id} className="flex items-start gap-2 py-2">
                    <Badge variant={SEVERITY_BADGE[ev.severity] ?? "unknown"} className="mt-0.5 shrink-0">
                      {ev.severity}
                    </Badge>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm">{ev.message}</div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        {formatDateTime(ev.ts)} · {formatRelative(ev.ts)}
                        {ev.service_id ? ` · ${ev.service_id}` : ""}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <button
              type="button"
              onClick={() => navigate("/events")}
              className="mt-3 w-full rounded-md border border-border py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              전체 이벤트 보기
            </button>
          </CardContent>
        </Card>
      </div>

    </div>
  );
}
