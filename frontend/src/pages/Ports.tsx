import * as React from "react";
import { Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import {
  createReservation,
  deleteReservation,
  fetchAvailablePorts,
  fetchPorts,
  fetchServices,
  isApiError,
  type PortEntry,
  type ServiceListItem,
} from "../lib/api";
import { EXPOSURE_LABEL, PORT_STATE_LABEL, PORT_STATE_VARIANT } from "../lib/labels";
import { formatDateTime, formatRelative } from "../lib/format";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../components/feedback";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Dialog } from "../components/ui/dialog";
import { Input, Label } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Tooltip } from "../components/ui/tooltip";

const STATE_FILTERS = [
  { value: "", label: "전체" },
  { value: "conflict", label: "충돌" },
  { value: "reserved", label: "예약됨" },
  { value: "in_use", label: "점유 중" },
  { value: "unmanaged", label: "미관리 점유" },
  { value: "available", label: "가용" },
  { value: "proxy", label: "프록시" },
  { value: "internal", label: "내부 전용" },
];

/* ------------------------------ 포트 예약 다이얼로그 ------------------------------ */

interface ReserveForm {
  service_id: string;
  component: string;
  host_port: string;
  protocol: string;
  bind_addr: string;
  container_port: string;
  exposure: string;
}

const EMPTY_FORM: ReserveForm = {
  service_id: "",
  component: "",
  host_port: "",
  protocol: "tcp",
  bind_addr: "0.0.0.0",
  container_port: "",
  exposure: "internal",
};

