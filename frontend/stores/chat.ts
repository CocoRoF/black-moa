"use client";
import { create } from "zustand";
import type { CardData, MessageOut } from "@/lib/api";
import type { TurnEvent } from "@/lib/sse";

export interface ToolChipState { call_id: string; name: string; label: string; label_en?: string; input_preview?: string; done: boolean; is_error?: boolean; duration_ms?: number; output_preview?: string }
export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "card" | "system";
  content: string;
  cards: CardData[];
  attachments?: any[];
  created_at: string;
  turn_id?: string | null;
  feedback?: { verdict: string; note: string };
  streaming?: boolean;
  tools?: ToolChipState[];
  thinking?: boolean;
  thinkingText?: string;
  notices?: string[];
  redacted?: number;
  memory?: { count: number; chars: number };
  usage?: { input_tokens: number; output_tokens: number; cache_read: number; credits: number; balance_after: number };
  error?: { code: string; message: string; retryable?: boolean };
  cancelled?: boolean;
  /** 왜 멈췄나: 누가 [그만] 을 눌렀다 · 다른 화면(탭·PC 앱)에서 새로 물었다 (plan/69). */
  stopReason?: "cancelled" | "superseded";
  /** 이 말로 시작한 턴이 답을 받지 못했다 — 어느 화면에서 열어도 그렇게 보인다. */
  failedTurn?: boolean;
  pending?: boolean;
}

export type ConnState = "idle" | "streaming" | "reconnecting" | "offline";

interface ConvState {
  messages: ChatMessage[];
  loaded: boolean;
  activeTurnId: string | null;
  streamingMsgId: string | null;
  conn: ConnState;
  lastSeq: number;
}

interface ChatStore {
  convs: Record<string, ConvState>;
  ensure: (cid: string) => ConvState;
  setMessages: (cid: string, msgs: MessageOut[]) => void;
  /** 서버에 저장된 기록으로 맞춘다(plan/69). 이 화면이 흐르며 받은 것(도구·크레딧·기억)은 같은 말에 남긴다. */
  mergeServer: (cid: string, msgs: MessageOut[]) => void;
  prependMessages: (cid: string, msgs: MessageOut[]) => void;
  addMessage: (cid: string, m: ChatMessage) => void;
  updateMessage: (cid: string, id: string, patch: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>)) => void;
  removeMessage: (cid: string, id: string) => void;
  /** userMsg 가 null 이면 답의 자리만 만든다 — 다른 곳에서 보낸 말의 답을 따라갈 때(plan/62). */
  beginTurn: (cid: string, userMsg: ChatMessage | null, assistantMsgId: string) => void;
  applyEvent: (cid: string, ev: TurnEvent) => void;
  /** The last relationship milestone a turn reported (plan/37); the chat surface toasts it. */
  milestone: { agent_id: string; stage: string; milestones: string[]; days_together: number; seq: number } | null;
  setConn: (cid: string, conn: ConnState) => void;
  setActiveTurn: (cid: string, turnId: string | null) => void;
  endTurn: (cid: string) => void;
  reset: (cid: string) => void;
}

const empty = (): ConvState => ({ messages: [], loaded: false, activeTurnId: null, streamingMsgId: null, conn: "idle", lastSeq: 0 });

export function fromServer(m: MessageOut): ChatMessage {
  return { id: m.id, role: m.role, content: m.content ?? "", cards: m.cards ?? [], attachments: m.attachments, created_at: m.created_at, turn_id: m.turn_id ?? null, feedback: m.feedback };
}

/** 흐르는 동안에만 알 수 있던 것 — 저장된 기록에는 없으니 같은 말에 그대로 남긴다. */
const TRANSIENT = ["tools", "usage", "memory", "notices", "redacted", "thinkingText", "error"] as const;

