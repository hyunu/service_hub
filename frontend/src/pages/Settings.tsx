import * as React from "react";
import { Link } from "react-router-dom";
import { ClipboardList, Fingerprint, KeyRound, RefreshCw, Save, ShieldCheck, Trash2 } from "lucide-react";
import {
  changePassword,
  fetchAuditLogs,
  fetchSettings,
  isApiError,
  updateSettings,
  type AuditLog,
  type HubSettings,
} from "../lib/api";
import {
  deletePasskey,
  fetchPasskeys,
  isPlatformAuthenticatorAvailable,
  isWebAuthnSupported,
  registerPasskey,
  type PasskeyInfo,
} from "../lib/webauthn";
import { formatDateTime, formatRelative } from "../lib/format";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../components/feedback";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Input, Label } from "../components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { Badge } from "../components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";

function NumberField({
  id,
  label,
  value,
  onChange,
  min,
  max,
  suffix,
}: {
  id: string;
  label: string;
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  min?: number;
  max?: number;
  suffix?: string;
}) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        <Input
          id={id}
          type="number"
          min={min}
          max={max}
          value={value ?? ""}
          onChange={(e) => {
            const raw = e.target.value;
            onChange(raw === "" ? null : Number(raw));
          }}
          className="pr-10"
        />
        {suffix ? (
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
            {suffix}
          </span>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------ 설정 탭 ------------------------------ */

function GeneralSettings() {
  const [settings, setSettings] = React.useState<HubSettings | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState<{ ok: boolean; text: string } | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await fetchSettings();
      setSettings(s);
    } catch (e) {
      setError(isApiError(e) ? e.message : "설정을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const patch = (p: Partial<HubSettings>) => setSettings((s) => (s ? { ...s, ...p } : s));

  const patchThreshold = (key: string, v: number | null) =>
    setSettings((s) =>
      s ? { ...s, thresholds: { ...s.thresholds, [key]: v } } : s,
    );

  const save = async () => {
    if (!settings) return;
    const t = settings.thresholds ?? {};
    const pairs: Array<[number | null | undefined, number | null | undefined, string]> = [
      [t.memory_warn_percent, t.memory_critical_percent, "메모리"],
      [t.disk_warn_percent, t.disk_critical_percent, "디스크"],
      [t.cpu_warn_percent, t.cpu_critical_percent, "CPU"],
    ];
    for (const [warn, crit, name] of pairs) {
      if (warn != null && crit != null && warn >= crit) {
        setNotice({ ok: false, text: `${name} 주의 임계값은 위험 임계값보다 낮아야 합니다.` });
        return;
      }
    }
    if (
      settings.monitor_interval_seconds != null &&
      (settings.monitor_interval_seconds < 5 || settings.monitor_interval_seconds > 3600)
    ) {
      setNotice({ ok: false, text: "수집 주기는 5~3600초 사이로 입력하세요." });
      return;
    }

    setBusy(true);
    setNotice(null);
    try {
      const updated = await updateSettings(settings);
      setSettings(updated);
      setNotice({ ok: true, text: "설정을 저장했습니다." });
    } catch (e) {
      setNotice({ ok: false, text: isApiError(e) ? e.message : "설정 저장에 실패했습니다." });
    } finally {
      setBusy(false);
    }
  };

  if (loading && !settings) return <LoadingState label="설정을 불러오는 중…" />;
  if (error && !settings) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!settings) return null;

  const t = settings.thresholds ?? {};
  const bind = settings.bind ?? {};

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="pb-1">
          <CardTitle>일반</CardTitle>
          <CardDescription>허브 이름과 모니터 수집 주기</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <Label htmlFor="set-name">허브 이름</Label>
            <Input
              id="set-name"
              value={settings.hub_name ?? ""}
              onChange={(e) => patch({ hub_name: e.target.value })}
              placeholder="N100 Service Hub"
            />
            <p className="mt-1 text-[11px] text-muted-foreground">
              SSH 환영 메시지(MOTD)와 화면 제목에 표시됩니다.
            </p>
          </div>
          <NumberField
            id="set-interval"
            label="모니터 수집 주기"
            value={settings.monitor_interval_seconds}
            onChange={(v) => patch({ monitor_interval_seconds: v ?? 15 })}
            min={5}
            max={3600}
            suffix="초"
          />
          <div className="rounded-md border border-border bg-muted/40 px-3 py-2.5">
            <div className="mb-1 text-xs font-medium text-muted-foreground">Bind 정보 (읽기 전용)</div>
            <div className="font-mono text-sm">
              {bind.host ?? "0.0.0.0"}:{bind.port ?? 8420}
              {bind.internal_only ? (
                <Badge variant="ok" className="ml-2">
                  내부망 전용
                </Badge>
              ) : (
                <Badge variant="warn" className="ml-2">
                  외부 접근 허용
                </Badge>
              )}
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">
              관리 API의 bind 정책은 설치 시 설정됩니다 (환경변수 HUB_*).
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-1">
          <CardTitle>자원 경고 임계값</CardTitle>
          <CardDescription>사양 §10.4 기본값: 80% 주의 / 90% 위험</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2">
            <NumberField
              id="th-mem-warn"
              label="메모리 주의"
              value={t.memory_warn_percent}
              onChange={(v) => patchThreshold("memory_warn_percent", v)}
              min={1}
              max={100}
              suffix="%"
            />
            <NumberField
              id="th-mem-crit"
              label="메모리 위험"
              value={t.memory_critical_percent}
              onChange={(v) => patchThreshold("memory_critical_percent", v)}
              min={1}
              max={100}
              suffix="%"
            />
            <NumberField
              id="th-disk-warn"
              label="디스크 주의"
              value={t.disk_warn_percent}
              onChange={(v) => patchThreshold("disk_warn_percent", v)}
              min={1}
              max={100}
              suffix="%"
            />
            <NumberField
              id="th-disk-crit"
              label="디스크 위험"
              value={t.disk_critical_percent}
              onChange={(v) => patchThreshold("disk_critical_percent", v)}
              min={1}
              max={100}
              suffix="%"
            />
            <NumberField
              id="th-cpu-warn"
              label="CPU 주의"
              value={t.cpu_warn_percent}
              onChange={(v) => patchThreshold("cpu_warn_percent", v)}
              min={1}
              max={100}
              suffix="%"
            />
            <NumberField
              id="th-cpu-crit"
              label="CPU 위험"
              value={t.cpu_critical_percent}
              onChange={(v) => patchThreshold("cpu_critical_percent", v)}
              min={1}
              max={100}
              suffix="%"
            />
            <NumberField
              id="th-cpu-sustained"
              label="CPU 지속 시간"
              value={t.cpu_sustained_seconds}
              onChange={(v) => patchThreshold("cpu_sustained_seconds", v)}
              min={0}
              suffix="초"
            />
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
            CPU 임계값은 지속 시간이 경과한 뒤에만 경고로 판정합니다. 경고 판정 결과는{" "}
            <Link to="/resources" className="text-primary hover:underline">
              Resources
            </Link>{" "}
            에서 확인할 수 있습니다.
          </p>

          {notice ? (
            <div
              className={`mt-3 rounded-md border px-3 py-2 text-xs ${
                notice.ok
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400"
              }`}
              role="alert"
            >
              {notice.text}
            </div>
          ) : null}

          <div className="mt-3 flex items-center justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => void load()} disabled={busy}>
              변경 되돌리기
            </Button>
            <Button size="sm" onClick={() => void save()} disabled={busy}>
              <Save className="h-3.5 w-3.5" />
              {busy ? "저장 중…" : "설정 저장"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* ------------------------------ 보안 탭 ------------------------------ */

function SecuritySettings() {
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState<{ ok: boolean; text: string } | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (next.length < 8) {
      setNotice({ ok: false, text: "새 비밀번호는 8자 이상이어야 합니다." });
      return;
    }
    if (next !== confirm) {
      setNotice({ ok: false, text: "새 비밀번호가 확인 값과 일치하지 않습니다." });
      return;
    }
    if (next === current) {
      setNotice({ ok: false, text: "새 비밀번호가 현재 비밀번호와 같습니다." });
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      await changePassword({ current_password: current, new_password: next });
      setNotice({ ok: true, text: "비밀번호를 변경했습니다. 다음 로그인부터 새 비밀번호를 사용하세요." });
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (e2) {
      setNotice({ ok: false, text: isApiError(e2) ? e2.message : "비밀번호 변경에 실패했습니다." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="inline-flex items-center gap-1.5">
            <KeyRound className="h-4 w-4 text-primary" />
            비밀번호 변경
          </CardTitle>
          <CardDescription>
            현 비밀번호를 확인한 뒤 변경합니다. 변경은 감사 로그에 기록됩니다.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="max-w-md space-y-3">
            <div>
              <Label htmlFor="cur-pw">현재 비밀번호</Label>
              <Input
                id="cur-pw"
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                required
              />
            </div>
            <div>
              <Label htmlFor="new-pw">새 비밀번호</Label>
              <Input
                id="new-pw"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                required
              />
              <p className="mt-1 text-[11px] text-muted-foreground">8자 이상</p>
            </div>
            <div>
              <Label htmlFor="new-pw2">새 비밀번호 확인</Label>
              <Input
                id="new-pw2"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
              />
            </div>

            {notice ? (
              <div
                className={`rounded-md border px-3 py-2 text-xs ${
                  notice.ok
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                    : "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400"
                }`}
                role="alert"
              >
                {notice.text}
              </div>
            ) : null}

            <div className="flex justify-end">
              <Button type="submit" size="sm" disabled={busy}>
                <Save className="h-3.5 w-3.5" />
                {busy ? "변경 중…" : "비밀번호 변경"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-1">
          <CardTitle>보안 안내</CardTitle>
          <CardDescription>비밀번호와 세션에 대한 기본 원칙</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2 text-xs leading-relaxed text-muted-foreground">
            <li>• 비밀번호는 최소 8자, 빈번한 재사용을 피해 주세요.</li>
            <li>• 로그인 실패 5회 시 5분간 접속이 제한됩니다.</li>
            <li>• 세션 쿠키는 HttpOnly이며, 변경 요청에는 CSRF 토큰이 필요합니다.</li>
            <li>• 비밀번호 변경·배포·포트 예약 기록은 탭 상단의 감사 로그에서 확인할 수 있습니다.</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

/* --------------------------- 패스워드리스(생체인식) --------------------------- */

function PasskeySettings() {
  const [items, setItems] = React.useState<PasskeyInfo[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [label, setLabel] = React.useState("");
  const [notice, setNotice] = React.useState<{ ok: boolean; text: string } | null>(null);
  const [platformOk, setPlatformOk] = React.useState<boolean | null>(null);
  const supported = React.useMemo(() => isWebAuthnSupported(), []);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setItems(await fetchPasskeys());
    } catch (e) {
      if (isApiError(e) && e.code === "webauthn_disabled") {
        setError("생체인식 로그인은 HTTPS(보안 컨텍스트) 접속에서만 사용할 수 있습니다.");
      } else {
        setError(isApiError(e) ? e.message : "패스워드 키 목록을 불러오지 못했습니다.");
      }
      setItems([]);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  React.useEffect(() => {
    void isPlatformAuthenticatorAvailable().then(setPlatformOk);
  }, []);

  const register = async () => {
    setNotice(null);
    setBusy(true);
    try {
      await registerPasskey(label.trim() || "내 기기");
      setLabel("");
      setNotice({ ok: true, text: "패스워드 키를 등록했습니다. 다음부터 생체인식으로 로그인할 수 있습니다." });
      await load();
    } catch (e) {
      if (isApiError(e)) {
        setNotice({
          ok: false,
          text: e.code === "webauthn_disabled"
            ? "생체인식 로그인은 HTTPS(보안 컨텍스트) 접속에서만 사용할 수 있습니다."
            : e.message,
        });
      } else if ((e as Error)?.name === "NotAllowedError") {
        setNotice({ ok: false, text: "등록이 취소되었습니다." });
      } else {
        setNotice({ ok: false, text: "패스워드 키 등록에 실패했습니다." });
      }
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    if (!window.confirm("이 패스워드 키를 삭제할까요? 삭제하면 해당 기기로 생체인식 로그인을 할 수 없습니다.")) {
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      await deletePasskey(id);
      await load();
      setNotice({ ok: true, text: "패스워드 키를 삭제했습니다." });
    } catch (e) {
      setNotice({ ok: false, text: isApiError(e) ? e.message : "삭제에 실패했습니다." });
    } finally {
      setBusy(false);
    }
  };

  const deviceLabel = (t: string | null) =>
    t === "multiDevice" ? "동기화(여러 기기)" : t === "singleDevice" ? "단일 기기" : "알 수 없음";

  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="inline-flex items-center gap-1.5">
          <Fingerprint className="h-4 w-4 text-primary" />
          패스워드리스 (생체인식)
        </CardTitle>
        <CardDescription>
          지문·Face ID·Windows Hello로 비밀번호 없이 로그인합니다. 서버에는 공개키만 저장됩니다.
        </CardDescription>
      </CardHeader>
      <CardContent className="max-w-2xl space-y-3">
        {!supported ? (
          <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
            현재 접속은 HTTPS가 아니어서 브라우저가 생체인식을 차단합니다. HTTPS 주소로 접속하면 사용할 수 있습니다.
          </p>
        ) : null}

        {platformOk === false ? (
          <p className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            이 기기에서 플랫폼 인증기(지문/Face ID 등)를 찾지 못했습니다. 보안 키(USB)는 등록할 수 있습니다.
          </p>
        ) : null}

        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[12rem] flex-1">
            <Label htmlFor="passkey-label">기기 이름</Label>
            <Input
              id="passkey-label"
              value={label}
              placeholder="예: MacBook Touch ID"
              maxLength={120}
              onChange={(e) => setLabel(e.target.value)}
              disabled={busy || !supported}
            />
          </div>
          <Button size="sm" onClick={() => void register()} disabled={busy || !supported}>
            <KeyRound className="h-3.5 w-3.5" />
            {busy ? "등록 중…" : "패스워드 키 등록"}
          </Button>
        </div>

        {notice ? (
          <div
            className={`rounded-md border px-3 py-2 text-xs ${
              notice.ok
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400"
            }`}
            role="alert"
          >
            {notice.text}
          </div>
        ) : null}

        {error ? (
          <p className="text-xs text-destructive" role="alert">{error}</p>
        ) : null}

        {items === null ? (
          <p className="text-xs text-muted-foreground">불러오는 중…</p>
        ) : items.length === 0 ? (
          <p className="text-xs text-muted-foreground">등록된 패스워드 키가 없습니다.</p>
        ) : (
          <div className="overflow-x-auto rounded-md border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>이름</TableHead>
                  <TableHead>유형</TableHead>
                  <TableHead>등록</TableHead>
                  <TableHead>마지막 사용</TableHead>
                  <TableHead className="w-16" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">{p.label}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {deviceLabel(p.device_type)}
                      {p.backed_up ? " · 백업됨" : ""}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(p.created_at)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {p.last_used_at ? formatDateTime(p.last_used_at) : "사용 기록 없음"}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void remove(p.id)}
                        disabled={busy}
                        aria-label={`${p.label} 삭제`}
                        title="삭제"
                      >
                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        <p className="text-[11px] leading-relaxed text-muted-foreground">
          비밀번호를 잊었을 때를 대비해 비밀번호 로그인은 그대로 유지하는 것을 권장합니다.
        </p>
      </CardContent>
    </Card>
  );
}

/* ------------------------------ 감사 로그 탭 ------------------------------ */

function AuditLogViewer() {
  const [items, setItems] = React.useState<AuditLog[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      const list = await fetchAuditLogs(200);
      setItems(list);
    } catch (e) {
      setError(isApiError(e) ? e.message : "감사 로그를 불러오지 못했습니다.");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!items) return <LoadingState label="감사 로그를 불러오는 중…" />;
  if (items.length === 0) return <EmptyState message="감사 로그가 없습니다." />;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between pb-2">
        <div>
          <CardTitle className="inline-flex items-center gap-1.5">
            <ClipboardList className="h-4 w-4" />
            감사 로그 (최근 200건)
          </CardTitle>
          <CardDescription>설정 변경·배포·포트 예약 등 주요 작업 기록</CardDescription>
        </div>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw className="h-3.5 w-3.5" />
          새로고침
        </Button>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-48">시각</TableHead>
              <TableHead className="w-32">행위자</TableHead>
              <TableHead className="w-48">작업</TableHead>
              <TableHead>대상</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((a) => (
              <TableRow key={a.id}>
                <TableCell className="text-xs tabular-nums">
                  <div>{formatDateTime(a.ts)}</div>
                  <div className="text-[11px] text-muted-foreground">{formatRelative(a.ts)}</div>
                </TableCell>
                <TableCell className="text-xs font-medium">{a.actor}</TableCell>
                <TableCell className="font-mono text-xs">{a.action}</TableCell>
                <TableCell className="text-xs">{a.target}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

/* --------------------------------- 페이지 --------------------------------- */

export default function Settings() {
  const [tab, setTab] = React.useState("general");

  return (
    <div>
      <PageHeader
        title="Settings"
        description="허브 설정, 경고 임계값, 보안, 감사 로그"
        actions={
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <ShieldCheck className="h-4 w-4 text-emerald-500" />
            비밀 필드는 이 화면에 포함되지 않습니다
          </span>
        }
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="general">일반/임계값</TabsTrigger>
          <TabsTrigger value="security">보안</TabsTrigger>
          <TabsTrigger value="audit">감사 로그</TabsTrigger>
        </TabsList>
        <TabsContent value="general">
          <GeneralSettings />
        </TabsContent>
        <TabsContent value="security">
          <div className="space-y-4">
            <SecuritySettings />
            <PasskeySettings />
          </div>
        </TabsContent>
        <TabsContent value="audit">
          <AuditLogViewer />
        </TabsContent>
      </Tabs>
    </div>
  );
}