function ReserveDialog({
  open,
  onClose,
  services,
  presetPort,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  services: ServiceListItem[];
  presetPort?: number | null;
  onCreated: () => void;
}) {
  const [form, setForm] = React.useState<ReserveForm>(EMPTY_FORM);
  const [error, setError] = React.useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setForm({ ...EMPTY_FORM, host_port: presetPort != null ? String(presetPort) : "" });
      setError(null);
      setFieldErrors({});
    }
  }, [open, presetPort]);

  const submit = async () => {
    const errs: Record<string, string> = {};
    const port = Number(form.host_port);
    if (!form.service_id) errs.service_id = "서비스를 선택하세요.";
    if (!form.component.trim()) errs.component = "컴포넌트 이름을 입력하세요.";
    if (!Number.isInteger(port) || port < 1 || port > 65535)
      errs.host_port = "호스트 포트는 1~65535 사이 정수여야 합니다.";
    if (form.container_port) {
      const cp = Number(form.container_port);
      if (!Number.isInteger(cp) || cp < 1 || cp > 65535)
        errs.container_port = "컨테이너 포트는 1~65535 사이 정수여야 합니다.";
    }
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) return;

    setBusy(true);
    setError(null);
    try {
      await createReservation({
        service_id: form.service_id,
        component: form.component.trim(),
        host_port: port,
        protocol: form.protocol as "tcp" | "udp",
        bind_addr: form.bind_addr,
        container_port: form.container_port ? Number(form.container_port) : null,
        exposure: form.exposure as "public" | "proxy" | "direct" | "internal" | "host",
      });
      onCreated();
      onClose();
    } catch (e) {
      if (isApiError(e)) {
        setError(
          e.status === 409
            ? `포트 충돌: ${e.message}`
            : e.message,
        );
        if (e.fieldErrors) setFieldErrors(e.fieldErrors);
      } else {
        setError("포트 예약에 실패했습니다.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="포트 예약"
      description="Port Registry에 예약을 기록합니다. 실제 바인딩은 배포 시 확인됩니다 (예약 성공 ≠ 바인딩 성공)."
      className="max-w-xl"
      footer={
        <>
          <Button variant="outline" size="sm" onClick={onClose} disabled={busy}>
            취소
          </Button>
          <Button size="sm" onClick={() => void submit()} disabled={busy}>
            {busy ? "예약 중…" : "예약"}
          </Button>
        </>
      }
    >
      {error ? (
        <div className="mb-3">
          <ErrorState message={error} />
        </div>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="res-svc" required>
            서비스
          </Label>
          <Select
            id="res-svc"
            value={form.service_id}
            onValueChange={(v) => setForm({ ...form, service_id: v })}
            placeholder="서비스 선택"
            options={services.map((s) => ({ value: s.id, label: `${s.name} (${s.id})` }))}
            aria-invalid={!!fieldErrors.service_id}
          />
          {fieldErrors.service_id ? (
            <p className="mt-1 text-xs text-destructive">{fieldErrors.service_id}</p>
          ) : null}
        </div>
        <div>
          <Label htmlFor="res-comp" required>
            구성요소
          </Label>
          <Input
            id="res-comp"
            value={form.component}
            onChange={(e) => setForm({ ...form, component: e.target.value })}
            placeholder="frontend"
            aria-invalid={!!fieldErrors.component}
          />
          {fieldErrors.component ? (
            <p className="mt-1 text-xs text-destructive">{fieldErrors.component}</p>
          ) : null}
        </div>
        <div>
          <Label htmlFor="res-port" required>
            호스트 포트
          </Label>
          <Input
            id="res-port"
            type="number"
            min={1}
            max={65535}
            value={form.host_port}
            onChange={(e) => setForm({ ...form, host_port: e.target.value })}
            placeholder="8080"
            aria-invalid={!!fieldErrors.host_port}
          />
          {fieldErrors.host_port ? (
            <p className="mt-1 text-xs text-destructive">{fieldErrors.host_port}</p>
          ) : null}
        </div>
        <div>
          <Label htmlFor="res-proto">프로토콜</Label>
          <Select
            id="res-proto"
            value={form.protocol}
            onValueChange={(v) => setForm({ ...form, protocol: v })}
            options={[
              { value: "tcp", label: "TCP" },
              { value: "udp", label: "UDP" },
            ]}
          />
        </div>
        <div>
          <Label htmlFor="res-bind">바인드 주소</Label>
          <Select
            id="res-bind"
            value={form.bind_addr}
            onValueChange={(v) => setForm({ ...form, bind_addr: v })}
            options={[
              { value: "0.0.0.0", label: "0.0.0.0 (전체)" },
              { value: "127.0.0.1", label: "127.0.0.1 (로컬만)" },
              { value: "::", label: ":: (IPv6 전체)" },
            ]}
          />
        </div>
        <div>
          <Label htmlFor="res-cport">컨테이너 포트</Label>
          <Input
            id="res-cport"
            type="number"
            min={1}
            max={65535}
            value={form.container_port}
            onChange={(e) => setForm({ ...form, container_port: e.target.value })}
            placeholder="3000"
            aria-invalid={!!fieldErrors.container_port}
          />
          {fieldErrors.container_port ? (
            <p className="mt-1 text-xs text-destructive">{fieldErrors.container_port}</p>
          ) : null}
        </div>
        <div className="sm:col-span-2">
          <Label htmlFor="res-exp">공개 범위</Label>
          <Select
            id="res-exp"
            value={form.exposure}
            onValueChange={(v) => setForm({ ...form, exposure: v })}
            options={[
              { value: "internal", label: "내부 전용 (Docker 내부 네트워크)" },
              { value: "proxy", label: "프록시 (리버스 프록시 경유)" },
              { value: "public", label: "공개 (호스트 직접 노출)" },
              { value: "host", label: "호스트 네트워크" },
            ]}
          />
        </div>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
        SSH(22)와 관리 포트(8420)는 자동 할당 대상에서 제외됩니다. 기존에 사용 중인 포트는 자동 변경되지
        않으며, 충돌 시 409 오류로 거부됩니다.
      </p>
    </Dialog>
  );
}

/* ------------------------------ 가용 포트 찾기 ------------------------------ */

function AvailableFinder({ onReserve }: { onReserve: (port: number) => void }) {
  const [count, setCount] = React.useState("5");
  const [range, setRange] = React.useState("8000-9000");
  const [protocol, setProtocol] = React.useState("tcp");
  const [ports, setPorts] = React.useState<number[] | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const find = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetchAvailablePorts({
        count: Number(count) || 5,
        range,
        protocol: protocol as "tcp" | "udp",
      });
      setPorts(res.ports);
    } catch (e) {
      setError(isApiError(e) ? e.message : "가용 포트 조회에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>가용 포트 찾기</CardTitle>
        <CardDescription>예약·실제 점유 상태를 모두 확인한 후보 포트를 조회합니다.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-24">
            <Label htmlFor="avail-count">개수</Label>
            <Input
              id="avail-count"
              type="number"
              min={1}
              max={50}
              value={count}
              onChange={(e) => setCount(e.target.value)}
              className="h-8"
            />
          </div>
          <div className="w-40">
            <Label htmlFor="avail-range">범위</Label>
            <Input
              id="avail-range"
              value={range}
              onChange={(e) => setRange(e.target.value)}
              placeholder="8000-9000"
              className="h-8 font-mono"
            />
          </div>
          <div className="w-28">
            <Label htmlFor="avail-proto">프로토콜</Label>
            <Select
              id="avail-proto"
              value={protocol}
              onValueChange={setProtocol}
              options={[
                { value: "tcp", label: "TCP" },
                { value: "udp", label: "UDP" },
              ]}
              className="h-8"
            />
          </div>
          <Button size="sm" onClick={() => void find()} disabled={busy}>
            <Search className="h-3.5 w-3.5" />
            {busy ? "조회 중…" : "조회"}
          </Button>
        </div>

        {error ? (
          <div className="mt-3">
            <ErrorState message={error} />
          </div>
        ) : null}

        {ports ? (
          ports.length === 0 ? (
            <p className="mt-3 text-xs text-muted-foreground">
              해당 범위에서 사용 가능한 포트를 찾지 못했습니다. 다른 범위를 시도하세요.
            </p>
          ) : (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {ports.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => onReserve(p)}
                  className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 font-mono text-xs font-medium text-emerald-600 hover:bg-emerald-500/20 dark:text-emerald-400"
                  title="클릭하여 예약"
                >
                  {p}
                  <span className="ml-1 font-sans text-[10px] font-normal">예약하기</span>
                </button>
              ))}
            </div>
          )
        ) : (
          <p className="mt-3 text-xs text-muted-foreground">범위를 지정해 조회하세요.</p>
        )}
      </CardContent>
    </Card>
  );
}

