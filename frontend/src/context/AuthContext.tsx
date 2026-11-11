import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, setAccessToken } from "../lib/api";
import { invalidateRecommendationQueries } from "../lib/queryInvalidation";
import { clearUserBrowserState } from "../lib/sessionCleanup";
import type { Industry, User } from "../types/cinema";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (email: string, username: string, password: string) => Promise<User>;
  googleLogin: (credential: string) => Promise<User>;
  logout: () => Promise<void>;
  saveOnboarding: (genres: string[], industries: Industry[]) => Promise<User>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const queryClient = useQueryClient();

  useEffect(() => {
    const onExpired = () => {
      setAccessToken(null);
      setUser(null);
      clearUserBrowserState(queryClient);
    };
    window.addEventListener("ac:auth-expired", onExpired);
    return () => window.removeEventListener("ac:auth-expired", onExpired);
  }, [queryClient]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const { has_session } = await api.hasSession();
        if (!active) return;
        if (!has_session) {
          setAccessToken(null);
          setUser(null);
          return;
        }
        const res = await api.refresh();
        if (active) {
          setAccessToken(res.access_token);
          setUser(res.user);
        }
      } catch {
        if (active) {
          setAccessToken(null);
          setUser(null);
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api.login({ email, password });
      clearUserBrowserState(queryClient);
      setAccessToken(res.access_token);
      setUser(res.user);
      return res.user;
    },
    [queryClient]
  );

  const register = useCallback(
    async (email: string, username: string, password: string) => {
      const res = await api.register({ email, username, password });
      clearUserBrowserState(queryClient);
      setAccessToken(res.access_token);
      setUser(res.user);
      return res.user;
    },
    [queryClient]
  );

  const googleLogin = useCallback(
    async (credential: string) => {
      const res = await api.googleSignIn(credential);
      clearUserBrowserState(queryClient);
      setAccessToken(res.access_token);
      setUser(res.user);
      return res.user;
    },
    [queryClient]
  );

  const logout = useCallback(async () => {
    setAccessToken(null);
    setUser(null);
    clearUserBrowserState(queryClient);
    try {
      await api.logout();
    } catch {
      // Ignore network errors on logout; client state is already cleared
    }
  }, [queryClient]);

  const saveOnboarding = useCallback(
    async (genres: string[], industries: Industry[]) => {
      const updated = await api.saveOnboarding({
        preferred_genres: genres,
        preferred_industries: industries,
      });
      setUser(updated);
      invalidateRecommendationQueries(queryClient);
      return updated;
    },
    [queryClient]
  );

  const refreshUser = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me);
    } catch {
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, googleLogin, logout, saveOnboarding, refreshUser }),
    [user, loading, login, register, googleLogin, logout, saveOnboarding, refreshUser]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
