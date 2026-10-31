"use client";

import { createContext, useContext, useEffect, useState } from "react";

import { apiFetch, clearLegacyToken } from "@/lib/api-client";
import type { User } from "@/lib/types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName?: string) => Promise<void>;
  logout: () => Promise<void>;
  clearSession: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    clearLegacyToken();
    apiFetch<User>("/auth/me")
      .then((me) => { if (!cancelled) setUser(me); })
      .catch(() => { if (!cancelled) setUser(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // The API sets an httpOnly session cookie; the page never handles the token itself.
  async function login(email: string, password: string) {
    await apiFetch("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    setUser(await apiFetch<User>("/auth/me"));
  }

  async function register(email: string, password: string, fullName?: string) {
    await apiFetch("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name: fullName ?? null }),
    });
    setUser(await apiFetch<User>("/auth/me"));
  }

  async function logout() {
    try {
      await apiFetch("/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
    }
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, clearSession: () => setUser(null) }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
