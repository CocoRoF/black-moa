"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "@/components/icons";
import { Agents, type Agent } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Avatar } from "@/components/ui/misc";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/empty";
import { friendlyError } from "@/lib/errors";
import { useLocale } from "@/lib/i18n";

const AgentCtx = createContext<Agent | null>(null);
/** Lets a surface outside /app/agents (the standalone chat) supply the agent OwnerChat reads. */
export function AgentProvider({ agent, children }: { agent: Agent; children: ReactNode }) {
  return <AgentCtx.Provider value={agent}>{children}</AgentCtx.Provider>;
}

export const useAgent = () => { const a = useContext(AgentCtx); if (!a) throw new Error("no agent ctx"); return a; };

export function AgentLayout({ id, children }: { id: string; children: ReactNode }) {
  const t = useT(); const locale = useLocale();
  const path = usePathname();
  const q = useQuery({ queryKey: ["agents", id], queryFn: () => Agents.get(id) });
  const base = `/app/agents/${id}`;
  const tabs = [
    { href: base, key: "agent.tab_overview", exact: true },
    { href: `${base}/settings`, key: "agent.tab_settings" },
    { href: `${base}/relationship`, key: "agent.tab_relationship" },
    { href: `${base}/knowledge`, key: "agent.tab_knowledge" },
    { href: `${base}/memory`, key: "agent.tab_memory" },
    // 들어온 자료가 쌓이는 곳. 기억(메모리) 바로 옆이다 — 둘 다 비서가 다시 꺼내 보는 것.
    { href: `${base}/files`, key: "agent.tab_files" },
    { href: `${base}/inbox`, key: "agent.tab_inbox" },
    { href: `${base}/links`, key: "agent.tab_links" },
    { href: `${base}/simulate`, key: "agent.tab_simulate" },
  ];
  if (q.isLoading) return <div className="p-6"><Skeleton className="h-10 w-64" /><Skeleton className="mt-4 h-40" /></div>;
  if (q.error || !q.data) return <div className="p-6"><ErrorState message={friendlyError(q.error, locale)} onRetry={() => q.refetch()} retryLabel={t("common.retry")} /></div>;
  const a = q.data;
  return (
    <AgentCtx.Provider value={a}>
      {/* One header for every tab. It used to shrink on the chat/simulator tabs, so moving
          between tabs shifted the whole page; identity and tabs now share a single row on
          desktop and stack on phones, at the same size everywhere. */}
      <div className="shrink-0 border-b border-border bg-card">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-1 px-4 md:flex-row md:items-center md:gap-4 md:px-6">
          <div className="flex min-w-0 items-center gap-2.5 py-2.5 md:py-0 md:h-14 md:shrink-0">
            <Link href="/app/agents" className="-ml-2 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg hover:bg-muted" aria-label={t("common.back")}><ChevronLeft className="h-5 w-5" /></Link>
            <Avatar mascot name={a.name} src={a.avatar_url} size={30} accent={a.theme?.accent} shape={a.theme?.avatar_shape} />
            <div className="flex min-w-0 items-baseline gap-2">
              <span className="truncate text-[15px] font-semibold">{a.name}</span>
              {a.role_line ? <span className="hidden truncate text-xs text-muted-fg lg:inline">{a.role_line}</span> : null}
            </div>
            <Badge tone={a.status === "active" ? "success" : a.status === "paused" ? "warning" : "neutral"}>{t(`agents.status_${a.status}`)}</Badge>
          </div>
          <nav className="-mx-1 flex shrink-0 gap-1 overflow-x-auto scroll-fade-x px-1 md:ml-auto md:justify-end" aria-label="agent sections">
            {tabs.map((tb) => {
              const active = tb.exact ? path === tb.href : path.startsWith(tb.href);
              return (
                <Link key={tb.href} href={tb.href} aria-current={active ? "page" : undefined}
                  className={cn("shrink-0 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition-colors md:py-[15px]",
                    active ? "border-accent text-fg" : "border-transparent text-muted-fg hover:text-fg")}>
                  {t(tb.key)}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
      {children}
    </AgentCtx.Provider>
  );
}
