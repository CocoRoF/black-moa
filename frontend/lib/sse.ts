"use client";
import { ApiError } from "./errors";
import { parseError, refreshAccess } from "./api";
import { sleep } from "./utils";

export type TurnEventType =
  | "turn.start" | "text.delta" | "thinking.delta" | "thinking.status" | "tool.start" | "tool.end" | "card"
  | "memory.retrieved" | "guard.redacted" | "usage" | "notice" | "turn.complete" | "turn.error" | "turn.cancelled";

export interface TurnEvent { seq: number; type: TurnEventType | string; at: string; data: Record<string, any> }

export const TERMINAL = new Set(["turn.complete", "turn.error", "turn.cancelled"]);

interface RawBlock { id?: string; event?: string; data: string }

/** Parse a text/event-stream body, invoking onBlock per event block. Ignores comment lines (": ping").
 *  `onChunk` hears every read, pings included — the watchdog below uses it to tell a quiet stream from a dead one. */
export async function readSse(body: ReadableStream<Uint8Array>, onBlock: (b: RawBlock) => void, signal?: AbortSignal, onChunk?: () => void) {
  const reader = body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let cur: RawBlock = { data: "" };
  let hasData = false;
  const flush = () => {
    if (hasData) onBlock({ ...cur, data: cur.data.replace(/\n$/, "") });
    cur = { data: "" }; hasData = false;
  };
  try {
    while (true) {
      if (signal?.aborted) break;
      const { value, done } = await reader.read();
      if (done) break;
      onChunk?.();
      buf += dec.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf("\n")) >= 0) {
        let line = buf.slice(0, idx);
        buf = buf.slice(idx + 1);
        if (line.endsWith("\r")) line = line.slice(0, -1);
        if (line === "") { flush(); continue; }
        if (line.startsWith(":")) continue;
        const c = line.indexOf(":");
        const field = c === -1 ? line : line.slice(0, c);
        let val = c === -1 ? "" : line.slice(c + 1);
        if (val.startsWith(" ")) val = val.slice(1);
        if (field === "data") { cur.data += val + "\n"; hasData = true; }
        else if (field === "event") cur.event = val;
        else if (field === "id") cur.id = val;
      }
    }
    if (buf.trim()) { const rest = buf; buf = ""; if (rest.startsWith("data:")) { cur.data += rest.slice(5).trimStart(); hasData = true; } }
    flush();
  } finally {
    try { reader.releaseLock(); } catch { /* ignore */ }
  }
}

export interface StreamOptions {
  url: string;
  body?: unknown;
  token: string | null;
  method?: "POST" | "GET";
  onEvent: (ev: TurnEvent) => void;
  onTurnId?: (turnId: string) => void;
  signal?: AbortSignal;
  /** owner tokens get refreshed on 401 (visitor tokens don't) */
  refreshable?: boolean;
  getToken?: () => string | null;
}

/** 서버는 답이 조용해도 15초마다 한 줄을 보낸다. 이만큼 아무것도 오지 않으면 끊긴 것으로 보고 이어 받는다(plan/69) —
 *  반쯤 열린 연결이 "답하는 중" 을 영원히 붙잡고 있지 않게. */
const STALL_MS = 45_000;

/** Start a turn (POST) or subscribe (GET) and pump events. Resolves when the stream ends (any reason). Throws ApiError on HTTP errors. */
export async function streamTurn(o: StreamOptions): Promise<{ lastSeq: number; terminal: boolean }> {
  const inner = new AbortController();
  const onOuter = () => inner.abort();
  if (o.signal?.aborted) inner.abort();
  o.signal?.addEventListener("abort", onOuter);
  let stall: ReturnType<typeof setTimeout> | undefined;
  const arm = () => { if (stall) clearTimeout(stall); stall = setTimeout(() => inner.abort(), STALL_MS); };
  try {
    return await streamTurnInner(o, inner.signal, arm);
  } finally {
    if (stall) clearTimeout(stall);
    o.signal?.removeEventListener("abort", onOuter);
  }
}

async function streamTurnInner(o: StreamOptions, signal: AbortSignal, arm: () => void): Promise<{ lastSeq: number; terminal: boolean }> {
  const doFetch = async (tok: string | null) => {
    const headers: Record<string, string> = { Accept: "text/event-stream" };
    if (tok) headers.Authorization = `Bearer ${tok}`;
    let payload: string | undefined;
    if (o.body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(o.body); }
    return fetch(o.url, { method: o.method ?? (o.body !== undefined ? "POST" : "GET"), headers, body: payload, signal, cache: "no-store" });
  };
  let r = await doFetch(o.token);
  if (r.status === 401 && o.refreshable) {
    const fresh = await refreshAccess();
    if (fresh) r = await doFetch(fresh);
  }
  if (!r.ok) throw await parseError(r);
  const tid = r.headers.get("X-Turn-Id");
  if (tid) o.onTurnId?.(tid);
  if (!r.body) throw new ApiError(0, "network", "no body");
  let lastSeq = 0; let terminal = false;
  arm();
  await readSse(r.body, (b) => {
    if (!b.data) return;
    let ev: TurnEvent | null = null;
    try { ev = JSON.parse(b.data) as TurnEvent; } catch { return; }
    if (!ev || typeof ev !== "object") return;
    if (typeof ev.seq !== "number" && b.id) ev.seq = parseInt(b.id, 10) || 0;
    if (!ev.type && b.event) ev.type = b.event;
    if (ev.seq > lastSeq) lastSeq = ev.seq;
    if (TERMINAL.has(ev.type)) terminal = true;
    o.onEvent(ev);
  }, signal, arm);
  return { lastSeq, terminal };
}

