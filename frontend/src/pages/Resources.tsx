import * as React from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, RefreshCw, Settings2 } from "lucide-react";
import {
  fetchContainerResources,
  fetchHostResources,
  fetchResourceWarnings,
  fetchServiceResources,
  isApiError,
  type ContainerResourceRow,
  type HostResources,
  type ResourceWarning,
  type ServiceResourceRow,
} from "../lib/api";
import { formatBytesMb, formatDateTime, formatPercent, formatUptime } from "../lib/format";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../components/feedback";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { LineChart, Sparkline } from "../components/LineChart";
import { StatusBadge } from "../components/StatusBadge";

/** 자원 모니터링 (사양 §11.8) — 차트는 SVG로 직접 구현 (라이브러리 없음) */
export default function Resources() {
  const [host, setHost] = React.useState<HostResources | null>(null);
  const [containers, setContainers] = React.useState<ContainerResourceRow[]>([]);
  const [services, setServices] = React.useState<ServiceResourceRow[]>([]);
  const [warnings, setWarnings] = React.useState<ResourceWarning[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [h, c, s, w] = await Promise.all([
        fetchHostResources(),
        fetchContainerResources().catch(() => [] as ContainerResourceRow[]),
        fetchServiceResources().catch(() => [] as ServiceResourceRow[]),
        fetchResourceWarnings().catch(() => [] as ResourceWarning[]),
      ]);
      setHost(h);
      setContainers(c);
      setServices(s);
      setWarnings(w);
    } catch (e) {
      setError(isApiError(e) ? e.message : "자원 데이터를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (loading && !host) return <LoadingState label="자원 데이터를 불러오는 중…" />;
  if (error && !host) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!host) return <EmptyState message="자원 데이터가 없습니다." />;

  const samples = host.samples ?? [];
  const cpuSeries = samples.map((s) => ({ ts: s.ts, value: s.cpu_percent ?? null }));
  const memSeries = samples.map((s) => ({ ts: s.ts, value: s.mem_used_mb ?? null }));
  const diskSeries = samples.map((s) => ({ ts: s.ts, value: s.disk_used_gb ?? null }));
  const rxSeries = samples.map((s) => ({ ts: s.ts, value: s.net_rx_bytes ?? null }));
  const txSeries = samples.map((s) => ({ ts: s.ts, value: s.net_tx_bytes ?? null }));

  const memLimit = samples.find((s) => s.mem_limit_mb != null)?.mem_limit_mb ?? null;
  const thr = {
    memWarn: 80,
    memCrit: 90,
    cpuWarn: 80,
    cpuCrit: 95,
  };

  const topServices = [...services].sort((a, b) => (b.cpu_percent ?? -1) - (a.cpu_percent ?? -1));
  const topContainers = [...containers].sort((a, b) => (b.cpu_percent ?? -1) - (a.cpu_percent ?? -1));

  return (
    <div>
      <PageHeader
        title="Resources"
        description={
          host.collected_at
            ? `호스트/컨테이너 자원 · 수집 ${formatDateTime(host.collected_at)}`
            : "호스트/컨테이너 자원"
        }
        actions={
          <>
            <Link
              to="/settings"
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border px-3 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <Settings2 className="h-3.5 w-3.5" />
              임계값 설정
            </Link>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              <RefreshCw className="h-3.5 w-3.5" />
              새로고침
            </Button>
          </>
        }
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      {/* 경고 */}
      {warnings.length > 0 ? (
        <div className="mb-4 space-y-2">
          {warnings.map((w, i) => (
            <div
              key={i}
              className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${
                w.level === "critical"
                  ? "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400"
              }`}
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                {w.message}
                {w.value != null && w.threshold != null
                  ? ` (값 ${w.value} / 임계 ${w.threshold})`
                  : ""}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {/* 추이 차트 */}
      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-1">
            <CardTitle>CPU 사용률</CardTitle>
            <CardDescription>
              최근 {cpuSeries.length}샘플 · 주의 {thr.cpuWarn}% / 위험 {thr.cpuCrit}% (지속 시간 적용)
              {host.cpu.cores != null ? ` · 코어 ${host.cpu.cores}개` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <LineChart
              points={cpuSeries}
              ariaLabel="CPU 사용률 추이"
              unit="%"
              warnAt={thr.cpuWarn}
              criticalAt={thr.cpuCrit}
              color="stroke-blue-500"
              fill="fill-blue-500/10"
            />
            {host.cpu.per_core && host.cpu.per_core.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {host.cpu.per_core.map((v, i) => (
                  <Badge key={i} variant="outline" className="tabular-nums">
                    core {i}: {formatPercent(v, 0)}
                  </Badge>
                ))}
              </div>
            ) : null}
            {host.cpu.load_avg && host.cpu.load_avg.length > 0 ? (
              <div className="mt-1 text-[11px] text-muted-foreground">
                load avg: {host.cpu.load_avg.join(" / ")}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-1">
            <CardTitle>메모리 사용량</CardTitle>
            <CardDescription>
              {host.memory.used_mb != null && host.memory.total_mb != null
                ? `${(host.memory.used_mb / 1024).toFixed(1)} / ${(host.memory.total_mb / 1024).toFixed(1)} GB`
                : "N/A"}{" "}
              · 주의 {thr.memWarn}% / 위험 {thr.memCrit}%
              {host.memory.swap_total_mb != null
                ? ` · 스왑 ${host.memory.swap_used_mb ?? "?"} / ${host.memory.swap_total_mb} MB`
                : ""}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <LineChart
              points={memSeries}
              ariaLabel="메모리 사용량 추이"
              unit=" MB"
              warnAt={memLimit != null ? (memLimit * thr.memWarn) / 100 : null}
              criticalAt={memLimit != null ? (memLimit * thr.memCrit) / 100 : null}
              color="stroke-violet-500"
              fill="fill-violet-500/10"
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-1">
            <CardTitle>디스크 사용량</CardTitle>
            <CardDescription>
              {host.disk.used_gb != null && host.disk.total_gb != null
                ? `${Math.round(host.disk.used_gb)} / ${Math.round(host.disk.total_gb)} GB`
                : "N/A"}
              {host.disk.docker_data_gb != null
                ? ` · Docker 데이터 ${Math.round(host.disk.docker_data_gb)} GB`
                : ""}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <LineChart
              points={diskSeries}
              ariaLabel="디스크 사용량 추이"
              unit=" GB"
              warnAt={
                host.disk.total_gb != null ? (host.disk.total_gb * thr.memWarn) / 100 : null
              }
              criticalAt={
                host.disk.total_gb != null ? (host.disk.total_gb * thr.memCrit) / 100 : null
              }
              color="stroke-cyan-600"
              fill="fill-cyan-600/10"
            />
            {host.disk.filesystems && host.disk.filesystems.length > 0 ? (
              <div className="mt-2 space-y-1">
                {host.disk.filesystems.map((fs) => (
                  <div key={fs.mount} className="flex items-center justify-between text-xs">
                    <span className="font-mono">{fs.mount}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {fs.used_gb != null && fs.total_gb != null
                        ? `${Math.round(fs.used_gb)}/${Math.round(fs.total_gb)} GB`
                        : "N/A"}{" "}
                      · {formatPercent(fs.percent, 0)}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-1">
            <CardTitle>네트워크</CardTitle>
            <CardDescription>인터페이스별 수신/송신 추이 (누적 값은 인터페이스 표 참조)</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <div className="mb-1 text-[11px] font-medium text-muted-foreground">수신 (RX)</div>
              <LineChart
                points={rxSeries}
                height={80}
                ariaLabel="네트워크 수신 추이"
                color="stroke-emerald-500"
                fill="fill-emerald-500/10"
              />
            </div>
            <div>
              <div className="mb-1 text-[11px] font-medium text-muted-foreground">송신 (TX)</div>
              <LineChart
                points={txSeries}
                height={80}
                ariaLabel="네트워크 송신 추이"
                color="stroke-orange-500"
                fill="fill-orange-500/10"
              />
            </div>
            {host.network?.interfaces?.length ? (
              <div className="space-y-1 border-t border-border pt-2">
                {host.network.interfaces.map((iface) => (
                  <div
                    key={iface.name}
                    className="flex items-center justify-between gap-2 text-xs"
                  >
                    <span className="font-mono">{iface.name}</span>
                    <span className="tabular-nums text-muted-foreground">
                      RX {formatBytesMb((iface.rx_total_bytes ?? 0) / 1_048_576)} · TX{" "}
                      {formatBytesMb((iface.tx_total_bytes ?? 0) / 1_048_576)}
                      {iface.errors ? ` · 오류 ${iface.errors}` : ""}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      {/* 시스템 정보 + 스파크라인 */}
      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader className="pb-1">
            <CardTitle>시스템</CardTitle>
          </CardHeader>
          <CardContent>
            {host.system ? (
              <div className="divide-y divide-border text-sm">
                <InfoRow label="호스트명" value={host.system.hostname ?? "—"} />
                <InfoRow label="OS" value={host.system.os ?? "—"} />
                <InfoRow label="커널" value={host.system.kernel ?? "—"} />
                <InfoRow label="부팅 시각" value={formatDateTime(host.system.booted_at)} />
                <InfoRow label="가동 시간" value={formatUptime(host.system.uptime_seconds)} />
                <InfoRow
                  label="CPU 온도"
                  value={host.system.cpu_temp_c != null ? `${host.system.cpu_temp_c}°C` : "N/A"}
                />
              </div>
            ) : (
              <EmptyState message="시스템 정보 없음" className="py-4" />
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="pb-1">
            <CardTitle>최근 추이 (요약)</CardTitle>
            <CardDescription>자원 샘플에서 계산한 미니 차트</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-2">
              <SparkRow label="CPU" values={cpuSeries.map((p) => p.value)} suffix="%" />
              <SparkRow label="메모리" values={memSeries.map((p) => p.value)} suffix=" MB" />
              <SparkRow label="디스크" values={diskSeries.map((p) => p.value)} suffix=" GB" />
              <SparkRow label="네트워크 수신" values={rxSeries.map((p) => p.value)} suffix=" B" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 순위 표 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-1">
            <CardTitle>서비스별 자원</CardTitle>
            <CardDescription>
              집계값은 호스트 전체와 정확히 일치하지 않을 수 있습니다.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {topServices.length === 0 ? (
              <EmptyState message="집계된 서비스가 없습니다." className="py-6" />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>서비스</TableHead>
                    <TableHead>상태</TableHead>
                    <TableHead className="text-right">CPU</TableHead>
                    <TableHead className="text-right">메모리</TableHead>
                    <TableHead className="text-right">컨테이너</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {topServices.map((s) => (
                    <TableRow key={s.service_id}>
                      <TableCell>
                        <div className="text-sm font-medium">{s.name}</div>
                        <div className="text-[11px] text-muted-foreground">{s.service_id}</div>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={s.status} />
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatPercent(s.cpu_percent)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatBytesMb(s.memory_mb)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {s.containers_running}/{s.containers_total}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-1">
            <CardTitle>컨테이너별 자원 (상위)</CardTitle>
            <CardDescription>미지원 지표는 0이 아니라 N/A로 표시합니다.</CardDescription>
          </CardHeader>
          <CardContent>
            {topContainers.length === 0 ? (
              <EmptyState message="컨테이너 통계가 없습니다." className="py-6" />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>컨테이너</TableHead>
                    <TableHead className="text-right">CPU</TableHead>
                    <TableHead className="text-right">메모리</TableHead>
                    <TableHead className="text-right">재시작</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {topContainers.slice(0, 12).map((c) => (
                    <TableRow key={c.container_id}>
                      <TableCell>
                        <div className="text-sm font-medium">{c.name}</div>
                        <div className="text-[11px] text-muted-foreground">
                          {c.service_name ?? "미연결"}
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatPercent(c.cpu_percent)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatBytesMb(c.mem_used_mb)}
                        <span className="ml-1 text-[11px] text-muted-foreground">
                          / {c.mem_limit_mb != null ? formatBytesMb(c.mem_limit_mb) : "N/A"}
                        </span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {c.restart_count ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="truncate text-right text-sm">{value}</span>
    </div>
  );
}

function SparkRow({
  label,
  values,
  suffix,
}: {
  label: string;
  values: Array<number | null>;
  suffix: string;
}) {
  const nums = values.filter((v): v is number => v != null);
  const last = nums.length ? nums[nums.length - 1] : null;
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2">
      <div>
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="text-sm font-medium tabular-nums">
          {last != null ? `${last.toFixed(1)}${suffix}` : "N/A"}
        </div>
      </div>
      <Sparkline
        values={values}
        color={
          label === "CPU"
            ? "stroke-blue-500"
            : label === "메모리"
              ? "stroke-violet-500"
              : label === "디스크"
                ? "stroke-cyan-600"
                : "stroke-emerald-500"
        }
      />
    </div>
  );
}
