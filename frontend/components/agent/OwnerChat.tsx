"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronDown, ChevronLeft, Eye, MessagesSquare, MoreHorizontal, Pencil, Plus, RefreshCw, Trash2 } from "@/components/icons";
import Link from "next/link";
import { Agents, Chat, Network, RoomAccess, type CardData, type Conversation, type MessageOut } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { cn, isDarkColor, storageGet, storageSet } from "@/lib/utils";
import { fmtRelative, fmtCredits } from "@/lib/format";
import { useOnline, useVoiceFeatures } from "@/lib/hooks";
import { fromServer, useChat } from "@/stores/chat";
import { onLive } from "@/lib/live";
import { useAuth } from "@/stores/auth";
import { useAgent } from "./AgentLayout";
import { MessageList, type MessageListHandle } from "@/components/chat/MessageList";
import { FileDrop } from "@/components/chat/FileDrop";
import { AttachmentRefresh, FileLinks } from "@/components/chat/MessageAttachments";
import { uploadFile } from "@/lib/upload";
import { Composer, type Attachment, type ComposerHandle } from "@/components/chat/Composer";
import { ConnectionBanner } from "@/components/chat/ConnectionBanner";
import { useTurnRunner } from "@/components/chat/useTurnRunner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Sheet, Dialog } from "@/components/ui/dialog";
import { DropdownMenu } from "@/components/ui/dropdown";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { KeyValue } from "@/components/ui/misc";
import { Badge } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/misc";
import { confirm } from "@/lib/confirm";