export function resumeTurn(o: Omit<StreamOptions, "body" | "method"> & { after: number }) {
  const sep = o.url.includes("?") ? "&" : "?";
  return streamTurn({ ...o, url: `${o.url}${sep}after=${o.after}`, method: "GET" });
}

/**
 * Run a turn with automatic resume on network failure (exponential backoff 0.5s→8s, max 6 tries).
 * `resumeUrl` is the events endpoint (without ?after=).
 */
export async function runTurnWithResume(o: StreamOptions & { resumeUrl: (turnId: string) => string; onReconnecting?: (attempt: number) => void; onReconnected?: () => void }) {
  let turnId: string | null = null;
  let lastSeq = 0;
  const seen = new Set<number>();
  const onEvent = (ev: TurnEvent) => {
    if (ev.seq && seen.has(ev.seq)) return;
    if (ev.seq) { seen.add(ev.seq); if (ev.seq > lastSeq) lastSeq = ev.seq; }
    o.onEvent(ev);
  };
  const onTurnId = (id: string) => { turnId = id; o.onTurnId?.(id); };
  try {
    const res = await streamTurn({ ...o, onEvent, onTurnId });
    if (res.terminal || o.signal?.aborted) return { turnId, lastSeq: res.lastSeq, terminal: res.terminal };
  } catch (e) {
    if (o.signal?.aborted) return { turnId, lastSeq, terminal: false };
    if (e instanceof ApiError && e.status > 0) throw e; // HTTP error → surface immediately (no resume without turn)
    if (!turnId) throw e;
  }
  // stream ended without terminal → resume loop
  let delay = 500;
  for (let attempt = 1; attempt <= 6; attempt++) {
    if (o.signal?.aborted || !turnId) break;
    o.onReconnecting?.(attempt);
    await sleep(delay);
    delay = Math.min(delay * 2, 8000);
    try {
      const tok = o.getToken ? o.getToken() : o.token;
      const res = await resumeTurn({ ...o, token: tok, onEvent, url: o.resumeUrl(turnId), after: lastSeq });
      o.onReconnected?.();
      if (res.terminal || o.signal?.aborted) return { turnId, lastSeq, terminal: res.terminal };
    } catch (e) {
      if (o.signal?.aborted) break;
      if (e instanceof ApiError && e.status === 404) throw e;
    }
  }
  return { turnId, lastSeq, terminal: false };
}

/** Generic SSE subscription for non-turn streams (notifications, admin login events).
 *  Returns an abort function.
 *
 *  `refreshable` is the same switch `streamTurn` has, and for the same reason: an access
 *  token lives fifteen minutes while a stream is meant to stay open for hours, so the
 *  first thing a long subscription meets is a 401. Only owner streams may ask for it — a
 *  visitor token must never reach for the account's refresh cookie. */
export function subscribeSse(url: string, token: string | null, onEvent: (event: string, data: any) => void,
                             onEnd?: (err?: unknown) => void,
                             opts: { refreshable?: boolean; onOpen?: () => void; stallMs?: number } = {}) {
  const ac = new AbortController();
  // 조용한 것과 끊긴 것을 가른다(plan/69): 서버는 조용해도 잠깐마다 한 줄을 보낸다. 그만큼 아무것도 오지 않으면
  // 반쯤 열린 연결이다 — 끊고 onEnd 로 알려 다시 붙게 한다. 그러지 않으면 실시간 소식이 조용히 멈춘다.
  let stalled = false;
  let stall: ReturnType<typeof setTimeout> | undefined;
  const arm = () => {
    if (!opts.stallMs) return;
    if (stall) clearTimeout(stall);
    stall = setTimeout(() => { stalled = true; ac.abort(); }, opts.stallMs);
  };
  (async () => {
    try {
      const doFetch = (tok: string | null) => {
        const headers: Record<string, string> = { Accept: "text/event-stream" };
        if (tok) headers.Authorization = `Bearer ${tok}`;
        return fetch(url, { headers, signal: ac.signal, cache: "no-store" });
      };
      let r = await doFetch(token);
      if (r.status === 401 && opts.refreshable) {
        const fresh = await refreshAccess();
        if (fresh) r = await doFetch(fresh);
      }
      if (!r.ok || !r.body) throw await parseError(r);
      // **붙었다는 것은 첫 이벤트가 아니라 여기다.** 알림 스트림은 아무 일도 없으면
      // 몇 시간이고 조용하므로, 첫 이벤트를 기다리면 "다시 붙었다" 는 소식이 영영
      // 오지 않는다 — 놓친 것을 다시 불러오는 일도 그때까지 일어나지 않았다.
      opts.onOpen?.();
      arm();
      await readSse(r.body, (b) => {
        let data: any = b.data;
        try { data = JSON.parse(b.data); } catch { /* keep string */ }
        onEvent(b.event ?? data?.kind ?? "message", data);
      }, ac.signal, arm);
      if (stall) clearTimeout(stall);
      onEnd?.(stalled ? new ApiError(0, "stalled", "stream stalled") : undefined);
    } catch (e) {
      if (stall) clearTimeout(stall);
      if (stalled) onEnd?.(new ApiError(0, "stalled", "stream stalled"));
      else if (!ac.signal.aborted) onEnd?.(e);
    }
  })();
  return () => { if (stall) clearTimeout(stall); ac.abort(); };
}
