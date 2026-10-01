"use client";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { confirm as confirmDialog } from "@/lib/confirm";
import { Copy, EllipsisVertical, Home, LogIn, Moon, RotateCcw, Share2, Sun, UserRound, Volume2, VolumeX } from "@/components/icons";
import { LocaleProvider, useT, type Locale } from "@/lib/i18n";
import { useBrowserLocale, useOnline } from "@/lib/hooks";
import { api, get, post, patch } from "@/lib/api";
import { ApiError, friendlyError } from "@/lib/errors";
import { cn, copyText, isDarkColor, isIOS, storageGet, storageSet } from "@/lib/utils";
import { enqueueAudio, splitSentences, stopAudio, unlockAudio } from "@/lib/audio";
import { useChat, type ChatMessage } from "@/stores/chat";
import { refreshAccess } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { useTheme } from "@/lib/theme";
import { MessageList, type MessageListHandle } from "@/components/chat/MessageList";
import { Composer, type Attachment, type ComposerHandle } from "@/components/chat/Composer";
import { FileDrop } from "@/components/chat/FileDrop";
import { AttachmentRefresh } from "@/components/chat/MessageAttachments";
import { uploadFile } from "@/lib/upload";
import { ConnectionBanner } from "@/components/chat/ConnectionBanner";
import { LeaveMessageForm } from "@/components/chat/CardRenderer";
import { useTurnRunner } from "@/components/chat/useTurnRunner";
import { Avatar } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { DropdownMenu } from "@/components/ui/dropdown";
import { Turnstile } from "./Turnstile";
import { WelcomeGate, type GateChoice } from "./WelcomeGate";
import { AgentProfile } from "./AgentProfile";
import { StageView } from "./StageView";
import { AiNotice } from "./AiNotice";
import Link from "next/link";
import { Mascot, Wordmark } from "@/components/brand/Logo";

export interface PublicAgent { name: string; role_line: string; avatar_url: string | null; cover_url?: string | null;
  /** 무대(plan/71)에 설 그림 — 올린 원본(동그라미로 자르기 전). 없으면 프로필 사진. */
  character_url?: string | null; greeting: string; suggested_questions: string[]; theme: { accent?: string; avatar_shape?: string; bubble_style?: string; background?: string }; language: string; owner_display_name: string; voice_enabled: boolean;
  /** 서비스와 비서가 함께 허락한 것만 (plan/67): 마이크는 받아쓰기, 음성으로 듣기는 읽어 주기. */
  stt_enabled?: boolean; tts_enabled?: boolean; leave_message_enabled: boolean; collect_identity: string; require_turnstile: boolean; status: string; resting: boolean;
  /** 방문자에게서 파일을 받는가 (plan/55 §6-3). 꺼져 있으면 📎·붙여넣기·끌어다 놓기가 없다. */
  files?: { accept: boolean; per_day: number; max_mb: number } }
export interface LinkAccount { signed_in: boolean; name: string; is_owner: boolean; agent_id: string | null }
/** 공개 대화의 모양 (plan/71): 채팅(기본) · 무대(배경 위에 비서가 서고 게임처럼 대화창으로 말한다). */
export type LinkLayout = "chat" | "stage";
export interface PublicLinkPayload { agent: PublicAgent; link: { code: string; status: string; layout?: LinkLayout }; account?: LinkAccount }

interface Stored { token: string; cid: string; uid?: string }
const key = (code: string) => `blackmoa:v:${code}`;

/** The stored visitor session, unless it belongs to somebody who is no longer signed in.
 *
 *  A session created while signed in carries the account it speaks for. Once that account
 *  is gone from this browser — a logout, or a different person signing in — the stored
 *  token would otherwise walk back in wearing the previous name, so it is dropped here as
 *  well as refused by the server. */
function readStored(code: string, currentUid: string | null): Stored | null {
  const raw = storageGet("local", key(code)); if (!raw) return null;
  let stored: Stored;
  try { const j = JSON.parse(raw); if (!j?.token) return null; stored = j as Stored; }
  catch { stored = { token: raw, cid: "" }; }   // legacy plain token
  if (stored.uid && stored.uid !== currentUid) { storageSet("local", key(code), null); return null; }
  return stored;
}


/**
 * `preview` (plan/71): 주인이 링크 설정에서 모양을 고를 때 보는 미리보기. 보기 예시 대화만 보이고, 방문자 세션을 만들지
 * 않으며 말을 걸 수 없다. 아무나 붙여 볼 수 있지만 공개된 것 말고는 아무것도 보이지 않는다.
 */
export function PublicChat({ code, initial, embed = false, preview = null }: { code: string; initial: PublicLinkPayload | null; embed?: boolean; preview?: LinkLayout | null }) {
  const locale = useBrowserLocale();
  return <LocaleProvider locale={locale}><Inner code={code} initial={initial} locale={locale} embed={embed} preview={preview} /></LocaleProvider>;
}

