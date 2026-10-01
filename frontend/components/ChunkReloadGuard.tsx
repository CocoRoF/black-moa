"use client";
import { useEffect } from "react";

const KEY = "blackmoa:chunk-reload";
/** After a deploy, stale clients hit ChunkLoadError — reload once (sessionStorage breaks loops). */
export function ChunkReloadGuard() {
  useEffect(() => {
    const isChunkErr = (msg: unknown) => typeof msg === "string" && /ChunkLoadError|Loading chunk [\d\w-]+ failed|Failed to fetch dynamically imported module|Importing a module script failed/i.test(msg);
    const handle = () => {
      try {
        const last = Number(sessionStorage.getItem(KEY) ?? 0);
        if (Date.now() - last < 60_000) return;
        sessionStorage.setItem(KEY, String(Date.now()));
      } catch { /* ignore */ }
      window.location.reload();
    };
    const onErr = (e: ErrorEvent) => { if (isChunkErr(e.message) || isChunkErr((e.error as Error | undefined)?.message)) handle(); };
    const onRej = (e: PromiseRejectionEvent) => { const r = e.reason as { message?: string; name?: string } | undefined; if (isChunkErr(r?.message) || r?.name === "ChunkLoadError") handle(); };
    window.addEventListener("error", onErr); window.addEventListener("unhandledrejection", onRej);
    return () => { window.removeEventListener("error", onErr); window.removeEventListener("unhandledrejection", onRej); };
  }, []);
  return null;
}
