import * as React from "react";
import { useNavigate } from "react-router-dom";
import { Check, ChevronLeft, ChevronRight, Server, ShieldCheck } from "lucide-react";
import { isApiError } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Input, Label } from "../components/ui/input";
import { ErrorState } from "../components/feedback";

interface FormErrors {
  username?: string;
  password?: string;
  confirm?: string;
}

/** 최초 실행 시 관리자 계정 생성 위자드 (POST /setup/admin) */
export default function Setup() {
  const { completeSetup } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = React.useState(1);
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [errors, setErrors] = React.useState<FormErrors>({});
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  const validateStep1 = (): boolean => {
    const e: FormErrors = {};
    if (!username.trim()) e.username = "관리자 아이디를 입력하세요.";
    else if (!/^[a-zA-Z0-9_.-]{3,32}$/.test(username.trim()))
      e.username = "아이디는 영문/숫자/._- 3~32자로 입력하세요.";
    if (!password) e.password = "비밀번호를 입력하세요.";
    else if (password.length < 8) e.password = "비밀번호는 8자 이상이어야 합니다.";
    if (confirm !== password) e.confirm = "비밀번호가 서로 다릅니다.";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const submit = async () => {
    if (!validateStep1()) return;
    setSubmitting(true);
    setServerError(null);
    try {
      await completeSetup(username.trim(), password);
      navigate("/", { replace: true });
    } catch (err) {
      setServerError(isApiError(err) ? err.message : "관리자 생성 요청에 실패했습니다.");
      setStep(1);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-background px-4 py-10">
      <Card className="w-full max-w-md">
        <CardHeader className="pb-4">
          <div className="mb-2 flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded bg-primary text-primary-foreground">
              <Server className="h-4 w-4" />
            </span>
            <div>
              <CardTitle className="text-base">N100 Service Hub 초기 설정</CardTitle>
              <CardDescription>최초 1회 관리자 계정을 생성합니다.</CardDescription>
            </div>
          </div>
          <ol className="flex items-center gap-2 text-xs">
            <li
              className={
                step === 1
                  ? "rounded border border-primary/40 bg-primary/10 px-2 py-1 font-medium"
                  : "rounded border border-border px-2 py-1 text-muted-foreground"
              }
            >
              1. 관리자 계정
            </li>
            <li className="text-muted-foreground" aria-hidden="true">
              <ChevronRight className="h-3.5 w-3.5" />
            </li>
            <li
              className={
                step === 2
                  ? "rounded border border-primary/40 bg-primary/10 px-2 py-1 font-medium"
                  : "rounded border border-border px-2 py-1 text-muted-foreground"
              }
            >
              2. 확인 및 생성
            </li>
          </ol>
        </CardHeader>
        <CardContent>
          {serverError ? (
            <div className="mb-3">
              <ErrorState message={serverError} />
            </div>
          ) : null}

          {step === 1 ? (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (validateStep1()) setStep(2);
              }}
            >
              <div>
                <Label htmlFor="setup-username" required>
                  관리자 아이디
                </Label>
                <Input
                  id="setup-username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  placeholder="admin"
                  aria-invalid={!!errors.username}
                />
                {errors.username ? (
                  <p className="mt-1 text-xs text-destructive">{errors.username}</p>
                ) : null}
              </div>
              <div>
                <Label htmlFor="setup-password" required>
                  비밀번호
                </Label>
                <Input
                  id="setup-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  placeholder="8자 이상"
                  aria-invalid={!!errors.password}
                />
                {errors.password ? (
                  <p className="mt-1 text-xs text-destructive">{errors.password}</p>
                ) : null}
              </div>
              <div>
                <Label htmlFor="setup-confirm" required>
                  비밀번호 확인
                </Label>
                <Input
                  id="setup-confirm"
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  autoComplete="new-password"
                  aria-invalid={!!errors.confirm}
                />
                {errors.confirm ? (
                  <p className="mt-1 text-xs text-destructive">{errors.confirm}</p>
                ) : null}
              </div>
              <Button type="submit" className="w-full">
                다음
                <ChevronRight className="h-4 w-4" />
              </Button>
            </form>
          ) : (
            <div className="space-y-4">
              <div className="flex items-start gap-2 rounded-md border border-border bg-muted/50 px-3 py-2.5 text-sm">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                <div>
                  <div className="font-medium">관리자 계정을 생성합니다</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    아이디 <span className="font-mono">{username}</span> · 비밀번호 8자 이상 ·
                    이후 로그인에 사용됩니다. 기본 비밀번호는 하드코딩되지 않습니다.
                  </div>
                </div>
              </div>
              <ul className="space-y-1.5 text-xs text-muted-foreground">
                <li className="flex items-center gap-2">
                  <Check className="h-3.5 w-3.5 text-emerald-500" />
                  설정 변경과 배포 이력은 감사 로그에 기록됩니다.
                </li>
                <li className="flex items-center gap-2">
                  <Check className="h-3.5 w-3.5 text-emerald-500" />
                  기존 Docker 컨테이너/볼륨은 이 단계에서 변경되지 않습니다.
                </li>
              </ul>
              <div className="flex items-center justify-between gap-2">
                <Button variant="outline" size="sm" onClick={() => setStep(1)} disabled={submitting}>
                  <ChevronLeft className="h-4 w-4" />
                  이전
                </Button>
                <Button onClick={submit} disabled={submitting}>
                  {submitting ? "생성 중…" : "관리자 생성"}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
