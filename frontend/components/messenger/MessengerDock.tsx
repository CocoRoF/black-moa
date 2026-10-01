"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, ChevronDown, Eye, Maximize2, MessageSquare, PenLine, Search, X } from "@/components/icons";
import { Agents, Network, RoomAccess, Rooms, type Mentionable, type RoomFace, type RoomMessage, type RoomRow } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { confirm } from "@/lib/confirm";
import { fmtRelative } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { onLive } from "@/lib/live";
import { streamTurn } from "@/lib/sse";
import { cn } from "@/lib/utils";
import { useAuth } from "@/stores/auth";
import { useMessenger } from "@/stores/messenger";
import { Avatar } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Markdown } from "@/components/chat/Markdown";
import { Composer, type Attachment, type ComposerHandle } from "@/components/chat/Composer";
import { FileDrop } from "@/components/chat/FileDrop";
import { AttachmentRefresh, MessageAttachments } from "@/components/chat/MessageAttachments";
import { uploadFile } from "@/lib/upload";
import { ProfileModal } from "@/components/profile/ProfileModal";

/** A preview line: the words without the markdown that dressed them. */
function plain(s: string) { return s.replace(/(\*\*|__|`+|~~)/g, "").replace(/^[#>\s-]+/gm, "").replace(/\s+/g, " ").trim(); }

/** 메신저 — 어느 화면에 있든 오른쪽 아래 (plan/44 §7).
 *
 *  Everything said inside black-moa is a room, and a room can be read without leaving the page
 *  you were on. On a desktop that is a panel in the corner; on a phone there is no corner
 *  free, so it takes the screen.
 *
 *  Saying something to a person is this panel's own business. Saying something to a
 *  secretary is a turn — something is spent, tools may run — so that goes to the door that
 *  has always run turns, and the answer streams back into the same bubble.
 */
export function MessengerDock({ pill = true }: { pill?: boolean } = {}) {
  const t = useT();
  const qc = useQueryClient();
  const { open, roomId, unread, toggle, hide, openRoom, back, takePending, setUnread } = useMessenger();
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: Rooms.list, enabled: open, refetchOnWindowFocus: true });
  const badge = useQuery({ queryKey: ["rooms", "unread"], queryFn: Rooms.unread, refetchInterval: 120_000 });
  const [composing, setComposing] = useState(false);
  useEffect(() => { if (!open) setComposing(false); }, [open]);

  useEffect(() => { setUnread(rooms.data?.unread ?? badge.data?.unread ?? 0); }, [rooms.data?.unread, badge.data?.unread, setUnread]);

  // Somebody on some page asked for a room with a person or a secretary. The dock is the
  // one that knows how to get it, so the asking is a note left here rather than a call.
  const [opening, setOpening] = useState(false);
  const locale = useLocale();
  const openWith = useCallback((to: { userId?: string; agentId?: string }) => {
    setOpening(true);
    Rooms.open({ user_id: to.userId, agent_id: to.agentId })
      .then((r) => { setComposing(false); openRoom(r.id); void qc.invalidateQueries({ queryKey: ["rooms"] }); })
      .catch((e) => toast.error(friendlyError(e, locale)))
      .finally(() => setOpening(false));
  }, [openRoom, qc, locale]);
  useEffect(() => {
    if (!open) return;
    const want = takePending();
    if (want) openWith(want);
  }, [open, takePending, openWith]);

  // A message anywhere moves the badge and the list, on whatever this person has open.
  useEffect(() => onLive("room", () => {
    void qc.invalidateQueries({ queryKey: ["rooms"] });
    void qc.invalidateQueries({ queryKey: ["rooms", "unread"] });
  }), [qc]);

  return (
    <>
      {/* The pill. Hidden while the panel is up, because the panel has its own way out. */}
      {/* PC 앱의 틀 안(plan/62)에서는 문 위 탭 줄에 제 버튼이 있어 떠 있는 알약을 두지 않는다. */}
      {!open && pill ? (
        <button type="button" onClick={toggle} aria-label={t("msg.title")}
                className="messenger-pill fixed bottom-[max(1rem,var(--sab))] right-4 z-[80] hidden items-center gap-2 h-10 rounded-full border border-border bg-card px-4 shadow-xl transition-[transform,bottom] hover:-translate-y-0.5 md:inline-flex">
          <MessageSquare className="h-5 w-5 text-accent" />
          <span className="text-sm font-medium">{t("msg.title")}</span>
          {unread ? <span className="min-w-[20px] rounded-full bg-accent px-1.5 text-center text-[11px] leading-5 text-accent-fg">{unread}</span> : null}
        </button>
      ) : null}

      {open ? (
        <div className={cn("fixed z-[90] flex flex-col overflow-hidden border-border bg-card shadow-2xl",
                           "inset-0 md:inset-auto md:bottom-4 md:right-4 md:h-[min(640px,calc(100dvh-2rem))] md:w-[390px] md:rounded-2xl md:border")}>
          {roomId ? (
            <RoomView id={roomId} onBack={back} onClose={hide} />
          ) : composing ? (
            <Compose onBack={() => setComposing(false)} onClose={hide} onPick={openWith} busy={opening} />
          ) : (
            <>
              <header className="flex shrink-0 items-center gap-1 border-b border-border px-3 py-2 pt-[max(0.5rem,var(--sat))]">
                <h2 className="flex-1 px-1 text-sm font-semibold">{t("msg.title")}</h2>
                {/* Writing to somebody new starts here, not on some other page. */}
                <button type="button" onClick={() => setComposing(true)} aria-label={t("msg.new")}
                        className="rounded-lg p-2 text-muted-fg hover:bg-muted hover:text-fg"><PenLine className="h-5 w-5" /></button>
                <button type="button" onClick={hide} aria-label={t("common.close")}
                        className="rounded-lg p-2 text-muted-fg hover:bg-muted hover:text-fg">
                  <ChevronDown className="hidden h-5 w-5 md:block" /><X className="h-5 w-5 md:hidden" />
                </button>
              </header>
              <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">
                {rooms.isLoading || opening ? <div className="space-y-2 p-3"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
                  : rooms.data?.items.length ? (
                    <ul className="divide-y divide-border">
                      {rooms.data.items.map((r) => <RoomRowView key={r.id} room={r} onOpen={() => openRoom(r.id)} />)}
                    </ul>
                  ) : (
                    <EmptyState icon={<MessageSquare />} title={t("msg.empty")} description={t("msg.empty_desc")}
                                action={<Button variant="accent" onClick={() => setComposing(true)}><PenLine className="h-4 w-4" />{t("msg.new")}</Button>} />
                  )}
              </div>
            </>
          )}
        </div>
      ) : null}
    </>
  );
}

/** What to call the other side, and the second line under it.
 *  A secretary is named with whose it is: two people can each have a 제니. */
function faceLine(f: RoomFace | undefined, t: (k: string, v?: Record<string, string | number>) => string) {
  if (!f) return { name: "", sub: "" };
  if (f.kind !== "agent") return { name: f.name, sub: f.handle ? `@${f.handle}` : "" };
  return { name: f.name, sub: f.mine ? t("msg.mine") : f.owner_name ? t("msg.of_owner", { name: f.owner_name }) : t("net.kind_agent") };
}

function RoomRowView({ room, onOpen }: { room: RoomRow; onOpen: () => void }) {
  const t = useT(); const locale = useLocale();
  const face = room.others[0];
  const { name, sub } = faceLine(face, t);
  return (
    <li>
      <button type="button" onClick={onOpen}
              className={cn("flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/50", room.unread && "bg-accent/5")}>
        <Avatar name={name} src={face?.avatar_url ?? undefined} size={42} mascot={face?.kind === "agent"} />
        <span className="block min-w-0 flex-1">
          <span className="flex items-baseline gap-1.5">
            <span className={cn("truncate text-sm", room.unread ? "font-semibold" : "font-medium")}>{name || t("msg.untitled")}</span>
            {sub ? <span className="shrink-0 truncate text-[11px] text-muted-fg">{sub}</span> : null}
          </span>
          <span className={cn("block truncate text-xs", room.unread ? "text-fg" : "text-muted-fg")}>{room.last?.body ? plain(room.last.body) : t("msg.no_words")}</span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <span className="text-[11px] text-muted-fg">{room.last_message_at ? fmtRelative(room.last_message_at, locale) : ""}</span>
          {room.unread ? <span className="h-2 w-2 rounded-full bg-accent" /> : null}
        </span>
      </button>
    </li>
  );
}

/** Picking who to write to (plan/44 §7).
 *
 *  The people I can write to are the people I am connected to, and the secretaries I can
 *  reach are the published ones in my graph — the same list `@` offers, because it is the
 *  same question. My own secretaries come first: they need no link to be talked to.
 */
function Compose({ onBack, onClose, onPick, busy }: {
  onBack: () => void; onClose: () => void; onPick: (to: { userId?: string; agentId?: string }) => void; busy: boolean;
}) {
  const t = useT();
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim(), 250);
  const mine = useQuery({ queryKey: ["agents"], queryFn: () => Agents.list() });
  const found = useQuery({ queryKey: ["network", "mentionable", dq], queryFn: () => Network.mentionable(dq) });
  const own = (mine.data?.items ?? []).filter((a) => a.status === "active" && (!dq || a.name.toLowerCase().includes(dq.toLowerCase())));
  const ownIds = new Set(own.map((a) => a.id));
  const people = (found.data?.items ?? []).filter((x) => x.kind === "person");
  const bots = (found.data?.items ?? []).filter((x) => x.kind === "agent" && !ownIds.has(x.id));
  const nothing = !mine.isLoading && !found.isLoading && !own.length && !people.length && !bots.length;
  const row = (key: string, name: string, sub: string, avatar: string | null, mascot: boolean, go: () => void) => (
    <li key={key}>
      <button type="button" disabled={busy} onClick={go} className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-muted/50 disabled:opacity-60">
        <Avatar name={name} src={avatar ?? undefined} size={36} mascot={mascot} />
        <span className="block min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{name}</span>
          {sub ? <span className="block truncate text-xs text-muted-fg">{sub}</span> : null}
        </span>
      </button>
    </li>
  );
  const section = (label: string) => <li className="px-4 pb-1 pt-3 text-[11px] font-medium text-muted-fg">{label}</li>;
  return (
    <>
      <header className="flex shrink-0 items-center gap-1 border-b border-border px-2 py-2 pt-[max(0.5rem,var(--sat))]">
        <button type="button" onClick={onBack} aria-label={t("common.back")}
                className="rounded-lg p-2 text-muted-fg hover:bg-muted hover:text-fg"><ArrowLeft className="h-5 w-5" /></button>
        <h2 className="flex-1 px-1 text-sm font-semibold">{t("msg.new")}</h2>
        <button type="button" onClick={onClose} aria-label={t("common.close")}
                className="rounded-lg p-2 text-muted-fg hover:bg-muted hover:text-fg"><X className="h-5 w-5" /></button>
      </header>
      <div className="shrink-0 border-b border-border p-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("msg.search_ph")}
                 className="h-10 w-full rounded-xl bg-muted pl-9 pr-3 text-sm outline-none placeholder:text-muted-fg/70" />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">
        {mine.isLoading || found.isLoading ? <div className="space-y-2 p-3"><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
          : nothing ? <EmptyState icon={<Search />} title={t("msg.no_match")} description={t("msg.no_match_desc")} />
          : (
            <ul className="pb-2">
              {own.length ? section(t("msg.my_secretaries")) : null}
              {own.map((a) => row(`a:${a.id}`, a.name, t("msg.mine"), a.avatar_url, true, () => onPick({ agentId: a.id })))}
              {people.length ? section(t("msg.people")) : null}
              {people.map((p: Mentionable) => row(`p:${p.id}`, p.display_name, p.handle ? `@${p.handle}` : "", p.avatar_url, false, () => onPick({ userId: p.id })))}
              {bots.length ? section(t("msg.secretaries")) : null}
              {bots.map((b: Mentionable) => row(`b:${b.id}`, b.display_name,
                b.owner_name ? t("msg.of_owner", { name: b.owner_name }) : t("net.kind_agent"), b.avatar_url, true, () => onPick({ agentId: b.id })))}
            </ul>
          )}
      </div>
    </>
  );
}

/** One room, read and answered without leaving the page. */
function RoomView({ id, onBack, onClose }: { id: string; onBack: () => void; onClose: () => void }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const me = useAuth((s) => s.user);
  const room = useQuery({ queryKey: ["rooms", id], queryFn: () => Rooms.read(id) });
  const msgs = useQuery({ queryKey: ["rooms", id, "messages"], queryFn: () => Rooms.messages(id) });
  // 한 번 읽은 말은 이 방을 닫을 때까지 없어지지 않는다.
  //
  // 최신 서른 개를 다시 받아 오는 창은 새 말이 하나 들어올 때마다 한 칸씩 밀린다. 과거를
  // 따로 들고 있으면 그 사이로 정확히 한 줄이 빠져나가고, 읽던 사람에게는 아무 일도 없이
  // 대화 한 줄이 사라진 것으로 보인다. 그래서 받은 것을 전부 쌓고 시간순으로 세운다.
  const [kept, setKept] = useState<Record<string, RoomMessage>>({});
  const [more, setMore] = useState(true);
  useEffect(() => { setKept({}); setMore(true); }, [id]);
  const fold = useCallback((list: RoomMessage[]) => {
    if (!list.length) return;
    setKept((k) => ({ ...k, ...Object.fromEntries(list.map((m) => [m.id, m])) }));
  }, []);
  const forget = useCallback((mid: string) => setKept(({ [mid]: _drop, ...rest }) => rest), []);
  useEffect(() => { fold(msgs.data?.items ?? []); }, [msgs.data, fold]);
  const rows = useMemo(() => Object.values(kept)
    .sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0)), [kept]);
  const loadEarlier = async () => {
    const first = rows[0];
    if (!first) return;
    try {
      const r = await Rooms.messages(id, first.id);
      fold(r.items);
      if (r.items.length < 30) setMore(false);
    } catch (e) { toast.error(friendlyError(e, locale)); }
  };
  const [busy, setBusy] = useState(false);
  const composer = useRef<ComposerHandle | null>(null);
  //: The answer being typed by a secretary, before it is a row anybody can fetch.
  const [live, setLive] = useState<string | null>(null);
  //: 그 답이 어느 턴의 것인지. 같은 턴의 줄이 방에 앉으면 흐르던 말풍선은 물러난다.
  const [liveTurn, setLiveTurn] = useState<string | null>(null);
  const [profile, setProfile] = useState<RoomFace | null>(null);
  const foot = useRef<HTMLDivElement | null>(null);
  const face = room.data?.others[0];
  const { name, sub } = faceLine(face, t);
  const secretary = room.data?.kind === "secretary";

  // 답은 두 길로 온다. 하나는 지금 흐르는 글자고, 하나는 저장된 뒤 방에 방송되는 줄이다.
  // 그 줄이 앉는 순간 흐르던 말풍선을 물린다. 잠깐이라도 둘이 같이 서 있으면 비서가
  // 같은 말을 두 번 한 것처럼 보인다.
  const landed = !!liveTurn && rows.some((m) => m.role === "assistant" && m.turn_id === liveTurn);
  const showLive = live !== null && !landed;


  const toBottom = useCallback(() => foot.current?.scrollIntoView({ block: "end" }), []);
  useEffect(() => { toBottom(); }, [rows.length, showLive, live, toBottom]);
  // Opening a room is reading it, and reading it is the same fact on every device.
  useEffect(() => {
    void Rooms.markRead(id).then(() => {
      void qc.invalidateQueries({ queryKey: ["rooms"] });
      void qc.invalidateQueries({ queryKey: ["rooms", "unread"] });
    }).catch(() => { /* a badge that is one late is not worth a toast */ });
  }, [id, qc]);
  useEffect(() => onLive("room", (d: any) => {
    if (d?.room_id !== id) return;
    // 방금 온 말은 봉투에 실려 오니 그대로 세우고, 누가 자기 말을 거둬들이면 그 줄을 뺀다.
    if (d.message) fold([d.message as RoomMessage]);
    if (d.removed) forget(String(d.removed));
    void qc.invalidateQueries({ queryKey: ["rooms", id, "messages"] });
    void Rooms.markRead(id).catch(() => {});
  }), [id, qc, fold, forget]);

  // 비서가 이 사람끼리 방을 볼 수 있게 허락해 둔 것 (plan/55 §6-4). 방 위에 한 줄로 보이고
  // 그 자리에서 거둔다 — 모르는 사이에 비서가 보고 있는 대화는 없어야 한다.
  const grants = useQuery({ queryKey: ["room-grants", id], queryFn: () => RoomAccess.list({ room_id: id }), enabled: room.data?.kind === "dm" });
  const revokeAll = async () => {
    const list = grants.data?.items ?? [];
    if (!list.length || !await confirm({ title: t("msg.access_revoke_q"), confirmLabel: t("msg.access_revoke"), danger: true })) return;
    try {
      for (const g of list) await RoomAccess.revoke(g.id);
      await qc.invalidateQueries({ queryKey: ["room-grants"] });
    } catch (e) { toast.error(friendlyError(e, locale)); }
  };

  // 파일을 어느 입구로 올리나: 사람끼리 방은 내 [메신저] 칸, 내 비서 방은 내 비서의 파일,
  // 남의 비서 방은 그 비서 주인의 방문자 파일(그 방의 입구).
  const upload = async (f: File, onProgress: (r: number) => void): Promise<Attachment> => {
    try {
      const r = secretary && !room.data?.own_secretary
        ? await uploadFile(f, { url: `/api/rooms/${id}/uploads`, onProgress })
        : await uploadFile(f, { kind: secretary ? "attachment" : "room", onProgress });
      return { upload_id: r.upload_id, filename: r.filename, mime: r.mime, url: r.url, size: r.size, localId: r.upload_id };
    } catch (e) { throw new Error(friendlyError(e, locale)); }
  };

  const send = async (body: string, atts: Attachment[]) => {
    if ((!body && !atts.length) || busy) return;
    setBusy(true);
    const ids = atts.map((a) => a.upload_id);
    try {
      if (secretary) {
        // A turn, through the door that has always run turns. The words arrive here as
        // they are produced and land as a row when it finishes.
        let acc = "";
        setLive("");
        await streamTurn({
          url: `/api/rooms/${id}/turns`, body: { text: body, upload_ids: ids }, token: useAuth.getState().token,
          refreshable: true,
          onEvent: (ev) => {
            if (ev.type === "turn.start" && typeof ev.data?.turn_id === "string") setLiveTurn(ev.data.turn_id);
            if (ev.type === "text.delta" && typeof ev.data?.text === "string") { acc += ev.data.text; setLive(acc); }
          },
        });
      } else {
        await Rooms.say(id, body, ids);
      }
      await qc.invalidateQueries({ queryKey: ["rooms", id, "messages"] });
      await qc.invalidateQueries({ queryKey: ["rooms"] });
    } catch (e) {
      throw new Error(friendlyError(e, locale));
    } finally { setLive(null); setLiveTurn(null); setBusy(false); }
  };

  return (
    <>
      <header className="flex shrink-0 items-center gap-1 border-b border-border px-2 py-2 pt-[max(0.5rem,var(--sat))]">
        <button type="button" onClick={onBack} aria-label={t("common.back")}
                className="rounded-lg p-2 text-muted-fg hover:bg-muted hover:text-fg"><ArrowLeft className="h-5 w-5" /></button>
        <button type="button" onClick={() => face && setProfile(face)} className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1 py-1 text-left hover:bg-muted">
          <Avatar name={name} src={face?.avatar_url ?? undefined} size={32} mascot={face?.kind === "agent"} />
          <span className="block min-w-0">
            <span className="block truncate text-sm font-medium">{name}</span>
            {sub ? <span className="block truncate text-[11px] text-muted-fg">{sub}</span> : null}
          </span>
        </button>
        {/* The full-screen chat is for my own secretary. Somebody else's is reached the
            way anybody reaches it, and this panel is that way. */}
        {room.data?.own_secretary && room.data.conversation_id && face ? (
          <a href={`/app/chat?a=${face.id}&c=${room.data.conversation_id}`} aria-label={t("msg.expand")}
             className="rounded-lg p-2 text-muted-fg hover:bg-muted hover:text-fg"><Maximize2 className="h-4 w-4" /></a>
        ) : null}
        <button type="button" onClick={onClose} aria-label={t("common.close")}
                className="rounded-lg p-2 text-muted-fg hover:bg-muted hover:text-fg"><X className="h-5 w-5" /></button>
      </header>

      {grants.data?.items.length ? (
        <div className="flex shrink-0 items-center gap-2 border-b border-border bg-accent/5 px-3 py-1.5 text-xs">
          <Eye className="h-3.5 w-3.5 shrink-0 text-accent" />
          <span className="min-w-0 flex-1 truncate">{t("msg.access_on", { names: grants.data.items.map((g) => g.agent.name).join(", ") })}</span>
          <button type="button" onClick={() => void revokeAll()} className="shrink-0 font-medium text-accent hover:underline">{t("msg.access_revoke")}</button>
        </div>
      ) : null}
      <FileDrop className="flex min-h-0 flex-1 flex-col" onFiles={(fs) => { composer.current?.addFiles(fs); }}>
      <AttachmentRefresh.Provider value={() => qc.invalidateQueries({ queryKey: ["rooms", id, "messages"] })}>
      {/* A short conversation sits on the floor, not at the ceiling: an empty column above
          three lines reads as a room that lost something. */}
      <div className="flex min-h-0 flex-1 flex-col justify-end overflow-y-auto px-3 py-3 scrollbar-thin">
        <div className="space-y-3">
        {/* Only when there is something before this. A room shorter than one screen has
            nothing older and should not offer to look for it. */}
        {!msgs.isLoading && more && rows.length >= 30 ? (
          <button type="button" onClick={() => void loadEarlier()}
                  className="mx-auto block rounded-lg px-3 py-1 text-xs text-muted-fg hover:bg-muted">{t("msg.earlier")}</button>
        ) : null}
        {msgs.isLoading ? <Skeleton className="h-24" /> : rows.map((m) => (
          <Bubble key={m.id} m={m} mine={!!me && m.sender_user_id === me.id} face={face}
                  onUnsay={!secretary && me && m.sender_user_id === me.id ? async () => {
                    if (!await confirm({ title: t("msg.unsay_q"), danger: true, confirmLabel: t("common.delete") })) return;
                    try {
                      await Rooms.unsay(id, m.id);
                      forget(m.id);
                      await qc.invalidateQueries({ queryKey: ["rooms", id, "messages"] });
                      await qc.invalidateQueries({ queryKey: ["rooms"] });
                    } catch (e) { toast.error(friendlyError(e, locale)); }
                  } : undefined} />
        ))}
        {!msgs.isLoading && !rows.length && !showLive ? (
          <p className="py-8 text-center text-xs text-muted-fg">{t(secretary ? "msg.first_ask" : "msg.first_say", { name })}</p>
        ) : null}
        {showLive ? (
          <Bubble m={{ id: "live", role: "assistant", body: live, sender_user_id: null, sender_agent_id: null,
                       attachments: [], cards: [], turn_id: null, created_at: new Date().toISOString() }}
                  mine={false} face={face} typing={!live} />
        ) : null}
        <div ref={foot} />
        </div>
      </div>

      {/* 비서 대화와 같은 글칸이다(plan/55 §6-1): 붙여넣기·끌어다 놓기·올라가는 만큼 차오르는
          칩이 어디서나 같다. 한 줄이면 한 줄, 넘치면 두 층. */}
      <footer className="shrink-0 border-t border-border p-2 pb-[max(0.5rem,var(--sab))]">
        <Composer ref={composer} onSend={send} sending={busy} attachments onUpload={upload}
                  placeholder={t(secretary ? "msg.ask_ph" : "msg.say_ph")} />
      </footer>
      </AttachmentRefresh.Provider>
      </FileDrop>
      {profile ? (
        <ProfileModal userId={profile.kind === "person" ? profile.id : undefined}
                      agentId={profile.kind === "agent" ? profile.id : undefined}
                      onClose={() => setProfile(null)} />
      ) : null}
    </>
  );
}

function Bubble({ m, mine, face, typing, onUnsay }: {
  m: RoomMessage; mine: boolean; face?: RoomFace; typing?: boolean;
  /** Taking it back. Only ever my own, and only between people. */
  onUnsay?: () => void;
}) {
  const locale = useLocale(); const t = useT();
  // 비서의 답은 서식이 있는 글이고, 사람이 친 말은 친 그대로다. 받는 쪽에서만 굵게 보이는
  // 별표는 보낸 사람이 쓴 적 없는 글자다.
  const bot = m.role === "assistant" || !!m.sender_agent_id;
  const files = (m.attachments ?? []).filter((a: any) => a && a.upload_id);
  if (m.role === "card" || (!m.body && !typing && !files.length)) return null;
  return (
    <div className={cn("flex gap-2", mine ? "justify-end" : "justify-start")}>
      {!mine ? <Avatar name={face?.name ?? ""} src={face?.avatar_url ?? undefined} size={26} mascot={face?.kind === "agent"} className="mt-auto shrink-0" /> : null}
      <div className={cn("flex max-w-[78%] flex-col gap-1", mine ? "items-end" : "items-start")}>
      {files.length ? <MessageAttachments items={files} align={mine ? "end" : "start"} /> : null}
      {m.body || typing ? (
      <div className={cn("rounded-2xl px-3 py-2 text-sm leading-relaxed",
                         mine ? "bg-accent text-accent-fg" : "bg-muted text-fg")}>
        {typing ? <span className="inline-flex gap-1 py-1">{[0, 1, 2].map((i) => (
          <span key={i} className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-fg" style={{ animationDelay: `${i * 150}ms` }} />
        ))}</span> : bot ? <Markdown text={m.body} />
          : <span className="whitespace-pre-wrap break-words">{m.body}</span>}
        {!typing ? (
          <div className={cn("mt-0.5 flex items-center gap-2 text-[10px]", mine ? "text-accent-fg/70" : "text-muted-fg")}>
            <span>{fmtRelative(m.created_at, locale)}</span>
            {onUnsay ? <button type="button" onClick={onUnsay} className="hover:underline">{t("common.delete")}</button> : null}
          </div>
        ) : null}
      </div>
      ) : (
        <div className="flex items-center gap-2 text-[10px] text-muted-fg">
          <span>{fmtRelative(m.created_at, locale)}</span>
          {onUnsay ? <button type="button" onClick={onUnsay} className="hover:underline">{t("common.delete")}</button> : null}
        </div>
      )}
      </div>
    </div>
  );
}
