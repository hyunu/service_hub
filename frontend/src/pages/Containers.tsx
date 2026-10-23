import * as React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Boxes,
  ChevronDown,
  HardDrive,
  Link2,
  Play,
  RefreshCw,
  ScrollText,
  Square,
  Trash2,
  X,
} from "lucide-react";
import {
  attachOrphan,
  attachOrphans,
  containerAction,
  fetchContainer,
  fetchContainerResources,
  fetchContainers,
  fetchImages,
  fetchOrphans,
  fetchServices,
  isApiError,
  removeContainer,
  removeImage,
  reviewOrphan,
  type ContainerListItem,
  type ContainerResourceRow,
  type ContainerDetail,
  type ImageInfo,
  type ManagementState,
  type OrphanItem,
  type ServiceListItem,
} from "../lib/api";
import { containerStateLabel, MANAGEMENT_LABEL, MANAGEMENT_VARIANT, REVIEW_LABEL } from "../lib/labels";
import { formatBytesMb, formatDateTime, formatPercent, formatRelative } from "../lib/format";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../components/feedback";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Input, Label } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { StatusDot } from "../components/StatusBadge";

interface FilterChip {
  key: string;
  label: string;
  params: Record<string, string>;
}

const CHIPS: FilterChip[] = [
  { key: "all", label: "전체", params: {} },
  { key: "running", label: "실행 중", params: { state: "running" } },
  { key: "stopped", label: "중지", params: { state: "stopped" } },
  { key: "unmanaged", label: "미관리", params: { management: "unmanaged" } },
  { key: "mismatch", label: "구성 불일치", params: { management: "mismatch" } },
  { key: "missing", label: "누락", params: { management: "missing" } },
  { key: "unknown", label: "상태 불명", params: { management: "unknown" } },
];

/** 서비스 그룹 구분용 강조 색 — 서비스 ID 해시로 안정적으로 배정한다. */
const GROUP_ACCENTS = [
  { border: "border-l-sky-500", icon: "text-sky-600 dark:text-sky-400", tint: "bg-sky-500/5" },
  { border: "border-l-violet-500", icon: "text-violet-600 dark:text-violet-400", tint: "bg-violet-500/5" },
  { border: "border-l-emerald-500", icon: "text-emerald-600 dark:text-emerald-400", tint: "bg-emerald-500/5" },
  { border: "border-l-amber-500", icon: "text-amber-600 dark:text-amber-400", tint: "bg-amber-500/5" },
  { border: "border-l-rose-500", icon: "text-rose-600 dark:text-rose-400", tint: "bg-rose-500/5" },
  { border: "border-l-cyan-500", icon: "text-cyan-600 dark:text-cyan-400", tint: "bg-cyan-500/5" },
];

const UNGROUPED_ACCENT = {
  border: "border-l-slate-400 dark:border-l-slate-600",
  icon: "text-muted-foreground",
  tint: "bg-muted/20",
};

function accentFor(id: string | null) {
  if (!id) return UNGROUPED_ACCENT;
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) % 9973;
  return GROUP_ACCENTS[h % GROUP_ACCENTS.length];
}

function chipMatches(chip: FilterChip, params: URLSearchParams): boolean {
  return Object.entries(chip.params).every(([k, v]) => params.get(k) === v);
}

function stateLevel(state: string): "ok" | "warn" | "unknown" {
  if (state === "running") return "ok";
  if (state === "stopped" || state === "exited" || state === "created" || state === "paused") return "warn";
  return "unknown";
}

/* ------------------------------ 상세 드로어 ------------------------------ */

