"use client";
import { useSyncExternalStore } from "react";

/** The compare tray (plan/40 §7): up to four company ids the reader has picked, kept in
 *  this browser so a pick on one page is still there on the next. A tray is a per-viewer
 *  convenience, not shared state — nothing about it needs the server. */
const KEY = "memora:cx:compare";
export const COMPARE_MAX = 4;

type Entry = { id: string; name: string };
let cache: Entry[] | null = null;
const listeners = new Set<() => void>();

function read(): Entry[] {
  if (cache) return cache;
  try {
    const raw = typeof window === "undefined" ? null : window.localStorage.getItem(KEY);
    const parsed = raw ? (JSON.parse(raw) as Entry[]) : [];
    cache = Array.isArray(parsed) ? parsed.filter((e) => e && typeof e.id === "string").slice(0, COMPARE_MAX) : [];
  } catch { cache = []; }
  return cache;
}
function write(next: Entry[]) {
  cache = next.slice(0, COMPARE_MAX);
  try { window.localStorage.setItem(KEY, JSON.stringify(cache)); } catch { /* private mode: the tray lives for this page only */ }
  listeners.forEach((l) => l());
}
const EMPTY: Entry[] = [];

export const compareStore = {
  subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l); }; },
  get: read,
  has: (id: string) => read().some((e) => e.id === id),
  /** Returns false when the tray is full. */
  add(e: Entry): boolean {
    const cur = read();
    if (cur.some((x) => x.id === e.id)) return true;
    if (cur.length >= COMPARE_MAX) return false;
    write([...cur, e]); return true;
  },
  remove(id: string) { write(read().filter((e) => e.id !== id)); },
  toggle(e: Entry): "added" | "removed" | "full" {
    if (read().some((x) => x.id === e.id)) { compareStore.remove(e.id); return "removed"; }
    return compareStore.add(e) ? "added" : "full";
  },
  clear() { write([]); },
};

export function useCompare(): Entry[] {
  return useSyncExternalStore(compareStore.subscribe, read, () => EMPTY);
}
