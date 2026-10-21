import * as React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { LogIn, Server } from "lucide-react";
import { isApiError } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Input, Label } from "../components/ui/input";
import { ErrorState } from "../components/feedback";

interface FormErrors {
  username?: string;
  password?: string;
}

/** 로그인 (POST /auth/login) */
export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? "/";

  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [errors, setErrors] = React.useState<FormErrors>({});
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  const validate = (): boolean => {
    const e: FormErrors = {};
    if (!username.trim()) e.username = "아이디를 입력하세요.";
    if (!password) e.password = "비밀번호를 입력하세요.";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setServerError(null);
    if (!validate()) return;
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      if (isApiError(err)) {
        setServerError(
          err.status === 401 || err.status === 403
            ? "아이디 또는 비밀번호가 올바르지 않습니다."
            : err.message,
        );
      } else {
        setServerError("로그인 요청에 실패했습니다.");
      }
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-background px-4 py-10">
      <Card className="w-full max-w-sm">
        <CardHeader className="pb-4">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded bg-primary text-primary-foreground">
              <Server className="h-4 w-4" />
            </span>
            <div>
              <CardTitle className="text-base">N100 Service Hub</CardTitle>
              <CardDescription>서버 운영 대시보드 로그인</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {serverError ? (
            <div className="mb-3">
              <ErrorState message={serverError} />
            </div>
          ) : null}
          <form className="space-y-3" onSubmit={submit} noValidate>
            <div>
              <Label htmlFor="login-username" required>
                아이디
              </Label>
              <Input
                id="login-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                aria-invalid={!!errors.username}
              />
              {errors.username ? (
                <p className="mt-1 text-xs text-destructive" role="alert">
                  {errors.username}
                </p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="login-password" required>
                비밀번호
              </Label>
              <Input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                aria-invalid={!!errors.password}
              />
              {errors.password ? (
                <p className="mt-1 text-xs text-destructive" role="alert">
                  {errors.password}
                </p>
              ) : null}
            </div>
            <Button type="submit" className="w-full" disabled={submitting}>
              <LogIn className="h-4 w-4" />
              {submitting ? "로그인 중…" : "로그인"}
            </Button>
          </form>
          <p className="mt-4 text-center text-[11px] text-muted-foreground">
            관리 웹 UI는 기본적으로 내부 네트워크에서만 접근합니다.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
