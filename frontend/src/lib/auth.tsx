import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import * as api from './api';

type AuthState = {
  user: api.User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  adopt: (s: api.Session) => void;
};

const Ctx = createContext<AuthState>({
  user: null, ready: false, login: async () => {}, register: async () => {}, logout: () => {}, adopt: () => {},
});
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<api.User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!api.getToken()) {
      setReady(true);
      return;
    }
    api.me().then((r) => setUser(r.user)).catch(() => api.setToken(null)).finally(() => setReady(true));
  }, []);

  const adopt = useCallback((s: api.Session) => {
    api.setToken(s.token);
    setUser(s.user);
  }, []);
  const login = useCallback(async (email: string, password: string) => adopt(await api.login(email, password)), [adopt]);
  const register = useCallback(async (email: string, password: string) => adopt(await api.register(email, password)), [adopt]);
  const logout = useCallback(() => {
    api.setToken(null);
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, ready, login, register, logout, adopt }), [user, ready, login, register, logout, adopt]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
