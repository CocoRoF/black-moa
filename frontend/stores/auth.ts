"use client";
import { create } from "zustand";
import { storageGet, storageSet } from "@/lib/utils";
import { desktopHost } from "@/lib/desktop";

export interface User {
  id: string;
  email: string;
  display_name: string;
  nickname?: string;
  name_confirmed?: boolean;
  role: "user" | "admin";
  /** The single maintainer: the only admin who may grant or revoke admin (plan/31). */
  is_super?: boolean;
  locale: "ko" | "en";
  timezone: string;
  avatar_url: string | null;
  plan_id: string | null;
  onboarding_state: Record<string, unknown>;
  /** Whether this person's public page may be listed in search results. */
  page_indexable?: boolean;
  /** Who may see the people I am connected to: "all" or "friends" (plan/43 §5). */
  /** 프로필에서 내 인맥 목록을 누가 보나 — 서버가 세 범위 중 하나로 준다 (옛 값은 normalize 가 옮긴다). */
  network_public?: "public" | "known" | "private" | "all" | "friends" | "none";
  /** Whether my own secretaries may use my 인맥 at all. */
  network_to_secretary?: boolean;
  email_verified: boolean;
  /** 동의한 이용약관·개인정보 처리방침의 판 (plan/73). 지금 판과 다르면 앱이 한 번 동의를 받는다. */
  terms_version?: string | null;
  created_at: string | null;
}

interface AuthState {
  token: string | null;
  user: User | null;
  hydrated: boolean;
  setAuth: (token: string, user: User) => void;
  setUser: (user: User) => void;
  clear: () => void;
  hydrate: () => void;
}

const KEY_U = "memora:user";
const VISIT_PREFIX = "memora:v:";

/** 앱에게 지금 토큰을 알려 준다.
 *
 *  앱이 자기 갱신 쿠키로 따로 갱신하면 서버가 토큰 도난으로 보고 세션을 끊는다.
 *  그래서 갱신하는 쪽은 여기 하나이고, 앱은 결과만 받아 간다. 호스트가 없으면
 *  (곧 보통의 브라우저이면) 아무 일도 일어나지 않는다. */
function tellHost(token: string | null) {
  const h = desktopHost();
  if (!h?.desktop) return;
  try {
    if (token) h.token?.(token);
    else h.signedOut?.();
  } catch { /* 다리가 없어도 웹은 그대로 돈다 */ }
}

/** Drop every stored visit that was made under an account. Anonymous visits stay: they
 *  belong to the browser, not to anyone who signed in. */
function forgetBoundVisits() {
  try {
    const ls = window.localStorage;
    for (const k of Object.keys(ls)) {
      if (!k.startsWith(VISIT_PREFIX)) continue;
      try { if (JSON.parse(ls.getItem(k) ?? "{}")?.uid) ls.removeItem(k); } catch { /* leave malformed entries */ }
    }
  } catch { /* storage can be unavailable; the server refuses these sessions anyway */ }
}

export const useAuth = create<AuthState>((set) => ({
  token: null,
  user: null,
  hydrated: false,
  setAuth: (token, user) => {
    // Access tokens are deliberately memory-only. A DOM XSS should not gain a
    // reload-persistent bearer credential from Web Storage; reload/session
    // recovery is performed through the HttpOnly refresh cookie instead.
    storageSet("session", KEY_U, JSON.stringify(user));
    storageSet("local", "memora:had-session", "1");
    tellHost(token);
    set({ token, user, hydrated: true });
  },
  setUser: (user) => {
    storageSet("session", KEY_U, JSON.stringify(user));
    set({ user });
  },
  clear: () => {
    // Remove the legacy key as part of migration from older frontend builds.
    storageSet("session", "memora:access", null);
    storageSet("session", KEY_U, null);
    // Signing out has to reach the shared-secretary pages too: a visitor session created
    // while signed in speaks under this account's name, and it must not outlive the
    // account session on this device.
    forgetBoundVisits();
    storageSet("local", "memora:had-session", null);
    tellHost(null);
    set({ token: null, user: null, hydrated: true });
  },
  hydrate: () => {
    // Only non-secret display state is restored synchronously. useSession then
    // performs a single-flight refresh when memora:had-session is present.
    const u = storageGet("session", KEY_U);
    // Proactively erase bearer tokens left behind by previous releases.
    storageSet("session", "memora:access", null);
    let user: User | null = null;
    try { user = u ? (JSON.parse(u) as User) : null; } catch { user = null; }
    set({ token: null, user, hydrated: true });
  },
}));

export function getToken() { return useAuth.getState().token; }
