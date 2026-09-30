"use client";
import { FactStatement } from "./FactStatement";
import { useState, type FormEvent } from "react";
import { ArrowLeftRight, Building2, CalendarClock, CalendarDays, Check, Download, FileText, Mail, MessageSquare, Network as NetworkIcon, Search, ShieldCheck, Star, UserCheck, UserPen } from "@/components/icons";
import Link from "next/link";
import { type CardData } from "@/lib/api";
import { ConnectionControl } from "@/components/network/Connection";
import { DateTimePicker, parseISO, toISODateTime } from "@cocorof/react-calendar";
import { useRcalTheme } from "@/lib/theme";
import { useLocale, useT } from "@/lib/i18n";
import { useCompanyFeatures } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface CardActions {
  mode: "owner" | "visitor";
  resting?: boolean;
  onLeaveMessage?: (f: { name: string; contact: string; message: string }) => Promise<void>;
  onMeetingRequest?: (f: { name: string; contact: string; purpose: string; slots: string[] }) => Promise<void>;
  onProposal?: (proposalId: string, decision: "accept" | "reject") => Promise<void>;
  /** Puts a line into the composer and sends it — the click is the owner's confirmation turn (plan/39). */
  onQuickReply?: (text: string) => void;
  /** 사람끼리 방을 비서에게 보여 줄지에 대한 답 (plan/55 §6-4). 누른 것이 곧 다음 턴이 된다. */
  onRoomAccess?: (messageId: string, card: CardData, roomId: string | null, choice: "conversation" | "always" | "deny") => Promise<void>;
}

function Shell({ icon, title, children, tone = "accent", className }: { icon: React.ReactNode; title: React.ReactNode; children?: React.ReactNode; tone?: "accent" | "success" | "neutral"; className?: string }) {
  return (
    <div className={cn("rounded-2xl border border-border bg-card p-3.5 text-sm shadow-soft w-full max-w-[420px]", className)}>
      <div className={cn("flex items-center gap-2 font-medium", tone === "accent" ? "text-accent" : tone === "success" ? "text-success" : "text-fg")}>
        <span className="[&>svg]:h-4 [&>svg]:w-4">{icon}</span>{title}
      </div>
      {children ? <div className="mt-2 text-fg">{children}</div> : null}
    </div>
  );
}

export function LeaveMessageForm({ onSubmit, compact }: { onSubmit: (f: { name: string; contact: string; message: string }) => Promise<void>; compact?: boolean }) {
  const t = useT();
  const [name, setName] = useState(""); const [contact, setContact] = useState(""); const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false); const [done, setDone] = useState(false);
  const submit = async (e: FormEvent) => { e.preventDefault(); if (!message.trim()) return; setBusy(true); try { await onSubmit({ name, contact, message }); setDone(true); } finally { setBusy(false); } };
  if (done) return <p className="flex items-center gap-1.5 text-success"><Check className="h-4 w-4" />{t("card.message_sent")}</p>;
  return (
    <form onSubmit={submit} className="space-y-2">
      <div className={cn("grid gap-2", compact ? "" : "sm:grid-cols-2")}>
        <Input placeholder={t("card.your_name")} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
        <Input placeholder={t("card.your_contact")} value={contact} onChange={(e) => setContact(e.target.value)} autoComplete="email" inputMode="email" />
      </div>
      <Textarea placeholder={t("card.message_placeholder")} value={message} onChange={(e) => setMessage(e.target.value)} required className="min-h-[80px]" />
      <Button type="submit" size="sm" variant="accent" loading={busy} className="w-full">{t("card.send_message")}</Button>
    </form>
  );
}

