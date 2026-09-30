"use client";
/**
 * 인박스 항목 하나 (plan/70) — 가운데에 뜨는 창, 소식의 종류마다 그에 맞는 모양.
 *
 * 예전에는 오른쪽에서 밀려 나오는 한 가지 모양이 모든 소식을 받았다: 방문자 칸과 [답장] 이 늘 붙어 있어서, 비서끼리
 * 나눈 대화에도 "방문자 차단"·"답장" 이 떴고, 댓글 소식에도 이메일 답장 칸이 떴다. 이제 소식마다 할 일이 다르다.
 *
 *  - 방문자가 남긴 말(message)        비서가 받아 전해 준 말과 남긴 사람. 여기서 답하지 않는다 — 전해 들은 것으로 충분하다.
 *  - 미팅 요청(meeting_request)        희망 시간·목적 → 시간을 골라 [수락하고 일정에 넣기] 또는 [거절].
 *  - 비서가 답하지 못한 질문           다음에는 이렇게 답하라고 비서에게 가르친다(지식이 된다).
 *  - 비서끼리 나눈 대화(relay_*)       요약·상대·[인맥 맺기]·대화 기록. 답하는 칸은 없다.
 *  - 광장 댓글·답글(community_*)       그 글의 그 댓글을 보이고, 거기에 **답글**을 단다.
 *  - 소식 글의 댓글·답글·언급(post_*)  그 글을 열어 그 댓글을 짚고, 입력칸이 그 댓글의 답글이 된다.
 *  - 나를 연결했어요(person_follow)    그 사람과 지금 사이, [인맥 맺기]·[프로필].
 *  - 관심 기업(company_*)              새 리뷰·공고의 요지와 [보러 가기].
 *  - 저장 공간(storage_notice)         얼마나 찼는지와 [파일 정리하기].
 */
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Ban, Bot, Briefcase, Building2, CalendarCheck, Check, ChevronDown, GraduationCap, HardDrive, Mail, MessageSquare, Send, Star, UserRound, X } from "@/components/icons";
import { Community, Inbox, Network, type CommunityComment, type InboxItem } from "@/lib/api";
import { DateTimePicker, parseISO, toISODateTime } from "@cocorof/react-calendar";
import { useRcalTheme } from "@/lib/theme";
import { useLocale, useT, type TFn } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtBytes, fmtDateTime, fmtNumber, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useMessenger } from "@/stores/messenger";
import { Dialog } from "@/components/ui/dialog";
import { Button, buttonLook } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar } from "@/components/ui/misc";
import { Input, Textarea } from "@/components/ui/input";
import { CardRenderer } from "@/components/chat/CardRenderer";
import { Markdown } from "@/components/chat/Markdown";
import { ConnectionControl, useLink } from "@/components/network/Connection";
import { PostModal } from "@/components/feed/PostModal";
import { inboxTitle } from "./inboxUtil";

/** 소식 글(내 페이지의 글)에 달린 것 — 그 글을 열어 보인다. */
const POST_KINDS = new Set(["post_comment", "post_reply", "post_mention"]);

