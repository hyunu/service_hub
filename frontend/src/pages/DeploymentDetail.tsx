import * as React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Check, RefreshCw, Rocket, X } from "lucide-react";
import {
  fetchDeployment,
  fetchDeploymentLogs,
  isApiError,
  type Deployment,
  type LogLine,
} from "../lib/api";
import { DEPLOYMENT_STATUS_LABEL, DEPLOYMENT_STATUS_VARIANT } from "../lib/labels";
import { formatDateTime, formatRelative } from "../lib/format";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../components/feedback";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { StatusDot, normalizeStatus } from "../components/StatusBadge";

function stepDot(status: string): React.ReactNode {
  const level = normalizeStatus(status);
  if (status === "succeeded") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-500">
        <Check className="h-3 w-3" />
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-red-500/15 text-red-500">
        <X className="h-3 w-3" />
      </span>
    );
  }
  return (
    <span className="flex h-5 w-5 items-center justify-center">
      <StatusDot level={level} />
    </span>
  );
}

/** 배포 상세 — 단계별 진행 타임라인 (읽기 전용) */
export default function DeploymentDetail() {
  const { deploymentId = "" } = useParams();
  const navigate = useNavigate();
  const [deployment, setDeployment] = React.useState<Deployment | null>(null);
  const [logs, setLogs] = React.useState<LogLine[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [d, l] = await Promise.all([
        fetchDeployment(deploymentId),
        fetchDeploymentLogs(deploymentId).catch(() => ({ lines: [] as LogLine[] })),
      ]);
      setDeployment(d);
      setLogs(l.lines);
    } catch (e) {
      setError(isApiError(e) ? e.message : "배포 기록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [deploymentId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (loading && !deployment) return <LoadingState label="배포 기록을 불러오는 중…" />;
  if (error && !deployment) {
    return (
      <div>
        <ErrorState message={error} onRetry={() => void load()} />
        <Button
          variant="ghost"
          size="sm"
          className="mt-2"
          onClick={() => navigate("/deployments")}
        >
          <ArrowLeft className="h-3.5 w-3.5" /> 목록으로
        </Button>
      </div>
    );
  }
  if (!deployment) return null;

  const steps = deployment.steps ?? [];

  return (
    <div>
      <PageHeader
        title={deployment.id}
        description={`서비스 ${deployment.service_id} · 요청자 ${deployment.requested_by}`}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => navigate("/deployments")}>
              <ArrowLeft className="h-3.5 w-3.5" /> 목록
            </Button>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              <RefreshCw className="h-3.5 w-3.5" /> 새로고침
            </Button>
          </>
        }
      />

      <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-xs text-amber-700 dark:text-amber-400">
        <Rocket className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <strong className="font-semibold">배포 비활성화됨 (읽기 전용)</strong>
          <p className="mt-0.5">
            이 배포는 기록된 이력입니다. 재실행/롤백 API는 현재 빌드에서 제공되지 않습니다 (
            <span className="font-mono">HUB_ENABLE_DEPLOY=false</span>).
          </p>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Badge variant={DEPLOYMENT_STATUS_VARIANT[deployment.status] ?? "unknown"}>
          {DEPLOYMENT_STATUS_LABEL[deployment.status] ?? deployment.status}
        </Badge>
        <span className="text-xs text-muted-foreground">
          시작 {formatDateTime(deployment.started_at)} ({formatRelative(deployment.started_at)})
          {deployment.finished_at
            ? ` · 완료 ${formatDateTime(deployment.finished_at)}`
            : " · 완료되지 않음"}
        </span>
      </div>

      {deployment.error ? (
        <div className="mb-4">
          <ErrorState message={`배포 오류: ${deployment.error}`} />
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-1">
            <CardTitle>단계 진행</CardTitle>
            <CardDescription>deployment_steps 기록 (seq 순)</CardDescription>
          </CardHeader>
          <CardContent>
            {steps.length === 0 ? (
              <EmptyState message="단계 기록이 없습니다." className="py-6" />
            ) : (
              <ol className="relative ml-2.5 border-l border-border">
                {steps.map((s, i) => (
                  <li key={s.seq} className="relative pb-4 pl-6 last:pb-0">
                    <span className="absolute -left-[11px] top-0 flex h-5 w-5 items-center justify-center rounded-full border border-border bg-card">
                      {stepDot(s.status)}
                    </span>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">
                        {i + 1}. {s.name}
                      </span>
                      <Badge
                        variant={
                          s.status === "succeeded"
                            ? "ok"
                            : s.status === "failed"
                              ? "critical"
                              : s.status === "running"
                                ? "default"
                                : "unknown"
                        }
                      >
                        {DEPLOYMENT_STATUS_LABEL[s.status] ?? s.status}
                      </Badge>
                      {s.at ? (
                        <span className="text-[11px] text-muted-foreground">
                          {formatDateTime(s.at)}
                        </span>
                      ) : null}
                    </div>
                    {s.detail ? (
                      <p className="mt-0.5 text-xs text-muted-foreground">{s.detail}</p>
                    ) : null}
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-1">
            <CardTitle>배포 로그</CardTitle>
            <CardDescription>기록된 실행 로그 (읽기 전용)</CardDescription>
          </CardHeader>
          <CardContent>
            {!logs ? (
              <LoadingState />
            ) : logs.length === 0 ? (
              <EmptyState message="기록된 로그가 없습니다." className="py-6" />
            ) : (
              <div className="max-h-96 overflow-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-xs leading-relaxed">
                {logs.map((l, i) => (
                  <div key={i} className="flex gap-2">
                    <span className="shrink-0 text-muted-foreground">{formatDateTime(l.ts)}</span>
                    <span>{l.message}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