export function MeetingRequestForm({ onSubmit, initialPurpose = "" }: { onSubmit: (f: { name: string; contact: string; purpose: string; slots: string[] }) => Promise<void>; initialPurpose?: string }) {
  const t = useT(); const locale = useLocale(); const rcalTheme = useRcalTheme();
  const [name, setName] = useState(""); const [contact, setContact] = useState(""); const [purpose, setPurpose] = useState(initialPurpose);
  const [slots, setSlots] = useState<string[]>(["", "", ""]); const [busy, setBusy] = useState(false); const [done, setDone] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); const s = slots.filter(Boolean); if (!purpose.trim() || !s.length) return;
    setBusy(true); try { await onSubmit({ name, contact, purpose, slots: s }); setDone(true); } finally { setBusy(false); }
  };
  if (done) return <p className="flex items-center gap-1.5 text-success"><Check className="h-4 w-4" />{t("card.meeting_sent")}</p>;
  return (
    <form onSubmit={submit} className="space-y-2">
      <div className="grid gap-2 sm:grid-cols-2">
        <Input placeholder={t("card.your_name")} value={name} onChange={(e) => setName(e.target.value)} />
        <Input placeholder={t("card.your_contact")} value={contact} onChange={(e) => setContact(e.target.value)} inputMode="email" />
      </div>
      <Textarea placeholder={t("card.meeting_purpose")} value={purpose} onChange={(e) => setPurpose(e.target.value)} required className="min-h-[64px]" />
      <div className="space-y-1.5">
        <div className="text-xs text-muted-fg">{t("card.meeting_slots")}</div>
        {slots.map((s, i) => (
          <DateTimePicker key={i} value={parseISO(s)} minDate={new Date()} minuteStep={30} locale={locale}
                          className={rcalTheme} panelClassName={rcalTheme}
            onChange={(d) => setSlots(slots.map((x, j) => (j === i ? toISODateTime(d) : x)))} />
        ))}
      </div>
      <Button type="submit" size="sm" variant="accent" loading={busy} className="w-full">{t("card.send_meeting")}</Button>
    </form>
  );
}