export function InboxItemModal({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const t = useT(); const locale = useLocale();
  const q = useQuery({ queryKey: ["inbox", "item", id], queryFn: () => Inbox.get(id) });
  const it = q.data;
  // 여는 것만으로 읽은 것이 된다(서버가 GET 에서 적는다) — 목록의 점을 바로 지운다.
  useEffect(() => { if (it) onChanged(); }, [it?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const status = useMutation({
    mutationFn: (b: { status: string; start_at?: string; duration_minutes?: number }) => Inbox.setStatus(id, b),
    onSuccess: () => { void q.refetch(); onChanged(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const archive = () => status.mutate({ status: "archived" }, { onSuccess: () => { toast.success(t("inbox.archived_toast")); onClose(); } });

  if (!it) {
    return (
      <Dialog open onClose={onClose} size="lg" title={t("inbox.detail")}>
        {q.isError ? <p className="py-8 text-center text-sm text-muted-fg">{friendlyError(q.error, locale)}</p> : <Skeleton className="h-48" />}
      </Dialog>
    );
  }
  const p = it.payload ?? {};

  // 소식 글의 댓글·답글·언급: 답은 그 글에 단다. 인박스 창을 하나 더 세우지 않고 글을 그대로 연다.
  if (POST_KINDS.has(it.kind) && p.post_id) {
    return (
      <PostModal postId={String(p.post_id)} focusCommentId={it.kind === "post_mention" ? null : (p.comment_id as string | undefined) ?? null}
        onClose={onClose} onChanged={() => {}} onSent={() => { if (it.status !== "replied") status.mutate({ status: "replied" }); }}
        notice={
          <div className="flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate text-muted-fg">{inboxTitle(it, t)}</span>
            {it.status !== "archived" ? <button type="button" className="shrink-0 text-muted-fg underline-offset-2 hover:text-fg hover:underline" onClick={archive}>{t("inbox.archive")}</button> : null}
          </div>
        } />
    );
  }

  const footer = (primary?: ReactNode) => (
    <div className="flex w-full flex-wrap items-center gap-2">
      {it.status !== "archived"
        ? <Button variant="ghost" size="sm" loading={status.isPending && status.variables?.status === "archived"} onClick={archive}>{t("inbox.archive")}</Button>
        : <Badge tone="neutral">{t("inbox.status_archived")}</Badge>}
      <div className="ml-auto flex flex-wrap items-center gap-2">{primary}</div>
    </div>
  );

  const body = (() => {
    switch (it.kind) {
      case "message":
      case "contact_share":
        return <VisitorMessage it={it} />;
      case "meeting_request":
        return <MeetingRequest it={it} busy={status.isPending} decide={(b) => status.mutate(b)} />;
      case "question_unanswered":
        return <UnansweredQuestion it={it} onTaught={() => { void q.refetch(); onChanged(); }} />;
      case "relay_result":
      case "relay_visit":
        return <RelayResult it={it} />;
      case "community_comment":
      case "community_reply":
        return <CommunityThread it={it} onReplied={() => { if (it.status !== "replied") status.mutate({ status: "replied" }); }} />;
      case "person_follow":
      case "link_request":
      case "link_accepted":
        return <PersonFollow it={it} onClose={onClose} />;
      case "company_review":
      case "company_job":
        return <CompanyNews it={it} />;
      case "storage_notice":
        return <StorageNotice it={it} />;
      default:
        return p.text ? <Quote>{String(p.text)}</Quote> : null;
    }
  })();

  const primary = (() => {
    switch (it.kind) {
      case "message":
      case "contact_share":
      case "meeting_request":
      case "question_unanswered":
        return it.conversation_id ? <Link href={`/app/conversations?c=${it.conversation_id}`} className={buttonLook("outline", "sm")} onClick={onClose}><MessageSquare className="h-4 w-4" />{t("inbox.open_conversation")}</Link> : null;
      case "relay_result":
      case "relay_visit":
        return p.relay_id ? <Link href={`/app/conversations?relay=${p.relay_id}`} className={buttonLook("outline", "sm")} onClick={onClose}><MessageSquare className="h-4 w-4" />{t("card.relay_open")}</Link> : null;
      case "community_comment":
      case "community_reply":
        return p.post_id ? <Link href={`/app/community/p/${p.post_id}`} className={buttonLook("outline", "sm")} onClick={onClose}>{t("inbox.open_post")}</Link> : null;
      case "company_review":
      case "company_job":
        return p.company_id ? (
          <Link href={`/app/community/companies/${p.company_id}?tab=${it.kind === "company_job" ? "hiring" : "reviews"}`} className={buttonLook("accent", "sm")} onClick={onClose}>
            {t(it.kind === "company_job" ? "inbox.open_job" : "inbox.open_review")}
          </Link>
        ) : null;
      case "storage_notice":
        return <Link href="/app/files" className={buttonLook("accent", "sm")} onClick={onClose}><HardDrive className="h-4 w-4" />{t("inbox.open_storage")}</Link>;
      default:
        return null;
    }
  })();

  return (
    <Dialog open onClose={onClose} size="lg" title={inboxTitle(it, t)}
      description={<span className="inline-flex flex-wrap items-center gap-2">
        <Badge tone="outline">{t(`inbox.kind_${it.kind}`)}</Badge>
        <span>{fmtRelative(it.created_at, locale)} · {fmtDateTime(it.created_at)}</span>
      </span>}
      footer={footer(primary)}>
      <div className="space-y-4">{body}</div>
    </Dialog>
  );
}

// ─────────────────────────────── 조각 ───────────────────────────────

/** 받은 글 그대로 — 테두리 없이 옅은 바탕 하나로 둘레와 나눈다. 색 테두리·왼쪽 줄로 꾸미지 않는다. */
function Quote({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("whitespace-pre-wrap break-words rounded-xl bg-muted/60 px-4 py-3 text-sm leading-relaxed", className)}>{children}</div>;
}

function Label({ children }: { children: ReactNode }) {
  return <div className="mb-1.5 text-xs font-medium text-muted-fg">{children}</div>;
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  const shown = rows.filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!shown.length) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
      {shown.map(([k, v]) => (
        <div key={k} className="contents"><dt className="text-muted-fg">{k}</dt><dd className="min-w-0 break-words">{v}</dd></div>
      ))}
    </dl>
  );
}

/** 연락처: 이메일이면 누르면 메일이 열린다. 여기서 답장을 쓰지는 않는다. */
function Contact({ value }: { value?: string | null }) {
  if (!value) return null;
  return value.includes("@") ? <a href={`mailto:${value}`} className="text-accent underline-offset-2 hover:underline">{value}</a> : <span>{value}</span>;
}

/** 대화 기록 — 접어 두고, 펼치면 본다. 누가 한 말인지는 옆에 적는다. */
function Transcript({ it, mine, theirs, open: initial = false }: { it: InboxItem; mine: string; theirs: string; open?: boolean }) {
  const t = useT();
  const [open, setOpen] = useState(initial);
  const msgs = it.conversation ?? [];
  if (!msgs.length) return null;
  return (
    <div className="rounded-xl border border-border">
      <button type="button" onClick={() => setOpen((x) => !x)} aria-expanded={open}
        className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-sm font-medium hover:bg-muted/40">
        <MessageSquare className="h-4 w-4 text-muted-fg" />{t("inbox.transcript_n", { n: msgs.filter((m) => m.role !== "card").length })}
        <ChevronDown className={cn("ml-auto h-4 w-4 text-muted-fg transition-transform", open && "rotate-180")} />
      </button>
      {open ? (
        <div className="max-h-[44vh] space-y-2 overflow-y-auto border-t border-border bg-bg p-3 scrollbar-thin">
          {msgs.map((m, i) => (
            m.role === "card" && m.cards?.length ? (
              <div key={i} className="space-y-1">{m.cards.map((c, j) => <CardRenderer key={j} card={c} actions={{ mode: "owner" }} />)}</div>
            ) : (
              <div key={i} className={cn("flex flex-col", m.role === "user" ? "items-start" : "items-end")}>
                <span className="mb-0.5 px-1 text-[10px] text-muted-fg">{m.role === "user" ? theirs : mine}</span>
                <div className={cn("max-w-[85%] rounded-2xl px-3 py-2 text-sm", m.role === "user" ? "border border-border bg-card" : "bg-accent/10")}>
                  {m.role === "user" ? <p className="whitespace-pre-wrap">{m.content}</p> : <Markdown text={m.content} />}
                  <div className="mt-1 text-[10px] opacity-60">{fmtDateTime(m.created_at)}</div>
                </div>
              </div>
            )
          ))}
        </div>
      ) : null}
    </div>
  );
}

function VisitorCard({ it, t }: { it: InboxItem; t: TFn }) {
  const p = it.payload ?? {};
  const v = it.visitor;
  const locale = useLocale();
  const qc = useQueryClient();
  const block = useMutation({
    mutationFn: (unblock: boolean) => Inbox.block(it.visitor_id!, unblock),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["inbox", "item", it.id] }); toast.success(t(r.blocked ? "inbox.blocked_toast" : "inbox.unblocked_toast")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const name = p.visitor_name || v?.display_name || t("inbox.visitor");
  return (
    <div className="rounded-xl border border-border p-3.5">
      <div className="mb-2 flex items-center gap-2">
        <Avatar name={name} size={28} />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{name}</span>
        {v?.blocked ? <Badge tone="danger">{t("inbox.blocked")}</Badge> : null}
      </div>
      <Facts rows={[
        [t("inbox.contact"), <Contact key="c" value={p.contact || v?.email} />],
        [t("inbox.via_agent"), p.agent_name || null],
        [t("inbox.first_seen"), v ? fmtDateTime(v.first_seen_at) : null],
        [t("inbox.turns"), v ? fmtNumber(v.turn_count) : null],
      ]} />
      {it.visitor_id ? (
        <div className="mt-2.5 border-t border-border pt-2.5">
          <button type="button" disabled={block.isPending} onClick={() => block.mutate(!!v?.blocked)}
            className={cn("inline-flex items-center gap-1.5 text-xs underline-offset-2 hover:underline disabled:opacity-60", v?.blocked ? "text-muted-fg" : "text-danger")}>
            <Ban className="h-3.5 w-3.5" />{t(v?.blocked ? "inbox.unblock" : "inbox.block")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

// ─────────────────────────────── 종류마다 ───────────────────────────────

/** 방문자가 남긴 말: 비서가 받아 전해 준 것. 여기서 답하지 않는다. */
function VisitorMessage({ it }: { it: InboxItem }) {
  const t = useT();
  const p = it.payload ?? {};
  return (
    <>
      {p.text ? <div><Label>{t("inbox.left_message")}</Label><Quote>{String(p.text)}</Quote></div> : null}
      <div><Label>{t("inbox.left_by")}</Label><VisitorCard it={it} t={t} /></div>
      <Transcript it={it} theirs={p.visitor_name || t("inbox.visitor")} mine={p.agent_name || t("inbox.my_agent")} />
    </>
  );
}

/** 미팅 요청: 시간을 골라 수락하면 스케줄에 들어간다. 거절도 여기서. */
function MeetingRequest({ it, busy, decide }: { it: InboxItem; busy: boolean; decide: (b: { status: string; start_at?: string; duration_minutes?: number }) => void }) {
  const t = useT(); const locale = useLocale(); const rcal = useRcalTheme();
  const p = it.payload ?? {};
  const decided = it.status === "accepted" || it.status === "declined";
  const [when, setWhen] = useState("");
  const [mins, setMins] = useState(30);
  useEffect(() => {
    const iso = Array.isArray(p.slots_iso) ? p.slots_iso.find((x: unknown) => typeof x === "string" && x) : "";
    setWhen(p.scheduled_at || iso || "");
    setMins(Number(p.duration_minutes) > 0 ? Number(p.duration_minutes) : 30);
  }, [it.id]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      {p.purpose ? <div><Label>{t("inbox.meeting_purpose")}</Label><Quote>{String(p.purpose)}</Quote></div> : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label>{t("inbox.meeting_slots")}</Label>
          <div className="flex flex-wrap gap-1.5">
            {(Array.isArray(p.slots) ? p.slots : []).map((s: string, i: number) => <span key={i} className="rounded-lg bg-muted px-2.5 py-1 text-sm">{s}</span>)}
          </div>
        </div>
        <Facts rows={[
          [t("inbox.meeting_length"), p.duration_minutes ? t("inbox.minutes_n", { n: p.duration_minutes }) : null],
          [t("inbox.meeting_place"), p.location || null],
        ]} />
      </div>
      <div><Label>{t("inbox.requested_by")}</Label><VisitorCard it={it} t={t} /></div>
      {decided ? (
        <div className={cn("flex items-center gap-2 rounded-xl bg-muted/60 px-4 py-3 text-sm", it.status === "accepted" ? "text-success" : "text-muted-fg")}>
          {it.status === "accepted" ? <CalendarCheck className="h-4 w-4" /> : <X className="h-4 w-4" />}
          {it.status === "accepted"
            ? (p.scheduled_at ? t(p.schedule_event_id || p.calendar_event_id ? "inbox.cal_done" : "inbox.cal_agreed", { when: fmtDateTime(p.scheduled_at) }) : t("inbox.meeting_accepted"))
            : t("inbox.meeting_declined")}
          {it.status === "accepted" && p.calendar_event_id
            ? <span className="text-muted-fg">· {t(p.calendar_provider === "google" ? "inbox.cal_external_google" : p.calendar_provider === "kakao" ? "inbox.cal_external_kakao" : "inbox.cal_external")}</span>
            : null}
        </div>
      ) : (
        <div className="space-y-2.5 rounded-xl border border-border p-3.5">
          <div className="text-sm font-medium">{t("inbox.when")}</div>
          <div className="flex flex-wrap items-center gap-2">
            <DateTimePicker value={when ? parseISO(when) : null} locale={locale} minuteStep={15} className={rcal} panelClassName={rcal}
                            onChange={(d: Date | null) => setWhen(d ? toISODateTime(d) : "")} />
            <Input type="number" min={10} max={480} step={10} value={mins} onChange={(e) => setMins(Number(e.target.value) || 30)} className="h-10 w-24" aria-label={t("inbox.minutes")} />
            <span className="text-xs text-muted-fg">{t("inbox.minutes")}</span>
          </div>
          <p className="text-xs text-muted-fg">{when ? t("inbox.cal_will_add") : t("inbox.cal_pick_time")}</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="accent" size="sm" loading={busy} onClick={() => decide({ status: "accepted", start_at: when || undefined, duration_minutes: mins })}>
              <Check className="h-4 w-4" />{t(when ? "inbox.accept_schedule" : "common.accept")}
            </Button>
            <Button variant="outline" size="sm" loading={busy} onClick={() => decide({ status: "declined" })}><X className="h-4 w-4" />{t("common.decline")}</Button>
          </div>
        </div>
      )}
      <Transcript it={it} theirs={p.visitor_name || t("inbox.visitor")} mine={p.agent_name || t("inbox.my_agent")} />
    </>
  );
}

/** 비서가 답하지 못한 질문: 다음에는 이렇게 답하라고 가르친다(내 지식이 된다). */
function UnansweredQuestion({ it, onTaught }: { it: InboxItem; onTaught: () => void }) {
  const t = useT(); const locale = useLocale();
  const p = it.payload ?? {};
  const [answer, setAnswer] = useState("");
  const taught = it.status === "replied";
  const teach = useMutation({
    mutationFn: () => Inbox.teach(it.id, { answer: answer.trim() }),
    onSuccess: () => { setAnswer(""); toast.success(t("inbox.taught")); onTaught(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <>
      <div><Label>{t("inbox.asked_question")}</Label><Quote>{String(p.question || p.text || "")}</Quote></div>
      <Facts rows={[[t("inbox.asked_by"), p.visitor_name || null], [t("inbox.via_agent"), p.agent_name || null]]} />
      <div className="space-y-2 rounded-xl border border-border p-3.5">
        <div className="flex items-center gap-1.5 text-sm font-medium"><GraduationCap className="h-4 w-4" />{t("inbox.teach_title")}</div>
        {taught && it.owner_reply ? <div><Label>{t("inbox.taught_answer")}</Label><Quote>{it.owner_reply}</Quote></div> : null}
        <Textarea value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder={t("inbox.teach_placeholder")} className="min-h-[96px]" />
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-fg">{t("inbox.teach_where")}</span>
          <Button className="ml-auto" size="sm" variant="accent" loading={teach.isPending} disabled={!answer.trim()} onClick={() => teach.mutate()}>
            <GraduationCap className="h-4 w-4" />{t(taught ? "inbox.teach_again" : "inbox.teach")}
          </Button>
        </div>
      </div>
      <Transcript it={it} theirs={p.visitor_name || t("inbox.visitor")} mine={p.agent_name || t("inbox.my_agent")} />
    </>
  );
}

/** 비서끼리 나눈 대화: 무엇이었고 어떻게 끝났는지, 상대가 누구인지. 답하는 칸은 없다. */
function RelayResult({ it }: { it: InboxItem }) {
  const t = useT();
  const p = it.payload ?? {};
  const mineVisited = it.kind === "relay_visit";
  const other = mineVisited ? { user: p.initiator_user_id, owner: p.initiator_owner_name, agent: p.initiator_agent_name }
                            : { user: p.target_user_id, owner: p.target_owner_name, agent: p.target_agent_name };
  const me = mineVisited ? p.target_agent_name : p.initiator_agent_name;
  return (
    <>
      {p.text ? <div><Label>{t("inbox.relay_summary")}</Label><Quote>{String(p.text)}</Quote></div> : null}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {p.reason_text ? <Badge tone="outline">{p.reason_text}</Badge> : null}
        {typeof p.message_count === "number" ? <span className="text-xs text-muted-fg">{t("relay.messages_n", { n: p.message_count })}</span> : null}
      </div>
      {p.purpose ? <Facts rows={[[t("inbox.relay_purpose"), String(p.purpose)]]} /> : null}
      <div>
        <Label>{t("inbox.relay_other")}</Label>
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border p-3.5">
          <Avatar name={other.owner || other.agent || "?"} size={32} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{other.owner || t("inbox.someone")}</div>
            {other.agent ? <div className="flex items-center gap-1 truncate text-xs text-muted-fg"><Bot className="h-3.5 w-3.5" />{t("inbox.their_agent", { name: other.agent })}</div> : null}
          </div>
          {other.user ? <ConnectionControl userId={String(other.user)} name={other.owner || undefined} /> : null}
        </div>
      </div>
      <Transcript it={it} theirs={other.agent || t("inbox.their_agent_short")} mine={me || t("inbox.my_agent")} />
    </>
  );
}

/** 광장의 내 글·내 댓글에 달린 것: 그 댓글을 보이고, 거기에 답글을 단다(이메일 답장이 아니다). */
function CommunityThread({ it, onReplied }: { it: InboxItem; onReplied: () => void }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const p = it.payload ?? {};
  const postId = p.post_id ? String(p.post_id) : "";
  const cq = useQuery({ queryKey: ["c", "comments", postId, "new"], queryFn: () => Community.comments(postId, "new"), enabled: !!postId });
  const all = useMemo(() => cq.data?.items ?? [], [cq.data]);
  const target = all.find((c) => c.id === p.comment_id) ?? null;
  const parent = target?.parent_id ? all.find((c) => c.id === target.parent_id) ?? null : null;
  const replies = useMemo(() => (target ? all.filter((c) => c.parent_id === target.id) : []), [all, target]);
  const [body, setBody] = useState("");
  const send = useMutation({
    // 답글은 두 층까지다 — 가장 깊은 댓글에 답하면 그 댓글과 나란히 달린다.
    mutationFn: () => Community.addComment(postId, { body: body.trim(), parent_id: target ? (target.depth >= 2 ? target.parent_id : target.id) : null }),
    onSuccess: () => {
      setBody("");
      toast.success(t("inbox.comment_sent"));
      qc.invalidateQueries({ queryKey: ["c", "comments", postId] });
      qc.invalidateQueries({ queryKey: ["c", "post", postId] });
      onReplied();
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <>
      {p.post_title ? (
        <Link href={`/app/community/p/${postId}`} className="block rounded-xl border border-border px-3.5 py-2.5 text-sm transition-colors hover:bg-muted/60">
          <div className="text-xs text-muted-fg">{t(it.kind === "community_reply" ? "inbox.on_post_reply" : "inbox.on_my_post")}</div>
          <div className="mt-0.5 truncate font-medium">{p.post_title}</div>
        </Link>
      ) : null}
      {cq.isLoading ? <Skeleton className="h-24" /> : (
        <div className="space-y-2">
          {parent ? <CommentBubble c={parent} muted /> : null}
          {target ? <CommentBubble c={target} focus indent={!!parent} /> : (
            <Quote className="text-muted-fg">{p.excerpt ? String(p.excerpt) : t("com.comment_deleted")}</Quote>
          )}
          {replies.map((r) => <CommentBubble key={r.id} c={r} indent />)}
        </div>
      )}
      {target && !target.deleted ? (
        <div className="space-y-2 rounded-xl border border-border p-3">
          <Textarea value={body} onChange={(e) => setBody(e.target.value)} className="min-h-[80px]"
            placeholder={t("com.reply_ph", { name: target.author?.name ?? "" })}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && body.trim() && !send.isPending) send.mutate(); }} />
          <div className="flex items-center">
            <span className="text-xs text-muted-fg">{t("inbox.reply_in_thread")}</span>
            <Button className="ml-auto" size="sm" variant="accent" loading={send.isPending} disabled={!body.trim()} onClick={() => send.mutate()}>
              <Send className="h-4 w-4" />{t("inbox.comment_send")}
            </Button>
          </div>
        </div>
      ) : null}
    </>
  );
}

function CommentBubble({ c, focus, muted, indent }: { c: CommunityComment; focus?: boolean; muted?: boolean; indent?: boolean }) {
  const t = useT(); const locale = useLocale();
  return (
    <div className={cn("rounded-xl p-3", indent && "ml-6", focus ? "bg-muted/60" : "border border-border", muted && "opacity-75")}>
      <div className="flex items-center gap-2 text-xs text-muted-fg">
        <span className="font-medium text-fg/90">{c.author?.name ?? t("inbox.someone")}</span>
        {c.author?.is_me ? <Badge tone="neutral">{t("inbox.me")}</Badge> : null}
        <span>{fmtRelative(c.created_at, locale)}</span>
      </div>
      <p className={cn("mt-1 whitespace-pre-wrap break-words text-sm", c.deleted && "italic text-muted-fg")}>{c.deleted ? t("com.comment_deleted") : c.body}</p>
    </div>
  );
}

/** 누군가 나를 연결했다: 그 사람과 지금 사이, 그리고 할 수 있는 일. */
function PersonFollow({ it, onClose }: { it: InboxItem; onClose: () => void }) {
  const t = useT();
  const p = it.payload ?? {};
  const uid = p.actor_id ? String(p.actor_id) : null;
  const prof = useQuery({ queryKey: ["network", "profile", uid], queryFn: () => Network.profile(uid!), enabled: !!uid });
  const link = useLink(uid);
  const openWith = useMessenger((s) => s.openWith);
  const name = prof.data?.display_name || p.actor_name || t("inbox.someone");
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-border px-4 py-5 text-center">
      <Avatar name={name} src={prof.data?.avatar_url} size={64} />
      <div>
        <div className="text-base font-semibold">{name}</div>
        {prof.data?.handle ? <div className="text-xs text-muted-fg">@{prof.data.handle}</div> : null}
      </div>
      <p className="text-sm text-muted-fg">{t(link === "mutual" ? "inbox.follow_mutual" : "inbox.follow_them")}</p>
      {uid ? <ConnectionControl userId={uid} name={name} size="md" /> : null}
      <div className="flex flex-wrap justify-center gap-2">
        {uid ? <Link href={`/app/u/${uid}`} onClick={onClose} className={buttonLook("outline", "sm")}><UserRound className="h-4 w-4" />{t("inbox.see_profile")}</Link> : null}
        {uid && link && link !== "none" && link !== "self" ? (
          <Button variant="outline" size="sm" onClick={() => { openWith({ userId: uid }); onClose(); }}><Mail className="h-4 w-4" />{t("msg.message")}</Button>
        ) : null}
      </div>
    </div>
  );
}

/** 관심 기업에 새 리뷰·공고. */
function CompanyNews({ it }: { it: InboxItem }) {
  const t = useT();
  const p = it.payload ?? {};
  const job = it.kind === "company_job";
  const pay = (n?: number | null) => (typeof n === "number" && n > 0 ? fmtNumber(n) : null);
  const salary = pay(p.salary_min) || pay(p.salary_max) ? `${pay(p.salary_min) ?? ""}${pay(p.salary_max) ? ` ~ ${pay(p.salary_max)}` : ""}` : null;
  return (
    <div className="rounded-xl border border-border p-3.5">
      <div className="mb-2 flex items-center gap-2 text-sm font-medium">
        {job ? <Briefcase className="h-4 w-4 text-muted-fg" /> : <Building2 className="h-4 w-4 text-muted-fg" />}{p.company_name}
      </div>
      {job ? (
        <>
          <div className="text-base font-semibold">{p.title}</div>
          <div className="mt-1.5"><Facts rows={[[t("inbox.job_location"), p.location || null], [t("inbox.job_salary"), salary]]} /></div>
        </>
      ) : (
        <>
          <div className="flex items-center gap-2">
            {typeof p.rating === "number" ? <span className="inline-flex items-center gap-1 text-sm font-medium"><Star className="h-4 w-4 fill-current text-warning" />{Number(p.rating).toFixed(1)}</span> : null}
            <span className="min-w-0 flex-1 truncate font-semibold">{p.title}</span>
          </div>
          {p.excerpt ? <Quote className="mt-2">{String(p.excerpt)}</Quote> : null}
        </>
      )}
    </div>
  );
}

/** 저장 공간이 찼다. */
function StorageNotice({ it }: { it: InboxItem }) {
  const t = useT();
  const p = it.payload ?? {};
  const used = Number(p.used_bytes) || 0;
  const limit = Number(p.limit_bytes) || 0;
  const ratio = limit ? Math.min(1, used / limit) : Number(p.level) >= 100 ? 1 : 0.9;
  return (
    <>
      <div className="rounded-xl border border-border p-3.5">
        <div className="mb-2 flex items-baseline justify-between text-sm">
          <span className="font-medium">{t("inbox.storage_used")}</span>
          {limit ? <span className="text-muted-fg">{fmtBytes(used)} / {fmtBytes(limit)}</span> : null}
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-muted">
          <div className={cn("h-full rounded-full", ratio >= 1 ? "bg-danger" : "bg-warning")} style={{ width: `${Math.round(ratio * 100)}%` }} />
        </div>
      </div>
      <p className="text-sm">{Number(p.level) >= 100 ? t("inbox.storage_full_body") : t("inbox.storage_warn_body")}</p>
    </>
  );
}
