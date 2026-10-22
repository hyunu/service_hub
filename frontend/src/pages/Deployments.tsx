import * as React from "react";
import { useNavigate } from "react-router-dom";
import { RefreshCw, Rocket, RotateCcw, ShieldAlert } from "lucide-react";
import {
  fetchDeployments,
  getDeployPlan,
  applyDeploy,
  rollbackDeployment,
  isApiError,
  type Deployment,
  type DeployPlan,
} from "../lib/api";
import { DEPLOYMENT_STATUS_LABEL, DEPLOYMENT_STATUS_VARIANT } from "../lib/labels";
import { formatDateTime, formatRelative } from "../lib/format";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../components/feedback";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";

/** 배포 목록 + 계획 미리보기/실행 (Phase 3 — 서버 잠금 시 조회만 가능) */
export default function Deployments() {
  const navigate = useNavigate();
  const [items, setItems] = React.useState<Deployment[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const [specText, setSpecText] = React.useState("");
  const [plan, setPlan] = React.useState<DeployPlan | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [rollbackBusy, setRollbackBusy] = React.useState<string | null>(null);
  const [rollbackMsg, setRollbackMsg] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchDeployments();
      setItems(list);
    } catch (e) {
      setError(isApiError(e) ? e.message : "배포 이력을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const parseSpec = (): unknown | null => {
    try {
      return JSON.parse(specText) as unknown;
    } catch {
      setActionError("서비스 정의(JSON)를 해석할 수 없습니다.");
      return null;
    }
  };

  const onRollback = async (d: Deployment) => {
    if (
      !window.confirm(
        `배포 ${d.id} 시점의 정의 파일로 되돌려 재배포할까요?\n` +
          "컨테이너가 재생성될 수 있습니다. DB/볼륨은 자동 롤백되지 않습니다.",
      )
    ) {
      return;
    }
    setRollbackBusy(d.id);
    setRollbackMsg(null);
    try {
      const res = await rollbackDeployment(d.id);
      setRollbackMsg(
        `롤백 배포 ${res.deployment_id} — ${res.status}` +
          (res.error ? ` (${res.error})` : "") +
          ` · 복원 파일: ${res.restored_files.join(", ")}`,
      );
      await load();
    } catch (e) {
      setRollbackMsg(isApiError(e) ? e.message : "롤백에 실패했습니다.");
    } finally {
      setRollbackBusy(null);
    }
  };

  const onPreview = async () => {
    setActionError(null);
    setPlan(null);
    const spec = parseSpec();
    if (spec === null) return;
    setBusy(true);
    try {
      setPlan(await getDeployPlan(spec));
    } catch (e) {
      setActionError(isApiError(e) ? e.message : "계획 생성에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const onApply = async () => {
    setActionError(null);
    const spec = parseSpec();
    if (spec === null) return;
    setBusy(true);
    try {
      const res = await applyDeploy(spec);
      setActionError(
        res.error ? `배포 ${res.status}: ${res.error}` : `배포 ${res.status} (${res.deployment_id})`,
      );
      await load();
    } catch (e) {
      if (isApiError(e) && e.code === "deploy_disabled") {
        setActionError("배포 기능이 비활성화되어 있습니다 (HUB_ENABLE_DEPLOY=false).");
      } else {
        setActionError(isApiError(e) ? e.message : "배포 실행에 실패했습니다.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Deployments"
        description="배포 계획/실행 이력 · 계획 미리보기는 읽기 전용, 실행은 서버 잠금 해제 시에만 동작합니다."
        actions={
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
            새로고침
          </Button>
        }
      />

      {rollbackMsg ? (
        <div
          className="mb-4 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs"
          role="alert"
        >
          {rollbackMsg}
        </div>
      ) : null}

      <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-xs text-amber-700 dark:text-amber-400">
        <Rocket className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <strong className="font-semibold">배포는 기본 잠금 상태입니다</strong>
          <p className="mt-0.5">
            실행은 <span className="font-mono">HUB_ENABLE_DEPLOY=true</span>에서만 허용됩니다.
            잠겨 있으면 실행 요청은 <span className="font-mono">deploy_disabled</span>로 거부되며
            위험 작업은 승인과 감사 로그를 거칩니다.
          </p>
        </div>
      </div>

      <Card className="mb-4 p-4">
        <div className="mb-2 text-sm font-semibold">배포 계획 미리보기</div>
        <textarea
          className="h-32 w-full rounded-md border bg-background p-2 font-mono text-xs"
          placeholder="service.yaml 내용을 JSON으로 붙여넣으세요"
          aria-label="서비스 정의(JSON)"
          value={specText}
          onChange={(e) => setSpecText(e.target.value)}
        />
        <div className="mt-2 flex gap-2">
          <Button size="sm" variant="outline" onClick={() => void onPreview()} disabled={busy}>
            계획 미리보기
          </Button>
          <Button size="sm" onClick={() => void onApply()} disabled={busy}>
            <ShieldAlert className="h-3.5 w-3.5" />
            배포 실행
          </Button>
        </div>

        {actionError ? (
          <p className="mt-2 text-xs text-red-500" role="alert">{actionError}</p>
        ) : null}

        {plan ? (
          <div className="mt-3 rounded-md border p-3 text-xs">
            <div className="mb-1 font-semibold">
              {plan.service} · <span className="font-mono">{plan.result}</span>
            </div>
            <ul className="space-y-0.5">
              {plan.changes.map((c) => (
                <li key={c.name}>
                  <span className="font-mono">{c.name}</span>: {c.action}
                  {c.detail ? ` — ${c.detail}` : ""}
                </li>
              ))}
            </ul>
            <div className="mt-2">
              {plan.validation.map((v) => (
                <div key={v.check}>
                  {v.check}: <span className="font-mono">{v.result}</span>
                </div>
              ))}
            </div>
            {plan.impact.length > 0 ? (
              <ul className="mt-2 text-red-500">
                {plan.impact.map((i) => (
                  <li key={i.message}>{i.message}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </Card>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      <Card>
        {loading ? (
          <LoadingState label="배포 이력을 불러오는 중…" />
        ) : items.length === 0 ? (
          <EmptyState message="배포 이력이 없습니다." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-56">배포 ID</TableHead>
                <TableHead className="w-44">서비스</TableHead>
                <TableHead className="w-44">시작 / 완료</TableHead>
                <TableHead className="w-24">결과</TableHead>
                <TableHead>오류</TableHead>
                <TableHead className="w-48">요청자</TableHead>
                <TableHead className="w-24">작업</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((d) => (
                <TableRow
                  key={d.id}
                  className="cursor-pointer"
                  tabIndex={0}
                  role="link"
                  aria-label={`${d.id} 상세 보기`}
                  onClick={() => navigate(`/deployments/${d.id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") navigate(`/deployments/${d.id}`);
                  }}
                >
                  <TableCell className="font-mono text-xs">{d.id}</TableCell>
                  <TableCell className="text-sm font-medium">{d.service_id}</TableCell>
                  <TableCell className="text-xs tabular-nums">
                    <div>{formatDateTime(d.started_at)}</div>
                    <div className="text-[11px] text-muted-foreground">
                      {d.finished_at
                        ? `종료 ${formatDateTime(d.finished_at)}`
                        : `진행 중 · ${formatRelative(d.started_at)}`}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={DEPLOYMENT_STATUS_VARIANT[d.status] ?? "unknown"}>
                      {DEPLOYMENT_STATUS_LABEL[d.status] ?? d.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="max-w-80 text-xs text-red-500">{d.error ?? "—"}</TableCell>
                  <TableCell className="text-xs">{d.requested_by}</TableCell>
                  <TableCell>
                    {d.status === "succeeded" ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          void onRollback(d);
                        }}
                        disabled={rollbackBusy === d.id}
                        title="이 배포 시점으로 롤백"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        {rollbackBusy === d.id ? "롤백 중…" : "롤백"}
                      </Button>
                    ) : (
                      <span className="text-[11px] text-muted-foreground">—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