function DetailDrawer({
  containerId,
  onClose,
  actionsEnabled,
}: {
  containerId: string;
  onClose: () => void;
  actionsEnabled: boolean;
}) {
  const navigate = useNavigate();
  const [detail, setDetail] = React.useState<ContainerDetail | null>(null);
  const [orphan, setOrphan] = React.useState<OrphanItem | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [attachService, setAttachService] = React.useState("");
  const [attachComponent, setAttachComponent] = React.useState("");
  const [reviewState, setReviewState] = React.useState("reviewing");
  const [actionMsg, setActionMsg] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    setError(null);
    setActionMsg(null);
    try {
      const d = await fetchContainer(containerId);
      setDetail(d);
      if (d.management_state === "unmanaged") {
        const orphans = await fetchOrphans().catch(() => [] as OrphanItem[]);
        setOrphan(orphans.find((o) => o.id === d.id) ?? null);
      } else {
        setOrphan(null);
      }
    } catch (e) {
      setError(isApiError(e) ? e.message : "컨테이너 상세를 불러오지 못했습니다.");
    }
  }, [containerId]);

  React.useEffect(() => {
    setDetail(null);
    setOrphan(null);
    void load();
  }, [load]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const attach = async () => {
    if (!attachService.trim() || !attachComponent.trim()) {
      setActionMsg("서비스 ID와 컴포넌트 이름을 모두 입력하세요.");
      return;
    }
    setBusy(true);
    setActionMsg(null);
    try {
      await attachOrphan(containerId, {
        service_id: attachService.trim(),
        component_name: attachComponent.trim(),
      });
      await load();
      setActionMsg("연결했습니다. 실제 컨테이너는 재생성되지 않았습니다.");
    } catch (e) {
      setActionMsg(isApiError(e) ? e.message : "연결에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const review = async () => {
    setBusy(true);
    setActionMsg(null);
    try {
      await reviewOrphan(containerId, { review_state: reviewState });
      await load();
      setActionMsg(`검토 상태를 "${REVIEW_LABEL[reviewState] ?? reviewState}"(으)로 변경했습니다.`);
    } catch (e) {
      setActionMsg(isApiError(e) ? e.message : "검토 상태 변경에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const runAction = async (action: "start" | "stop") => {
    setBusy(true);
    setActionMsg(null);
    try {
      await containerAction(containerId, action);
      await load();
      // load()가 메시지를 초기화하므로 결과 표시는 반드시 load 이후에 한다.
      setActionMsg(action === "start" ? "컨테이너를 시작했습니다." : "컨테이너를 정지했습니다.");
    } catch (e) {
      setActionMsg(isApiError(e) ? e.message : "작업에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const removeCurrent = async () => {
    if (!detail) return;
    const typed = window.prompt(
      `컨테이너를 제거합니다. 계속하려면 이름을 정확히 입력하세요:\n${detail.name}`,
      "",
    );
    if (typed === null) return;
    setBusy(true);
    setActionMsg(null);
    try {
      await removeContainer(detail.id, typed);
      onClose();
    } catch (e) {
      setActionMsg(isApiError(e) ? e.message : "제거에 실패했습니다.");
      setBusy(false);
    }
  };

  const stats = detail?.stats ?? null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/55" onClick={onClose} aria-hidden="true" />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="컨테이너 상세"
        className="relative flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-border bg-card shadow-xl"
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-border bg-card px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <StatusDot level={stateLevel(detail?.state ?? "unknown")} />
              <h2 className="truncate text-sm font-semibold">{detail?.name ?? containerId}</h2>
              {detail ? (
                <Badge variant={MANAGEMENT_VARIANT[detail.management_state] ?? "unknown"}>
                  {MANAGEMENT_LABEL[detail.management_state] ?? detail.management_state}
                </Badge>
              ) : null}
            </div>
            <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
              {detail ? `${detail.image} · ${detail.id}` : "로딩 중…"}
            </p>
          </div>
          <div className="flex items-center gap-1">
            {detail?.service_id ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate(`/services/${detail.service_id}`)}
                title="연결된 서비스 보기"
              >
                서비스 보기
              </Button>
            ) : null}
            <Button variant="ghost" size="icon" onClick={onClose} aria-label="닫기">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="flex-1 space-y-4 px-4 py-4">
          {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
          {!detail && !error ? <LoadingState /> : null}

          {detail ? (
            <>
              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  컨테이너 작업
                </h3>
                <div className="rounded-md border border-border px-3 py-2.5">
                  {/* 보호 대상(허브 자신/보호 목록)은 서버가 actions_allowed=false 로 알려준다. */}
                  {(() => {
                    const canAct = detail.actions_allowed ?? actionsEnabled;
                    const blockedTitle = canAct
                      ? undefined
                      : detail.protected_reason ?? "HUB_ENABLE_DOCKER_ACTIONS=false";
                    return (
                      <>
                        <div className="flex flex-wrap gap-2">
                          {detail.state === "running" ? (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => void runAction("stop")}
                              disabled={!canAct || busy}
                              title={blockedTitle ?? "정지"}
                            >
                              <Square className="h-3.5 w-3.5" />
                              정지
                            </Button>
                          ) : (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => void runAction("start")}
                              disabled={!canAct || busy}
                              title={blockedTitle ?? "시작"}
                            >
                              <Play className="h-3.5 w-3.5" />
                              시작
                            </Button>
                          )}
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => void removeCurrent()}
                            disabled={!canAct || busy || detail.state === "running"}
                            title={
                              detail.state === "running" && canAct
                                ? "실행 중에는 제거할 수 없습니다. 먼저 정지하세요."
                                : blockedTitle ?? "제거"
                            }
                          >
                            <Trash2 className="h-3.5 w-3.5 text-destructive" />
                            제거
                          </Button>
                        </div>
                        {detail.protected_reason ? (
                          <p className="mt-2 text-[11px] leading-relaxed text-amber-600 dark:text-amber-400">
                            {detail.protected_reason}
                          </p>
                        ) : null}
                      </>
                    );
                  })()}
                  {actionMsg ? (
                    <p className="mt-2 text-xs" role="alert">{actionMsg}</p>
                  ) : null}
                  <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                    작업은 감사 로그에 기록됩니다. 허브 자신과 보호 대상
                    (HUB_PROTECTED_CONTAINERS/PROJECTS)은 조작할 수 없습니다.
                  </p>
                </div>
              </section>

              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  기본 정보
                </h3>
                <div className="divide-y divide-border rounded-md border border-border px-3">
                  <Row label="실행 상태" value={`${containerStateLabel(detail.state)} · ${detail.status}`} />
                  <Row label="헬스체크" value={detail.health ?? "N/A"} />
                  <Row label="서비스" value={detail.service_id ? `${detail.service_id} / ${detail.component_name ?? "—"}` : "미연결"} />
                  <Row label="Compose 프로젝트" value={detail.compose_project ?? "—"} />
                  <Row label="Compose 서비스" value={detail.compose_service ?? "—"} />
                  <Row label="생성 시각" value={`${formatDateTime(detail.created_at)} (${formatRelative(detail.created_at)})`} />
                  <Row label="시작 시각" value={formatDateTime(detail.started_at)} />
                  <Row label="재시작 횟수" value={String(detail.restart_count)} />
                  <Row label="마지막 관찰" value={formatDateTime(detail.observed_at)} />
                </div>
              </section>

              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  네트워크
                </h3>
                <div className="rounded-md border border-border px-3 py-2 text-sm">
                  {detail.networks.length === 0 ? (
                    <span className="text-xs text-muted-foreground">확인되지 않은 정보</span>
                  ) : (
                    <ul className="space-y-1">
                      {detail.networks.map((n, i) => {
                        const name = typeof n === "string" ? n : n.name;
                        const ip = typeof n === "string" ? null : (n.ip_address ?? null);
                        return (
                          <li key={i} className="flex items-center justify-between gap-2">
                            <span className="font-mono text-xs">{name}</span>
                            <span className="text-xs text-muted-foreground">{ip ?? "IP 미확인"}</span>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </section>

              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  포트 매핑
                </h3>
                <div className="rounded-md border border-border px-3 py-2 text-sm">
                  {detail.ports.length === 0 ? (
                    <span className="text-xs text-muted-foreground">호스트 포트 매핑 없음</span>
                  ) : (
                    <ul className="space-y-1">
                      {detail.ports.map((p, i) => (
                        <li key={i} className="flex items-center justify-between gap-2 font-mono text-xs">
                          <span>
                            {p.host_ip ?? "0.0.0.0"}:{p.host_port ?? "—"} → {p.container_port}/{p.protocol}
                          </span>
                          <button
                            type="button"
                            onClick={() => {
                              onClose();
                              navigate("/ports");
                            }}
                            className="text-primary hover:underline"
                          >
                            포트 레지스트리
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </section>

              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  볼륨/마운트
                </h3>
                <div className="rounded-md border border-border px-3 py-2 text-sm">
                  {detail.mounts.length === 0 ? (
                    <span className="text-xs text-muted-foreground">마운트 없음</span>
                  ) : (
                    <ul className="space-y-1.5">
                      {detail.mounts.map((m, i) => (
                        <li key={i} className="break-all font-mono text-xs">
                          <span className="text-muted-foreground">{m.type}</span> {m.source} → {m.target}
                          {m.mode ? <span className="text-muted-foreground"> ({m.mode})</span> : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </section>

              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  자원 사용량
                </h3>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  <Stat label="CPU" value={stats?.cpu_percent != null ? formatPercent(stats.cpu_percent) : "N/A"} />
                  <Stat label="메모리" value={stats?.mem_used_mb != null ? formatBytesMb(stats.mem_used_mb) : "N/A"} />
                  <Stat label="메모리 제한" value={stats?.mem_limit_mb != null ? formatBytesMb(stats.mem_limit_mb) : "N/A"} />
                  <Stat label="네트워크 수신" value={stats?.net_rx_bytes != null ? formatBytesMb(stats.net_rx_bytes / 1_048_576) : "N/A"} />
                  <Stat label="네트워크 송신" value={stats?.net_tx_bytes != null ? formatBytesMb(stats.net_tx_bytes / 1_048_576) : "N/A"} />
                  <Stat label="블록 I/O (읽기)" value={stats?.block_read_bytes != null ? formatBytesMb(stats.block_read_bytes / 1_048_576) : "N/A"} />
                </div>
              </section>

              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  레이블
                </h3>
                <div className="max-h-40 overflow-y-auto rounded-md border border-border px-3 py-2 font-mono text-[11px] leading-relaxed">
                  {Object.keys(detail.labels).length === 0 ? (
                    <span className="font-sans text-muted-foreground">레이블 없음</span>
                  ) : (
                    Object.entries(detail.labels).map(([k, v]) => (
                      <div key={k} className="break-all">
                        <span className="text-muted-foreground">{k}</span>={v}
                      </div>
                    ))
                  )}
                </div>
              </section>

              {/* 미관리 컨테이너 검토/연결 */}
              {detail.management_state === "unmanaged" ? (
                <section className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
                  <h3 className="mb-1 text-xs font-semibold text-amber-700 dark:text-amber-400">
                    미관리 컨테이너
                  </h3>
                  <p className="mb-2 text-xs leading-relaxed text-amber-700 dark:text-amber-400">
                    {orphan?.reason ?? "미관리로 판정되었습니다."}
                    {orphan?.suspected_service_name
                      ? ` · 추정 서비스: ${orphan.suspected_service_name}`
                      : ""}
                    <br />
                    연결해도 실제 컨테이너는 재생성되지 않습니다.
                  </p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div>
                      <Label htmlFor="orphan-svc">연결할 서비스 ID</Label>
                      <Input
                        id="orphan-svc"
                        value={attachService}
                        onChange={(e) => setAttachService(e.target.value)}
                        placeholder={orphan?.suspected_service_id ?? "service-id"}
                      />
                    </div>
                    <div>
                      <Label htmlFor="orphan-comp">컴포넌트 이름</Label>
                      <Input
                        id="orphan-comp"
                        value={attachComponent}
                        onChange={(e) => setAttachComponent(e.target.value)}
                        placeholder="frontend"
                      />
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Button size="sm" onClick={() => void attach()} disabled={busy}>
                      <Link2 className="h-3.5 w-3.5" />
                      서비스에 연결
                    </Button>
                    <div className="w-32">
                      <Select
                        value={reviewState}
                        onValueChange={setReviewState}
                        options={[
                          { value: "pending", label: REVIEW_LABEL.pending },
                          { value: "reviewing", label: REVIEW_LABEL.reviewing },
                          { value: "ignored", label: REVIEW_LABEL.ignored },
                        ]}
                        aria-label="검토 상태"
                      />
                    </div>
                    <Button size="sm" variant="outline" onClick={() => void review()} disabled={busy}>
                      검토 상태 지정
                    </Button>
                  </div>
                  {actionMsg ? (
                    <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">{actionMsg}</p>
                  ) : null}
                </section>
              ) : null}

              <section className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    navigate(
                      detail.service_id
                        ? `/services/${detail.service_id}?tab=logs`
                        : "/events",
                    )
                  }
                >
                  <ScrollText className="h-3.5 w-3.5" />
                  {detail.service_id ? "서비스 로그 보기" : "이벤트 보기"}
                </Button>
                <Button variant="outline" size="sm" onClick={() => void load()}>
                  <RefreshCw className="h-3.5 w-3.5" />
                  다시 조회
                </Button>
              </section>
            </>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5 text-sm">
      <span className="shrink-0 text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 break-all text-right">{value}</span>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border px-2.5 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="text-sm font-medium tabular-nums">{value}</div>
    </div>
  );
}

/* --------------------------------- 목록 --------------------------------- */

export default function Containers() {
  const [params, setParams] = useSearchParams();
  const [items, setItems] = React.useState<ContainerListItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [focus, setFocus] = React.useState<string | null>(params.get("focus"));

  // 수동 그룹핑(다중 선택 → 서비스 연결)
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [services, setServices] = React.useState<ServiceListItem[]>([]);
  const [bulkService, setBulkService] = React.useState("");
  const [bulkComponent, setBulkComponent] = React.useState("");
  const [bulkBusy, setBulkBusy] = React.useState(false);
  const [bulkMsg, setBulkMsg] = React.useState<{ ok: boolean; text: string } | null>(null);

  // 이미지 관리 (읽기 + 제거)
  const [images, setImages] = React.useState<ImageInfo[]>([]);
  const [actionsEnabled, setActionsEnabled] = React.useState(false);
  const [imageMsg, setImageMsg] = React.useState<string | null>(null);
  const [imageBusy, setImageBusy] = React.useState<string | null>(null);

  const state = params.get("state") ?? "";
  const management = params.get("management") ?? "";
  const statsSeq = React.useRef(0);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchContainers({
        state: (state || undefined) as "running" | "stopped" | "all" | undefined,
        management: (management || undefined) as ManagementState | undefined,
      });
      setItems(list);
      // 필터 변경 등으로 사라진 항목은 선택에서 제거
      setSelected((prev) => {
        const ids = new Set(list.map((c) => c.id));
        return new Set([...prev].filter((id) => ids.has(id)));
      });
    } catch (e) {
      setError(isApiError(e) ? e.message : "컨테이너 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }

    // CPU/메모리는 docker stats 수집에 ~2초 걸리므로 목록을 먼저 보여주고
    // 도착하는 대로 해당 컨테이너 행만 갱신한다 (실패해도 목록은 유지).
    const seq = ++statsSeq.current;
    void fetchContainerResources()
      .then((resources: ContainerResourceRow[]) => {
        if (seq !== statsSeq.current) return;
        const byId = new Map(resources.map((r) => [r.container_id, r]));
        setItems((prev) =>
          prev.map((c) => {
            const r = byId.get(c.id);
            return r ? { ...c, cpu_percent: r.cpu_percent, memory_mb: r.mem_used_mb } : c;
          }),
        );
      })
      .catch(() => {
        /* 자원 수집 실패는 목록 표시에 영향을 주지 않는다 (N/A 유지) */
      });
  }, [state, management]);

  React.useEffect(() => {
    void load();
  }, [load]);

  React.useEffect(() => {
    fetchServices().then(setServices).catch(() => setServices([]));
  }, []);

  const loadImages = React.useCallback(async () => {
    try {
      const res = await fetchImages();
      setImages(res.items);
      setActionsEnabled(res.actions_enabled);
    } catch {
      setImages([]);
      setActionsEnabled(false);
    }
  }, []);

  React.useEffect(() => {
    void loadImages();
  }, [loadImages]);

  const removeImageAction = async (img: ImageInfo) => {
    const label = img.tags[0] ?? img.short_id ?? img.id;
    const typed = window.prompt(
      `이미지를 제거합니다. 계속하려면 태그를 정확히 입력하세요:\n${label}`,
      "",
    );
    if (typed === null) return;
    setImageBusy(img.id);
    setImageMsg(null);
    try {
      await removeImage(img.id, typed);
      setImageMsg(`이미지 ${label}를 제거했습니다.`);
      await loadImages();
    } catch (e) {
      setImageMsg(isApiError(e) ? e.message : "이미지 제거에 실패했습니다.");
    } finally {
      setImageBusy(null);
    }
  };

  const canSelect = (c: ContainerListItem) =>
    c.management_state === "unmanaged" || c.management_state === "unknown";

  const selectableIds = items.filter(canSelect).map((c) => c.id);
  const allSelected =
    selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));

  const toggleSelect = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set(selectableIds));

  // 서비스에 연결된 컨테이너를 서비스 단위로 묶어서 표시한다.
  // 연결되지 않은 컨테이너(미관리/미연결)는 마지막 그룹으로 모은다.
  const groups = React.useMemo(() => {
    const byService = new Map<string, ContainerListItem[]>();
    const ungrouped: ContainerListItem[] = [];
    for (const c of items) {
      if (c.service_id) {
        const arr = byService.get(c.service_id) ?? [];
        arr.push(c);
        byService.set(c.service_id, arr);
      } else {
        ungrouped.push(c);
      }
    }
    const nameOf = (id: string) => services.find((s) => s.id === id)?.name ?? id;
    const out = [...byService.entries()]
      .sort((a, b) => nameOf(a[0]).localeCompare(nameOf(b[0]), "ko"))
      .map(([sid, cs]) => ({
        key: `svc:${sid}`,
        serviceId: sid as string | null,
        name: nameOf(sid),
        accent: accentFor(sid),
        // 이름이 ID의 슬러그와 같으면 ID를 중복 표시하지 않는다.
        showId: nameOf(sid).trim().toLowerCase().replace(/\s+/g, "-") !== sid,
        running: cs.filter((c) => c.state === "running").length,
        items: [...cs].sort((x, y) =>
          (x.component_name ?? x.name).localeCompare(y.component_name ?? y.name, "ko"),
        ),
      }));
    if (ungrouped.length > 0) {
      out.push({
        key: "ungrouped",
        serviceId: null,
        name: "서비스 미지정",
        accent: accentFor(null),
        showId: false,
        running: ungrouped.filter((c) => c.state === "running").length,
        items: [...ungrouped].sort((a, b) => a.name.localeCompare(b.name, "ko")),
      });
    }
    return out;
  }, [items, services]);

  const hasGroupedServices = groups.some((g) => g.serviceId !== null);

  // 그룹 접기/펼치기 — 그룹 키 기준으로 기억한다.
  const [collapsedGroups, setCollapsedGroups] = React.useState<Set<string>>(new Set());
  const toggleGroup = React.useCallback((key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);
  const allCollapsed =
    groups.length > 0 && groups.every((g) => collapsedGroups.has(g.key));
  const toggleAllGroups = () =>
    setCollapsedGroups(allCollapsed ? new Set() : new Set(groups.map((g) => g.key)));

  const attachSelected = async () => {
    if (!bulkService) {
      setBulkMsg({ ok: false, text: "연결할 서비스를 선택하세요." });
      return;
    }
    setBulkBusy(true);
    setBulkMsg(null);
    try {
      const res = await attachOrphans({
        service_id: bulkService,
        container_ids: Array.from(selected),
        component_name: bulkComponent.trim() || null,
      });
      const reasons = res.results
        .filter((r) => !r.ok)
        .map((r) => r.reason)
        .filter(Boolean)
        .slice(0, 2);
      setBulkMsg({
        ok: res.attached > 0,
        text:
          `${res.attached}개를 서비스 '${res.service_id}'에 연결했습니다.` +
          (res.skipped ? ` (${res.skipped}개 건너뜀: ${reasons.join(", ")})` : ""),
      });
      setSelected(new Set());
      setBulkComponent("");
      await load();
    } catch (e) {
      setBulkMsg({ ok: false, text: isApiError(e) ? e.message : "그룹핑에 실패했습니다." });
    } finally {
      setBulkBusy(false);
    }
  };

  const setChip = (chip: FilterChip) => {
    const next = new URLSearchParams();
    for (const [k, v] of Object.entries(chip.params)) next.set(k, v);
    if (focus) next.set("focus", focus);
    setParams(next);
  };

  return (
    <div>
      <PageHeader
        title="Containers"
        description="Docker 전체 컨테이너 조회 · 등록 정보와 실제 상태를 분리해서 표시합니다."
        actions={
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
            새로고침
          </Button>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {CHIPS.map((chip) => {
          const active = chipMatches(chip, params);
          return (
            <button
              key={chip.key}
              type="button"
              onClick={() => setChip(chip)}
              aria-pressed={active}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                active
                  ? "border-primary/50 bg-primary/15 text-foreground"
                  : "border-border text-muted-foreground hover:bg-accent hover:text-foreground"
              }`}
            >
              {chip.label}
            </button>
          );
        })}
        {state || management ? (
          <button
            type="button"
            onClick={() => setParams(new URLSearchParams())}
            className="px-2 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            필터 해제
          </button>
        ) : null}
        {hasGroupedServices ? (
          <button
            type="button"
            onClick={toggleAllGroups}
            className="rounded border border-border px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            {allCollapsed ? "모두 펼치기" : "모두 접기"}
          </button>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground">
          {items.length}개 · CPU/메모리는 docker stats 기준(새로고침 시 갱신, N/A=측정 불가)
        </span>
      </div>

      {selected.size > 0 ? (
        <div className="mb-3 flex flex-wrap items-end gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2">
          <div className="text-xs font-medium">선택 {selected.size}개</div>
          <div className="w-56">
            <Select
              value={bulkService}
              onValueChange={setBulkService}
              placeholder="서비스 선택"
              options={services.map((s) => ({ value: s.id, label: `${s.name} (${s.id})` }))}
              aria-label="연결할 서비스"
            />
          </div>
          <div className="w-48">
            <Input
              value={bulkComponent}
              onChange={(e) => setBulkComponent(e.target.value)}
              placeholder="컴포넌트 이름(선택)"
              aria-label="컴포넌트 이름"
              maxLength={120}
            />
          </div>
          <Button size="sm" onClick={() => void attachSelected()} disabled={!bulkService || bulkBusy}>
            <Link2 className="h-3.5 w-3.5" />
            {bulkBusy ? "연결 중…" : "서비스에 연결"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelected(new Set())}
            disabled={bulkBusy}
          >
            선택 해제
          </Button>
          <p className="w-full text-[11px] text-muted-foreground">
            선택한 컨테이너는 재시작되지 않습니다(DB 연결만). 컴포넌트 이름을 비우면 compose
            서비스명 기준으로 묶입니다.
          </p>
        </div>
      ) : null}

      {bulkMsg ? (
        <div
          className={`mb-3 rounded-md border px-3 py-2 text-xs ${
            bulkMsg.ok
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              : "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400"
          }`}
          role="alert"
        >
          {bulkMsg.text}
        </div>
      ) : null}

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      <Card>
        {loading ? (
          <LoadingState label="컨테이너를 불러오는 중…" />
        ) : items.length === 0 ? (
          <EmptyState message="조건에 맞는 컨테이너가 없습니다." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8">
                  <input
                    type="checkbox"
                    aria-label="미관리 컨테이너 전체 선택"
                    checked={allSelected}
                    onChange={toggleAll}
                    disabled={selectableIds.length === 0}
                    className="h-3.5 w-3.5 cursor-pointer accent-current"
                  />
                </TableHead>
                <TableHead>컨테이너</TableHead>
                <TableHead>이미지</TableHead>
                <TableHead>상태</TableHead>
                <TableHead>포트</TableHead>
                <TableHead>CPU</TableHead>
                <TableHead>메모리</TableHead>
                <TableHead>재시작</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {groups.map((g) => (
                <React.Fragment key={g.key}>
                  {hasGroupedServices ? (
                    <>
                      {g.key !== groups[0].key ? (
                        <TableRow aria-hidden="true" className="hover:bg-transparent">
                          <TableCell colSpan={8} className="h-3 border-0 p-0" />
                        </TableRow>
                      ) : null}
                      <TableRow className="hover:bg-transparent">
                        <TableCell
                          colSpan={8}
                          className={`border-l-4 ${g.accent.border} ${g.accent.tint} py-2`}
                        >
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => toggleGroup(g.key)}
                              aria-expanded={!collapsedGroups.has(g.key)}
                              aria-label={`${g.name} 그룹 ${collapsedGroups.has(g.key) ? "펼치기" : "접기"}`}
                              className="inline-flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-background/70"
                            >
                              <ChevronDown
                                className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${
                                  collapsedGroups.has(g.key) ? "-rotate-90" : ""
                                }`}
                              />
                              <Boxes className={`h-4 w-4 ${g.accent.icon}`} />
                              <span className="text-sm font-semibold">{g.name}</span>
                            </button>
                            {g.serviceId && g.showId ? (
                              <span className="font-mono text-[11px] text-muted-foreground">
                                · {g.serviceId}
                              </span>
                            ) : null}
                            <span
                              className="ml-auto inline-flex items-center gap-1.5"
                              title={`실행 중 ${g.running} / 전체 ${g.items.length}`}
                            >
                              <span
                                className={`h-1.5 w-1.5 rounded-full ${
                                  g.items.length > 0 && g.running === g.items.length
                                    ? "bg-emerald-500"
                                    : "bg-amber-500"
                                }`}
                              />
                              <span className="text-[11px] font-medium tabular-nums text-muted-foreground">
                                {g.running}/{g.items.length} 실행 중
                              </span>
                            </span>
                          </div>
                        </TableCell>
                      </TableRow>
                    </>
                  ) : null}
                  {(collapsedGroups.has(g.key) ? [] : g.items).map((c) => (
                    <TableRow
                      key={c.id}
                      className={`cursor-pointer ${
                        hasGroupedServices ? `${g.accent.tint} [&>td:first-child]:border-l-4 ${g.accent.border}` : ""
                      }`}
                      tabIndex={0}
                      role="button"
                      aria-label={`${c.name} 상세 보기`}
                      onClick={() => setFocus(c.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") setFocus(c.id);
                      }}
                    >
                      <TableCell className="w-8" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          aria-label={`${c.name} 선택`}
                          checked={selected.has(c.id)}
                          onChange={() => toggleSelect(c.id)}
                          disabled={!canSelect(c)}
                          title={canSelect(c) ? "선택해서 서비스로 그룹핑" : "이미 서비스에 연결됨"}
                          className="h-3.5 w-3.5 cursor-pointer accent-current disabled:cursor-not-allowed"
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="font-medium leading-tight">{c.name}</span>
                          {c.component_name ? (
                            <span className="rounded bg-muted px-1 py-0.5 text-[10px] font-medium text-muted-foreground">
                              {c.component_name}
                            </span>
                          ) : null}
                        </div>
                        <div className="font-mono text-[11px] text-muted-foreground">{c.id.slice(0, 12)}</div>
                      </TableCell>
                      <TableCell className="max-w-52">
                        <div className="truncate font-mono text-xs">{c.image}</div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="inline-flex items-center gap-1.5 text-xs">
                            <StatusDot level={stateLevel(c.state)} />
                            {containerStateLabel(c.state)}
                            {c.health ? ` · ${c.health}` : ""}
                          </span>
                          {/* 정상(managed)은 표시하지 않고, 검토가 필요한 예외만 배지로 노출한다. */}
                          {c.management_state !== "managed" ? (
                            <Badge variant={MANAGEMENT_VARIANT[c.management_state] ?? "unknown"}>
                              {MANAGEMENT_LABEL[c.management_state] ?? c.management_state}
                            </Badge>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs tabular-nums">
                        {c.ports.length === 0
                          ? "—"
                          : c.ports.map((p) => `${p.host_port ?? "—"}→${p.container_port}`).join(", ")}
                      </TableCell>
                      <TableCell className="tabular-nums">{formatPercent(c.cpu_percent)}</TableCell>
                      <TableCell className="tabular-nums">{formatBytesMb(c.memory_mb)}</TableCell>
                      <TableCell className="tabular-nums">{c.restart_count}</TableCell>
                    </TableRow>
                  ))}
                </React.Fragment>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <Card className="mt-4">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div>
            <div className="flex items-center gap-1.5 text-sm font-semibold">
              <HardDrive className="h-4 w-4" />
              Images
            </div>
            <div className="text-[11px] text-muted-foreground">
              사용 중인 이미지와 허브 이미지는 제거할 수 없습니다.
              {!actionsEnabled ? " · 조작 비활성화(HUB_ENABLE_DOCKER_ACTIONS=false)" : ""}
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={() => void loadImages()}>
            <RefreshCw className="h-3.5 w-3.5" />
            새로고침
          </Button>
        </div>
        {imageMsg ? (
          <p className="px-4 py-2 text-xs" role="alert">{imageMsg}</p>
        ) : null}
        {images.length === 0 ? (
          <EmptyState message="이미지가 없거나 조회할 수 없습니다." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>태그</TableHead>
                <TableHead>ID</TableHead>
                <TableHead className="w-28">크기</TableHead>
                <TableHead className="w-20">작업</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {images.map((img) => (
                <TableRow key={img.id}>
                  <TableCell className="font-mono text-xs">
                    {img.tags.length > 0 ? img.tags.join(", ") : "<none>"}
                  </TableCell>
                  <TableCell className="font-mono text-[11px] text-muted-foreground">
                    {(img.short_id ?? img.id).replace(/^sha256:/, "").slice(0, 12)}
                  </TableCell>
                  <TableCell className="tabular-nums text-xs">
                    {img.size_mb != null ? `${img.size_mb} MB` : "N/A"}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void removeImageAction(img)}
                      disabled={!actionsEnabled || imageBusy === img.id}
                      title={actionsEnabled ? "이미지 제거" : "HUB_ENABLE_DOCKER_ACTIONS=false"}
                      aria-label={`${img.tags[0] ?? img.id} 제거`}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      {focus ? (
        <DetailDrawer
          containerId={focus}
          actionsEnabled={actionsEnabled}
          onClose={() => {
            setFocus(null);
            const next = new URLSearchParams(params);
            next.delete("focus");
            setParams(next, { replace: true });
          }}
        />
      ) : null}
    </div>
  );
}
