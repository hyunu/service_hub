import * as React from "react";
import { useNavigate } from "react-router-dom";
import { ArrowDown, ArrowUp, ArrowUpDown, BookOpen, Plus, Search, X } from "lucide-react";
import {
  createService,
  fetchServices,
  isApiError,
  type ServiceListItem,
  type ServiceListQuery,
} from "../lib/api";
import { formatDateTime, formatPercent, formatBytesMb } from "../lib/format";
import { cn } from "../lib/utils";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../components/feedback";import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input, Label, Textarea } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { Dialog } from "../components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import { StatusBadge } from "../components/StatusBadge";
import { SpecGuideDialog } from "../components/SpecGuide";

const STATUS_OPTIONS = [
  { value: "", label: "상태 전체" },
  { value: "ok", label: "정상 (OK)" },
  { value: "warn", label: "주의 (WARN)" },
  { value: "critical", label: "위험 (CRITICAL)" },
  { value: "unknown", label: "상태 불명" },
];

const CATEGORY_OPTIONS = [
  { value: "", label: "카테고리 전체" },
  { value: "web", label: "web" },
  { value: "backend", label: "backend" },
  { value: "database", label: "database" },
  { value: "ai", label: "ai" },
  { value: "media", label: "media" },
  { value: "automation", label: "automation" },
  { value: "dev", label: "dev" },
  { value: "other", label: "other" },
];

type SortKey = "name" | "status" | "containers" | "cpu" | "memory" | "deployed";

