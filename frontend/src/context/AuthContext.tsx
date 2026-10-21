import * as React from "react";
import {
  fetchSession,
  login as apiLogin,
  logout as apiLogout,
  setupAdmin,
  onUnauthorized,
  isApiError,
  type SessionInfo,
} from "../lib/api";
import { loginWithPasskey } from "../lib/webauthn";

export type AuthStatus = "loading" | "setup" | "anonymous" | "authenticated";

interface AuthContextValue {
  status: AuthStatus;
  session: SessionInfo | null;
  refresh: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  passkeyLogin: (username: string) => Promise<void>;
  logout: () => Promise<void>;
  completeSetup: (username: string, password: string) => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = React.useState<AuthStatus>("loading");
  const [session, setSession] = React.useState<SessionInfo | null>(null);

  const apply = React.useCallback((s: SessionInfo | null) => {
    setSession(s);
    if (!s) setStatus("anonymous");
    else if (s.setup_required) setStatus("setup");
    else if (s.authenticated) setStatus("authenticated");
    else setStatus("anonymous");
  }, []);

  const refresh = React.useCallback(async () => {
    try {
      const s = await fetchSession();
      apply(s);
    } catch (e) {
      if (isApiError(e) && e.status === 404) {
        // 백엔드에 auth 라우터가 아직 없는 초기 개발 환경
        apply(null);
        return;
      }
      apply(null);
    }
  }, [apply]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  // 세션 만료/401 → 로그인 화면으로
  React.useEffect(
    () =>
      onUnauthorized(() => {
        setSession(null);
        setStatus("anonymous");
      }),
    [],
  );

  const login = React.useCallback(
    async (username: string, password: string) => {
      const s = await apiLogin({ username, password });
      apply(s.authenticated === false && s.setup_required ? s : { ...s, authenticated: true });
    },
    [apply],
  );

  const passkeyLogin = React.useCallback(
    async (username: string) => {
      const s = await loginWithPasskey(username);
      apply(s);
    },
    [apply],
  );

  const logout = React.useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      apply(null);
    }
  }, [apply]);

  const completeSetup = React.useCallback(
    async (username: string, password: string) => {
      const s = await setupAdmin({ username, password });
      apply(
        s ?? {
          authenticated: true,
          setup_required: false,
          user: { username, role: "admin" },
          csrf_token: null,
        },
      );
    },
    [apply],
  );

  const value = React.useMemo(
    () => ({ status, session, refresh, login, passkeyLogin, logout, completeSetup }),
    [status, session, refresh, login, passkeyLogin, logout, completeSetup],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth는 AuthProvider 내부에서만 사용할 수 있습니다.");
  return ctx;
}
