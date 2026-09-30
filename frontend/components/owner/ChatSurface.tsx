"use client";
import { useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Bot, Check, ChevronDown } from "@/components/icons";
import { Agents } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { storageGet, storageSet } from "@/lib/utils";
import { inAppShell } from "@/lib/desktop";
import { AgentProvider } from "@/components/agent/AgentLayout";
import { OwnerChat } from "@/components/agent/OwnerChat";
import { DropdownMenu } from "@/components/ui/dropdown";
import { Button, buttonLook } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Avatar } from "@/components/ui/misc";

const LAST_AGENT = "memora:chat:agent";

/** The standalone chat surface: pick a secretary, talk to it, switch conversations.
 *  Opens the most recent conversation of the last secretary you talked to. */
export function ChatSurface() {
  const t = useT();
  const router = useRouter();
  const sp = useSearchParams();
  const q = useQuery({ queryKey: ["agents"], queryFn: () => Agents.list() });
  const items = useMemo(() => (q.data?.items ?? []).filter((a) => a.status !== "archived"), [q.data]);

  const requested = sp.get("a");
  const remembered = typeof window === "undefined" ? null : storageGet("local", LAST_AGENT);
  const agent = items.find((a) => a.id === requested) ?? items.find((a) => a.id === remembered) ?? items[0];

  useEffect(() => { if (agent) storageSet("local", LAST_AGENT, agent.id); }, [agent]);

  if (q.isLoading) return <div className="flex-1 p-4"><Skeleton className="h-full" /></div>;
  if (!agent) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <EmptyState icon={<Bot />} title={t("agents.empty_title")} description={t("agents.empty_desc")}
          action={<Link href="/app/onboarding" className={buttonLook("accent", "md")}>{t("dash.create_first")}</Link>} />
      </div>
    );
  }

  // Who you are talking to is always named. With two or more secretaries the name becomes
  // the switcher; with one, a menu of one would just be a dead arrow.
  const identity = (
    <span className="flex min-w-0 items-center gap-1.5 font-medium">
      <Avatar mascot name={agent.name} src={agent.avatar_url} size={20} accent={agent.theme?.accent} shape={agent.theme?.avatar_shape} />
      <span className="max-w-[180px] truncate">{agent.name}</span>
    </span>
  );
  const switcher = items.length > 1 ? (
    <DropdownMenu
      trigger={<Button variant="ghost" size="sm" className="-ml-1 gap-1.5">{identity}<ChevronDown className="h-3.5 w-3.5 text-muted-fg" /></Button>}
      items={items.map((a) => ({
        key: a.id,
        label: a.name,
        icon: a.id === agent.id ? <Check /> : undefined,
        onSelect: () => { storageSet("local", LAST_AGENT, a.id); router.replace(`/app/chat?a=${a.id}`); },
      }))}
    />
  ) : <span className="-ml-1 flex items-center px-2 text-sm">{identity}</span>;

  return (
    <AgentProvider agent={agent}>
      {/* keyed by agent: switching secretaries starts a clean chat state instead of
          carrying the previous one's conversation into the new runtime */}
      {/* PC 앱의 틀 안(plan/62)에서는 폭과 상관없이 한 줄 머리만 — 뒤로 갈 곳이 없다. */}
      <OwnerChat key={agent.id} basePath="/app/chat" backHref="/app" headerExtra={switcher} hideMobileHeader={inAppShell()} />
    </AgentProvider>
  );
}
