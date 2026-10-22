import * as React from "react";
import { BookOpen, Check, Copy, Download } from "lucide-react";
import { fetchSpecGuide, isApiError, type SpecGuide } from "../lib/api";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { LoadingState, ErrorState } from "./feedback";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";

/** 코드 블록 + 복사 버튼 */
function CodeBlock({ code, label }: { code: string; label?: string }) {
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* 클립보드 권한이 없으면 조용히 무시 */
    }
  };
  return (
    <div className="relative">
      <div className="mb-1 flex items-center justify-between">
        {label ? <span className="text-[11px] text-muted-foreground">{label}</span> : <span />}
        <Button variant="ghost" size="sm" onClick={() => void copy()} aria-label="복사">
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "복사됨" : "복사"}
        </Button>
      </div>
      <pre className="max-h-72 overflow-auto rounded-md border border-border bg-muted/30 p-3 text-[11px] leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  );
}

type GuideTab = "example" | "fields" | "rules";

/** service.yaml 작성 안내 — 백엔드(spec_guide)가 제공하는 단일 출처를 표시한다. */
export function SpecGuideDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [guide, setGuide] = React.useState<SpecGuide | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [tab, setTab] = React.useState<GuideTab>("example");

  React.useEffect(() => {
    if (!open || guide) return;
    setError(null);
    fetchSpecGuide()
      .then(setGuide)
      .catch((e) => setError(isApiError(e) ? e.message : "안내를 불러오지 못했습니다."));
  }, [open, guide]);

  const download = () => {
    if (!guide) return;
    const blob = new Blob([guide.minimal_example], { type: "text/yaml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "service.yaml";
    a.click();
    URL.revokeObjectURL(url);
  };

  const tabBtn = (key: GuideTab, label: string) => (
    <button
      type="button"
      onClick={() => setTab(key)}
      aria-pressed={tab === key}
      className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
        tab === key
          ? "bg-primary/15 text-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-foreground"
      }`}
    >
      {label}
    </button>
  );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="service.yaml 작성 안내"
      description="서비스 정의 파일의 구조와 규칙입니다. 등록(DB)과 별개로, 배포에는 이 파일이 필요합니다."
      className="max-w-3xl"
      footer={
        <Button variant="outline" size="sm" onClick={onClose}>
          닫기
        </Button>
      }
    >
      {error ? <ErrorState message={error} /> : null}
      {!guide && !error ? <LoadingState label="안내를 불러오는 중…" /> : null}
      {guide ? (
        <div className="space-y-3">
          <div className="rounded-md border border-border bg-muted/20 px-3 py-2 text-[11px] leading-relaxed">
            <div>
              <span className="font-medium">파일 위치</span>{" "}
              <code className="font-mono">{guide.file_location}</code>
            </div>
            <div className="mt-1 grid gap-1 sm:grid-cols-2">
              <div>
                <span className="text-muted-foreground">생성:</span>{" "}
                <code className="font-mono">{guide.create_command}</code>
              </div>
              <div>
                <span className="text-muted-foreground">검증:</span>{" "}
                <code className="font-mono">{guide.validate_command}</code>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1">
            {tabBtn("example", "예시")}
            {tabBtn("fields", `필드 (${guide.fields.length})`)}
            {tabBtn("rules", `규칙 (${guide.rules.length})`)}
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto"
              onClick={download}
              title="최소 예시를 service.yaml로 저장"
            >
              <Download className="h-3.5 w-3.5" />
              최소 예시 저장
            </Button>
          </div>

          {tab === "example" ? (
            <div className="space-y-3">
              <CodeBlock code={guide.minimal_example} label="최소 예시 (필수 항목만)" />
              <details className="rounded-md border border-border">
                <summary className="cursor-pointer px-3 py-2 text-xs font-medium">
                  전체 예시 보기 (엔드포인트·자원·볼륨·보안 포함)
                </summary>
                <div className="p-3 pt-0">
                  <CodeBlock code={guide.full_example} />
                </div>
              </details>
            </div>
          ) : null}

          {tab === "fields" ? (
            <div className="max-h-[26rem] overflow-auto rounded-md border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>경로</TableHead>
                    <TableHead className="w-14">필수</TableHead>
                    <TableHead className="w-20">타입</TableHead>
                    <TableHead>설명 / 허용값</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {guide.fields.map((f) => (
                    <TableRow key={f.path}>
                      <TableCell className="font-mono text-[11px]">{f.path}</TableCell>
                      <TableCell className="text-xs">
                        {f.required ? (
                          <span className="font-medium text-destructive">필수</span>
                        ) : (
                          <span className="text-muted-foreground">선택</span>
                        )}
                      </TableCell>
                      <TableCell className="text-[11px] text-muted-foreground">{f.type}</TableCell>
                      <TableCell className="text-[11px]">
                        {f.description}
                        {f.allowed ? (
                          <span className="block text-muted-foreground">{f.allowed}</span>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : null}

          {tab === "rules" ? (
            <ul className="space-y-1.5 text-xs leading-relaxed">
              {guide.rules.map((r, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-muted-foreground">{i + 1}.</span>
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          ) : null}

          <p className="text-[11px] text-muted-foreground">
            <BookOpen className="mr-1 inline h-3 w-3" />
            전체 문서: <code className="font-mono">{guide.docs}</code> · 배포 순서:{" "}
            <code className="font-mono">{guide.plan_command}</code> →{" "}
            <code className="font-mono">{guide.apply_command}</code>
          </p>
        </div>
      ) : null}
    </Dialog>
  );
}