export function CardRenderer({ card, actions, messageId }: { card: CardData; actions: CardActions; messageId?: string }) {
  const t = useT();
  // 관리자가 기업 기능을 끄면 지난 대화의 기업 카드와 소속도 보이지 않는다 (plan/71).
  const companies = useCompanyFeatures().on;
  const p = card.payload ?? {};
  switch (card.card_type) {
    case "room_access":
      return <RoomAccessCard card={card} actions={actions} messageId={messageId} />;
    case "leave_message":
      return (
        <Shell icon={<MessageSquare />} title={p.status === "delivered" ? t("card.message_delivered") : t("card.leave_message")} tone={p.status === "delivered" ? "success" : "accent"}>
          {p.message ? <p className="whitespace-pre-wrap text-muted-fg">{p.message}</p> : null}
          {p.status !== "delivered" && actions.mode === "visitor" && actions.onLeaveMessage ? <div className="mt-2"><LeaveMessageForm onSubmit={actions.onLeaveMessage} /></div> : null}
          {p.status && p.status !== "delivered" ? <Badge className="mt-2">{p.status}</Badge> : null}
        </Shell>
      );
    case "meeting_request":
      return (
        <Shell icon={<CalendarClock />} title={t("card.meeting_request")} tone={p.status === "submitted" || p.status === "delivered" ? "success" : "accent"}>
          {p.purpose ? <p className="text-muted-fg">{p.purpose}</p> : null}
          {Array.isArray(p.slots) && p.slots.length ? <ul className="mt-1.5 space-y-1">{p.slots.map((s: string, i: number) => <li key={i} className="rounded-lg bg-muted px-2 py-1 text-xs">{s}</li>)}</ul> : null}
          {p.status ? <Badge className="mt-2" tone={p.status === "accepted" ? "success" : p.status === "declined" ? "danger" : "neutral"}>{t(`card.status_${p.status}`) === `card.status_${p.status}` ? p.status : t(`card.status_${p.status}`)}</Badge> : null}
          {!p.status && actions.mode === "visitor" && actions.onMeetingRequest ? <div className="mt-2"><MeetingRequestForm onSubmit={actions.onMeetingRequest} initialPurpose={p.purpose} /></div> : null}
        </Shell>
      );
    case "schedule_saved":
      return (
        <Shell icon={<CalendarDays />} title={t(`card.sched_${p.action}`)} tone={p.action === "removed" ? "neutral" : "success"}>
          <p className={cn("font-medium", p.action === "removed" && "text-muted-fg line-through")}>{p.title}</p>
          {p.when ? <p className="mt-0.5 text-xs text-muted-fg">{p.when}</p> : null}
          {actions.mode === "owner" ? (
            <Link href={p.start_date ? `/app/schedule?date=${p.start_date}` : "/app/schedule"} className="mt-2 inline-flex text-xs font-medium text-accent hover:underline">{t("card.sched_open")}</Link>
          ) : null}
        </Shell>
      );
    case "email_sent":
      return (
        <Shell icon={<Mail />} title={t("card.email_sent")} tone="success">
          <p className="text-muted-fg">{p.subject}</p>
          <p className="mt-1 text-xs text-muted-fg">
            {t("card.email_to", { to: String(p.to ?? "") })}
            {p.reply_to ? <> · {t("card.email_reply_to", { to: String(p.reply_to) })}</> : null}
          </p>
          {typeof p.remaining_today === "number" ? <Badge className="mt-2">{t("card.email_left", { n: p.remaining_today })}</Badge> : null}
        </Shell>
      );
    case "visitor_identified":
      return <Shell icon={<UserCheck />} title={t("card.visitor_identified", { name: p.name ?? "" })} tone="success" />;
    case "file":
      return (
        <Shell icon={<FileText />} title={p.title || p.filename || t("card.file")}>
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-muted-fg text-xs">{p.filename}</span>
            <a href={p.url} target="_blank" rel="noopener noreferrer" className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-accent px-3 text-xs font-medium text-accent-fg"><Download className="h-3.5 w-3.5" />{t("card.download")}</a>
          </div>
          {p.expires_in_s ? <p className="mt-1 text-[11px] text-muted-fg">{t("card.link_expires", { min: Math.max(1, Math.round(p.expires_in_s / 60)) })}</p> : null}
        </Shell>
      );
    case "fact_saved":
      return (
        <Shell icon={<ShieldCheck />} title={t("card.fact_saved")} tone="success">
          <p><FactStatement subject={p.subject} predicate={p.predicate} object={p.object} statement={p.statement} /></p>
          {p.visibility ? <Badge className="mt-1.5" tone={p.visibility === "public" ? "accent" : "neutral"}>{t(`vis.${p.visibility}`)}</Badge> : null}
        </Shell>
      );
    case "network_proposal":
      return (
        <Shell icon={<NetworkIcon />} title={t("card.network_proposal")}>
          <p className="text-muted-fg text-xs">{p.kind}</p>
          <pre className="mt-1 whitespace-pre-wrap font-sans text-sm">{summarizeProposal(p.payload)}</pre>
          {actions.mode === "owner" && actions.onProposal && p.proposal_id ? (
            <ProposalButtons onDecide={(d) => actions.onProposal!(p.proposal_id, d)} />
          ) : null}
        </Shell>
      );
    case "profile_updated":
      return (
        <Shell icon={<UserPen />} title={t("card.profile_updated")} tone="success">
          {Array.isArray(p.fields) ? <div className="flex flex-wrap gap-1">{p.fields.map((f: string) => <Badge key={f}>{f}</Badge>)}</div> : null}
          {p.visibility ? <p className="mt-1 text-xs text-muted-fg">{t("card.visibility")}: {typeof p.visibility === "string" ? t(`vis.${p.visibility}`) : Object.entries(p.visibility).map(([k, v]) => `${k}=${v}`).join(", ")}</p> : null}
        </Shell>
      );
    case "owner_reply":
      return (
        <Shell icon={<Mail />} title={t("card.owner_reply")} tone="accent" className="bg-accent/5">
          <p className="whitespace-pre-wrap">{p.text}</p>
        </Shell>
      );
    case "contact_card":
      return (
        <Shell icon={<Mail />} title={t("card.contact")}>
          <div className="flex flex-wrap gap-2">
            {p.email ? <a className="rounded-lg bg-muted px-3 py-1.5 text-xs" href={`mailto:${p.email}`}>{p.email}</a> : null}
            {Array.isArray(p.links) ? p.links.map((l: string) => <a key={l} className="rounded-lg bg-muted px-3 py-1.5 text-xs" href={l} target="_blank" rel="noopener noreferrer">{l}</a>) : null}
          </div>
        </Shell>
      );
    case "proactive":
      return null; // the bubble shows the "sent first" label; there is nothing to render as a card
    case "relay_note":
      return null; // the opener sits in the secretary's own transcript; the conversation is tagged already
    case "relay_candidates":
      return (
        <Shell icon={<Search />} title={t("card.relay_candidates", { q: p.query || "" })}>
          <ul className="space-y-1.5">
            {(p.items ?? []).map((it: any) => (
              <li key={it.candidate_id} className="flex items-center gap-2 rounded-xl border border-border px-2.5 py-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{it.name}{it.title || (companies && it.company) ? <span className="ml-1 font-normal text-muted-fg">· {[it.title, companies ? it.company : ""].filter(Boolean).join(", ")}</span> : null}</div>
                  <div className="truncate text-[11px] text-muted-fg">{t(`card.relay_src_${it.source}`)}{it.secretary ? ` · ${t("card.relay_secretary", { name: it.secretary })}` : ` · ${t("card.relay_unreachable")}`}</div>
                  {/* Why this person is on the list: what they wrote, or what they say they do. */}
                  {it.why ? <div className="truncate text-[11px] text-accent">{it.why}</div> : null}
                </div>
                {it.reachable && actions.mode === "owner" && actions.onQuickReply ? (
                  <Button size="sm" variant="outline" onClick={() => actions.onQuickReply!(t("card.relay_confirm_text", { name: it.name, secretary: it.secretary }))}>{t("card.relay_send_to")}</Button>
                ) : null}
              </li>
            ))}
          </ul>
        </Shell>
      );
    case "relay_started":
      return (
        <Shell icon={<ArrowLeftRight />} title={p.status === "closed" || p.status === "failed" ? t("card.relay_not_sent") : t("card.relay_started", { agent: p.target_agent_name || "" })} tone={p.status === "closed" || p.status === "failed" ? "neutral" : "accent"}>
          {p.status === "closed" || p.status === "failed" ? <p className="text-muted-fg">{[`relay.err_${p.close_reason}`, `relay.reason_${p.close_reason}`].map((k) => t(k)).find((v, i) => v !== [`relay.err_${p.close_reason}`, `relay.reason_${p.close_reason}`][i]) ?? p.close_reason}</p>
            : <p className="text-muted-fg">{p.target_owner_name ? t("card.relay_started_desc", { who: p.target_owner_name }) : null}{p.purpose ? ` · ${p.purpose}` : ""}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-3">
            {p.relay_id ? <Link href={`/app/conversations?relay=${p.relay_id}`} className="text-xs text-accent underline-offset-2 hover:underline">{t("card.relay_open")}</Link> : null}
            {/* The exchange is the reason to know each other: the conversation becomes a
                connection between the people, not a thing their secretaries did once. */}
            {actions.mode === "owner" && p.target_user_id ? <ConnectAfterRelay userId={String(p.target_user_id)} name={String(p.target_owner_name || "")} /> : null}
          </div>
        </Shell>
      );
    case "company_card": {
      if (!companies) return null;
      const c = p.company ?? {}; const st = p.stats ?? {};
      return (
        <Shell icon={<Building2 />} title={c.name || t("cx.title")} tone="neutral">
          <p className="text-xs text-muted-fg">{[c.industry_text, c.region_text, c.market].filter(Boolean).join(" · ")}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {st.n ? <span className="inline-flex items-center gap-1 font-semibold"><Star className="h-3.5 w-3.5 fill-success text-success" />{Number(st.rating).toFixed(1)}<span className="font-normal text-muted-fg">({st.n})</span></span> : <span className="text-muted-fg">{t("cx.no_stats")}</span>}
            {st.recommend != null ? <span className="text-muted-fg">{t("cx.recommend_rate")} {st.recommend}%</span> : null}
            {st.salary_median ? <span className="text-muted-fg">{t("cx.salary_median")} {Number(st.salary_median).toLocaleString()}{t("cx.manwon")}</span> : null}
            {c.open_jobs ? <span className="text-accent">{t("cx.hiring_n", { n: c.open_jobs })}</span> : null}
          </div>
          {c.id ? <Link href={`/app/community/companies/${c.id}`} className="mt-2 inline-block text-xs text-accent underline-offset-2 hover:underline">{t("cx.view_company")}</Link> : null}
        </Shell>
      );
    }
    case "relay_result":
      return (
        <Shell icon={<ArrowLeftRight />} title={t("card.relay_result", { agent: p.target_agent_name || "" })} tone={p.reason === "done" || p.reason === "max_messages" ? "success" : "neutral"}>
          <p className="text-xs text-muted-fg">{p.reason_text || p.reason}{typeof p.message_count === "number" ? ` · ${t("relay.messages_n", { n: p.message_count })}` : ""}</p>
          {p.text ? <p className="mt-1 whitespace-pre-wrap">{p.text}</p> : null}
          <div className="mt-2 flex flex-wrap items-center gap-3">
            {p.relay_id ? <Link href={`/app/conversations?relay=${p.relay_id}`} className="text-xs text-accent underline-offset-2 hover:underline">{t("card.relay_open")}</Link> : null}
            {/* The exchange is the reason to know each other: the conversation becomes a
                connection between the people, not a thing their secretaries did once. */}
            {actions.mode === "owner" && p.target_user_id ? <ConnectAfterRelay userId={String(p.target_user_id)} name={String(p.target_owner_name || "")} /> : null}
          </div>
        </Shell>
      );
    default:
      return <Shell icon={<FileText />} title={card.card_type} tone="neutral"><pre className="whitespace-pre-wrap text-xs text-muted-fg">{JSON.stringify(p, null, 2)}</pre></Shell>;
  }
}

function summarizeProposal(payload: any): string {
  if (!payload) return "";
  if (typeof payload === "string") return payload;
  const parts: string[] = [];
  if (payload.name) parts.push(payload.name);
  if (payload.kind) parts.push(`(${payload.kind})`);
  if (payload.rel) parts.push(`— ${payload.rel}`);
  if (payload.src_name && payload.dst_name) parts.push(`${payload.src_name} → ${payload.dst_name}`);
  if (payload.summary) parts.push(payload.summary);
  return parts.length ? parts.join(" ") : JSON.stringify(payload, null, 1);
}

function ProposalButtons({ onDecide }: { onDecide: (d: "accept" | "reject") => Promise<void> }) {
  const t = useT();
  const [state, setState] = useState<"idle" | "busy" | "accept" | "reject">("idle");
  if (state === "accept" || state === "reject") return <p className="mt-2 text-xs text-muted-fg">{t(`card.proposal_${state}ed`)}</p>;
  return (
    <div className="mt-2 flex gap-2">
      <Button size="sm" variant="accent" loading={state === "busy"} onClick={async () => { setState("busy"); try { await onDecide("accept"); setState("accept"); } catch { setState("idle"); } }}>{t("common.accept")}</Button>
      <Button size="sm" variant="outline" disabled={state === "busy"} onClick={async () => { setState("busy"); try { await onDecide("reject"); setState("reject"); } catch { setState("idle"); } }}>{t("common.reject")}</Button>
    </div>
  );
}


/** Turning a finished exchange into a connection between the people (plan/41 §6, M5).
 *  지금 사이에 맞는 단추 하나 — 맺으면 [인맥 지우기] 로 바뀐다 (plan/69). */
function ConnectAfterRelay({ userId, name }: { userId: string; name: string }) {
  return <ConnectionControl userId={userId} name={name || undefined} look="link" className="text-xs" />;
}

/** 비서가 사람끼리 방을 읽어도 되는지 묻는 카드 (plan/55 §6-4).
 *
 *  "이 방이 맞나" 와 "읽어도 되나" 를 한 번에 묻는다. 같은 이름이 여럿이면 후보를 늘어놓고
 *  고르게 한다. 누르면 허락이 기록되고, 그 선택이 주인의 말로 대화에 들어가 턴이 이어진다.
 *  답한 뒤에는 무엇을 골랐는지만 남는다 — 다시 열어도 같다(서버가 카드에 적어 둔다).
 */
function RoomAccessCard({ card, actions, messageId }: { card: CardData; actions: CardActions; messageId?: string }) {
  const t = useT(); const locale = useLocale();
  const p = card.payload ?? {};
  const cands: any[] = p.candidates ?? [];
  const [pick, setPick] = useState<string | null>(cands.length === 1 ? cands[0].room_id : null);
  const [busy, setBusy] = useState<string | null>(null);
  const decided = p.decided as { choice: string; room_id: string | null } | undefined;
  const chosen = cands.find((c) => c.room_id === (decided?.room_id ?? pick));
  const meta = (c: any) => [
    c.last_message_at ? t("card.room_last", { at: new Date(c.last_message_at).toLocaleString(locale === "en" ? "en-US" : "ko-KR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) }) : null,
    t("card.room_messages", { n: c.message_count ?? 0 }),
    c.messages_with_files ? t("card.room_files", { n: c.messages_with_files }) : null,
  ].filter(Boolean).join(" · ");
  const who = (c: any) => `${c.name}${c.handle ? ` (@${c.handle})` : ""}`;
  const answer = async (choice: "conversation" | "always" | "deny") => {
    if (!actions.onRoomAccess || !messageId) return;
    setBusy(choice);
    try { await actions.onRoomAccess(messageId, card, choice === "deny" ? null : pick, choice); } finally { setBusy(null); }
  };
  const title = cands.length === 1 || chosen ? t("card.room_access_title", { who: who(chosen ?? cands[0]) }) : t("card.room_access_which");
  return (
    <Shell icon={<ShieldCheck />} title={title} tone={decided ? (decided.choice === "deny" ? "neutral" : "success") : "accent"}>
      {cands.length > 1 && !decided ? (
        <ul className="mb-2 space-y-1.5" role="radiogroup" aria-label={t("card.room_access_which")}>
          {cands.map((c) => (
            <li key={c.room_id}>
              <button type="button" role="radio" aria-checked={pick === c.room_id} onClick={() => setPick(c.room_id)}
                      className={cn("w-full rounded-xl border px-2.5 py-2 text-left", pick === c.room_id ? "border-accent bg-accent/5" : "border-border hover:bg-muted")}>
                <div className="truncate text-sm font-medium">{who(c)}</div>
                <div className="truncate text-[11px] text-muted-fg">{meta(c)}</div>
              </button>
            </li>
          ))}
        </ul>
      ) : chosen ? <p className="text-xs text-muted-fg">{meta(chosen)}</p> : null}
      {p.reason ? <p className="mt-1.5 text-muted-fg"><span className="text-xs">{t("card.room_reason")}</span> {p.reason}</p> : null}
      {decided ? (
        <p className="mt-2 flex items-center gap-1.5 text-sm">
          {decided.choice === "deny" ? t("card.room_denied") : decided.choice === "always" ? t("card.room_granted_always") : t("card.room_granted_here")}
          {decided.choice !== "deny" && p.agent_id ? <Link href={`/app/agents/${p.agent_id}/knowledge`} className="text-xs text-accent underline-offset-2 hover:underline">{t("card.room_manage")}</Link> : null}
        </p>
      ) : actions.mode === "owner" && actions.onRoomAccess && messageId ? (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <Button size="sm" variant="accent" disabled={!pick || !!busy} loading={busy === "conversation"} onClick={() => void answer("conversation")}>{t("card.room_allow_here")}</Button>
          <Button size="sm" variant="outline" disabled={!pick || !!busy} loading={busy === "always"} onClick={() => void answer("always")}>{t("card.room_allow_always")}</Button>
          <Button size="sm" variant="ghost" disabled={!!busy} loading={busy === "deny"} onClick={() => void answer("deny")}>{t("card.room_deny")}</Button>
        </div>
      ) : null}
    </Shell>
  );
}