/* --------------------------------- 목록 --------------------------------- */

export default function Ports() {
  const [items, setItems] = React.useState<PortEntry[]>([]);
  const [services, setServices] = React.useState<ServiceListItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [stateFilter, setStateFilter] = React.useState("");
  const [reserveOpen, setReserveOpen] = React.useState(false);
  const [presetPort, setPresetPort] = React.useState<number | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ports, svc] = await Promise.all([
        fetchPorts(),
        fetchServices().catch(() => [] as ServiceListItem[]),
      ]);
      setItems(ports);
      setServices(svc);
    } catch (e) {
      setError(isApiError(e) ? e.message : "포트 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const removeReservation = async (id: string) => {
    setNotice(null);
    try {
      await deleteReservation(id);
      setNotice("예약을 삭제했습니다. 실제 점유는 컨테이너 실행 상태를 따릅니다.");
      await load();
    } catch (e) {
      setNotice(isApiError(e) ? e.message : "예약 삭제에 실패했습니다.");
    }
  };

  const filtered = stateFilter
    ? items.filter((i) => i.state === stateFilter)
    : items;

  const counts = React.useMemo(() => {
    const m = new Map<string, number>();
    for (const i of items) m.set(i.state, (m.get(i.state) ?? 0) + 1);
    return m;
  }, [items]);

  return (
    <div>
      <PageHeader
        title="Ports & Routing"
        description="포트 예약(등록)과 실제 점유 상태를 구분해서 표시합니다. 충돌은 빨간색으로 표시됩니다."
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              <RefreshCw className="h-3.5 w-3.5" />
              새로고침
            </Button>
            <Button
              size="sm"
              onClick={() => {
                setPresetPort(null);
                setReserveOpen(true);
              }}
            >
              <Plus className="h-3.5 w-3.5" />
              포트 예약
            </Button>
          </>
        }
      />

      {notice ? (
        <div className="mb-3">
          <div className="rounded-md border border-border bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
            {notice}
          </div>
        </div>
      ) : null}

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {STATE_FILTERS.map((f) => {
          const active = stateFilter === f.value;
          const n = f.value ? (counts.get(f.value) ?? 0) : items.length;
          return (
            <button
              key={f.value || "all"}
              type="button"
              onClick={() => setStateFilter(f.value)}
              aria-pressed={active}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                active
                  ? "border-primary/50 bg-primary/15 text-foreground"
                  : "border-border text-muted-foreground hover:bg-accent hover:text-foreground"
              }`}
            >
              {f.label}
              <span className="ml-1 text-[10px] opacity-70">{n}</span>
            </button>
          );
        })}
      </div>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      <Card className="mb-4">
        {loading ? (
          <LoadingState label="포트 레지스트리를 불러오는 중…" />
        ) : filtered.length === 0 ? (
          <EmptyState message="표시할 포트 항목이 없습니다." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-24">포트</TableHead>
                <TableHead className="w-20">프로토콜</TableHead>
                <TableHead className="w-28">바인드</TableHead>
                <TableHead>서비스</TableHead>
                <TableHead className="w-28">컴포넌트</TableHead>
                <TableHead className="w-28">컨테이너 포트</TableHead>
                <TableHead className="w-24">노출</TableHead>
                <TableHead className="w-28">상태</TableHead>
                <TableHead>실제 점유</TableHead>
                <TableHead className="w-40">마지막 확인</TableHead>
                <TableHead className="w-20" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((p, i) => {
                const key = `${p.protocol}-${p.bind_addr}-${p.host_port}-${i}`;
                return (
                  <TableRow key={key}>
                    <TableCell
                      className={`font-mono text-sm font-semibold tabular-nums ${
                        p.state === "conflict" ? "text-red-500" : ""
                      }`}
                    >
                      {p.host_port}
                    </TableCell>
                    <TableCell className="font-mono text-xs uppercase">{p.protocol}</TableCell>
                    <TableCell className="font-mono text-xs">{p.bind_addr}</TableCell>
                    <TableCell>
                      {p.service_id ? (
                        <div>
                          <div className="text-sm font-medium">{p.service_name ?? p.service_id}</div>
                          <div className="text-[11px] text-muted-foreground">{p.service_id}</div>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs">{p.component ?? "—"}</TableCell>
                    <TableCell className="font-mono text-xs tabular-nums">
                      {p.container_port ?? "—"}
                    </TableCell>
                    <TableCell>
                      {p.exposure ? (
                        <Badge variant={p.exposure === "internal" ? "outline" : "secondary"}>
                          {EXPOSURE_LABEL[p.exposure] ?? p.exposure}
                        </Badge>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell>
                      <Tooltip
                        content={
                          p.state === "conflict"
                            ? "예약/등록 정보와 실제 점유가 다릅니다. 확인이 필요합니다."
                            : p.state === "unmanaged"
                              ? "관리 시스템에 예약되지 않은 컨테이너가 사용 중입니다."
                              : p.state === "reserved"
                                ? "예약만 되어 있고 아직 실제 연결되지 않았습니다."
                                : p.state === "in_use"
                                  ? "예약과 실제 점유가 일치합니다."
                                  : PORT_STATE_LABEL[p.state] ?? String(p.state)
                        }
                      >
                        <Badge variant={PORT_STATE_VARIANT[p.state] ?? "unknown"}>
                          {p.state === "conflict" ? (
                            <span className="mr-0.5 inline-block h-1.5 w-1.5 rounded-full bg-red-500" />
                          ) : null}
                          {PORT_STATE_LABEL[p.state] ?? p.state}
                        </Badge>
                      </Tooltip>
                    </TableCell>
                    <TableCell className="text-xs">
                      {p.occupied ? (
                        <span className="text-muted-foreground">
                          {p.occupied_by ?? "점유됨"}
                          {p.proxy_connected ? " · 프록시 연결" : ""}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">미점유</span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs tabular-nums">
                      <div>{formatDateTime(p.last_checked_at)}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {formatRelative(p.last_checked_at)}
                      </div>
                    </TableCell>
                    <TableCell>
                      {p.reservation_id ? (
                        <Tooltip content="예약 삭제 (실제 컨테이너는 변경되지 않음)">
                          <button
                            type="button"
                            onClick={() => void removeReservation(p.reservation_id as string)}
                            aria-label={`${p.host_port} 예약 삭제`}
                            className="rounded p-1.5 text-muted-foreground hover:bg-red-500/10 hover:text-red-500"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </Tooltip>
                      ) : null}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Card>

      <AvailableFinder
        onReserve={(port) => {
          setPresetPort(port);
          setReserveOpen(true);
        }}
      />

      <ReserveDialog
        open={reserveOpen}
        onClose={() => setReserveOpen(false)}
        services={services}
        presetPort={presetPort}
        onCreated={() => void load()}
      />
    </div>
  );
}