export function OwnerChat({ simulate = false, basePath, backHref = "/app/agents", headerExtra, hideMobileHeader = false }: {
  simulate?: boolean;
  /** Where the selected conversation is reflected in the URL. Defaults to this agent's own
   *  chat route; the standalone /app/chat surface passes its own path. */
  basePath?: string;
  backHref?: string;
  /** Rendered next to the agent name (the agent switcher on the standalone surface). */
  headerExtra?: React.ReactNode;
  /** Set when a surface already renders an agent header above this one (the simulator tab). */
  hideMobileHeader?: boolean;
}) {
  const t = useT(); const locale = useLocale(); const a = useAgent(); const qc = useQueryClient();
  const router = useRouter(); const sp = useSearchParams();
  // A page elsewhere (a company page, say) can hand the chat an opening line: `?draft=`.
  // It goes into the box, not out — the owner still presses send.
  const composerRef = useRef<ComposerHandle>(null);
  const draftDone = useRef(false);
  useEffect(() => {
    const draft = sp.get("draft");
    if (!draft || draftDone.current) return;
    const id = window.setTimeout(() => { composerRef.current?.setText(draft); composerRef.current?.focus(); draftDone.current = true; }, 50);
    return () => window.clearTimeout(id);
  }, [sp]);
  const online = useOnline();
  const voiceOn = useVoiceFeatures();
  const [cid, setCid] = useState<string | null>(simulate ? null : sp.get("c"));
  const [drawer, setDrawer] = useState(false);
  const [turnInfo, setTurnInfo] = useState<string | null>(null);
  // Saying the secretary got something wrong about me, and what was actually the case.
  const [wrongTurn, setWrongTurn] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<Conversation | null>(null);
  const listRef = useRef<MessageListHandle>(null);
  const [welcome] = useState(() => sp.get("welcome") === "1"); // captured once: select() rewrites the URL
  // 바깥(PC 앱의 알림·빠른 대화, plan/62)이 열려 있는 이 화면을 다른 대화로 보낼 때 — 주소가 바뀌면 따라간다.
  // select() 는 cid 를 먼저 바꾸고 주소를 맞추므로 여기서 되돌아오지 않는다.
  const urlCid = simulate ? null : sp.get("c");
  useEffect(() => { if (urlCid && urlCid !== cid) setCid(urlCid); }, [urlCid]); // eslint-disable-line react-hooks/exhaustive-deps

  const convs = useQuery({ queryKey: ["conversations", a.id, "owner"], queryFn: () => Chat.conversations(a.id, "owner"), enabled: !simulate });
  const createConv = useMutation({ mutationFn: () => Chat.createConversation(a.id), onSuccess: (c) => { qc.invalidateQueries({ queryKey: ["conversations", a.id] }); select(c.id); } });
  const createSim = useMutation({ mutationFn: () => Agents.simulate(a.id), onSuccess: (c) => { storageSet("session", `memora:sim:${a.id}`, c.id); setCid(c.id); useChat.getState().reset(c.id); } });

  const chatUrl = useCallback((convId?: string) => {
    const base = basePath ?? `/app/agents/${a.id}/chat`;
    const q = new URLSearchParams();
    if (basePath) q.set("a", a.id);           // the standalone surface needs to know the agent
    if (convId) q.set("c", convId);
    const s = q.toString();
    return s ? `${base}?${s}` : base;
  }, [a.id, basePath]);
  const select = useCallback((id: string) => { setCid(id); setDrawer(false); if (!simulate) router.replace(chatUrl(id)); }, [chatUrl, router, simulate]);
  // plan/37: a stage change or anniversary reached during this turn is worth a line on screen.
  const milestone = useChat((s) => s.milestone);
  useEffect(() => {
    if (!milestone || milestone.agent_id !== a.id) return;
    const key = milestone.milestones[0];
    if (!key) return;
    toast(t("rel.toast_milestone", { name: a.name, what: t(`rel.ms_${key}`) === `rel.ms_${key}` ? key : t(`rel.ms_${key}`) }), { duration: 6000 });
    qc.invalidateQueries({ queryKey: ["relationship", a.id] }); qc.invalidateQueries({ queryKey: ["relationships"] });
  }, [milestone, a.id, a.name, qc, t]);

  // pick a conversation: url → most recent → create
  useEffect(() => {
    if (simulate) {
      if (cid) return;
      const prev = storageGet("session", `memora:sim:${a.id}`);
      if (prev) { Chat.getConversation(a.id, prev).then((c) => setCid(c.id)).catch(() => createSim.mutate()); } else createSim.mutate();
      return;
    }
    if (cid || !convs.data) return;
    if (convs.data.items.length) select(convs.data.items[0].id);
    else if (!createConv.isPending) createConv.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [convs.data, cid, simulate, a.id]);

  const conv = useChat((s) => (cid ? s.convs[cid] : undefined));
  // A message the server put into this conversation (the secretary speaking first, a relay
  // result) appears here the moment it exists, not on the next reload.
  useEffect(() => {
    if (!cid) return;
    return onLive("message", (data) => {
      const d = (data ?? {}) as { conversation_id?: string; message?: MessageOut };
      if (d.conversation_id !== cid || !d.message) return;
      const st = useChat.getState();
      const cur = st.convs[cid];
      if (!cur?.loaded || cur.messages.some((m) => m.id === d.message!.id)) return;
      st.addMessage(cid, fromServer(d.message));
    });
  }, [cid]);
  const runner = useTurnRunner({
    cid: cid ?? "",
    startUrl: `/api/agents/${a.id}/conversations/${cid}/turns`,
    resumeUrl: (tid) => `/api/agents/${a.id}/turns/${tid}/events`,
    cancelUrl: (tid) => `/api/agents/${a.id}/turns/${tid}/cancel`,
    stopUrl: `/api/agents/${a.id}/conversations/${cid}/cancel`,
    activeTurnUrl: `/api/agents/${a.id}/conversations/${cid}/active-turn`,
    messagesUrl: `/api/agents/${a.id}/conversations/${cid}/messages`,
    getToken: () => useAuth.getState().token,
    refreshable: true,
    extraBody: simulate ? { simulate_visitor: true } : undefined,
    // 어디서 말하든 이 화면은 실시간으로 같다(plan/69): 다른 탭·PC 앱에서 시작한 답도 따라 받는다.
    live: true,
    onComplete: () => { qc.invalidateQueries({ queryKey: ["credits", "balance"] }); qc.invalidateQueries({ queryKey: ["conversations", a.id] }); },
    onSynced: () => { qc.invalidateQueries({ queryKey: ["credits", "balance"] }); },
  });
  // 대화를 열 때마다 서버와 맞춘다: 저장된 기록을 받고, 흐르는 답이 있으면 따라 붙는다. 다른 대화의 답을 받던 중이면
  // 그 흐름은 놓는다(서버의 답은 계속되고, 돌아오면 다시 따라 붙는다).
  useEffect(() => {
    if (!cid) return;
    let alive = true;
    void runner.detach().then(() => { if (alive) void runner.sync(); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cid]);
  // PC 앱의 문이 다시 보일 때(plan/62) — 같은 맞추기.
  useEffect(() => {
    if (!cid) return;
    const resync = () => void runner.follow();
    window.addEventListener("memora:resync", resync);
    return () => window.removeEventListener("memora:resync", resync);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cid]);
  // 다른 화면에서 이 대화를 지웠다 — 남은 대화로 옮긴다.
  useEffect(() => {
    if (!cid) return;
    return onLive("conversation", (data) => {
      const d = (data ?? {}) as { change?: string; conversation_id?: string };
      if (d.change === "deleted" && d.conversation_id === cid) {
        // 목록을 다시 받기 전에 고르면 지운 대화를 또 고른다 — 목록에서 먼저 뺀다.
        qc.setQueryData(["conversations", a.id, "owner"], (prev: { items: Conversation[] } | undefined) =>
          prev ? { ...prev, items: prev.items.filter((x) => x.id !== cid) } : prev);
        useChat.getState().reset(cid);
        setCid(null);
        if (!simulate) router.replace(chatUrl());
      }
    });
  }, [cid, simulate, router, chatUrl, qc, a.id]);

  const onSend = async (text: string, atts: Attachment[]) => { if (!cid) return; await runner.send(text, atts); };
  const upload = async (f: File, onProgress: (r: number) => void): Promise<Attachment> => {
    try { const r = await uploadFile(f, { onProgress }); return { upload_id: r.upload_id, filename: r.filename, mime: r.mime, url: r.url, size: r.size, localId: r.upload_id }; }
    catch (e) { throw new Error(friendlyError(e, locale)); }
  };
  // 허락 카드의 답 (plan/55 §6-4): 서버에 적고, 카드에 답을 남기고, 그 답이 주인의 말로 턴을 잇는다.
  const onRoomAccess = async (messageId: string, card: CardData, roomId: string | null, choice: "conversation" | "always" | "deny") => {
    if (!cid) return;
    try {
      const r = await RoomAccess.decide(a.id, { message_id: messageId, room_id: roomId, choice });
      const st = useChat.getState();
      const m = (st.convs[cid]?.messages ?? []).find((x) => x.id === messageId);
      if (m) st.updateMessage(cid, messageId, { cards: m.cards.map((c) => (c === card ? { ...c, payload: { ...c.payload, decided: r.decided } } : c)) });
      const cand = (card.payload?.candidates ?? []).find((c: any) => c.room_id === roomId);
      const who = cand ? `${cand.name}${cand.handle ? `(@${cand.handle})` : ""}` : "";
      await onSend(choice === "deny" ? t("card.room_reply_deny") : t(choice === "always" ? "card.room_reply_always" : "card.room_reply_here", { who }), []);
    } catch (e) { toast.error(friendlyError(e, locale)); }
  };
  const fileHref = useCallback((fid: string) => `/app/agents/${a.id}/files?open=${fid}`, [a.id]);
  // 오래 열어 둔 대화에서 그림 주소가 끝나면 말들의 첨부만 새로 받아 바꿔 끼운다.
  const refreshAttachments = useCallback(async () => {
    if (!cid) return;
    try {
      const r = await Chat.messages(a.id, cid);
      const st = useChat.getState();
      for (const m of r.items) if (m.attachments?.length) st.updateMessage(cid, m.id, { attachments: m.attachments });
    } catch { /* 다음에 다시 */ }
  }, [a.id, cid]);
  const transcribe = async (blob: Blob) => { try { const r = await Chat.stt(a.id, blob, a.voice?.stt_language || ""); return r.text; } catch (e) { throw new Error(friendlyError(e, locale)); } };
  // 제안을 받아들이면 인맥이 생길 수 있다 — 인맥을 담은 화면들이 바로 알게(plan/69, 서버의 link 소식도 온다).
  const onProposal = async (pid: string, d: "accept" | "reject") => { try { await Network.decide(pid, d); qc.invalidateQueries({ queryKey: ["network"] }); toast.success(t("common.saved")); } catch (e) { toast.error(friendlyError(e, locale)); throw e; } };

  const rename = useMutation({ mutationFn: (x: { id: string; title: string }) => Chat.patchConversation(a.id, x.id, { title: x.title }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["conversations", a.id] }); setRenaming(null); } });
  const remove = useMutation({ mutationFn: (id: string) => Chat.deleteConversation(a.id, id), onSuccess: (_, id) => { qc.invalidateQueries({ queryKey: ["conversations", a.id] }); if (id === cid) { setCid(null); router.replace(chatUrl()); } } });

  const messages = conv?.messages ?? [];
  const busy = !!conv?.streamingMsgId;
  const current = convs.data?.items.find((c) => c.id === cid);
  const starters = useMemo(() => simulate ? [t("sim.q1"), t("sim.q2"), t("sim.q3")] : welcome ? [t("chat.welcome_q1"), t("chat.welcome_q2"), t("chat.welcome_q3")] : [], [simulate, welcome, t]);

  const convList = (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-sm font-semibold">{t("chat.conversations")}</span>
        <Button size="sm" variant="secondary" loading={createConv.isPending} onClick={() => createConv.mutate()}><Plus className="h-4 w-4" />{t("chat.new")}</Button>
      </div>
      <ul className="flex-1 overflow-y-auto scrollbar-thin px-2 pb-2 space-y-0.5">
        {convs.isLoading ? <Skeleton className="h-24" /> : convs.data?.items.map((c) => (
          <li key={c.id} className={cn("group flex items-center gap-1 rounded-xl", c.id === cid ? "bg-accent/10" : "hover:bg-muted")}>
            <button type="button" onClick={() => select(c.id)} className="min-w-0 flex-1 px-3 py-2.5 text-left">
              <div className="truncate text-sm font-medium">{c.title || c.summary || t("conv.untitled")}</div>
              <div className="truncate text-[11px] text-muted-fg">{fmtRelative(c.last_message_at ?? c.created_at, locale)} · {c.message_count}</div>
            </button>
            <DropdownMenu trigger={<Button variant="ghost" size="icon-sm" aria-label={t("common.more")}><MoreHorizontal className="h-4 w-4" /></Button>} items={[
              { key: "rename", label: t("common.rename"), icon: <Pencil />, onSelect: () => setRenaming(c) },
              { key: "del", label: t("common.delete"), icon: <Trash2 />, danger: true, onSelect: async () => { if (await confirm({ title: t("chat.delete_confirm"), danger: true, confirmLabel: t("common.delete") })) remove.mutate(c.id); } },
            ]} />
          </li>
        ))}
      </ul>
    </div>
  );

  return (
    <div className="flex min-h-0 flex-1">
      {!simulate ? <aside className="hidden lg:flex w-72 shrink-0 flex-col border-r border-border bg-card">{convList}</aside> : null}
      <FileDrop className="flex min-w-0 flex-1 flex-col bg-bg" style={a.theme?.accent ? { ["--accent" as string]: a.theme.accent, ["--accent-fg" as string]: isDarkColor(a.theme.accent) ? "#ffffff" : "#111318" } : undefined}
        disabled={simulate || !cid || !online} onFiles={(fs) => { composerRef.current?.addFiles(fs); }}>
        {/* mobile: ONE 52px row replaces shell header + agent header/tabs + conversation bar */}
        <div className={cn("safe-pt shrink-0 border-b border-border bg-card/95 backdrop-blur md:hidden", hideMobileHeader && "hidden")}>
          <div className="flex h-[52px] items-center gap-1 px-1.5">
            <Link href={backHref} className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl hover:bg-muted" aria-label={t("common.back")}><ChevronLeft className="h-5 w-5" /></Link>
            <Avatar mascot name={a.name} src={a.avatar_url} size={30} accent={a.theme?.accent} shape={a.theme?.avatar_shape} />
            <button type="button" onClick={() => !simulate && setDrawer(true)} className="min-w-0 flex-1 px-1.5 text-left" aria-label={simulate ? undefined : t("chat.conversations")}>
              <div className="truncate text-[15px] font-semibold leading-tight">{a.name}</div>
              <div className="flex items-center gap-0.5 text-[11px] text-muted-fg"><span className="truncate">{simulate ? t("agent.tab_simulate") : current?.title || t("chat.conversations")}</span>{!simulate ? <ChevronDown className="h-3 w-3 shrink-0" /> : null}</div>
            </button>
            {simulate ? <Button variant="ghost" size="icon-sm" loading={createSim.isPending} onClick={() => createSim.mutate()} aria-label={t("sim.new")}><RefreshCw className="h-4 w-4" /></Button> : null}
            <DropdownMenu trigger={<Button variant="ghost" size="icon" aria-label={t("common.more")}><MoreHorizontal className="h-5 w-5" /></Button>} items={[
              ...(!simulate ? [{ key: "new", label: t("chat.new"), icon: <Plus />, onSelect: () => createConv.mutate() }, { key: "sep0", label: "", separator: true }] : []),
              ...([["", "agent.tab_overview"], ["/settings", "agent.tab_settings"], ["/links", "agent.tab_links"], ["/inbox", "agent.tab_inbox"], ["/simulate", "agent.tab_simulate"], ["/memory", "agent.tab_memory"], ["/files", "agent.tab_files"]] as const)
                .filter(([suffix]) => !(simulate && suffix === "/simulate"))
                .map(([suffix, key]) => ({ key, label: t(key), onSelect: () => router.push(`/app/agents/${a.id}${suffix}`) })),
            ]} />
          </div>
        </div>
        <div className={cn("h-10 shrink-0 items-center gap-2 border-b border-border px-3 text-sm md:flex", hideMobileHeader ? "flex" : "hidden")}>
          {!simulate ? <Button variant="ghost" size="sm" className="lg:hidden -ml-2" onClick={() => setDrawer(true)}><MessagesSquare className="h-4 w-4" />{t("chat.conversations")}</Button> : <span className="inline-flex items-center gap-1.5 text-muted-fg"><Eye className="h-4 w-4" />{t("sim.banner")}</span>}
          {headerExtra}
          <span className="min-w-0 flex-1 truncate text-muted-fg">{simulate ? "" : current?.title || ""}</span>
          {simulate ? <Button variant="ghost" size="sm" loading={createSim.isPending} onClick={() => createSim.mutate()}><RefreshCw className="h-4 w-4" />{t("sim.new")}</Button> : null}
        </div>
        <ConnectionBanner online={online} conn={conv?.conn ?? "idle"} />
        {cid && conv?.loaded ? (
          <FileLinks.Provider value={simulate ? null : fileHref}>
          <AttachmentRefresh.Provider value={refreshAttachments}>
          <MessageList ref={listRef} messages={messages} mode={simulate ? "visitor" : "owner"} agentName={a.name} agentAvatar={a.avatar_url} bubbleStyle={a.theme?.bubble_style}
            cardActions={{ mode: simulate ? "visitor" : "owner", onProposal, onQuickReply: simulate ? undefined : (text) => { void onSend(text, []); },
              onRoomAccess: simulate ? undefined : onRoomAccess }} onTurnInfo={(tid) => setTurnInfo(tid)} onWrong={simulate ? undefined : (tid) => setWrongTurn(tid)}
            onRetry={(m) => { const idx = messages.findIndex((x) => x.id === m.id); const prev = [...messages.slice(0, idx)].reverse().find((x) => x.role === "user"); if (prev) void onSend(prev.content, []); }}
            header={messages.length === 0 ? (
              <div className="px-4 pt-8 pb-2 text-center">
                <div className="mx-auto mb-3 flex justify-center"><Avatar mascot name={a.name} src={a.avatar_url} size={72} accent={a.theme?.accent} shape={a.theme?.avatar_shape} /></div>
                <div className="text-lg font-semibold">{simulate ? t("sim.empty_title") : t("chat.empty_title", { name: a.name })}</div>
                <p className="mt-1 text-sm text-muted-fg">{simulate ? t("sim.empty_desc") : t("chat.empty_desc")}</p>
              </div>) : null}
            footer={messages.length === 0 && starters.length ? <div className="flex flex-wrap justify-center gap-2 px-4 pb-3">{starters.map((s) => <button key={s} type="button" onClick={() => void onSend(s, [])} className="rounded-full border border-accent/40 bg-accent/8 px-3 py-2 text-[13px] text-accent min-h-[40px]">{s}</button>)}</div> : null} />
          </AttachmentRefresh.Provider>
          </FileLinks.Provider>
        ) : <div className="flex-1 p-4"><Skeleton className="h-full" /></div>}
        <div className="shrink-0 border-t border-border px-3 pt-2 pb-[max(0.5rem,var(--sab))]">
          <Composer ref={composerRef} onSend={onSend} onCancel={runner.cancel} busy={busy} disabled={!cid || !online} voice={voiceOn.stt && (simulate ? a.capabilities?.voice !== false : true)} onTranscribe={transcribe} attachments={!simulate} onUpload={upload}
            placeholder={simulate ? t("sim.placeholder") : t("chat.placeholder_owner", { name: a.name })} />
        </div>
      </FileDrop>
      <Sheet open={drawer} onClose={() => setDrawer(false)} title={t("chat.conversations")} side="right">{convList}</Sheet>
      <Dialog open={!!renaming} onClose={() => setRenaming(null)} title={t("common.rename")} size="sm"
        footer={<><Button variant="outline" onClick={() => setRenaming(null)}>{t("common.cancel")}</Button><Button loading={rename.isPending} onClick={() => renaming && rename.mutate({ id: renaming.id, title: (document.getElementById("rename-input") as HTMLInputElement)?.value ?? "" })}>{t("common.save")}</Button></>}>
        <Input id="rename-input" defaultValue={renaming?.title ?? ""} maxLength={160} autoFocus />
      </Dialog>
      <TurnInfoDialog agentId={a.id} turnId={turnInfo} onClose={() => setTurnInfo(null)} />
      <WrongAnswerDialog agentId={a.id} turnId={wrongTurn} onClose={() => setWrongTurn(null)}
        onSaved={(tid, fb) => {
          if (!cid) return;
          const st = useChat.getState();
          const m = (st.convs[cid]?.messages ?? []).find((x) => x.turn_id === tid);
          if (m) st.updateMessage(cid, m.id, { feedback: fb });
        }} />
    </div>
  );
}

/** What one answer cost, and whether anything was kept back from the visitor.
 *
 *  This used to print the provider, the model id, token counts with cache reads, time to
 *  first token and every tool call with its raw arguments. None of that is the owner's
 *  question about an answer their secretary gave, and a screen that answers questions
 *  nobody asked is a screen about us.
 */
export function TurnInfoDialog({ agentId, turnId, onClose }: { agentId: string; turnId: string | null; onClose: () => void }) {
  const t = useT();
  const q = useQuery({ queryKey: ["turn", agentId, turnId], queryFn: () => Chat.turn(agentId, turnId!), enabled: !!turnId });
  const d = q.data;
  return (
    <Dialog open={!!turnId} onClose={onClose} title={t("chat.turn_info")}>
      {q.isLoading ? <Skeleton className="h-24" /> : d ? (
        <KeyValue items={[
          { k: t("turn.credits"), v: fmtCredits(d.credits) },
          ...(d.redactions ? [{ k: t("turn.redactions"), v: d.redactions }] : []),
          ...(d.status === "failed" ? [{ k: t("turn.status"), v: <Badge tone="danger">{t("turn.failed")}</Badge> }] : []),
        ]} />
      ) : null}
    </Dialog>
  );
}


/** "이 답은 틀렸어요" (plan/41 §8).
 *
 *  The correction is not filed as a complaint: it is stored as the answer to the question
 *  that was asked, so the next person to ask gets the right one. The dialog says that,
 *  because a person will write differently if they know it will be repeated.
 */
function WrongAnswerDialog({ agentId, turnId, onClose, onSaved }: {
  agentId: string; turnId: string | null; onClose: () => void;
  onSaved: (turnId: string, fb: { verdict: string; note: string }) => void;
}) {
  const t = useT(); const locale = useLocale();
  const [note, setNote] = useState("");
  useEffect(() => { if (turnId) setNote(""); }, [turnId]);
  const save = useMutation({
    // [표시만 하기] marks the answer and keeps the note to itself; only [이렇게 답하게 하기]
    // turns what was written into the answer visitors will get.
    mutationFn: (teach: boolean) => Chat.turnFeedback(agentId, turnId!, { verdict: "wrong", note: teach ? note.trim() : "" }),
    onSuccess: (r) => {
      toast.success(t(r.faq_id ? "chat.wrong_taught" : "chat.wrong_noted"));
      onSaved(turnId!, { verdict: "wrong", note: r.faq_id ? r.note : "" });
      onClose();
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <Dialog open={!!turnId} onClose={onClose} title={t("chat.mark_wrong_title")} description={t("chat.mark_wrong_desc")}
      footer={<>
        <Button variant="ghost" onClick={() => save.mutate(false)} loading={save.isPending}>{t("chat.wrong_only")}</Button>
        <Button variant="accent" onClick={() => save.mutate(true)} loading={save.isPending} disabled={!note.trim()}>{t("chat.wrong_teach")}</Button>
      </>}>
      <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("chat.mark_wrong_ph")} className="min-h-[120px]" autoFocus />
    </Dialog>
  );
}
