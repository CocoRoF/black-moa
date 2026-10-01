import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

export function isBrowser() {
  return typeof window !== "undefined";
}

export function safeStorage(kind: "local" | "session"): Storage | null {
  try {
    if (!isBrowser()) return null;
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function storageGet(kind: "local" | "session", key: string): string | null {
  try { return safeStorage(kind)?.getItem(key) ?? null; } catch { return null; }
}
export function storageSet(kind: "local" | "session", key: string, value: string | null) {
  try {
    const s = safeStorage(kind);
    if (!s) return;
    if (value === null) s.removeItem(key); else s.setItem(key, value);
  } catch { /* ignore */ }
}

/** Carry per-browser state across the 2026-09-09 rename.
 *
 *  The keys are namespaced `blackmoa:` now. Without this, every signed-in browser would look
 *  logged out (the "had a session" flag is what triggers the silent refresh), every
 *  anonymous visitor to a shared secretary would start over, and the sidebar would forget
 *  itself. Runs once per load and is a no-op after the first. */
export function migrateStorageKeys() {
  for (const kind of ["local", "session"] as const) {
    const s = safeStorage(kind);
    if (!s) continue;
    try {
      for (const key of Object.keys(s)) {
        if (!key.startsWith("mfsg:")) continue;
        const next = "blackmoa:" + key.slice(5);
        if (s.getItem(next) === null) s.setItem(next, s.getItem(key) ?? "");
        s.removeItem(key);
      }
    } catch { /* private mode and blocked site data both throw; the app works without it */ }
  }
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select(); document.execCommand("copy"); document.body.removeChild(ta);
      return true;
    } catch { return false; }
  }
}

export function clamp(n: number, lo: number, hi: number) { return Math.min(hi, Math.max(lo, n)); }

export function initials(name?: string | null) {
  if (!name) return "?";
  const t = name.trim();
  if (!t) return "?";
  const parts = t.split(/\s+/);
  if (parts.length >= 2 && /^[A-Za-z]/.test(parts[0])) return (parts[0][0] + parts[1][0]).toUpperCase();
  return t.slice(0, 1);
}

export function hexToRgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function isDarkColor(hex: string) {
  const rgb = hexToRgb(hex);
  if (!rgb) return true;
  const [r, g, b] = rgb.map((v) => v / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.55;
}

export function detectLocale(): "ko" | "en" {
  if (!isBrowser()) return "ko";
  const l = (navigator.language || "ko").toLowerCase();
  return l.startsWith("ko") ? "ko" : "en";
}

export function isIOS() {
  if (!isBrowser()) return false;
  return /iP(hone|od|ad)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

