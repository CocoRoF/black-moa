"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "@/stores/auth";
import { Auth, hadSession, refreshAccess } from "./api";
import { detectLocale } from "./utils";
import type { Locale } from "./i18n";

/** Hydrate from sessionStorage, then try a cookie refresh if no token.
 *  `optional` (marketing pages): skip the refresh round-trip when this browser never had a session. */
export function useSession(optional = false) {
  const { token, user, hydrated, hydrate } = useAuth();
  const [checked, setChecked] = useState(false);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; started.current = true;
    hydrate();
    (async () => {
      const t = useAuth.getState().token;
      if (!t && (!optional || hadSession())) await refreshAccess();
      setChecked(true);
    })();
  }, [hydrate, optional]);
  return { token, user, ready: hydrated && checked };
}

/** Client guard: redirect to /login?next= when unauthenticated (after refresh attempt). */
export function useRequireAuth(role?: "admin") {
  const s = useSession();
  const router = useRouter();
  useEffect(() => {
    if (!s.ready) return;
    if (!s.token || !s.user) {
      const here = window.location.pathname + window.location.search;
      router.replace(`/login?next=${encodeURIComponent(here)}`);
    } else if (role === "admin" && s.user.role !== "admin") {
      toast.error(s.user.locale === "en" ? "Administrators only." : "관리자만 들어갈 수 있는 곳이에요.");
      router.replace("/app");
    }
  }, [s.ready, s.token, s.user, role, router]);
  return { ...s, ok: s.ready && !!s.token && !!s.user && (role !== "admin" || s.user.role === "admin") };
}

/** 이 서비스에서 음성을 쓰는가 (plan/67). 알기 전에는 감춘다 — 꺼진 단추가 잠깐 보였다 사라지지 않게. */
export function useVoiceFeatures(): { stt: boolean; tts: boolean } {
  const { data } = useQuery({ queryKey: ["auth-status"], queryFn: Auth.status, staleTime: 60_000 });
  return { stt: !!data?.voice?.stt, tts: !!data?.voice?.tts };
}

/** 기업 기능을 쓰는가 (plan/71). ``ready`` 전에는 감춘다 — 꺼진 탭·칸이 잠깐 보였다 사라지지 않게. */
export function useCompanyFeatures(): { on: boolean; ready: boolean } {
  const { data } = useQuery({ queryKey: ["auth-status"], queryFn: Auth.status, staleTime: 60_000 });
  return { on: data?.companies !== false && !!data, ready: !!data };
}

export function useBrowserLocale(): Locale {
  const [l, setL] = useState<Locale>("ko");
  useEffect(() => { setL(detectLocale()); }, []);
  return l;
}

export function useMediaQuery(q: string) {
  const [m, setM] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(q);
    setM(mq.matches);
    const h = (e: MediaQueryListEvent) => setM(e.matches);
    mq.addEventListener("change", h);
    return () => mq.removeEventListener("change", h);
  }, [q]);
  return m;
}

export function useOnline() {
  const [on, setOn] = useState(true);
  useEffect(() => {
    setOn(navigator.onLine);
    const a = () => setOn(true), b = () => setOn(false);
    window.addEventListener("online", a); window.addEventListener("offline", b);
    return () => { window.removeEventListener("online", a); window.removeEventListener("offline", b); };
  }, []);
  return on;
}

export function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

export function useObjectUrl(loader: (() => Promise<string>) | null, deps: unknown[] = []) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let alive = true; let u: string | null = null;
    if (loader) loader().then((x) => { if (alive) { u = x; setUrl(x); } else URL.revokeObjectURL(x); }).catch(() => { if (alive) setUrl(null); });
    return () => { alive = false; if (u) URL.revokeObjectURL(u); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return url;
}
