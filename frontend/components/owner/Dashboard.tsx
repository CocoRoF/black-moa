"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Bot, CheckCircle2, Circle, Copy, HeartHandshake, Inbox, Link2, MessageSquare, Plus, Settings2, Sparkles } from "@/components/icons";
import { toast } from "sonner";
import { copyText } from "@/lib/utils";
import { friendlyError } from "@/lib/errors";
import { Agents, Credits, Inbox as InboxApi, Integrations, Knowledge, Network, Relationships, Users, type Agent } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useAuth } from "@/stores/auth";
import { fmtCredits, fmtRelative } from "@/lib/format";
import { useLocale } from "@/lib/i18n";
import { Page } from "./Shell";
import { Button, buttonLook } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress, Avatar, PageHeader } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { inboxTitle } from "./inboxUtil";

export function Dashboard() {
  const t = useT(); const locale = useLocale();
  const user = useAuth((s) => s.user)!;
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => Agents.list() });
  const bal = useQuery({ queryKey: ["credits", "balance"], queryFn: Credits.balance });
  const inbox = useQuery({ queryKey: ["inbox", "recent"], queryFn: () => InboxApi.list({}) });
  const unanswered = useQuery({ queryKey: ["inbox", "unanswered"], queryFn: () => InboxApi.list({ kind: "question_unanswered", status: "new" }) });
  const profile = useQuery({ queryKey: ["profile"], queryFn: Users.profile });
  const docs = useQuery({ queryKey: ["knowledge", "docs"], queryFn: () => Knowledge.docs() });
  const net = useQuery({ queryKey: ["network", "stats"], queryFn: Network.stats });
  const integ = useQuery({ queryKey: ["integrations"], queryFn: Integrations.list });

  const items = agents.data?.items.filter((a) => a.status !== "archived") ?? [];
  const links = items.reduce((n, a) => n + (a.links?.length ?? 0), 0);
  const checklist = [
    { key: "agent", done: items.length > 0 || !!user.onboarding_state?.agent_created, href: items.length ? "/app/agents" : "/app/onboarding" },
    { key: "profile", done: Object.keys(profile.data?.data ?? {}).some((k) => !!profile.data?.data[k]) || !!user.onboarding_state?.profile_done, href: "/app/profile" },
    { key: "knowledge", done: (docs.data?.items.length ?? 0) > 0, href: "/app/knowledge" },
    { key: "network", done: (net.data?.nodes ?? 0) > 0, href: "/app/network" },
    { key: "integrations", done: (integ.data?.connections.length ?? 0) > 0, href: "/app/integrations" },
    { key: "link", done: links > 0, href: items[0] ? `/app/agents/${items[0].id}/links` : "/app/agents" },
  ];
  const doneCount = checklist.filter((c) => c.done).length;
  // 시작 체크리스트는 **보이지 않는 것이 기본**이다. 여섯 가지를 셀 자료가 다 온 뒤에, 접어 두지 않았고 아직 다
  // 채우지 않은 사람에게만 보인다 — 자료가 오는 사이에 반쯤 빈 목록이 떴다가 사라지지 않게.
  const [hidden, setHidden] = useState(false);
  const counted = [agents, profile, docs, net, integ].every((q) => q.isSuccess);
  const showChecklist = counted && !hidden && !user.onboarding_state?.checklist_dismissed && doneCount < checklist.length;
  const dismiss = async () => {
    setHidden(true);
    try {
      const u = await Users.patchMe({ onboarding_state: { checklist_dismissed: true } });
      useAuth.getState().setUser(u);
    } catch (e) {
      setHidden(false);
      toast.error(friendlyError(e, locale));
    }
  };
  const monthly = bal.data?.plan.monthly_credits ?? 0;

  return (
    <Page>
      <PageHeader title={t("dash.greeting", { name: user.display_name })} description={t("dash.subtitle")}
        action={items.length ? (
          <div className="flex flex-wrap items-center gap-2">
            {/* 비서 목록으로 가는 길은 여기 하나 — 카드 위의 "비서 ― 전체 보기" 줄은 옆 칸(크레딧)과 높이를 어긋나게 했다. */}
            <Link href="/app/agents" className={buttonLook("outline", "md")}><Bot className="h-4 w-4" />{t("dash.manage_agents")}</Link>
            <Link href="/app/chat" className={buttonLook("accent", "md")}><MessageSquare className="h-4 w-4" />{t("dash.open_chat")}</Link>
          </div>
        ) : <Link href="/app/onboarding" className={buttonLook("accent", "md")}><Sparkles className="h-4 w-4" />{t("dash.create_first")}</Link>} />

      {showChecklist ? (
        <Card className="mb-5">
          <CardHeader title={t("dash.checklist_title")} description={t("dash.checklist_desc", { done: doneCount, total: checklist.length })}
            action={<Button variant="ghost" size="sm" className="text-muted-fg" onClick={() => void dismiss()}>{t("dash.checklist_dismiss")}</Button>} />
          <CardBody>
            <Progress value={doneCount} max={checklist.length} className="mb-3" />
            <ul className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
              {checklist.map((c) => (
                <li key={c.key}>
                  <Link href={c.href} className="flex items-center gap-2 rounded-xl px-2 py-2 text-sm hover:bg-muted min-h-[40px]">
                    {c.done ? <CheckCircle2 className="h-4 w-4 text-success shrink-0" /> : <Circle className="h-4 w-4 text-muted-fg shrink-0" />}
                    <span className={c.done ? "text-muted-fg line-through" : ""}>{t(`dash.check_${c.key}`)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-4">
          <section>
            {agents.isLoading ? <Skeleton className="h-28" /> : items.length ? (
              <div className="grid gap-3 sm:grid-cols-2">{items.map((a) => <AgentCard key={a.id} a={a} />)}
                {items.length < (agents.data?.max_agents ?? 1) ? <Link href="/app/onboarding" className="flex min-h-[120px] items-center justify-center gap-2 rounded-2xl border border-dashed border-border text-sm text-muted-fg hover:bg-muted"><Plus className="h-4 w-4" />{t("agents.new")}</Link> : null}
              </div>
            ) : <EmptyState icon={<Bot />} title={t("agents.empty_title")} description={t("agents.empty_desc")} action={<Link href="/app/onboarding" className={buttonLook("accent", "md")}>{t("dash.create_first")}</Link>} />}
          </section>

          <section>
            <div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-semibold text-muted-fg">{t("dash.latest_inbox")}</h2><Link href="/app/inbox" className="text-xs text-accent inline-flex items-center gap-1">{t("common.view_all")}<ArrowRight className="h-3 w-3" /></Link></div>
            <Card>
              {inbox.isLoading ? <CardBody className="pt-5"><Skeleton className="h-24" /></CardBody> : inbox.data?.items.length ? (
                <ul className="divide-y divide-border">
                  {inbox.data.items.slice(0, 5).map((it) => (
                    <li key={it.id}><Link href={`/app/inbox?item=${it.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/50">
                      <Inbox className="h-4 w-4 text-muted-fg shrink-0" />
                      <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{inboxTitle(it, t)}</div><div className="truncate text-xs text-muted-fg">{it.payload?.text ?? it.payload?.question ?? ""}</div></div>
                      {it.status === "new" ? <Badge tone="accent">{t("inbox.status_new")}</Badge> : null}
                      <span className="text-xs text-muted-fg shrink-0">{fmtRelative(it.created_at, locale)}</span>
                    </Link></li>
                  ))}
                </ul>
              ) : <CardBody className="pt-5 text-sm text-muted-fg">{t("inbox.empty")}</CardBody>}
            </Card>
          </section>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader title={t("nav.credits")} action={<Link href="/app/credits" className="text-xs text-accent">{t("common.details")}</Link>} />
            <CardBody>
              {bal.data ? (
                <>
                  <div className="text-3xl font-semibold tabular-nums">{fmtCredits(bal.data.balance)}<span className="ml-1 text-sm font-normal text-muted-fg">{t("credits.unit")}</span></div>
                  <Progress value={Math.min(bal.data.balance, monthly)} max={monthly || 1} tone={bal.data.low ? "danger" : "accent"} className="mt-3" />
                  <div className="mt-1.5 flex justify-between text-xs text-muted-fg"><span>{bal.data.plan.name}</span><span>{t("credits.monthly", { n: fmtCredits(monthly) })}</span></div>
                  {bal.data.low ? <p className="mt-2 text-xs text-warning">{t("credits.low_warning")}</p> : null}
                </>
              ) : <Skeleton className="h-20" />}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title={t("dash.unanswered")} description={t("dash.unanswered_desc")} />
            <CardBody>
              {unanswered.data?.items.length ? (
                <ul className="space-y-1.5">{unanswered.data.items.slice(0, 5).map((it) => (
                  <li key={it.id}><Link href={`/app/inbox?item=${it.id}`} className="block rounded-xl bg-muted px-3 py-2 text-sm hover:bg-border/60 line-clamp-2">{it.payload?.question ?? it.payload?.text}</Link></li>
                ))}</ul>
              ) : <p className="text-sm text-muted-fg">{t("dash.no_unanswered")}</p>}
            </CardBody>
          </Card>
        </div>
      </div>
    </Page>
  );
}

export function AgentCard({ a }: { a: Agent }) {
  const t = useT();
  const st = a.stats ?? {};
  // plan/37: one line about where the two of you stand, shared across every card on the page.
  const rels = useQuery({ queryKey: ["relationships"], queryFn: Relationships.list, staleTime: 60_000 });
  const rel = rels.data?.items.find((r) => r.agent_id === a.id);
  const link = (a.links ?? []).find((l) => (l.effective_status ?? l.status) === "active") ?? (a.links ?? [])[0];
  return (
    <div className="rounded-2xl border border-border bg-card p-4 hover:border-accent/50 transition-colors">
      <Link href={`/app/agents/${a.id}`} className="flex items-center gap-3 rounded-lg focus-visible:outline-2 focus-visible:outline-ring">
        <Avatar mascot name={a.name} src={a.avatar_url} size={44} accent={a.theme?.accent} shape={a.theme?.avatar_shape} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2"><span className="truncate font-semibold">{a.name}</span><Badge tone={a.status === "active" ? "success" : a.status === "paused" ? "warning" : "neutral"}>{t(`agents.status_${a.status}`)}</Badge></div>
          {a.role_line ? <div className="truncate text-xs text-muted-fg">{a.role_line}</div> : null}
        </div>
      </Link>
      {link ? (
        <div className="mt-3 flex h-9 items-center gap-1.5 rounded-xl border border-border bg-bg px-2.5 text-xs">
          <Link2 className="h-3.5 w-3.5 shrink-0 text-accent" />
          <a href={link.url} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate text-accent underline-offset-2 hover:underline">{link.url.replace(/^https?:\/\//, "")}</a>
          <Button variant="ghost" size="icon-sm" className="h-7 w-7 rounded-md" aria-label={t("links.copy_url")} onClick={async () => { if (await copyText(link.url)) toast.success(t("common.copied")); }}><Copy className="h-3.5 w-3.5" /></Button>
        </div>
      ) : <Link href={`/app/agents/${a.id}/links`} className="mt-3 flex h-9 items-center gap-1.5 rounded-xl border border-dashed border-border px-2.5 text-xs text-muted-fg hover:text-fg"><Plus className="h-3.5 w-3.5 shrink-0" />{t("links.new")}</Link>}
      {rel ? (
        <Link href={`/app/agents/${a.id}/relationship`} className="mt-3 flex items-center gap-2 rounded-xl bg-accent/6 px-2.5 py-1.5 text-xs hover:bg-accent/10">
          <HeartHandshake className="h-3.5 w-3.5 shrink-0 text-accent" />
          <span className="min-w-0 flex-1 truncate">{rel.started_at ? t("rel.card_line", { n: rel.days_together, stage: t(`rel.stage_${rel.stage}`) }) : t("rel.card_new")}</span>
          {rel.streak_days >= 2 ? <span className="shrink-0 text-muted-fg">{t("rel.card_streak", { n: rel.streak_days })}</span> : null}
        </Link>
      ) : null}
      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-xl bg-muted py-2"><div className="text-sm font-semibold tabular-nums">{st.visitor_conversations_7d ?? 0}</div><div className="text-[10px] text-muted-fg">{t("agents.stat_conv7")}</div></div>
        <div className="rounded-xl bg-muted py-2"><div className="text-sm font-semibold tabular-nums">{st.turns_7d ?? 0}</div><div className="text-[10px] text-muted-fg">{t("agents.stat_turns7")}</div></div>
        <div className="rounded-xl bg-muted py-2"><div className="text-sm font-semibold tabular-nums">{fmtCredits(st.credits_7d ?? 0)}</div><div className="text-[10px] text-muted-fg">{t("agents.stat_credits7")}</div></div>
      </div>
      {/* The two things you do with a secretary from the picker: talk to it, or set it up. */}
      <div className="mt-3 grid grid-cols-2 gap-2">
        {/* Links wearing the button's look. A <Button> inside a <Link> is a button inside
            an anchor: two things to press, and markup no parser keeps. */}
        <Link href={`/app/chat?a=${a.id}`} className={buttonLook("primary", "md", "w-full")}><MessageSquare className="h-4 w-4" />{t("agent.tab_chat")}</Link>
        <Link href={`/app/agents/${a.id}/settings`} className={buttonLook("outline", "md", "w-full")}><Settings2 className="h-4 w-4" />{t("agent.tab_settings")}</Link>
      </div>
    </div>
  );
}
