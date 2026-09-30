"use client";
import Link from "next/link";
import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Bot, Plus } from "@/components/icons";
import { Agents } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Page } from "@/components/owner/Shell";
import { AgentCard } from "@/components/owner/Dashboard";
import { buttonLook } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Busy } from "@/components/ui/busy";
import { Checkbox } from "@/components/ui/input";

export function AgentsList() {
  const t = useT();
  const [archived, setArchived] = useState(false);
  const q = useQuery({ queryKey: ["agents", { archived }], queryFn: () => Agents.list(archived), placeholderData: keepPreviousData });
  const items = q.data?.items ?? [];
  const max = q.data?.max_agents ?? 1;
  const active = items.filter((a) => a.status !== "archived").length;
  return (
    <Page>
      <PageHeader title={t("nav.agents")} description={t("agents.count", { n: active, max })}
        action={active >= max
          ? <span title={t("err.agent_limit")} className={buttonLook("primary", "md", "pointer-events-none opacity-50")}><Plus className="h-4 w-4" />{t("agents.new")}</span>
          : <Link href="/app/onboarding" className={buttonLook("primary", "md")}><Plus className="h-4 w-4" />{t("agents.new")}</Link>} />
      <div className="mb-3"><Checkbox checked={archived} onChange={setArchived} label={t("agents.show_archived")} /></div>
      <Busy busy={q.isFetching && !q.isLoading}>
      {q.isLoading ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"><Skeleton className="h-36" /><Skeleton className="h-36" /></div>
        : items.length ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{items.map((a) => <AgentCard key={a.id} a={a} />)}</div>
        : <EmptyState icon={<Bot />} title={t("agents.empty_title")} description={t("agents.empty_desc")} action={<Link href="/app/onboarding" className={buttonLook("accent", "md")}>{t("dash.create_first")}</Link>} />}
      </Busy>
    </Page>
  );
}
