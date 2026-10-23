import * as React from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  Copy,
  ExternalLink,
  GitBranch,
  HardDrive,
  Link2,
  Pencil,
  RefreshCw,
  Rocket,
  Trash2,
  Unlink,
} from "lucide-react";
import {
  deleteService,
  detachContainer,
  autoAttachService,
  fetchDeployments,
  fetchHostResources,
  fetchService,
  fetchServiceContainers,
  fetchServiceEvents,
  fetchServiceLogs,
  fetchServiceEndpoints,
  fetchServiceResources,
  isApiError,
  updateService,
  type Deployment,
  type HubEvent,
  type HostResources,
  type LogLine,
  type ServiceDetail as ServiceDetailData,
  type ServiceEndpoint,
  type ServiceResourceRow,
  type ContainerListItem,
} from "../lib/api";
import { formatDateTime, formatRelative, formatPercent, formatBytesMb } from "../lib/format";
import { EXPOSURE_LABEL, MANAGEMENT_LABEL, MANAGEMENT_VARIANT, SEVERITY_LABEL, SEVERITY_VARIANT, DEPLOYMENT_STATUS_LABEL, DEPLOYMENT_STATUS_VARIANT, containerStateLabel } from "../lib/labels";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../components/feedback";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { Dialog } from "../components/ui/dialog";
import { Input, Label, Textarea } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { StatusBadge, StatusDot } from "../components/StatusBadge";
import { LineChart } from "../components/LineChart";

/** 엔드포인트 접속 URL 계산 — 허브에 접속한 호스트를 기준으로 한다. */
function endpointAccessUrl(ep: ServiceEndpoint): string | null {
  const scheme = ep.type === "https" ? "https" : "http";
  if (ep.exposure === "proxy" && ep.hostname) return `${scheme}://${ep.hostname}`;
  if (ep.exposure === "host" && ep.host_port) {
    const host = typeof window !== "undefined" ? window.location.hostname : "localhost";
    return `${scheme}://${host}:${ep.host_port}`;
  }
  return null;
}

type TabKey = "overview" | "containers" | "endpoints" | "deployment" | "resources" | "logs" | "configuration" | "events";

const TAB_LABEL: Record<TabKey, string> = {
  overview: "Overview",
  containers: "Containers",
  endpoints: "Endpoints",
  deployment: "Deployment",
  resources: "Resources",
  logs: "Logs",
  configuration: "Configuration",
  events: "Events",
};

function kv(label: string, value: React.ReactNode) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5 text-sm">
      <span className="shrink-0 text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 break-all text-right">{value}</span>
    </div>
  );
}

/* --------------------------------- 페이지 --------------------------------- */

