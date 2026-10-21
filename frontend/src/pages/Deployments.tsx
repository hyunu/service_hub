import * as React from "react";
import { useNavigate } from "react-router-dom";
import { RefreshCw, Rocket } from "lucide-react";
import { fetchDeployments, isApiError, type Deployment } from "../lib/api";
import { DEPLOYMENT_STATUS_LABEL, DEPLOYMENT_STATUS_VARIANT } from "../lib/labels";
import { formatDateTime, formatRelative } from "../lib/format";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../components/feedback";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";

/** 배포 목록 (Phase 1: 읽기 전용) */
export default function Deployments() {
  const navigate = useNavigate();
  const [items, setItems] = React.useState<Deployment[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

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

  return (
    <div>
      <PageHeader
        title="Deployments"
        description="배포 계획/실행 이력 · Phase 1에서는 조회만 가능합니다."
        actions={
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
            새로고침
          </Button>
        }
      />

      <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-xs text-amber-700 dark:text-amber-400">
        <Rocket className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <strong className="font-semibold">배포 비활성화됨</strong>
          <p className="mt-0.5">
            현재 빌드는 읽기 전용 단계이며 <span className="font-mono">HUB_ENABLE_DEPLOY=false</span> 로
            잠겨 있습니다. 새 배포 실행 API는 제공되지 않습니다.
          </p>
        </div>
      </div>

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
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
