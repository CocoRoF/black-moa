"use client";
import { useCallback, useEffect, useRef } from "react";
import { toast } from "sonner";
import { useChat, type ChatMessage } from "@/stores/chat";
import { runTurnWithResume, resumeTurn, type TurnEvent } from "@/lib/sse";
import { ApiError, friendlyError } from "@/lib/errors";
import { uuid } from "@/lib/utils";
import { useLocale } from "@/lib/i18n";
import { onLive } from "@/lib/live";
import { post, get, type MessageOut } from "@/lib/api";

export interface TurnRunnerConfig {
  cid: string;
  startUrl: string;
  resumeUrl: (turnId: string) => string;
  cancelUrl: (turnId: string) => string;
  /** [그만] 을 대화 단위로 — 이 대화에서 지금 흐르는 답을, 번호를 몰라도, 누가 시작했든 멈춘다(plan/69). */
  stopUrl?: string;
  activeTurnUrl: string;
  messagesUrl: string;
  getToken: () => string | null;
  refreshable: boolean;
  /**
   * 주인의 대화: 다른 화면(다른 탭, PC 앱의 본창·아바타·빠른 대화)과 실시간으로 같게 둔다(plan/69).
   * 계정의 실시간 흐름에서 `turn` 소식을 듣고, 다른 곳에서 시작한 답은 처음부터 따라 받고, 끝나면 저장된 기록으로
   * 맞춘다. 다시 보일 때·다시 연결될 때도 같다.
   */
  live?: boolean;
  extraBody?: Record<string, unknown>;
  onError?: (e: unknown) => void;
  onComplete?: (ev: TurnEvent) => void;
  /** 이 화면이 받지 않은 답이 끝났을 때(다른 곳에서 한 말) — 크레딧·목록을 새로 받게. */
  onSynced?: () => void;
}

/** [그만] 을 누른 뒤 멈췄다는 소식을 이만큼 기다린다. 오지 않으면 이 화면만이라도 멈춘다. */
const STOP_WAIT_MS = 5000;

