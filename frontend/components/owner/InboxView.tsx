"use client";
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Inbox as InboxIcon } from "@/components/icons";
import { Agents, Inbox } from "@/lib/api";
import { DateRangePicker, toISODate } from "@cocorof/react-calendar";
import { useRcalTheme } from "@/lib/theme";
import { useLocale, useT } from "@/lib/i18n";
import { fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "./Shell";
import { inboxTitle } from "./inboxUtil";
import { InboxItemModal } from "./InboxItemModal";
import { Selector } from "@cocorof/react-selector";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Busy } from "@/components/ui/busy";
import { PageHeader } from "@/components/ui/misc";

export function InboxPage() { return <InboxView />; }

export function InboxView({ agentId }: { agentId?: string }) {
  const t = useT(); const locale = useLocale(); const rcal = useRcalTheme(); const qc = useQueryClient(); const sp = useSearchParams(); const router = useRouter();
  const [kind, setKind] = useState(""); const [status, setStatus] = useState(""); const [agent, setAgent] = useState(agentId ?? "");
  // Community notifications have no secretary, so "which secretary" cannot narrow this
  // list on its own — source splits the two halves before the other filters apply.
  const [source, setSource] = useState("");
  // 인박스는 쌓아 두는 곳이 아니라 처리하는 곳이다. 열면 이번 주에 들어온 것이 보이고,
  // 더 뒤를 찾을 때만 기간을 넓힌다. 처음부터 전부를 세워 두면 오늘 할 일이 안 보인다.
  const [range, setRange] = useState<[Date | null, Date | null]>(() => {
    const until = new Date();
    const since = new Date(until);
    since.setDate(since.getDate() - 6);
    return [since, until];
  });
  const since = range[0] ? toISODate(range[0]) : undefined;
  const until = range[1] ? toISODate(range[1]) : undefined;
  const [sel, setSel] = useState<string | null>(sp.get("item"));
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => Agents.list(), enabled: !agentId });
  const q = useQuery({ queryKey: ["inbox", { kind, status, agent, source, since, until }], queryFn: () => Inbox.list({ kind: kind || undefined, status: status || undefined, agent_id: agent || undefined, source: source || undefined, since, until }), placeholderData: keepPreviousData });
  useEffect(() => { const it = sp.get("item"); if (it) setSel(it); }, [sp]);
  const open = (id: string | null) => { setSel(id); if (!agentId) router.replace(id ? `/app/inbox?item=${id}` : "/app/inbox"); };
  const invalAll = () => { qc.invalidateQueries({ queryKey: ["inbox"] }); };
  return (
    <Page>
      {!agentId ? <PageHeader title={t("nav.inbox")} description={t("inbox.desc")} /> : null}
      {/* 한 줄이다: [기간] [출처] [종류] [상태] [비서].
          기간이 맨 앞인 것은 나머지가 모두 "그 기간 안에서" 걸러지기 때문이고,
          지우는 일은 달력 안에서 한다 — 옆에 버튼을 하나 더 세우면 줄이 또 늘어난다. */}
      <div className="filter-row mb-3 flex flex-wrap items-center gap-2">
        {/* 폭은 글자가 정한다. 숫자로 박아 두면 "2026. 9. 17 ~ 2026. 9. 23" 처럼
            날짜가 둘 다 들어가는 날에 뒤가 잘린다 — 읽으라고 세운 칸이 못 읽게 된다. */}
        <DateRangePicker value={range} onChange={setRange} locale={locale} clearable
                         className={rcal} panelClassName={rcal}
                         width="auto" aria-label={t("inbox.period")} placeholder={t("inbox.all_time")} />
        <Selector size="lg" ariaLabel={t("inbox.source")} value={source} onChange={(v) => { setSource(v); if (v !== "" && v !== "agent") { setAgent(""); } setKind(""); }}
          options={[{ value: "", label: t("inbox.all_sources") }, { value: "agent", label: t("inbox.source_agent") },
                    { value: "people", label: t("inbox.source_people") }, { value: "community", label: t("inbox.source_community") }]} />
        <Selector size="lg" ariaLabel={t("inbox.all_kinds")} value={kind} onChange={setKind}
          options={[{ value: "", label: t("inbox.all_kinds") },
                    ...(source === "community"
                      ? ["community_comment", "community_reply"]
                      : source === "people"
                      ? ["person_follow", "post_comment", "post_reply", "post_mention"]
                      : ["message", "meeting_request", "contact_share", "question_unanswered"]
                     ).map((k) => ({ value: k, label: t(`inbox.kind_${k}`) }))]} />
        <Selector size="lg" ariaLabel={t("inbox.all_status")} value={status} onChange={setStatus}
          options={[{ value: "", label: t("inbox.all_status") },
                    ...["new", "read", "replied", "accepted", "declined", "archived"].map((x) => ({ value: x, label: t(`inbox.status_${x}`) }))]} />
        {/* Secretaries can outnumber a short list, so this one searches; the fixed filters
            above do not. That difference is the whole point of the control. */}
        {!agentId && source !== "community" ? (
          <Selector size="lg" ariaLabel={t("inbox.all_agents")} value={agent} onChange={setAgent} searchThreshold={6}
            options={[{ value: "", label: t("inbox.all_agents") },
                      ...(agents.data?.items ?? []).map((a) => ({ value: a.id, label: a.name, keywords: a.name }))]} />
        ) : null}
      </div>
      <Busy busy={q.isFetching && !q.isLoading}>
      {q.isLoading ? <Skeleton className="h-60" /> : q.data?.items.length ? (
        <ul key={`${kind}:${status}:${agent}:${source}`} className="list-in divide-y divide-border rounded-2xl border border-border bg-card">
          {q.data.items.map((it) => (
            <li key={it.id}><button type="button" onClick={() => open(it.id)} className={cn("flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-muted/50", it.status === "new" && "bg-accent/5")}>
              <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", it.status === "new" ? "bg-accent" : "bg-transparent")} />
              {/* Spans: a button may only hold phrasing content, and markup a browser has
                  to re-shape is markup React did not render. */}
              <span className="block min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2"><span className="truncate text-sm font-medium">{inboxTitle(it, t)}</span><Badge tone="outline">{t(`inbox.kind_${it.kind}`)}</Badge><Badge tone={it.status === "new" ? "accent" : it.status === "replied" || it.status === "accepted" ? "success" : it.status === "declined" ? "danger" : "neutral"}>{t(`inbox.status_${it.status}`)}</Badge></span>
                <span className="mt-0.5 line-clamp-2 text-sm text-muted-fg">{it.payload?.text ?? it.payload?.question ?? it.payload?.purpose ?? it.payload?.excerpt ?? it.payload?.title ?? ""}</span>
              </span>
              <span className="shrink-0 text-xs text-muted-fg">{fmtRelative(it.created_at, locale)}</span>
            </button></li>
          ))}
        </ul>
      ) : <EmptyState icon={<InboxIcon />} title={t("inbox.empty")} description={t("inbox.empty_desc")} />}
      </Busy>
      {/* 가운데에 뜨는 창, 소식의 종류마다 그에 맞는 모양(plan/70). */}
      {sel ? <InboxItemModal key={sel} id={sel} onChanged={invalAll} onClose={() => open(null)} /> : null}
    </Page>
  );
}
