import * as React from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import {
  fetchEvents,
  fetchServices,
  isApiError,
  type HubEvent,
  type ServiceListItem,
} from "../lib/api";
import { SEVERITY_LABEL, SEVERITY_VARIANT } from "../lib/labels";
import { formatDateTime, formatRelative } from "../lib/format";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../components/feedback";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Select } from "../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";

const SEVERITY_OPTIONS = [
  { value: "", label: "심각도 전체" },
  { value: "critical", label: "위험 (CRITICAL)" },
  { value: "error", label: "오류 (ERROR)" },
  { value: "warning", label: "주의 (WARN)" },
  { value: "info", label: "정보 (INFO)" },
];

const PAGE_SIZES = [
  { value: "20", label: "20건" },
  { value: "50", label: "50건" },
  { value: "100", label: "100건" },
];

const FETCH_LIMIT = 500;

/** 이벤트 목록 (사양 §11.9) */
export default function Events() {
  const [params, setParams] = useSearchParams();
  const severity = params.get("severity") ?? "";
  const serviceId = params.get("service_id") ?? "";

  const [events, setEvents] = React.useState<HubEvent[]>([]);
  const [services, setServices] = React.useState<ServiceListItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [page, setPage] = React.useState(0);
  const [pageSize, setPageSize] = React.useState("20");

  React.useEffect(() => {
    let alive = true;
    fetchServices()
      .then((s) => alive && setServices(s))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchEvents({
        severity: severity || undefined,
        service_id: serviceId || undefined,
        limit: FETCH_LIMIT,
      });
      setEvents(list);
      setPage(0);
    } catch (e) {
      setError(isApiError(e) ? e.message : "이벤트를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [severity, serviceId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };

  const size = Number(pageSize);
  const pageCount = Math.max(1, Math.ceil(events.length / size));
  const safePage = Math.min(page, pageCount - 1);
  const visible = events.slice(safePage * size, safePage * size + size);

  return (
    <div>
      <PageHeader
        title="Events"
        description={`컨테이너/서비스/포트/배포/자원 이벤트 · 수집 ${events.length}건 (최근 ${FETCH_LIMIT}건 기준)`}
        actions={
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
            새로고침
          </Button>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-44">
          <Select
            value={severity}
            onValueChange={(v) => setParam("severity", v)}
            options={SEVERITY_OPTIONS}
            aria-label="심각도 필터"
          />
        </div>
        <div className="w-56">
          <Select
            value={serviceId}
            onValueChange={(v) => setParam("service_id", v)}
            placeholder="서비스 전체"
            options={services.map((s) => ({ value: s.id, label: s.name }))}
            aria-label="서비스 필터"
          />
        </div>
        {severity || serviceId ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setParams(new URLSearchParams())}
          >
            필터 해제
          </Button>
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted-foreground">페이지당</span>
          <div className="w-24">
            <Select value={pageSize} onValueChange={setPageSize} options={PAGE_SIZES} aria-label="페이지 크기" />
          </div>
        </div>
      </div>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      <Card>
        {loading ? (
          <LoadingState label="이벤트를 불러오는 중…" />
        ) : visible.length === 0 ? (
          <EmptyState message="조건에 맞는 이벤트가 없습니다." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-44">시각</TableHead>
                <TableHead className="w-24">심각도</TableHead>
                <TableHead className="w-44">종류</TableHead>
                <TableHead className="w-44">서비스</TableHead>
                <TableHead className="w-44">컨테이너</TableHead>
                <TableHead>내용</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="text-xs tabular-nums">
                    <div>{formatDateTime(e.ts)}</div>
                    <div className="text-[11px] text-muted-foreground">{formatRelative(e.ts)}</div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={SEVERITY_VARIANT[e.severity] ?? "unknown"}>
                      {SEVERITY_LABEL[e.severity] ?? e.severity}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{e.kind}</TableCell>
                  <TableCell className="text-xs">{e.service_id ?? "—"}</TableCell>
                  <TableCell className="truncate font-mono text-xs" title={e.container_id ?? undefined}>
                    {e.container_id ?? "—"}
                  </TableCell>
                  <TableCell className="text-sm">{e.message}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      {!loading && events.length > size ? (
        <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {safePage * size + 1}–{Math.min((safePage + 1) * size, events.length)} / {events.length}건
          </span>
          <div className="flex items-center gap-1.5">
            <Button
              variant="outline"
              size="sm"
              disabled={safePage === 0}
              onClick={() => setPage(safePage - 1)}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              이전
            </Button>
            <span className="tabular-nums">
              {safePage + 1} / {pageCount}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={safePage >= pageCount - 1}
              onClick={() => setPage(safePage + 1)}
            >
              다음
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