export function useTurnRunner(cfg: TurnRunnerConfig) {
  const locale = useLocale();
  const ac = useRef<AbortController | null>(null);
  const running = useRef(false);
  const pumping = useRef<Promise<void> | null>(null);
  const cfgRef = useRef(cfg); cfgRef.current = cfg;
  const store = useChat;
  /** 이 화면이 보낸 턴의 표(client_turn_id) — 자기 턴의 소식에 다시 따라 붙지 않게. */
  const mine = useRef(new Set<string>());
  /** 같은 턴을 계속 다시 따라 붙지 않게(서버가 "아직 흐른다" 고 하는데 이어 받기가 곧장 끝나는 경우). */
  const followed = useRef(new Map<string, number>());
  const syncGen = useRef(0);
  const syncAgain = useRef(false);

  const pump = useCallback(async (run: () => Promise<{ turnId: string | null; terminal: boolean }>) => {
    const c = cfgRef.current;
    running.current = true;
    let done!: () => void;
    pumping.current = new Promise<void>((r) => { done = r; });
    try {
      const res = await run();
      if (!res.terminal && !ac.current?.signal.aborted) {
        // could not finish: check server state once more
        const st = store.getState().convs[c.cid];
        if (st?.streamingMsgId) {
          store.getState().updateMessage(c.cid, st.streamingMsgId, { error: { code: "disconnected", message: friendlyError(new ApiError(0, "network", ""), locale), retryable: false } });
        }
      }
    } catch (e) {
      const st = store.getState().convs[c.cid];
      if (st?.streamingMsgId) store.getState().updateMessage(c.cid, st.streamingMsgId, { error: { code: e instanceof ApiError ? e.code : "error", message: friendlyError(e, locale) } });
      c.onError?.(e);
      if (e instanceof ApiError && e.status === 429) toast.error(friendlyError(e, locale));
    } finally {
      running.current = false;
      store.getState().endTurn(c.cid);
      store.getState().setConn(c.cid, navigator.onLine ? "idle" : "offline");
      done();
      pumping.current = null;
      // 답 하나가 끝났다(이 화면의 것이든 따라 받던 것이든). 저장된 기록으로 맞추고, 그사이 다른 곳에서 시작한
      // 답이 있으면 이어서 따라 받는다.
      if (cfgRef.current.live) void syncRef.current();
    }
  }, [locale, store]);

  const send = useCallback(async (text: string, attachments: { upload_id: string; filename: string; mime: string; url?: string; size?: number }[] = []) => {
    const c = cfgRef.current;
    if (running.current) return;
    const userMsg: ChatMessage = { id: `local-${uuid()}`, role: "user", content: text, cards: [], created_at: new Date().toISOString(), attachments: attachments.map((a) => ({ upload_id: a.upload_id, filename: a.filename, mime: a.mime, url: a.url, size: a.size })), pending: true };
    const asstId = `stream-${uuid()}`;
    store.getState().beginTurn(c.cid, userMsg, asstId);
    ac.current = new AbortController();
    const client_turn_id = uuid();
    mine.current.add(client_turn_id);
    const body: Record<string, unknown> = { text, client_turn_id, ...(c.extraBody ?? {}) };
    if (attachments.length) body.upload_ids = attachments.map((a) => a.upload_id);
    await pump(() => runTurnWithResume({
      url: c.startUrl, body, token: c.getToken(), getToken: c.getToken, refreshable: c.refreshable, signal: ac.current!.signal,
      resumeUrl: c.resumeUrl,
      // 번호를 받는 순간 보낸 말에도 적는다 — 저장된 기록과 맞출 때 같은 말로 알아본다.
      onTurnId: (tid) => { store.getState().setActiveTurn(c.cid, tid); store.getState().updateMessage(c.cid, userMsg.id, { pending: false, turn_id: tid }); },
      onEvent: (ev) => { store.getState().applyEvent(c.cid, ev); if (ev.type === "turn.complete") c.onComplete?.(ev); },
      onReconnecting: () => store.getState().setConn(c.cid, "reconnecting"),
      onReconnected: () => store.getState().setConn(c.cid, "streaming"),
    }));
  }, [pump, store]);

  /**
   * [그만]. 서버에 멈추라고 하고, 멈췄다는 소식(turn.cancelled)이 흐름으로 올 때까지 기다린다 — 그래야 이 화면도
   * 다른 화면과 같게 "중단됨" 으로 남는다. 소식이 오지 않으면(연결이 나쁘다) 이 화면만이라도 멈춘다.
   */
  const cancel = useCallback(async () => {
    const c = cfgRef.current;
    const st = store.getState().convs[c.cid];
    const tid = st?.activeTurnId;
    try {
      if (c.stopUrl) await post(c.stopUrl, undefined, { token: c.getToken(), auth: c.refreshable });
      else if (tid) await post(c.cancelUrl(tid), undefined, { token: c.getToken(), auth: c.refreshable });
    } catch { /* 아래에서 이 화면만이라도 멈춘다 */ }
    if (!running.current) return;
    const current = ac.current;
    setTimeout(() => { if (ac.current === current && running.current) current?.abort(); }, STOP_WAIT_MS);
  }, [store]);

  /** 흐르는 답을 이 화면에서만 놓는다(서버의 답은 계속된다) — 다른 대화로 옮길 때. */
  const detach = useCallback(async () => {
    ac.current?.abort();
    if (pumping.current) await pumping.current.catch(() => {});
  }, []);

  /** 다른 곳에서 시작한 답을 이 화면에서 처음부터 따라 받는다. 보낸 말은 서버 기록에 이미 있으므로 답의 자리만 만든다. */
  const followTurn = useCallback(async (turnId: string) => {
    const c = cfgRef.current;
    if (running.current) return;
    const n = followed.current.get(turnId) ?? 0;
    if (n >= 3) return;
    followed.current.set(turnId, n + 1);
    store.getState().beginTurn(c.cid, null, `stream-${uuid()}`);
    store.getState().setActiveTurn(c.cid, turnId);
    ac.current = new AbortController();
    await pump(async () => {
      const r = await resumeTurn({ url: c.resumeUrl(turnId), after: 0, token: c.getToken(), refreshable: c.refreshable, signal: ac.current!.signal, onEvent: (ev) => store.getState().applyEvent(c.cid, ev) });
      return { turnId, terminal: r.terminal };
    });
  }, [pump, store]);

  /**
   * 서버와 맞춘다(plan/69): 저장된 기록을 다시 읽어 합치고, 이 대화에 아직 흐르는 답이 있으면 따라 붙는다.
   * 이 화면이 답을 받는 중이면 끝난 뒤에 한 번 더 한다 — 받는 중인 자리를 기록으로 덮지 않게.
   */
  const sync = useCallback(async () => {
    const c = cfgRef.current;
    if (!c.cid) return;
    if (running.current) { syncAgain.current = true; return; }
    const gen = ++syncGen.current;
    try {
      const [msgs, active] = await Promise.all([
        get<{ items: MessageOut[] }>(c.messagesUrl, { token: c.getToken(), auth: c.refreshable, query: { limit: 100 } }),
        get<{ turn_id: string; seq: number } | null>(c.activeTurnUrl, { token: c.getToken(), auth: c.refreshable }),
      ]);
      if (gen !== syncGen.current || running.current || cfgRef.current.cid !== c.cid) return;
      store.getState().mergeServer(c.cid, msgs.items);
      c.onSynced?.();
      if (active?.turn_id) await followTurn(active.turn_id);
    } catch { /* 다음 소식·다시 보일 때 다시 */ }
    if (syncAgain.current && !running.current) { syncAgain.current = false; void syncRef.current(); }
  }, [followTurn, store]);
  const syncRef = useRef(sync); syncRef.current = sync;

  /** On tab return: if a turn is still running server-side, re-subscribe; else reconcile with server messages. */
  const reconcile = useCallback(async () => {
    const c = cfgRef.current;
    if (c.live) return syncRef.current();
    if (running.current) return;
    const st = store.getState().convs[c.cid];
    if (!st?.streamingMsgId) return;
    try {
      const active = await get<{ turn_id: string; seq: number } | null>(c.activeTurnUrl, { token: c.getToken(), auth: c.refreshable });
      // 다른 곳이 새로 시작한 턴이면 그 턴은 처음부터 받는다 — 앞 턴의 번호로 이어 받으면 앞부분이 빠진다.
      if (active?.turn_id) {
        const after = active.turn_id === st.activeTurnId ? st.lastSeq : 0;
        ac.current = new AbortController();
        store.getState().setActiveTurn(c.cid, active.turn_id);
        await pump(async () => {
          const r = await resumeTurn({ url: c.resumeUrl(active.turn_id), after, token: c.getToken(), refreshable: c.refreshable, signal: ac.current!.signal, onEvent: (ev) => store.getState().applyEvent(c.cid, ev) });
          return { turnId: active.turn_id, terminal: r.terminal };
        });
      } else {
        const r = await get<{ items: any[] }>(c.messagesUrl, { token: c.getToken(), auth: c.refreshable, query: { limit: 100 } });
        store.getState().setMessages(c.cid, r.items);
        store.getState().endTurn(c.cid);
      }
    } catch { /* ignore */ }
  }, [pump, store]);

  /** 바깥(PC 앱의 문, plan/62)이 "다시 보인다" 고 알릴 때 — 서버와 맞춘다. */
  const follow = useCallback(async () => {
    if (cfgRef.current.live) return syncRef.current();
    return reconcile();
  }, [reconcile]);

  // 계정의 실시간 흐름: 이 대화에서 답이 시작되거나 끝났다(plan/69).
  useEffect(() => {
    if (!cfg.live) return;
    const offTurn = onLive("turn", (data) => {
      const d = (data ?? {}) as { phase?: string; turn_id?: string; conversation_id?: string; client_turn_id?: string };
      const c = cfgRef.current;
      if (!d.turn_id || d.conversation_id !== c.cid) return;
      const st = store.getState().convs[c.cid];
      if (d.phase === "start") {
        if (d.client_turn_id && mine.current.has(d.client_turn_id)) return;   // 이 화면이 보낸 것
        if (running.current && st?.activeTurnId === d.turn_id) return;        // 이미 받는 중
      } else if (running.current && st?.activeTurnId === d.turn_id) {
        return;                                                               // 받던 흐름이 끝을 알린다
      }
      // 다른 곳의 답이 시작됐거나 끝났다. 받는 중이면 끝난 뒤에(그 답은 멈췄다는 소식을 받는다), 아니면 지금 맞춘다.
      void syncRef.current();
    });
    // 끊겼다 다시 붙었다 — 그사이 놓친 것을 맞춘다.
    const offOpen = onLive("$open", () => void syncRef.current());
    return () => { offTurn(); offOpen(); };
  }, [cfg.live, store]);

  useEffect(() => {
    const onVis = () => { if (document.visibilityState === "visible") void (cfgRef.current.live ? syncRef.current() : reconcile()); };
    const onOnline = () => { store.getState().setConn(cfgRef.current.cid, "idle"); void (cfgRef.current.live ? syncRef.current() : reconcile()); };
    const onOffline = () => store.getState().setConn(cfgRef.current.cid, "offline");
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("online", onOnline); window.addEventListener("offline", onOffline);
    return () => { document.removeEventListener("visibilitychange", onVis); window.removeEventListener("online", onOnline); window.removeEventListener("offline", onOffline); };
  }, [reconcile, store]);

  // abort on unmount
  useEffect(() => () => { ac.current?.abort(); }, []);

  return { send, cancel, reconcile, follow, sync, detach };
}