export default function ServiceDetail() {
  const { serviceId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const initialTab = (searchParams.get("tab") as TabKey | null) ?? "overview";
  const [tab, setTabState] = React.useState<TabKey>(
    (Object.keys(TAB_LABEL) as TabKey[]).includes(initialTab) ? initialTab : "overview",
  );

  const setTab = (k: TabKey) => {
    setTabState(k);
    const next = new URLSearchParams(searchParams);
    if (k === "overview") next.delete("tab");
    else next.set("tab", k);
    setSearchParams(next, { replace: true });
  };
  const [service, setService] = React.useState<ServiceDetailData | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [deleteMsg, setDeleteMsg] = React.useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await fetchService(serviceId);
      setService(s);
    } catch (e) {
      setError(isApiError(e) ? e.message : "서비스 정보를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [serviceId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const doDelete = async () => {
    setDeleteBusy(true);
    setDeleteMsg(null);
    try {
      const res = await deleteService(serviceId);
      const unchanged = res?.runtime_unchanged === true;
      navigate("/services", {
        replace: true,
        state: {
          notice: unchanged
            ? `"${serviceId}" 레지스트리 레코드를 삭제했습니다. 실행 중인 컨테이너/볼륨은 변경되지 않았습니다 (runtime_unchanged).`
            : `"${serviceId}" 레코드를 삭제했습니다.`,
        },
      });
    } catch (e) {
      setDeleteMsg(isApiError(e) ? e.message : "삭제에 실패했습니다.");
      setDeleteBusy(false);
    }
  };

  if (loading && !service) return <LoadingState label="서비스 정보를 불러오는 중…" />;
  if (error && !service) {
    return (
      <div>
        <ErrorState message={error} onRetry={() => void load()} />
        <button
          type="button"
          onClick={() => navigate("/services")}
          className="mt-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> 서비스 목록으로
        </button>
      </div>
    );
  }
  if (!service) return null;

  return (
    <div>
      <PageHeader
        title={service.name}
        description={service.description}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => navigate("/services")}>
              <ArrowLeft className="h-3.5 w-3.5" />
              목록
            </Button>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              <RefreshCw className="h-3.5 w-3.5" />
              새로고침
            </Button>
            <Button variant="destructive" size="sm" onClick={() => setDeleteOpen(true)}>
              <Trash2 className="h-3.5 w-3.5" />
              삭제
            </Button>
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <StatusBadge status={service.status} />
        <Badge variant="outline">{service.category}</Badge>
        <Badge variant="secondary" className="font-mono">
          {service.id}
        </Badge>
        {service.version ? <Badge variant="outline">v{service.version}</Badge> : null}
        <span className="text-xs text-muted-foreground">
          컨테이너 {service.containers.running}/{service.containers.total} 실행 ·
          {service.last_deployed_at
            ? ` 마지막 배포 ${formatRelative(service.last_deployed_at)}`
            : " 배포 이력 없음"}
        </span>
      </div>

      {error ? (
        <div className="mb-3">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
        <TabsList className="max-w-full overflow-x-auto">
          {(Object.keys(TAB_LABEL) as TabKey[]).map((k) => (
            <TabsTrigger key={k} value={k}>
              {TAB_LABEL[k]}
            </TabsTrigger>
          ))}
        </TabsList>

        {/* ---------------- Overview ---------------- */}
        <TabsContent value="overview">
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-3">
              <CardHeader className="pb-1">
                <CardTitle>접속 정보</CardTitle>
                <CardDescription>
                  등록된 엔드포인트의 접속 주소와 포트입니다. (주소는 현재 접속한 호스트 기준)
                </CardDescription>
              </CardHeader>
              <CardContent>
                {service.endpoints.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    등록된 엔드포인트가 없습니다. 서비스 정의에 endpoints 를 추가하세요.
                  </p>
                ) : (
                  <div className="divide-y divide-border">
                    {service.endpoints.map((ep) => {
                      const url = endpointAccessUrl(ep);
                      return (
                        <div
                          key={ep.name}
                          className="flex flex-wrap items-center justify-between gap-2 py-2"
                        >
                          <div className="min-w-0">
                            <div className="text-sm font-medium">{ep.name}</div>
                            <div className="text-[11px] text-muted-foreground">
                              {EXPOSURE_LABEL[ep.exposure] ?? ep.exposure} · {ep.type}
                              {ep.container ? ` · ${ep.container}:${ep.container_port ?? "—"}` : ""}
                            </div>
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            {url ? (
                              <>
                                <a
                                  href={url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="font-mono text-xs text-primary hover:underline"
                                >
                                  {url}
                                </a>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  aria-label={`${ep.name} 주소 복사`}
                                  onClick={() => void navigator.clipboard.writeText(url)}
                                >
                                  <Copy className="h-3.5 w-3.5" />
                                </Button>
                              </>
                            ) : (
                              <span className="font-mono text-xs text-muted-foreground">
                                내부 전용 ({ep.container ?? "—"}:{ep.container_port ?? "—"})
                              </span>
                            )}
                            {ep.host_port ? (
                              <Badge variant="outline">
                                포트 {ep.host_port} → {ep.container_port ?? "—"}
                              </Badge>
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader className="pb-1">
                <CardTitle>서비스 정보</CardTitle>
                <CardDescription>Service Registry에 저장된 관리 정보</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="mb-3 whitespace-pre-wrap text-sm leading-relaxed">
                  {service.description || "설명이 없습니다."}
                </p>
                <div className="divide-y divide-border border-t border-border">
                  {kv("카테고리", service.category)}
                  {kv("배포 유형", service.deployment_type ?? "—")}
                  {kv(
                    "배포 경로",
                    service.deployment_path ? (
                      <span className="font-mono text-xs">{service.deployment_path}</span>
                    ) : (
                      "—"
                    ),
                  )}
                  {kv(
                    "Compose 파일",
                    service.compose_file ? (
                      <span className="font-mono text-xs">{service.compose_file}</span>
                    ) : (
                      "—"
                    ),
                  )}
                  {kv(
                    "저장소",
                    service.repository_url ? (
                      <span className="inline-flex items-center gap-1 font-mono text-xs">
                        <GitBranch className="h-3 w-3" />
                        {service.repository_url}
                        {service.repository_branch ? ` (${service.repository_branch})` : ""}
                      </span>
                    ) : (
                      "—"
                    ),
                  )}
                  {kv("문서", service.documentation || "—")}
                  {kv(
                    "태그",
                    service.tags && service.tags.length ? (
                      <span className="inline-flex flex-wrap justify-end gap-1">
                        {service.tags.map((t) => (
                          <Badge key={t} variant="outline">
                            {t}
                          </Badge>
                        ))}
                      </span>
                    ) : (
                      "—"
                    ),
                  )}
                  {kv("마지막 배포", formatDateTime(service.last_deployed_at))}
                  {kv("마지막 헬스체크", formatDateTime(service.last_healthcheck_at))}
                  {kv("등록 시각", formatDateTime(service.created_at))}
                  {kv("수정 시각", formatDateTime(service.updated_at))}
                </div>
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card>
                <CardHeader className="pb-1">
                  <CardTitle>경고</CardTitle>
                </CardHeader>
                <CardContent>
                  {!service.warnings || service.warnings.length === 0 ? (
                    <p className="py-2 text-xs text-muted-foreground">현재 경고가 없습니다.</p>
                  ) : (
                    <ul className="space-y-2">
                      {service.warnings.map((w, i) => (
                        <li
                          key={i}
                          className={`rounded border px-2.5 py-2 text-xs ${
                            w.level === "critical"
                              ? "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400"
                              : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400"
                          }`}
                        >
                          {w.message}
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-1">
                  <CardTitle>컴포넌트</CardTitle>
                  <CardDescription>서비스를 구성하는 컴포넌트 {service.components.length}개</CardDescription>
                </CardHeader>
                <CardContent>
                  {service.components.length === 0 ? (
                    <p className="py-1 text-xs text-muted-foreground">
                      등록된 컴포넌트가 없습니다. 컨테이너가 없는 서비스도 허용됩니다.
                    </p>
                  ) : (
                    <ul className="divide-y divide-border">
                      {service.components.map((c) => (
                        <li key={c.name} className="flex items-center justify-between gap-2 py-2">
                          <div className="min-w-0">
                            <div className="text-sm font-medium">{c.name}</div>
                            <div className="truncate text-[11px] text-muted-foreground">
                              {c.role}
                              {c.description ? ` · ${c.description}` : ""}
                            </div>
                          </div>
                          <Badge variant={c.required ? "default" : "outline"}>
                            {c.required ? "필수" : "선택"}
                          </Badge>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>

              <ServiceGroupingCard serviceId={service.id} onChanged={() => void load()} />
            </div>
          </div>
        </TabsContent>

        {/* ---------------- Containers ---------------- */}
        <TabsContent value="containers">
          <ServiceContainers serviceId={service.id} />
        </TabsContent>

        {/* ---------------- Endpoints ---------------- */}
        <TabsContent value="endpoints">
          <ServiceEndpoints serviceId={service.id} />
        </TabsContent>

        {/* ---------------- Deployment ---------------- */}
        <TabsContent value="deployment">
          <ServiceDeployment serviceId={service.id} />
        </TabsContent>

        {/* ---------------- Resources ---------------- */}
        <TabsContent value="resources">
          <ServiceResources serviceId={service.id} />
        </TabsContent>

        {/* ---------------- Logs ---------------- */}
        <TabsContent value="logs">
          <ServiceLogsPanel serviceId={service.id} />
        </TabsContent>

        {/* ---------------- Configuration ---------------- */}
        <TabsContent value="configuration">
          <ConfigurationPanel service={service} onSaved={() => void load()} />
        </TabsContent>

        {/* ---------------- Events ---------------- */}
        <TabsContent value="events">
          <ServiceEvents serviceId={service.id} />
        </TabsContent>
      </Tabs>

      <Dialog
        open={deleteOpen}
        onClose={() => {
          setDeleteOpen(false);
          setDeleteMsg(null);
        }}
        title="서비스 삭제"
        description="Service Registry 레코드만 삭제합니다."
        footer={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteBusy}
            >
              취소
            </Button>
            <Button variant="destructive" size="sm" onClick={() => void doDelete()} disabled={deleteBusy}>
              {deleteBusy ? "삭제 중…" : "레지스트리 삭제"}
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm">
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-xs leading-relaxed text-amber-700 dark:text-amber-400">
            <strong className="font-semibold">실행 환경은 변경되지 않습니다.</strong>
            <ul className="mt-1.5 list-inside list-disc space-y-0.5">
              <li>실행 중인 컨테이너/볼륨/이미지/네트워크는 삭제되지 않습니다.</li>
              <li>삭제 대상은 서비스 등록 정보(DB 레코드)뿐입니다 (runtime_unchanged).</li>
              <li>포트 예약과 라우팅 정보는 별도로 확인이 필요합니다.</li>
            </ul>
          </div>
          <p className="text-xs text-muted-foreground">
            삭제하려면 서비스 ID <span className="font-mono font-medium">{service.id}</span> 를
            아래 버튼으로 확인합니다.
          </p>
          {deleteMsg ? <ErrorState message={deleteMsg} /> : null}
        </div>
      </Dialog>
    </div>
  );
}

/* ------------------------------ 탭 컨텐츠 ------------------------------ */

function ServiceGroupingCard({ serviceId, onChanged }: { serviceId: string; onChanged: () => void }) {
  const [project, setProject] = React.useState(serviceId);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState<{ ok: boolean; text: string } | null>(null);

  const run = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const res = await autoAttachService(serviceId, project.trim() || null);
      if (res.attached > 0) {
        setMsg({
          ok: true,
          text:
            `compose 프로젝트 '${res.compose_project}'에서 ${res.attached}개 컨테이너를 연결했습니다.` +
            (res.skipped ? ` (${res.skipped}개 건너뜀)` : ""),
        });
        onChanged();
      } else {
        setMsg({ ok: true, text: res.note ?? "연결할 컨테이너가 없습니다." });
      }
    } catch (e) {
      setMsg({ ok: false, text: isApiError(e) ? e.message : "자동 연결에 실패했습니다." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="inline-flex items-center gap-1.5">
          <Link2 className="h-4 w-4 text-primary" />
          compose 프로젝트 자동 연결
        </CardTitle>
        <CardDescription>
          같은 compose 프로젝트의 컨테이너를 compose 서비스명 기준 컴포넌트로 한 번에 묶습니다.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <Label htmlFor="auto-project">compose 프로젝트</Label>
            <Input
              id="auto-project"
              value={project}
              onChange={(e) => setProject(e.target.value)}
              placeholder={serviceId}
              maxLength={256}
            />
          </div>
          <Button size="sm" onClick={() => void run()} disabled={busy}>
            <Link2 className="h-3.5 w-3.5" />
            {busy ? "연결 중…" : "일괄 연결"}
          </Button>
        </div>
        {msg ? (
          <div
            className={`rounded-md border px-3 py-2 text-xs ${
              msg.ok
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400"
            }`}
            role="alert"
          >
            {msg.text}
          </div>
        ) : null}
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          비우면 서비스 ID(<span className="font-mono">{serviceId}</span>)를 사용합니다. 연결은 DB에만
          기록되며 컨테이너는 재시작되지 않습니다.
        </p>
      </CardContent>
    </Card>
  );
}

function ServiceContainers({ serviceId }: { serviceId: string }) {
  const [items, setItems] = React.useState<ContainerListItem[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [msg, setMsg] = React.useState<{ ok: boolean; text: string } | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setItems(await fetchServiceContainers(serviceId));
    } catch (e) {
      setError(isApiError(e) ? e.message : "조회 실패");
    }
  }, [serviceId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const detach = async (c: ContainerListItem) => {
    if (
      !window.confirm(
        `'${c.name}' 연결을 해제할까요? 컨테이너는 중지/재시작되지 않습니다.`,
      )
    ) {
      return;
    }
    setBusyId(c.id);
    setMsg(null);
    try {
      const r = await detachContainer(c.id);
      setMsg({ ok: true, text: r.note ?? "연결을 해제했습니다." });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: isApiError(e) ? e.message : "해제에 실패했습니다." });
    } finally {
      setBusyId(null);
    }
  };

  if (error) return <ErrorState message={error} />;
  if (!items) return <LoadingState />;

  return (
    <div className="space-y-2">
      {msg ? (
        <div
          className={`rounded-md border px-3 py-2 text-xs ${
            msg.ok
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              : "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400"
          }`}
          role="alert"
        >
          {msg.text}
        </div>
      ) : null}

      {items.length === 0 ? (
        <EmptyState message="이 서비스에 연결된 컨테이너가 없습니다. Containers 화면에서 여러 컨테이너를 선택해 그룹핑할 수 있습니다." />
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>컨테이너</TableHead>
                <TableHead>컴포넌트</TableHead>
                <TableHead>이미지</TableHead>
                <TableHead>상태</TableHead>
                <TableHead>관리 상태</TableHead>
                <TableHead>연결</TableHead>
                <TableHead>포트</TableHead>
                <TableHead>CPU</TableHead>
                <TableHead>메모리</TableHead>
                <TableHead>재시작</TableHead>
                <TableHead className="w-16" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-medium">{c.name}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{c.component_name ?? "—"}</TableCell>
                  <TableCell className="max-w-52 truncate font-mono text-xs">{c.image}</TableCell>
                  <TableCell>
                    <span className="inline-flex items-center gap-1.5 text-xs">
                      <StatusDot level={c.state === "running" ? "ok" : c.state === "unknown" ? "unknown" : "warn"} />
                      {containerStateLabel(c.state)}
                      {c.health ? ` (${c.health})` : ""}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge variant={MANAGEMENT_VARIANT[c.management_state] ?? "unknown"}>
                      {MANAGEMENT_LABEL[c.management_state] ?? c.management_state}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs">
                    <Badge variant={c.manual ? "default" : "outline"}>
                      {c.manual ? "수동" : "자동"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs tabular-nums">
                    {c.ports.length === 0
                      ? "—"
                      : c.ports.map((p) => `${p.host_port ?? "—"}→${p.container_port}`).join(", ")}
                  </TableCell>
                  <TableCell className="tabular-nums">{formatPercent(c.cpu_percent)}</TableCell>
                  <TableCell className="tabular-nums">{formatBytesMb(c.memory_mb)}</TableCell>
                  <TableCell className="tabular-nums">{c.restart_count}</TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void detach(c)}
                      disabled={busyId === c.id}
                      title="수동 그룹핑 해제 (컨테이너는 그대로)"
                      aria-label={`${c.name} 연결 해제`}
                    >
                      <Unlink className="h-3.5 w-3.5 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}

function ServiceEndpoints({ serviceId }: { serviceId: string }) {
  const [items, setItems] = React.useState<ServiceEndpoint[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    fetchServiceEndpoints(serviceId)
      .then((d) => alive && setItems(d))
      .catch((e) => alive && setError(isApiError(e) ? e.message : "조회 실패"));
    return () => {
      alive = false;
    };
  }, [serviceId]);

  if (error) return <ErrorState message={error} />;
  if (!items) return <LoadingState />;
  if (items.length === 0) {
    return <EmptyState message="등록된 엔드포인트가 없습니다." />;
  }

  return (
    <Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>이름</TableHead>
            <TableHead>유형</TableHead>
            <TableHead>노출 범위</TableHead>
            <TableHead>도메인</TableHead>
            <TableHead>컨테이너</TableHead>
            <TableHead>컨테이너 포트</TableHead>
            <TableHead>상태</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((ep) => (
            <TableRow key={ep.name}>
              <TableCell className="font-medium">{ep.name}</TableCell>
              <TableCell className="text-xs">{ep.type}</TableCell>
              <TableCell>
                <Badge variant={ep.exposure === "internal" ? "outline" : ep.exposure === "proxy" ? "default" : "secondary"}>
                  {EXPOSURE_LABEL[ep.exposure] ?? ep.exposure}
                </Badge>
              </TableCell>
              <TableCell className="font-mono text-xs">
                {ep.hostname ? (
                  <span className="inline-flex items-center gap-1">
                    <ExternalLink className="h-3 w-3" />
                    {ep.hostname}
                  </span>
                ) : (
                  "—"
                )}
              </TableCell>
              <TableCell className="text-xs">{ep.container ?? "—"}</TableCell>
              <TableCell className="tabular-nums">{ep.container_port ?? "—"}</TableCell>
              <TableCell>
                <Badge variant={ep.enabled === false ? "unknown" : "ok"}>
                  {ep.enabled === false ? "비활성" : "활성"}
                </Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

function ServiceDeployment({ serviceId }: { serviceId: string }) {
  const [items, setItems] = React.useState<Deployment[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    fetchDeployments({ service_id: serviceId })
      .then((d) => alive && setItems(d))
      .catch((e) => alive && setError(isApiError(e) ? e.message : "배포 이력을 불러오지 못했습니다."));
    return () => {
      alive = false;
    };
  }, [serviceId]);

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-xs text-amber-700 dark:text-amber-400">
        <Rocket className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <strong className="font-semibold">배포 비활성화됨 (Phase 1)</strong>
          <p className="mt-0.5">
            현재 빌드는 읽기 전용 단계이며 <span className="font-mono">HUB_ENABLE_DEPLOY=false</span>{" "}
            로 잠겨 있습니다. 배포 실행/재시작/삭제 API는 사용할 수 없습니다.
          </p>
        </div>
      </div>

      {error ? <ErrorState message={error} /> : null}
      {!items ? (
        <LoadingState label="배포 이력을 불러오는 중…" />
      ) : items.length === 0 ? (
        <EmptyState message="배포 이력이 없습니다." />
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>배포 ID</TableHead>
                <TableHead>결과</TableHead>
                <TableHead>시작</TableHead>
                <TableHead>완료</TableHead>
                <TableHead>요청자</TableHead>
                <TableHead>오류</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="font-mono text-xs">{d.id}</TableCell>
                  <TableCell>
                    <Badge variant={DEPLOYMENT_STATUS_VARIANT[d.status] ?? "unknown"}>
                      {DEPLOYMENT_STATUS_LABEL[d.status] ?? d.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs tabular-nums">{formatDateTime(d.started_at)}</TableCell>
                  <TableCell className="text-xs tabular-nums">{formatDateTime(d.finished_at)}</TableCell>
                  <TableCell className="text-xs">{d.requested_by}</TableCell>
                  <TableCell className="max-w-72 text-xs text-red-500">{d.error ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}

function ServiceResources({ serviceId }: { serviceId: string }) {
  const [host, setHost] = React.useState<HostResources | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [services, setServices] = React.useState<ServiceResourceRow[] | null>(null);

  React.useEffect(() => {
    let alive = true;
    Promise.all([
      fetchHostResources().catch(() => null),
      fetchServiceResources().catch(() => [] as ServiceResourceRow[]),
    ])
      .then(([h, s]) => {
        if (!alive) return;
        setHost(h);
        setServices(s);
      })
      .catch(() => {
        if (alive) setError("자원 데이터를 불러오지 못했습니다.");
      });
    return () => {
      alive = false;
    };
  }, []);

  const samples = host?.samples ?? [];
  const row = services?.find((s) => s.service_id === serviceId);

  if (error) return <ErrorState message={error} />;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="pb-1">
          <CardTitle>CPU 사용률 추이 (호스트 전체)</CardTitle>
          <CardDescription>자원 샘플 기준 · 최근 {samples.length}개</CardDescription>
        </CardHeader>
        <CardContent>
          {samples.length === 0 ? (
            <EmptyState message="샘플 데이터가 없습니다." className="py-6" />
          ) : (
            <LineChart
              points={samples.map((s) => ({ ts: s.ts, value: s.cpu_percent ?? null }))}
              unit="%"
              ariaLabel="서비스 CPU 사용률 추이"
              warnAt={80}
              criticalAt={95}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-1">
          <CardTitle>서비스 자원 집계</CardTitle>
          <CardDescription>호스트 전체와 정확히 일치하지 않을 수 있습니다.</CardDescription>
        </CardHeader>
        <CardContent>
          {!row ? (
            <EmptyState message="이 서비스의 자원 집계가 없습니다." className="py-6" />
          ) : (
            <div className="divide-y divide-border">
              {kv("CPU", formatPercent(row.cpu_percent))}
              {kv("메모리", formatBytesMb(row.memory_mb))}
              {kv("컨테이너", `${row.containers_running} / ${row.containers_total} 실행`)}
              {kv("재시작 횟수", row.restart_count ?? "—")}
              {kv(
                "상태",
                <StatusBadge status={row.status} />,
              )}
            </div>
          )}
          <div className="mt-3 flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <HardDrive className="h-3.5 w-3.5" />
            임계값 설정은 <span className="font-medium">Settings</span> 탭에서 변경할 수 있습니다.
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function ServiceLogsPanel({ serviceId }: { serviceId: string }) {
  const [tail, setTail] = React.useState("200");
  const [lines, setLines] = React.useState<LogLine[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchServiceLogs(serviceId, Number(tail));
      setLines(res.lines);
    } catch (e) {
      setError(isApiError(e) ? e.message : "로그를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [serviceId, tail]);

  React.useEffect(() => {
    void load();
  }, [load]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between pb-2">
        <div>
          <CardTitle>컨테이너 로그 (tail)</CardTitle>
          <CardDescription>최근 {tail}줄 · 로그 뷰는 읽기 전용</CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-28">
            <Select
              value={tail}
              onValueChange={setTail}
              options={[
                { value: "100", label: "100줄" },
                { value: "200", label: "200줄" },
                { value: "500", label: "500줄" },
                { value: "1000", label: "1000줄" },
              ]}
              aria-label="로그 줄 수"
            />
          </div>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
            새로고침
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
        {loading && !lines ? (
          <LoadingState />
        ) : !lines || lines.length === 0 ? (
          <EmptyState message="표시할 로그가 없습니다." />
        ) : (
          <div className="max-h-[28rem] overflow-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-xs leading-relaxed">
            {lines.map((l, i) => (
              <div key={i} className="flex gap-2">
                {l.ts ? (
                  <span className="shrink-0 text-muted-foreground">{formatDateTime(l.ts)}</span>
                ) : null}
                <span className={l.stream === "stderr" ? "text-red-500" : ""}>{l.message}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ConfigurationPanel({
  service,
  onSaved,
}: {
  service: ServiceDetailData;
  onSaved: () => void;
}) {
  const [description, setDescription] = React.useState(service.description);
  const [documentation, setDocumentation] = React.useState(service.documentation ?? "");
  const [tagsText, setTagsText] = React.useState((service.tags ?? []).join(", "));
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState<{ ok: boolean; text: string } | null>(null);

  React.useEffect(() => {
    setDescription(service.description);
    setDocumentation(service.documentation ?? "");
    setTagsText((service.tags ?? []).join(", "));
  }, [service]);

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await updateService(service.id, {
        description,
        documentation: documentation.trim() || null,
        tags: tagsText
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      });
      setMsg({ ok: true, text: "설정을 저장했습니다." });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: isApiError(e) ? e.message : "저장에 실패했습니다." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="max-w-2xl">
      <CardHeader className="pb-1">
        <CardTitle className="inline-flex items-center gap-1.5">
          <Pencil className="h-4 w-4" />
          설명/문서/태그 수정
        </CardTitle>
        <CardDescription>
          PATCH /services/{service.id} — 설명, 문서 위치, 태그를 수정합니다 (컨테이너는 변경되지 않음).
        </CardDescription>
      </CardHeader>
      <CardContent>
        {msg ? (
          <div className="mb-3">
            <ErrorState message={msg.text} onRetry={msg.ok ? undefined : () => setMsg(null)} />
          </div>
        ) : null}
        <div className="space-y-3">
          <div>
            <Label htmlFor="cfg-desc">설명</Label>
            <Textarea
              id="cfg-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={5}
              placeholder="서비스 목적, 주요 기능, 접속 방법, 데이터 저장 위치, 백업 방법 등"
            />
          </div>
          <div>
            <Label htmlFor="cfg-doc">문서 위치</Label>
            <Input
              id="cfg-doc"
              value={documentation}
              onChange={(e) => setDocumentation(e.target.value)}
              placeholder="/srv/services/.../README.md 또는 URL"
            />
          </div>
          <div>
            <Label htmlFor="cfg-tags">태그 (쉼표 구분)</Label>
            <Input
              id="cfg-tags"
              value={tagsText}
              onChange={(e) => setTagsText(e.target.value)}
              placeholder="핵심, 데이터베이스, 내부망"
            />
          </div>
          <div className="flex items-center justify-end gap-2 pt-1">
            <Button size="sm" onClick={() => void save()} disabled={busy}>
              {busy ? "저장 중…" : "저장"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ServiceEvents({ serviceId }: { serviceId: string }) {
  const [items, setItems] = React.useState<HubEvent[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    fetchServiceEvents(serviceId, 100)
      .then((d) => alive && setItems(d))
      .catch((e) => alive && setError(isApiError(e) ? e.message : "이벤트 조회 실패"));
    return () => {
      alive = false;
    };
  }, [serviceId]);

  if (error) return <ErrorState message={error} />;
  if (!items) return <LoadingState />;
  if (items.length === 0) return <EmptyState message="이 서비스의 이벤트가 없습니다." />;

  return (
    <Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-44">시각</TableHead>
            <TableHead className="w-20">심각도</TableHead>
            <TableHead className="w-40">종류</TableHead>
            <TableHead>내용</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((e) => (
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
              <TableCell className="text-sm">{e.message}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}