export const useChat = create<ChatStore>((set, get) => ({
  convs: {},
  milestone: null,
  ensure: (cid) => {
    const c = get().convs[cid];
    if (c) return c;
    const n = empty();
    set((s) => ({ convs: { ...s.convs, [cid]: n } }));
    return n;
  },
  setMessages: (cid, msgs) => set((s) => ({ convs: { ...s.convs, [cid]: { ...(s.convs[cid] ?? empty()), messages: msgs.map(fromServer), loaded: true } } })),
  mergeServer: (cid, msgs) => set((s) => {
    const c = s.convs[cid] ?? empty();
    const byId = new Map(c.messages.map((m) => [m.id, m]));
    // 이 화면에서 보낸 말은 서버 번호를 모른 채 있었다(local-…). 같은 턴의 같은 쪽 말로 찾아 잇는다.
    const byTurn = new Map(c.messages.filter((m) => m.turn_id).map((m) => [`${m.turn_id}:${m.role}`, m]));
    const sorted = [...msgs].sort((x, y) => x.created_at.localeCompare(y.created_at));
    const lastOfTurn = new Map<string, string>();
    for (const m of sorted) if (m.turn_id) lastOfTurn.set(m.turn_id, m.id);
    const messages = sorted.map((mo) => {
      const base = fromServer(mo);
      const prev = byId.get(mo.id) ?? (mo.turn_id ? byTurn.get(`${mo.turn_id}:${mo.role}`) : undefined);
      const keep: Partial<ChatMessage> = {};
      if (prev) for (const k of TRANSIENT) if (prev[k] !== undefined) (keep as Record<string, unknown>)[k] = prev[k];
      // 끝까지 가지 못한 턴은 그 턴의 마지막 말 아래에 한 번만 적는다 — 답이 한 글자도 오기 전에 멈췄으면 보낸 말
      // 아래에. 받지 못한 턴은 이 화면이 받은 자세한 오류가 있으면 그것을 둔다.
      const last = !!mo.turn_id && lastOfTurn.get(mo.turn_id) === mo.id;
      const stopped = last && (mo.turn_status === "cancelled" || mo.turn_status === "superseded");
      const failed = last && mo.turn_status === "failed" && !keep.error;
      return { ...base, ...keep, ...(stopped ? { cancelled: true, stopReason: mo.turn_status as "cancelled" | "superseded" } : {}),
               ...(failed ? { failedTurn: true } : {}) };
    });
    return { convs: { ...s.convs, [cid]: { ...c, messages, loaded: true, streamingMsgId: null, activeTurnId: null, lastSeq: 0,
                                           conn: c.conn === "offline" ? "offline" : "idle" } } };
  }),
  prependMessages: (cid, msgs) => set((s) => { const c = s.convs[cid] ?? empty(); const ids = new Set(c.messages.map((m) => m.id)); return { convs: { ...s.convs, [cid]: { ...c, messages: [...msgs.map(fromServer).filter((m) => !ids.has(m.id)), ...c.messages] } } }; }),
  addMessage: (cid, m) => set((s) => { const c = s.convs[cid] ?? empty(); return { convs: { ...s.convs, [cid]: { ...c, messages: [...c.messages, m] } } }; }),
  updateMessage: (cid, id, patch) => set((s) => {
    const c = s.convs[cid]; if (!c) return s;
    return { convs: { ...s.convs, [cid]: { ...c, messages: c.messages.map((m) => (m.id === id ? { ...m, ...(typeof patch === "function" ? patch(m) : patch) } : m)) } } };
  }),
  removeMessage: (cid, id) => set((s) => { const c = s.convs[cid]; if (!c) return s; return { convs: { ...s.convs, [cid]: { ...c, messages: c.messages.filter((m) => m.id !== id) } } }; }),
  beginTurn: (cid, userMsg, assistantMsgId) => set((s) => {
    const c = s.convs[cid] ?? empty();
    const a: ChatMessage = { id: assistantMsgId, role: "assistant", content: "", cards: [], created_at: new Date().toISOString(), streaming: true, tools: [] };
    return { convs: { ...s.convs, [cid]: { ...c, messages: [...c.messages, ...(userMsg ? [userMsg] : []), a], streamingMsgId: assistantMsgId, conn: "streaming", lastSeq: 0 } } };
  }),
  applyEvent: (cid, ev) => set((s) => {
    const c = s.convs[cid]; if (!c) return s;
    const mid = c.streamingMsgId; if (!mid) return s;
    const d = ev.data ?? {};
    let activeTurnId = c.activeTurnId;
    let milestone = s.milestone;
    const lastSeq = Math.max(c.lastSeq, ev.seq ?? 0);
    const messages = c.messages.map((m) => {
      if (m.id !== mid) return m;
      switch (ev.type) {
        case "turn.start": activeTurnId = d.turn_id ?? activeTurnId; return { ...m, turn_id: d.turn_id ?? m.turn_id };
        case "text.delta": return { ...m, content: m.content + (d.text ?? ""), thinking: false };
        case "thinking.delta": return { ...m, thinking: true, thinkingText: (m.thinkingText ?? "") + (d.text ?? "") };
        case "thinking.status": return { ...m, thinking: !!d.active };
        case "tool.start": return { ...m, thinking: false, tools: [...(m.tools ?? []), { call_id: d.call_id, name: d.name, label: d.label || d.name, label_en: d.label_en, input_preview: d.input_preview, done: false }] };
        case "tool.end": return { ...m, tools: (m.tools ?? []).map((t) => (t.call_id === d.call_id ? { ...t, done: true, is_error: d.is_error, duration_ms: d.duration_ms, output_preview: d.output_preview } : t)) };
        case "card": return { ...m, cards: [...m.cards, { card_type: d.card_type, payload: d.payload ?? {}, message_id: d.message_id }] };
        case "memory.retrieved": return { ...m, memory: { count: d.count ?? 0, chars: d.chars ?? 0 } };
        case "guard.redacted": return { ...m, redacted: (m.redacted ?? 0) + (d.count ?? 1) };
        case "usage": return { ...m, usage: d as ChatMessage["usage"] };
        case "notice": return { ...m, notices: [...(m.notices ?? []), d.message ?? d.kind] };
        case "turn.complete": return { ...m, content: typeof d.answer === "string" ? d.answer : m.content, streaming: false, thinking: false, id: d.message_id ?? m.id, turn_id: d.turn_id ?? m.turn_id };
        case "turn.error": return { ...m, streaming: false, thinking: false, error: { code: d.code, message: d.message, retryable: d.retryable } };
        case "turn.cancelled": return { ...m, streaming: false, thinking: false, cancelled: true, stopReason: (d.reason === "superseded" ? "superseded" : "cancelled") as ChatMessage["stopReason"] };
        case "relationship.milestone": milestone = { ...(d as any), seq: Date.now() }; return m;
        default: return m;
      }
    });
    return { convs: { ...s.convs, [cid]: { ...c, messages, activeTurnId, lastSeq } }, milestone };
  }),
  setConn: (cid, conn) => set((s) => ({ convs: { ...s.convs, [cid]: { ...(s.convs[cid] ?? empty()), conn } } })),
  setActiveTurn: (cid, turnId) => set((s) => ({ convs: { ...s.convs, [cid]: { ...(s.convs[cid] ?? empty()), activeTurnId: turnId } } })),
  endTurn: (cid) => set((s) => {
    const c = s.convs[cid]; if (!c) return s;
    const messages = c.messages.map((m) => (m.id === c.streamingMsgId && m.streaming ? { ...m, streaming: false, thinking: false } : m));
    return { convs: { ...s.convs, [cid]: { ...c, messages, streamingMsgId: null, activeTurnId: null, conn: c.conn === "offline" ? "offline" : "idle" } } };
  }),
  reset: (cid) => set((s) => ({ convs: { ...s.convs, [cid]: empty() } })),
}));