function SortHeader({
  label,
  sortKey,
  current,
  dir,
  onSort,
  className,
}: {
  label: string;
  sortKey: SortKey;
  current: SortKey | null;
  dir: "asc" | "desc";
  onSort: (k: SortKey) => void;
  className?: string;
}) {
  const active = current === sortKey;
  return (
    <TableHead className={cn("cursor-pointer select-none hover:text-foreground", className)}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className="inline-flex items-center gap-1"
        aria-label={`${label} 정렬 변경`}
      >
        {label}
        {active ? (
          dir === "asc" ? (
            <ArrowUp className="h-3 w-3" />
          ) : (
            <ArrowDown className="h-3 w-3" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-40" />
        )}
      </button>
    </TableHead>
  );
}

/* ------------------------- 서비스 등록 다이얼로그 ------------------------- */

interface FormState {
  id: string;
  name: string;
  description: string;
  category: string;
  deployment_type: string;
  deployment_path: string;
  compose_file: string;
}

const EMPTY_FORM: FormState = {
  id: "",
  name: "",
  description: "",
  category: "web",
  deployment_type: "docker-compose",
  deployment_path: "",
  compose_file: "compose.yaml",
};

function RegisterDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [mode, setMode] = React.useState("form");
  const [form, setForm] = React.useState<FormState>(EMPTY_FORM);
  const [jsonText, setJsonText] = React.useState("");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  const reset = () => {
    setForm(EMPTY_FORM);
    setJsonText("");
    setFieldErrors({});
    setServerError(null);
  };

  const close = () => {
    reset();
    onClose();
  };

  const submitForm = async () => {
    const errs: Record<string, string> = {};
    if (!/^[a-z0-9][a-z0-9-]{1,62}$/.test(form.id.trim()))
      errs.id = "id는 영문 소문자/숫자/하이픈이어야 합니다 (예: ai-platform).";
    if (!form.name.trim()) errs.name = "서비스 이름을 입력하세요.";
    if (!form.description.trim()) errs.description = "설명을 입력하세요.";
    if (!form.deployment_path.trim()) errs.deployment_path = "배포 경로를 입력하세요.";
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) return;

    setSubmitting(true);
    setServerError(null);
    try {
      await createService({
        service: {
          id: form.id.trim(),
          name: form.name.trim(),
          description: form.description.trim(),
          category: form.category,
        },
        deployment: {
          type: form.deployment_type,
          deployment_path: form.deployment_path.trim(),
          compose_file: form.compose_file.trim() || "compose.yaml",
        },
      });
      reset();
      onCreated();
      onClose();
    } catch (e) {
      if (isApiError(e)) {
        setServerError(e.message);
        if (e.status === 422 && e.fieldErrors) setFieldErrors(e.fieldErrors);
      } else {
        setServerError("서비스 등록에 실패했습니다.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const submitJson = async () => {
    setServerError(null);
    setFieldErrors({});
    let parsed: unknown;
    try {
      parsed = JSON.parse(jsonText);
    } catch {
      setServerError("JSON 파싱에 실패했습니다. service.yaml 내용을 JSON으로 변환해 붙여넣으세요.");
      return;
    }
    if (!parsed || typeof parsed !== "object") {
      setServerError("객체 형태의 JSON이 필요합니다.");
      return;
    }
    setSubmitting(true);
    try {
      await createService(parsed as Record<string, unknown>);
      reset();
      onCreated();
      onClose();
    } catch (e) {
      setServerError(isApiError(e) ? e.message : "서비스 등록에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title="서비스 등록"
      description="service.yaml 기준으로 Service Registry에 등록합니다. 컨테이너는 생성되지 않습니다."
      className="max-w-2xl"
      footer={
        <>
          <Button variant="outline" size="sm" onClick={close} disabled={submitting}>
            취소
          </Button>
          <Button
            size="sm"
            onClick={() => (mode === "form" ? void submitForm() : void submitJson())}
            disabled={submitting}
          >
            {submitting ? "등록 중…" : "등록"}
          </Button>
        </>
      }
    >
      {serverError ? (
        <div className="mb-3">
          <ErrorState message={serverError} />
        </div>
      ) : null}

      <Tabs value={mode} onValueChange={setMode}>
        <TabsList>
          <TabsTrigger value="form">등록 폼</TabsTrigger>
          <TabsTrigger value="json">JSON 붙여넣기</TabsTrigger>
        </TabsList>

        <TabsContent value="form">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="svc-id" required>
                서비스 ID
              </Label>
              <Input
                id="svc-id"
                value={form.id}
                onChange={(e) => setForm({ ...form, id: e.target.value })}
                placeholder="ai-platform"
                aria-invalid={!!fieldErrors.id}
              />
              {fieldErrors.id ? <p className="mt-1 text-xs text-destructive">{fieldErrors.id}</p> : null}
            </div>
            <div>
              <Label htmlFor="svc-name" required>
                서비스 이름
              </Label>
              <Input
                id="svc-name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="AI Platform"
                aria-invalid={!!fieldErrors.name}
              />
              {fieldErrors.name ? (
                <p className="mt-1 text-xs text-destructive">{fieldErrors.name}</p>
              ) : null}
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="svc-desc" required>
                설명
              </Label>
              <Textarea
                id="svc-desc"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="서비스의 목적, 주요 기능, 접속 방법, 데이터 저장 위치 등"
                aria-invalid={!!fieldErrors.description}
              />
              {fieldErrors.description ? (
                <p className="mt-1 text-xs text-destructive">{fieldErrors.description}</p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="svc-category">카테고리</Label>
              <Select
                id="svc-category"
                value={form.category}
                onValueChange={(v) => setForm({ ...form, category: v })}
                options={CATEGORY_OPTIONS.filter((c) => c.value)}
              />
            </div>
            <div>
              <Label htmlFor="svc-type">배포 유형</Label>
              <Select
                id="svc-type"
                value={form.deployment_type}
                onValueChange={(v) => setForm({ ...form, deployment_type: v })}
                options={[
                  { value: "docker-compose", label: "docker-compose" },
                  { value: "manual", label: "manual" },
                ]}
              />
            </div>
            <div>
              <Label htmlFor="svc-path" required>
                배포 경로
              </Label>
              <Input
                id="svc-path"
                value={form.deployment_path}
                onChange={(e) => setForm({ ...form, deployment_path: e.target.value })}
                placeholder="/srv/services/my-app"
                aria-invalid={!!fieldErrors.deployment_path}
              />
              {fieldErrors.deployment_path ? (
                <p className="mt-1 text-xs text-destructive">{fieldErrors.deployment_path}</p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="svc-compose">Compose 파일</Label>
              <Input
                id="svc-compose"
                value={form.compose_file}
                onChange={(e) => setForm({ ...form, compose_file: e.target.value })}
                placeholder="compose.yaml"
              />
            </div>
          </div>
        </TabsContent>

        <TabsContent value="json">
          <div>
            <Label htmlFor="svc-json">service.yaml 내용 (JSON)</Label>
            <Textarea
              id="svc-json"
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
              rows={12}
              spellCheck={false}
              className="font-mono text-xs"
              placeholder={'{\n  "service": {\n    "id": "sample-app",\n    "name": "Sample Application",\n    "description": "샘플 웹 애플리케이션",\n    "category": "web"\n  },\n  "deployment": {\n    "type": "docker-compose",\n    "compose_file": "compose.yaml"\n  }\n}'}
            />
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              service.yaml을 JSON으로 변환해 붙여넣습니다. 시크릿 값(비밀번호/토큰/키)은 포함하지 마세요.
            </p>
          </div>
        </TabsContent>
      </Tabs>
    </Dialog>
  );
}

/* ------------------------------ 목록 페이지 ------------------------------ */

export default function Services() {
  const navigate = useNavigate();
  const [items, setItems] = React.useState<ServiceListItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [searchInput, setSearchInput] = React.useState("");
  const [query, setQuery] = React.useState<ServiceListQuery>({});
  const [sortKey, setSortKey] = React.useState<SortKey | null>(null);
  const [sortDir, setSortDir] = React.useState<"asc" | "desc">("asc");
  const [registerOpen, setRegisterOpen] = React.useState(false);
  const [guideOpen, setGuideOpen] = React.useState(false);

  // 검색어 디바운스 → API 조회
  React.useEffect(() => {
    const t = setTimeout(() => {
      setQuery((q) => (q.search === searchInput ? q : { ...q, search: searchInput }));
    }, 250);
    return () => clearTimeout(t);
  }, [searchInput]);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchServices(query);
      setItems(list);
    } catch (e) {
      setError(isApiError(e) ? e.message : "서비스 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [query]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const onSort = (k: SortKey) => {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir(k === "name" ? "asc" : "desc");
    }
  };

  const sorted = React.useMemo(() => {
    if (!sortKey) return items;
    const mul = sortDir === "asc" ? 1 : -1;
    const val = (s: ServiceListItem): number | string | null => {
      switch (sortKey) {
        case "name":
          return s.name.toLowerCase();
        case "status": {
          const order = { critical: 0, warn: 1, unknown: 2, ok: 3 } as const;
          return order[s.status] ?? 2;
        }
        case "containers":
          return s.containers.running;
        case "cpu":
          return s.cpu_percent;
        case "memory":
          return s.memory_mb;
        case "deployed":
          return s.last_deployed_at;
      }
    };
    return [...items].sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * mul;
      return String(va).localeCompare(String(vb), "ko") * mul;
    });
  }, [items, sortKey, sortDir]);

  const activeFilters =
    (query.status ? 1 : 0) + (query.category ? 1 : 0) + (query.search ? 1 : 0);

  return (
    <div>
      <PageHeader
        title="Services"
        description={`등록 서비스 ${items.length}개 · Service Registry (컨테이너와 별개의 관리 정보)`}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => setGuideOpen(true)}>
              <BookOpen className="h-4 w-4" />
              service.yaml 안내
            </Button>
            <Button size="sm" onClick={() => setRegisterOpen(true)}>
              <Plus className="h-4 w-4" />
              서비스 등록
            </Button>
          </>
        }
      />

      {/* 필터 바 */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1 sm:max-w-72">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="이름/ID/설명 검색"
            aria-label="서비스 검색"
            className="h-8 pl-8"
          />
        </div>
        <div className="w-40">
          <Select
            value={query.status ?? ""}
            onValueChange={(v) => setQuery((q) => ({ ...q, status: v || undefined }))}
            options={STATUS_OPTIONS}
            aria-label="상태 필터"
          />
        </div>
        <div className="w-44">
          <Select
            value={query.category ?? ""}
            onValueChange={(v) => setQuery((q) => ({ ...q, category: v || undefined }))}
            options={CATEGORY_OPTIONS}
            aria-label="카테고리 필터"
          />
        </div>
        {activeFilters > 0 ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSearchInput("");
              setQuery({});
            }}
          >
            <X className="h-3.5 w-3.5" />
            필터 해제 ({activeFilters})
          </Button>
        ) : null}
      </div>

      {error ? (
        <div className="mb-3">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      <Card>
        {loading ? (
          <LoadingState label="서비스 목록을 불러오는 중…" />
        ) : sorted.length === 0 ? (
          <EmptyState message="조건에 맞는 서비스가 없습니다." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <SortHeader label="이름" sortKey="name" current={sortKey} dir={sortDir} onSort={onSort} className="w-52" />
                <TableHead>설명</TableHead>
                <SortHeader label="상태" sortKey="status" current={sortKey} dir={sortDir} onSort={onSort} className="w-24" />
                <SortHeader label="실행 컨테이너" sortKey="containers" current={sortKey} dir={sortDir} onSort={onSort} className="w-28" />
                <TableHead className="w-56">엔드포인트</TableHead>
                <SortHeader label="CPU" sortKey="cpu" current={sortKey} dir={sortDir} onSort={onSort} className="w-20" />
                <SortHeader label="메모리" sortKey="memory" current={sortKey} dir={sortDir} onSort={onSort} className="w-24" />
                <SortHeader label="마지막 배포" sortKey="deployed" current={sortKey} dir={sortDir} onSort={onSort} className="w-40" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((s) => (
                <TableRow
                  key={s.id}
                  className="cursor-pointer"
                  tabIndex={0}
                  role="link"
                  aria-label={`${s.name} 상세 보기`}
                  onClick={() => navigate(`/services/${s.id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") navigate(`/services/${s.id}`);
                  }}
                >
                  <TableCell>
                    <div className="font-medium leading-tight">{s.name}</div>
                    <div className="text-[11px] text-muted-foreground">{s.id}</div>
                  </TableCell>
                  <TableCell className="max-w-72">
                    <div className="line-clamp-2 text-xs text-muted-foreground">{s.description}</div>
                    {s.tags && s.tags.length > 0 ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {s.tags.slice(0, 3).map((t) => (
                          <Badge key={t} variant="outline">
                            {t}
                          </Badge>
                        ))}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={s.status} />
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {s.containers.running} / {s.containers.total}
                  </TableCell>
                  <TableCell>
                    {s.endpoints.length === 0 ? (
                      <span className="text-xs text-muted-foreground">—</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {s.endpoints.slice(0, 2).map((ep) => (
                          <Badge key={ep.name} variant="outline" title={`${ep.exposure} · ${ep.container_port ?? "?"}`}>
                            {ep.hostname ?? ep.name}
                          </Badge>
                        ))}
                        {s.endpoints.length > 2 ? (
                          <Badge variant="secondary">+{s.endpoints.length - 2}</Badge>
                        ) : null}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="tabular-nums">{formatPercent(s.cpu_percent)}</TableCell>
                  <TableCell className="tabular-nums">{formatBytesMb(s.memory_mb)}</TableCell>
                  <TableCell className="text-xs tabular-nums">
                    {s.last_deployed_at ? formatDateTime(s.last_deployed_at) : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <RegisterDialog
        open={registerOpen}
        onClose={() => setRegisterOpen(false)}
        onCreated={() => void load()}
      />

      <SpecGuideDialog open={guideOpen} onClose={() => setGuideOpen(false)} />
    </div>
  );
}
