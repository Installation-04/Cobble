import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { authApi } from "../api/endpoints";
import { setUnauthorizedHandler } from "../api/client";
import type { User } from "../api/types";
import { setLang, type Lang } from "../i18n";
import { setThemeMode, type ThemeMode } from "../theme/store";

export type AuthStatus = "loading" | "anonymous" | "authenticated";

interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  activate: (token: string, email: string, password: string, lang: Lang) => Promise<void>;
  logout: () => Promise<void>;
  /** Apply preferences locally at once, then persist them on the account when logged in. */
  savePrefs: (prefs: { lang?: Lang; theme?: ThemeMode }) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function adoptPrefs(user: User): void {
  setThemeMode(user.theme);
  void setLang(user.lang);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<User | null>(null);

  const setSession = useCallback((next: User | null) => {
    setUser(next);
    setStatus(next ? "authenticated" : "anonymous");
    if (next) adoptPrefs(next);
  }, []);

  useEffect(() => {
    let cancelled = false;
    authApi
      .me()
      .then((me) => {
        if (!cancelled) setSession(me);
      })
      .catch(() => {
        if (!cancelled) setSession(null);
      });
    setUnauthorizedHandler(() => {
      setUser(null);
      setStatus("anonymous");
    });
    return () => {
      cancelled = true;
      setUnauthorizedHandler(null);
    };
  }, [setSession]);

  const login = useCallback(
    async (email: string, password: string) => {
      setSession(await authApi.login(email, password));
    },
    [setSession],
  );

  const activate = useCallback(
    async (token: string, email: string, password: string, lang: Lang) => {
      setSession(await authApi.activate({ token, email, password, lang }));
    },
    [setSession],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  const savePrefs = useCallback(
    async (prefs: { lang?: Lang; theme?: ThemeMode }) => {
      if (prefs.theme) setThemeMode(prefs.theme);
      if (prefs.lang) await setLang(prefs.lang);
      if (!user) return;
      try {
        setUser(await authApi.updateMe(prefs));
      } catch {
        /* the local choice stays; it will be saved with the next change */
      }
    },
    [user],
  );

  const value = useMemo(
    () => ({ status, user, login, activate, logout, savePrefs }),
    [status, user, login, activate, logout, savePrefs],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
