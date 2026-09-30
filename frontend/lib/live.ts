/** The account's live event stream, once per tab, with the reconnects the first version
 *  did not have: a stream that ended (a proxy timeout, a rotated token, a sleeping laptop)
 *  simply stayed dead until the next reload, which read as "notifications only arrive when
 *  I refresh". Anyone on the page subscribes here instead of opening a second stream. */
import { hadSession } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { subscribeSse } from "@/lib/sse";
import { useAuth } from "@/stores/auth";

type Handler = (data: any) => void;
const handlers = new Map<string, Set<Handler>>();
let stop: (() => void) | null = null;
let attempt = 0;
let unauth = 0;
let timer: number | null = null;
let generation = 0;

export function onLive(event: string, fn: Handler): () => void {
  let set = handlers.get(event);
  if (!set) { set = new Set(); handlers.set(event, set); }
  set.add(fn);
  return () => { set!.delete(fn); };
}

function emit(event: string, data: any) {
  handlers.get(event)?.forEach((fn) => { try { fn(data); } catch { /* one listener must not break the rest */ } });
  handlers.get("*")?.forEach((fn) => { try { fn({ event, data }); } catch { /* ditto */ } });
}

function connect(gen: number) {
  if (gen !== generation) return;
  const token = useAuth.getState().token;
  if (!token) { timer = window.setTimeout(() => connect(gen), 1000); return; }
  let opened = false;
  const opening = () => { if (!opened) { opened = true; attempt = 0; unauth = 0; emit("$open", {}); } };
  stop = subscribeSse("/api/notifications/stream", token, (event, data) => {
    opening();        // 서버가 조용한 동안 붙은 경우까지 (onOpen 이 이미 불렸으면 아무 일도 없다)
    emit(event, data);
  }, (err) => {
    if (gen !== generation) return;
    stop = null;
    // A 401 that survived the refresh means the session itself is gone — the cookie
    // expired, or it was signed out elsewhere. Retrying that forever is what made an
    // idle tab produce a 401 every thirty seconds and never notice it had no session;
    // the next sign-in mounts the shell again and starts a new generation.
    //
    // "네 세션은 없다" 와 "갱신을 물어보지도 못했다" 는 다르다. 갱신이 401 을 받으면
    // markSession(false) 이 찍히고, 네트워크가 끊겨 물어보지 못한 경우에는 그대로다.
    // 후자까지 멈추면 잠깐 끊긴 것 때문에 알림이 영영 오지 않는다.
    if (err instanceof ApiError && err.status === 401) {
      unauth += 1;
      // 갱신이 "세션 없음" 이라고 답했으면 두드릴 것이 없다. 갱신을 물어보지도
      // 못한 경우(네트워크)는 다르므로 한 번 더 해 보고, 그래도 401 이면 멈춘다.
      // 어느 쪽이든 **401 을 무한히 만들지 않는다** — 그것이 이 버그였다.
      if (!hadSession() || unauth >= 2) { emit("$signedout", {}); return; }
    } else {
      unauth = 0;
    }
    // Back off from 1s to 30s; a fresh token is read on every attempt.
    const wait = Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5));
    attempt += 1;
    timer = window.setTimeout(() => connect(gen), wait);
  // 서버는 25초마다 한 줄을 보낸다. 70초 동안 아무것도 없으면 끊긴 것 — 다시 붙는다(plan/69).
  }, { refreshable: true, onOpen: opening, stallMs: 70_000 });
}

/** Start (or restart) the stream. Returns a function that stops it. */
export function startLive(): () => void {
  generation += 1;
  const gen = generation;
  if (timer) { window.clearTimeout(timer); timer = null; }
  stop?.(); stop = null;
  attempt = 0;
  unauth = 0;
  connect(gen);
  const onVisible = () => { if (document.visibilityState === "visible" && !stop && gen === generation) { if (timer) window.clearTimeout(timer); connect(gen); } };
  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("online", onVisible);
  return () => {
    generation += 1;
    if (timer) { window.clearTimeout(timer); timer = null; }
    stop?.(); stop = null;
    document.removeEventListener("visibilitychange", onVisible);
    window.removeEventListener("online", onVisible);
  };
}