function Inner({ code, initial, locale, embed, preview }: { code: string; initial: PublicLinkPayload | null; locale: Locale; embed: boolean; preview: LinkLayout | null }) {
  const t = useT();
  const online = useOnline();
  const { resolved, setPref } = useTheme();
  const [agent, setAgent] = useState<PublicAgent | null>(initial?.agent ?? null);
  const [status, setStatus] = useState<string>(initial?.link.status ?? "active");
  const [resting, setResting] = useState<boolean>(initial?.agent.resting ?? false);
  const [loadErr, setLoadErr] = useState<string | null>(initial ? null : t("public.load_error"));
  const [auth, setAuth] = useState<Stored | null>(null);
  const [visitor, setVisitor] = useState<{ display_name: string | null; email: string | null; signed_in?: boolean }>({ display_name: null, email: null });
  // The door: null while we work out whether one is needed, then a choice that gates bootstrap.
  const bootstrapped = useRef(false);
  // Bootstrap ends by replacing the message list with the server's. Anything sent before
  // that lands in a list that is about to be thrown away, so a first question waits here.
  const [ready, setReady] = useState(false);
  const [gate, setGateRaw] = useState<GateChoice | null>(null);
  // Re-opening the door (from the header) must let the session be built again, otherwise
  // signing in after choosing anonymous would change nothing.
  const setGate = useCallback((c: GateChoice | null) => { if (c) bootstrapped.current = false; setGateRaw(c); }, []);
  const [gateReady, setGateReady] = useState(false);
  // The owner of this link gets the same conversation, run as the console simulator.
  const [ownerPreview, setOwnerPreview] = useState<{ agentId: string } | null>(null);
  const [tsToken, setTsToken] = useState<string | null>(null);
  const [siteKey, setSiteKey] = useState<string>("");
  const [signupMode, setSignupMode] = useState<string>("open");
  const [identityOpen, setIdentityOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [copyMsg, setCopyMsg] = useState<ChatMessage | null>(null);
  const sttOk = !!(agent?.stt_enabled ?? agent?.voice_enabled);
  const ttsOk = !!(agent?.tts_enabled ?? agent?.voice_enabled);
  const [tts, setTts] = useState(false);
  const layout: LinkLayout = preview ?? initial?.link.layout ?? "chat";
  const listRef = useRef<MessageListHandle>(null);
  const composerRef = useRef<ComposerHandle>(null);
  const liveRef = useRef<HTMLDivElement>(null);
  const cid = auth?.cid ?? "";
  const conv = useChat((s) => (cid ? s.convs[cid] : undefined));
  const accent = agent?.theme?.accent || "#1a5fe0";
  const bubbleStyle = agent?.theme?.bubble_style ?? "soft";
  const needTurnstile = !!agent?.require_turnstile;

  // lock body scroll on chat page
  useEffect(() => { document.body.classList.add("chat-locked"); return () => document.body.classList.remove("chat-locked"); }, []);

  // keyboard handling via visualViewport → --kb-offset
  useEffect(() => {
    const vv = window.visualViewport; if (!vv) return;
    const apply = () => {
      const off = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
      document.documentElement.style.setProperty("--kb-offset", `${isIOS() ? off : 0}px`);
      if (off > 80) requestAnimationFrame(() => listRef.current?.scrollToBottom(false));
    };
    vv.addEventListener("resize", apply); vv.addEventListener("scroll", apply); apply();
    return () => { vv.removeEventListener("resize", apply); vv.removeEventListener("scroll", apply); document.documentElement.style.setProperty("--kb-offset", "0px"); };
  }, []);

  // branding (turnstile site key) — only when needed
  useEffect(() => {
    get<{ turnstile_site_key: string; signup_mode: string }>("/api/public/branding", { auth: false })
      .then((b) => { setSiteKey(b.turnstile_site_key); setSignupMode(b.signup_mode || "open"); })
      .catch(() => {});
  }, []);

  // One browser, one identity. If this person is already signed in to the service, the
  // public chat opens as that account — no door, no second anonymous persona — and if the
  // link is their own secretary they are not made a visitor to themselves.
  useEffect(() => {
    if (preview) return;   // 미리보기는 누구의 방문도 아니다
    let alive = true;
    (async () => {
      const tok = await refreshAccess().catch(() => null);
      if (!alive) return;
      if (tok) {
        try {
          const r = await get<PublicLinkPayload>(`/api/public/links/${code}`, { token: tok, auth: false });
          if (!alive) return;
          if (r.account?.is_owner) {
            const me = useAuth.getState().user;
            if (me) { setGate({ mode: "account", token: tok, user: me }); setGateReady(true); return; }
          }
        } catch { /* fall through to the normal paths */ }
        const u = useAuth.getState().user;
        if (u) { setGate({ mode: "account", token: tok, user: u }); setGateReady(true); return; }
      }
      // No account here — a stored visit only skips the door if it was anonymous.
      if (readStored(code, useAuth.getState().user?.id ?? null)) { setGate({ mode: "anon" }); setGateReady(true); return; }
      setGateReady(true);
    })();
    return () => { alive = false; };
  }, [code, setGate, preview]);

  // obtain / restore visitor token
  useEffect(() => {
    if (!agent || status !== "active" || bootstrapped.current || preview) return;
    if (!gate) return;   // the door is open; nothing to bootstrap yet
    if (needTurnstile && siteKey && !tsToken) return;
    bootstrapped.current = true;
    (async () => {
      const prev = readStored(code, gate.mode === "account" ? gate.user.id : null);
      try {
        const r = await post<{ visitor_token: string; conversation_id: string; visitor: { display_name: string | null; email: string | null; signed_in?: boolean }; agent: PublicAgent }>(
          `/api/public/links/${code}/visitor`,
          { existing_token: prev?.token ?? null, turnstile_token: tsToken },
          // The account token is what turns an anonymous session into a named one.
          gate.mode === "account" ? { token: gate.token, auth: false } : { auth: false });
        const owned = r as unknown as { owner_preview?: boolean; agent_id?: string; conversation_id: string; agent: PublicAgent };
        if (owned.owner_preview) {
          // No visitor token and nothing stored: this is the owner's own account talking to
          // their own secretary, so the session is the console's, not a guest's.
          const s = { token: gate.mode === "account" ? gate.token : "", cid: owned.conversation_id };
          setOwnerPreview({ agentId: owned.agent_id! });
          setAuth(s); setAgent(owned.agent); setResting(owned.agent.resting);
          useChat.getState().setMessages(s.cid, []);
          setReady(true);
          return;
        }
        // Remember who this session speaks for, so it can be dropped when they leave.
        const s: Stored = { token: r.visitor_token, cid: r.conversation_id,
                            ...(r.visitor.signed_in && gate.mode === "account" ? { uid: gate.user.id } : {}) };
        storageSet("local", key(code), JSON.stringify(s));
        setAuth(s); setVisitor(r.visitor); setAgent(r.agent); setResting(r.agent.resting);
        const msgs = await get<{ items: any[] }>(`/api/public/conversations/${s.cid}/messages`, { token: r.visitor_token, auth: false });
        const items = [...msgs.items].sort((a, b) => a.created_at.localeCompare(b.created_at));
        useChat.getState().setMessages(s.cid, items);
        setReady(true);
      } catch (e) {
        bootstrapped.current = false;
        if (e instanceof ApiError && e.code.startsWith("link_")) setStatus(e.code.replace("link_", ""));
        else if (e instanceof ApiError && e.code === "visitor_blocked") setLoadErr(friendlyError(e, locale));
        else setLoadErr(friendlyError(e, locale));
      }
    })();
  }, [agent, status, code, needTurnstile, siteKey, tsToken, locale, gate, preview]);

  const ownerBase = ownerPreview ? `/api/agents/${ownerPreview.agentId}` : "";
  const runner = useTurnRunner({
    cid,
    startUrl: ownerPreview ? `${ownerBase}/conversations/${cid}/turns` : `/api/public/conversations/${cid}/turns`,
    resumeUrl: (tid) => (ownerPreview ? `${ownerBase}/turns/${tid}/events` : `/api/public/turns/${tid}/events`),
    cancelUrl: (tid) => (ownerPreview ? `${ownerBase}/turns/${tid}/cancel` : `/api/public/turns/${tid}/cancel`),
    activeTurnUrl: ownerPreview ? `${ownerBase}/conversations/${cid}/active-turn` : `/api/public/conversations/${cid}/active-turn`,
    messagesUrl: ownerPreview ? `${ownerBase}/conversations/${cid}/messages` : `/api/public/conversations/${cid}/messages`,
    // An owner token is short-lived and refreshable; a visitor token is neither.
    getToken: () => (ownerPreview ? useAuth.getState().token : auth?.token ?? null),
    refreshable: !!ownerPreview,
    onError: (e) => {
      if (e instanceof ApiError) {
        // 주인의 사정(크레딧·하루 상한)은 방문자에게 말하지 않는다. 방문자에게는
        // "지금은 쉬고 있어요" 하나면 된다 — 주인 미리보기에서는 진짜 이유가 보인다.
        if (e.code === "secretary_resting" || e.code === "credits_exhausted"
            || (e.code === "visitor_daily_cap" && !ownerPreview)) setResting(true);
        else if (e.code.startsWith("link_")) setStatus(e.code.replace("link_", ""));
      }
    },
    onComplete: () => {
      const st = useChat.getState().convs[cid];
      const last = st?.messages[st.messages.length - 1];
      if (last?.role === "assistant" && last.content) {
        if (liveRef.current) liveRef.current.textContent = last.content.slice(0, 500);
        if (tts && ttsOk) void speak(last.content);
      }
    },
  });

  const speak = async (text: string) => {
    if (!auth) return;
    for (const s of splitSentences(text).slice(0, 12)) {
      try {
        const r = await api<Response>(`/api/public/conversations/${auth.cid}/tts`, { method: "POST", body: { text: s }, token: auth.token, auth: false, raw: true, headers: { Accept: "audio/mpeg" } });
        enqueueAudio(await r.arrayBuffer());
      } catch (e) { if (e instanceof ApiError && (e.code === "voice_disabled" || e.code === "tts_disabled")) { setTts(false); toast.error(friendlyError(e, locale)); } break; }
    }
  };

  const send = useCallback(async (text: string, atts: Attachment[] = []) => {
    if (!auth || (!text.trim() && !atts.length)) return;
    await runner.send(text, atts);
  }, [auth, runner]);
  // 오래 열어 둔 페이지에서 그림 주소가 끝나면 말들의 첨부만 새로 받는다.
  const refreshAttachments = useCallback(async () => {
    if (!auth || ownerPreview) return;
    try {
      const r = await get<{ items: any[] }>(`/api/public/conversations/${auth.cid}/messages`, { token: auth.token, auth: false });
      const st = useChat.getState();
      for (const m of r.items) if (m.attachments?.length) st.updateMessage(auth.cid, m.id, { attachments: m.attachments });
    } catch { /* 다음에 다시 */ }
  }, [auth, ownerPreview]);
  // 방문자의 파일은 그 대화에 딸린 입구로 올린다 — 주인의 한도를 쓰고 그 방문자 칸에 들어간다.
  const acceptFiles = !!agent?.files?.accept;
  const upload = async (f: File, onProgress: (r: number) => void): Promise<Attachment> => {
    if (!auth) throw new Error(t("chat.upload_failed"));
    try {
      const r = ownerPreview ? await uploadFile(f, { onProgress })
        : await uploadFile(f, { url: `/api/public/conversations/${auth.cid}/uploads`, token: auth.token, onProgress });
      return { upload_id: r.upload_id, filename: r.filename, mime: r.mime, url: r.url, size: r.size, localId: r.upload_id };
    } catch (e) { throw new Error(friendlyError(e, locale)); }
  };

  // A question typed on somebody's own page arrives here as ?q= and opens the conversation
  // with it, so the visitor does not have to ask twice (plan/41 §3). It is spent once: the
  // address is rewritten immediately, or a reload would ask again.
  const asked = useRef(false);
  useEffect(() => {
    if (asked.current || !ready || !auth || resting || status !== "active") return;
    const q = new URLSearchParams(window.location.search).get("q");
    if (!q?.trim()) return;
    asked.current = true;
    window.history.replaceState(null, "", window.location.pathname);
    void send(q.trim().slice(0, 2000));
  }, [ready, auth, resting, status, send]);

  const leaveMessage = useCallback(async (f: { name: string; contact: string; message: string }) => {
    if (!auth) return;
    try { await post(`/api/public/conversations/${auth.cid}/messages`, { name: f.name || null, contact: f.contact || null, message: f.message }, { token: auth.token, auth: false }); toast.success(t("card.message_sent")); }
    catch (e) { toast.error(friendlyError(e, locale)); throw e; }
  }, [auth, locale, t]);
  const meetingRequest = useCallback(async (f: { name: string; contact: string; purpose: string; slots: string[] }) => {
    if (!auth) return;
    try { await post(`/api/public/conversations/${auth.cid}/meeting-requests`, { ...f, name: f.name || null, contact: f.contact || null }, { token: auth.token, auth: false }); toast.success(t("card.meeting_sent")); }
    catch (e) { toast.error(friendlyError(e, locale)); throw e; }
  }, [auth, locale, t]);
  const transcribe = useCallback(async (blob: Blob) => {
    if (!auth) return "";
    const fd = new FormData(); fd.append("file", blob, blob.type.includes("mp4") ? "audio.mp4" : "audio.webm");
    try { const r = await post<{ text: string }>(`/api/public/conversations/${auth.cid}/stt`, fd, { token: auth.token, auth: false }); return r.text; }
    catch (e) { throw new Error(friendlyError(e, locale)); }
  }, [auth, locale]);

  /** Start a fresh thread. The old one stays on the server — the owner is entitled to read
   *  what was said to their secretary — so this is a new conversation, not a delete. */
  const resetChat = useCallback(async () => {
    if (!auth) return;
    try {
      const r = await post<{ conversation_id: string }>("/api/public/visitors/me/new-conversation", {}, { token: auth.token, auth: false });
      const next = { token: auth.token, cid: r.conversation_id };
      storageSet("local", key(code), JSON.stringify(next));
      useChat.getState().setMessages(next.cid, []);
      setAuth(next);
      toast.success(t("public.reset_done"));
    } catch (e) { toast.error(friendlyError(e, locale)); }
  }, [auth, code, locale, t]);

  const messages = useMemo<ChatMessage[]>(() => {
    if (preview && agent) return previewMessages(agent, locale);
    const base = conv?.messages ?? [];
    if (!agent) return base;
    const greeting: ChatMessage = { id: "greeting", role: "assistant", content: (agent.greeting || "").replace("{visitor_name}", visitor.display_name || (locale === "ko" ? "방문자" : "there")), cards: [], created_at: "" }; // no timestamp for the synthetic greeting
    return base.length ? base : greeting.content ? [greeting] : [];
  }, [conv?.messages, agent, visitor.display_name, locale, preview]);

  const busy = !!conv?.streamingMsgId;
  const showChips = (conv?.messages.length ?? 0) === 0 && !!auth && !resting && agent && agent.suggested_questions.length > 0;
  const dark = resolved === "dark";
  const accentFg = isDarkColor(accent) ? "#ffffff" : "#111318";

  // ─── static states ───
  if (!agent) return <CenteredNotice title={t("public.unavailable")} desc={loadErr ?? undefined} />;
  if (status !== "active") return <StaticState agent={agent} status={status} accent={accent} />;
  // A visitor arrived by link and has no other way back to this conversation, so walking
  // out of it is worth one question. Our own dialog, not the browser's: that one is modal
  // to the tab, unstyleable, and on iOS Safari it can be suppressed into a silent "no".
  const leaveSite = async (e: { preventDefault: () => void }) => {
    e.preventDefault();
    if (await confirmDialog({ title: t("public.leave_title"), description: t("public.leave_desc"),
                              confirmLabel: t("public.leave_go"), cancelLabel: t("public.leave_stay") })) {
      window.location.href = "/";
    }
  };

  const menuItems = [
    ...(ttsOk ? [{ key: "tts", icon: tts ? <VolumeX /> : <Volume2 />, label: tts ? t("public.tts_off") : t("public.tts_on"), onSelect: () => { void unlockAudio(); if (tts) stopAudio(); setTts(!tts); } }] : []),
    // A signed-in visitor already told us their name; asking again is noise.
    ...(visitor.signed_in || ownerPreview ? [] : [{ key: "identity", icon: <UserRound />, label: t("public.identify"), onSelect: () => setIdentityOpen(true) }]),
    ...(ownerPreview ? [] : [{ key: "reset", icon: <RotateCcw />, label: t("public.reset_chat"), onSelect: () => resetChat() }]),
    // The header chip is sm+ only, so on a phone this menu was the only place a visitor
    // who chose anonymous could still sign in — and it was not here either.
    ...(visitor.signed_in || ownerPreview ? [] : [{ key: "signin", icon: <LogIn />, label: t("gate.login"), onSelect: () => setGate(null) }]),
    { key: "theme", icon: dark ? <Sun /> : <Moon />, label: dark ? t("common.light_mode") : t("common.dark_mode"), onSelect: () => setPref(dark ? "light" : "dark") },
    { key: "home", icon: <Home />, label: t("public.go_home"), onSelect: () => void leaveSite({ preventDefault: () => {} }) },
    { key: "share", icon: <Share2 />, label: t("public.share_link"), onSelect: async () => { const url = window.location.href; if (navigator.share) { try { await navigator.share({ title: agent.name, url }); } catch { /* cancelled */ } } else if (await copyText(url)) toast.success(t("common.copied")); } },
  ];

  const chat = (
    <div className="flex h-full min-h-0 flex-col bg-bg" style={{ ["--accent" as string]: accent, ["--accent-fg" as string]: accentFg, ["--ring" as string]: accent }}>
      <header className="safe-pt shrink-0 border-b border-border bg-card/90 backdrop-blur">
        <div className="flex h-12 items-center gap-2.5 px-3">
          {/* Tapping the name opens the profile, the way a messenger does — a visitor
              deciding whether to speak wants to know who is answering. */}
          <button type="button" onClick={() => setProfileOpen(true)} aria-label={t("prof.open", { name: agent.name })}
                  className="-ml-1 flex min-w-0 flex-1 items-center gap-2.5 rounded-xl px-1 py-1 text-left hover:bg-muted/60">
            <Avatar mascot name={agent.name} src={agent.avatar_url} size={32} shape={agent.theme?.avatar_shape} accent={accent} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[15px] font-semibold leading-tight">{agent.name}</span>
              <span className="flex items-center gap-1 text-[11px] text-muted-fg"><span className={`h-1.5 w-1.5 rounded-full ${resting ? "bg-warning" : online ? "bg-success" : "bg-muted-fg"}`} />{resting ? t("public.resting_short") : online ? t("public.online") : t("chat.offline")}</span>
            </span>
          </button>
          {/* Who the secretary thinks it is talking to, and a way in for anyone who chose
              anonymous and changed their mind. */}
          {ownerPreview ? null : visitor.signed_in && visitor.display_name ? (
            <span className="hidden max-w-[140px] truncate rounded-full bg-accent/10 px-2 py-1 text-[11px] text-accent sm:inline">{t("gate.signed_in_as", { name: visitor.display_name })}</span>
          ) : (
            <button type="button" onClick={() => setGate(null)} className="hidden rounded-full border border-border px-2.5 py-1 text-[11px] text-muted-fg hover:text-fg sm:inline">{t("gate.login")}</button>
          )}
          {tts && ttsOk ? <span className="text-accent" aria-label={t("public.tts_on")}><Volume2 className="h-4 w-4" /></span> : null}
          <DropdownMenu trigger={<Button variant="ghost" size="icon" aria-label={t("common.more")}><EllipsisVertical className="h-5 w-5" /></Button>} items={menuItems} />
        </div>
        <ConnectionBanner online={online} conn={conv?.conn ?? "idle"} />
        {ownerPreview ? <div className="border-t border-border bg-accent/10 px-3 py-1.5 text-center text-[11px] text-accent">{t("public.owner_preview")}</div> : null}
        {preview ? <div className="border-t border-border bg-accent/10 px-3 py-1.5 text-center text-[11px] text-accent">{t("stage.preview_badge")}</div> : null}
      </header>

      <FileDrop className="flex min-h-0 flex-1 flex-col" disabled={!acceptFiles || !auth || resting}
                onFiles={(fs) => { composerRef.current?.addFiles(fs); }}>
      <div className="relative flex min-h-0 flex-1 flex-col">
        {(conv?.messages.length ?? 0) === 0 ? <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-[0.08]"><Mascot size={220} /></div> : null}
      <AttachmentRefresh.Provider value={refreshAttachments}>
      <MessageList ref={listRef} messages={messages} mode="visitor" agentName={agent.name} agentAvatar={agent.avatar_url}
        onAgentClick={() => setProfileOpen(true)} bubbleStyle={bubbleStyle}
        cardActions={{ mode: "visitor", resting, onLeaveMessage: agent.leave_message_enabled ? leaveMessage : undefined, onMeetingRequest: meetingRequest }}
        onLongPress={(m) => { if (m.content) setCopyMsg(m); }}
        footer={
          <>
            {showChips ? (
              <div className="flex flex-wrap gap-2 px-3 pt-1 pb-2 pl-[52px]">
                {agent.suggested_questions.slice(0, 4).map((q) => <button key={q} type="button" onClick={() => void send(q)} className="rounded-full border border-accent/40 bg-accent/8 px-3 py-2 text-left text-[13px] text-accent min-h-[40px] hover:bg-accent/15">{q}</button>)}
                {agent.collect_identity === "ask" && !visitor.display_name && !visitor.signed_in ? <button type="button" onClick={() => setIdentityOpen(true)} className="rounded-full border border-border px-3 py-2 text-[13px] text-muted-fg min-h-[40px]">{t("public.identify")}</button> : null}
              </div>
            ) : null}
            {resting ? (
              <div className="mx-3 my-2 rounded-2xl border border-warning/40 bg-warning/10 p-4 text-sm">
                <div className="font-medium">{t("public.resting_title")}</div>
                <p className="mt-1 text-muted-fg">{t("public.resting_desc", { name: agent.name })}</p>
                {auth ? <div className="mt-3"><LeaveMessageForm onSubmit={leaveMessage} compact /></div> : null}
              </div>
            ) : null}
          </>
        } />
      </AttachmentRefresh.Provider>
      </div>

      <div className="shrink-0 border-t border-border bg-bg px-3 pt-2" style={{ paddingBottom: "calc(var(--sab) + var(--kb-offset) + 6px)" }}>
        <Composer ref={composerRef} onSend={(txt, atts) => send(txt, atts)} onCancel={runner.cancel} busy={busy} disabled={!auth || resting || !online}
          attachments={acceptFiles} onUpload={upload} fileMaxMb={agent.files?.max_mb}
          voice={sttOk} onTranscribe={transcribe} placeholder={resting ? t("public.resting_short") : t("public.placeholder", { name: agent.name })} />
        <AiNotice ownerName={agent.owner_display_name} className="mt-1.5" />
      </div>
      </FileDrop>
    </div>
  );

  // 두 모양이 함께 쓰는 것: 비서 소개, 이름 남기기, 말 복사, 사람 확인(plan/71).
  const overlays = (
    <>
      {profileOpen ? <AgentProfile agent={agent} accent={accent} online={online} onClose={() => setProfileOpen(false)} onAsk={(q) => { if (!preview) void send(q); }} /> : null}
      <div ref={liveRef} aria-live="polite" className="sr-only" />

      <Sheet open={identityOpen} onClose={() => setIdentityOpen(false)} title={t("public.identify")}>
        <IdentityForm token={auth?.token ?? null} initial={visitor} onSaved={(v) => { setVisitor(v); setIdentityOpen(false); toast.success(t("common.saved")); }} />
      </Sheet>
      <Sheet open={!!copyMsg} onClose={() => setCopyMsg(null)} title={t("public.message_actions")}>
        <div className="space-y-2">
          <Button className="w-full justify-start" variant="outline" onClick={async () => { if (copyMsg && (await copyText(copyMsg.content))) toast.success(t("common.copied")); setCopyMsg(null); }}><Copy className="h-4 w-4" />{t("common.copy")}</Button>
          {typeof navigator !== "undefined" && "share" in navigator ? <Button className="w-full justify-start" variant="outline" onClick={async () => { try { await navigator.share({ text: copyMsg?.content }); } catch { /* cancelled */ } setCopyMsg(null); }}><Share2 className="h-4 w-4" />{t("common.share")}</Button> : null}
        </div>
      </Sheet>
      {needTurnstile && siteKey && !tsToken && !preview ? (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-bg/80 p-4"><div className="rounded-2xl border border-border bg-card p-4 text-center text-sm"><p className="mb-3">{t("public.verify_human")}</p><Turnstile siteKey={siteKey} onToken={setTsToken} /></div></div>
      ) : null}
    </>
  );
  const gateView = gateReady && !gate && !preview ? (
    <WelcomeGate agentName={agent.name} ownerName={agent.owner_display_name} avatarUrl={agent.avatar_url}
      accent={accent} shape={agent.theme?.avatar_shape} locale={locale}
      canSignUp={signupMode === "open"} onDone={setGate} />
  ) : null;
  const previewPill = preview ? (
    <span className="rounded-full bg-white/10 px-2.5 py-0.5 text-[11.5px] font-medium text-white/85 ring-1 ring-white/15">{t("stage.preview_badge")}</span>
  ) : null;

  // 무대(plan/71): 배경 위에 비서가 서고, 게임처럼 대화창으로 말한다. 같은 대화·같은 길, 모양만 다르다.
  if (layout === "stage") {
    return (
      <div className="relative h-full">
        <StageView agent={agent} accent={accent} accentFg={accentFg} messages={messages} busy={busy} online={online} resting={resting}
          disabled={!!preview || !auth || resting || !online}
          placeholder={preview ? t("stage.preview_placeholder") : resting ? t("public.resting_short") : t("public.placeholder", { name: agent.name })}
          suggestions={preview || showChips ? agent.suggested_questions : []}
          onSend={(q) => void send(q)} onStop={runner.cancel}
          voice={sttOk && !preview} onTranscribe={transcribe}
          onProfile={() => setProfileOpen(true)}
          menuItems={preview ? undefined : menuItems}
          cardActions={{ mode: "visitor", resting, onLeaveMessage: agent.leave_message_enabled ? leaveMessage : undefined, onMeetingRequest: meetingRequest }}
          bubbleStyle={bubbleStyle}
          banner={previewPill ?? (resting ? <span className="rounded-full bg-warning/90 px-2.5 py-0.5 text-[11.5px] font-medium text-black">{t("public.resting_title")}</span>
                  : ownerPreview ? <span className="rounded-full bg-white/10 px-2.5 py-0.5 text-[11.5px] text-white/85 ring-1 ring-white/15">{t("stage.owner_view")}</span> : null)} />
        {overlays}
        {gateView}
      </div>
    );
  }

  // Inside somebody else's page the chat is a panel, not a site: no margin, no corners of
  // ours, and no link that would navigate their visitor away (plan/41 M6). The server
  // decided this, so the first render matches the HTML it hydrates.
  const embedded = embed;
  return (
    <div className={cn("relative h-full", embedded ? "" : "md:flex md:items-stretch md:justify-center md:p-6")}
         style={{ background: agent.theme?.background === "plain" ? undefined : `linear-gradient(160deg, color-mix(in oklab, ${accent} 18%, var(--bg)) 0%, var(--bg) 55%)` }}>
      {/* The way back to the product. Leaving costs a visitor their link, so it asks. */}
      {embedded ? null : (
        <Link href="/" onClick={leaveSite}
              className="absolute left-5 top-5 z-20 hidden items-center gap-2 rounded-xl px-2 py-1.5 text-muted-fg transition-colors hover:bg-card/70 hover:text-fg md:inline-flex">
          <Wordmark size={20} />
        </Link>
      )}

      {/* The conversation, centred, and nothing beside it. There used to be a caption in
          the left margin carrying the avatar, the name and the role line — all three of
          which the chat header already shows a few pixels away. Removing it is what lets
          the card sit in the middle of the screen instead of being pushed off it. */}
      <div className={cn("h-full w-full", embedded ? "" : "md:mx-auto md:h-[min(900px,calc(100dvh-48px))] md:max-w-[720px] md:overflow-hidden md:rounded-3xl md:border md:border-border md:shadow-2xl xl:max-w-[820px] 2xl:max-w-[900px]")}>{chat}</div>

      {overlays}
      {gateView}
    </div>
  );
}

function IdentityForm({ token, initial, onSaved }: { token: string | null; initial: { display_name: string | null; email: string | null }; onSaved: (v: { display_name: string | null; email: string | null }) => void }) {
  const t = useT();
  const [name, setName] = useState(initial.display_name ?? ""); const [email, setEmail] = useState(initial.email ?? ""); const [note, setNote] = useState(""); const [busy, setBusy] = useState(false);
  return (
    <form className="space-y-3" onSubmit={async (e) => { e.preventDefault(); if (!token) return; setBusy(true); try { const r = await patch<{ display_name: string | null; email: string | null }>("/api/public/visitors/me", { display_name: name, email, note }, { token, auth: false }); onSaved(r); } catch (x) { toast.error((x as Error).message); } finally { setBusy(false); } }}>
      <p className="text-sm text-muted-fg">{t("public.identify_desc")}</p>
      <Field label={t("card.your_name")}><Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></Field>
      <Field label={t("auth.email")}><Input type="email" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></Field>
      <Field label={t("public.note")}><Textarea value={note} onChange={(e) => setNote(e.target.value)} className="min-h-[72px]" maxLength={500} /></Field>
      <Button type="submit" className="w-full" variant="accent" loading={busy} disabled={!token}>{t("common.save")}</Button>
    </form>
  );
}

function CenteredNotice({ title, desc, action }: { title: string; desc?: string; action?: ReactNode }) {
  return (
    <main className="flex h-full flex-col items-center justify-center p-6 text-center">
      <div className="text-lg font-semibold">{title}</div>
      {desc ? <p className="mt-2 text-sm text-muted-fg">{desc}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </main>
  );
}

function StaticState({ agent, status, accent }: { agent: PublicAgent; status: string; accent: string }) {
  const t = useT();
  const title = status === "paused" ? t("public.paused_title") : status === "expired" ? t("public.expired_title") : t("public.revoked_title");
  const desc = status === "paused" ? t("public.paused_desc", { name: agent.name }) : t("public.expired_desc");
  return (
    <main className="flex h-full flex-col items-center justify-center px-6 pt-[max(1.5rem,var(--sat))] pb-[max(1.5rem,var(--sab))] text-center" style={{ background: `linear-gradient(160deg, color-mix(in oklab, ${accent} 18%, var(--bg)), var(--bg) 60%)` }}>
      <Avatar mascot name={agent.name} src={agent.avatar_url} size={72} accent={accent} />
      <h1 className="mt-4 text-xl font-semibold">{agent.name}</h1>
      <p className="text-sm text-muted-fg">{t("public.owner_line", { owner: agent.owner_display_name })}</p>
      <div className="mt-8 rounded-2xl border border-border bg-card px-6 py-5 max-w-sm">
        <div className="font-medium">{title}</div>
        <p className="mt-1 text-sm text-muted-fg">{desc}</p>
      </div>
    </main>
  );
}


/** 미리보기(plan/71)에 보일 예시 대화 — 인사, 방문자의 물음, 비서의 답. 서버에 아무것도 묻지 않는다. */
function previewMessages(agent: PublicAgent, locale: Locale): ChatMessage[] {
  const ko = locale !== "en";
  const owner = agent.owner_display_name || (ko ? "주인" : "the owner");
  const greeting = (agent.greeting || (ko ? `안녕하세요, ${agent.name}이에요.` : `Hi, I'm ${agent.name}.`)).replace("{visitor_name}", ko ? "방문자" : "there");
  // 시각은 없다 — 서버가 그린 시각과 브라우저의 시각이 달라 화면이 어긋난다(인사말과 같이).
  const at = "";
  return [
    { id: "pv-1", role: "assistant", content: greeting, cards: [], created_at: at },
    { id: "pv-2", role: "user", content: ko ? "안녕하세요! 어떤 일을 도와주시나요?" : "Hi! What can you help with?", cards: [], created_at: at },
    { id: "pv-3", role: "assistant", turn_id: "pv-3", content: ko ? `${owner} 님의 일을 곁에서 돕고 있어요. 일정이나 연락처, 하시는 일에 대해 궁금한 것을 편하게 물어보세요. 메시지를 남기시면 ${owner} 님께 바로 전해 드릴게요.` : `I work alongside ${owner}. Ask me about their schedule, how to reach them, or what they do — or leave a message and I will pass it on.`, cards: [], created_at: at },
  ];
}
