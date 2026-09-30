"use client";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight, MessageSquare } from "@/components/icons";
import { RelaysPanel } from "./RelaysPanel";
import { Agents, Chat, type Conversation } from "@/lib/api";
import { Selector } from "@cocorof/react-selector";
import { useLocale, useT } from "@/lib/i18n";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "./Shell";
import { TurnInfoDialog } from "@/components/agent/OwnerChat";
import { Segmented } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Sheet } from "@/components/ui/dialog";
import { PageHeader } from "@/components/ui/misc";
import { AttachmentRefresh, FileLinks, MessageAttachments } from "@/components/chat/MessageAttachments";
import { CardRenderer } from "@/components/chat/CardRenderer";
import { Markdown } from "@/components/chat/Markdown";
import { buttonLook } from "@/components/ui/button";
import Link from "next/link";

export function ConversationsPage() {
  const t = useT(); const locale = useLocale(); const sp = useSearchParams();
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => Agents.list(true) });
  const [agent, setAgent] = useState(sp.get("agent") ?? "");
  const [aud, setAud] = useState<"all" | "owner" | "visitor" | "relay">(sp.get("relay") ? "relay" : "all");
  const [open, setOpen] = useState<Conversation | null>(null);
  const [relayOpen, setRelayOpen] = useState<string | null>(sp.get("relay"));
  useEffect(() => { if (!agent && agents.data?.items[0]) setAgent(agents.data.items[0].id); }, [agents.data, agent]);
  const q = useQuery({ queryKey: ["conversations", agent, aud], queryFn: () => Chat.conversations(agent, aud === "all" || aud === "relay" ? undefined : aud), enabled: !!agent && aud !== "relay" });
  useEffect(() => { const c = sp.get("c"); if (c && q.data) { const f = q.data.items.find((x) => x.id === c); if (f) setOpen(f); } }, [sp, q.data]);
  const agentName = useMemo(() => agents.data?.items.find((a) => a.id === agent)?.name ?? "", [agents.data, agent]);
  return (
    <Page>
      <PageHeader title={t("nav.conversations")} description={t("conv.desc")} />
      <div className="mb-3 flex flex-wrap gap-2">
        <Selector size="lg" className="min-w-[160px]" ariaLabel={t("nav.agents")} value={agent} onChange={setAgent} searchThreshold={6}
          options={(agents.data?.items ?? []).map((a) => ({ value: a.id, label: a.name, keywords: a.name }))} />
        <Segmented value={aud} onChange={setAud} options={[{ value: "all", label: t("common.all") }, { value: "owner", label: t("conv.audience_owner") }, { value: "visitor", label: t("conv.audience_visitor") }, { value: "relay", label: t("conv.kind_agent") }]} />
      </div>
      {aud === "relay" ? <RelaysPanel agentId={agent || undefined} openId={relayOpen} onOpenChange={setRelayOpen} /> : q.isLoading ? <Skeleton className="h-60" /> : q.data?.items.length ? (
        <ul className="divide-y divide-border rounded-2xl border border-border bg-card">
          {q.data.items.map((c) => (
            <li key={c.id}><button type="button" onClick={() => setOpen(c)} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/50">
              <Badge tone={c.audience === "owner" ? "accent" : "neutral"}>{t(`conv.audience_${c.audience}`)}</Badge>
              {c.kind === "agent" ? <Badge tone="warning"><ArrowLeftRight className="h-3 w-3" />{t("conv.kind_agent")}</Badge> : null}
              {/* Spans: a button holds phrasing content, and markup a browser has to
                  re-shape is markup React did not render. */}
              <span className="block min-w-0 flex-1"><span className="block truncate text-sm font-medium">{c.title || c.summary || t("conv.untitled")}</span><span className="block truncate text-xs text-muted-fg">{c.message_count} {t("conv.messages")}{c.summary && c.title ? ` · ${c.summary}` : ""}</span></span>
              {c.unread_owner ? <span className="h-2 w-2 rounded-full bg-accent" /> : null}
              <span className="shrink-0 text-xs text-muted-fg">{fmtRelative(c.last_message_at ?? c.created_at, locale)}</span>
            </button></li>
          ))}
        </ul>
      ) : <EmptyState icon={<MessageSquare />} title={t("conv.empty")} />}
      <Sheet open={!!open} onClose={() => setOpen(null)} side="right" title={open?.title || t("conv.untitled")}>
        {open ? <Transcript agentId={agent} agentName={agentName} conv={open} /> : null}
      </Sheet>
    </Page>
  );
}

function Transcript({ agentId, agentName, conv }: { agentId: string; agentName: string; conv: Conversation }) {
  const t = useT();
  const q = useQuery({ queryKey: ["messages", agentId, conv.id], queryFn: () => Chat.messages(agentId, conv.id) });
  const [turn, setTurn] = useState<string | null>(null);
  const items = useMemo(() => [...(q.data?.items ?? [])].sort((a, b) => a.created_at.localeCompare(b.created_at)), [q.data]);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-fg"><Badge tone={conv.audience === "owner" ? "accent" : "neutral"}>{t(`conv.audience_${conv.audience}`)}</Badge>{conv.kind === "agent" ? <Badge tone="warning"><ArrowLeftRight className="h-3 w-3" />{t("conv.kind_agent")}</Badge> : null}{conv.kind === "agent" && conv.relay_id ? <Link href={`/app/conversations?relay=${conv.relay_id}`} className="text-accent underline-offset-2 hover:underline">{t("conv.open_relay")}</Link> : null}<span>{agentName}</span><span>· {fmtDateTime(conv.created_at)}</span>{conv.audience === "owner" ? <Link href={`/app/chat?a=${agentId}&c=${conv.id}`} className={buttonLook("outline", "sm", "ml-auto")}>{t("conv.continue")}</Link> : null}</div>
      {q.isLoading ? <Skeleton className="h-60" /> : (
        <FileLinks.Provider value={(fid) => `/app/agents/${agentId}/files?open=${fid}`}>
        <AttachmentRefresh.Provider value={() => q.refetch()}>
        <div className="space-y-2">
          {items.map((m) => (
            <div key={m.id} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
              {m.role === "card" ? <div className="space-y-1">{m.cards.map((c, j) => <CardRenderer key={j} card={c} actions={{ mode: "owner" }} />)}</div> : (
                <div className={cn("flex max-w-[88%] flex-col gap-1.5", m.role === "user" ? "items-end" : "items-start")}>
                {/* 방문자가 건넨 사진·문서도 기록에서 보여야 한다. 전에는 이 화면이 첨부를 그리지 않아
                    사진만 보낸 말은 빈 말풍선이었다. */}
                {m.attachments?.length ? <MessageAttachments items={m.attachments} align={m.role === "user" ? "end" : "start"} /> : null}
                {m.content || m.cards?.length ? (
                <div className={cn("rounded-2xl px-3 py-2 text-sm", m.role === "user" ? "bg-accent text-accent-fg" : "bg-card border border-border")}>
                  {m.content ? (m.role === "user" ? <p className="whitespace-pre-wrap">{m.content}</p> : <Markdown text={m.content} />) : null}
                  {m.cards?.length ? <div className="mt-2 space-y-1">{m.cards.map((c, j) => <CardRenderer key={j} card={c} actions={{ mode: "owner" }} />)}</div> : null}
                  <div className="mt-1 flex items-center gap-2 text-[10px] opacity-60"><span>{fmtDateTime(m.created_at)}</span>{m.turn_id && m.role === "assistant" ? <button type="button" className="underline" onClick={() => setTurn(m.turn_id!)}>{t("chat.turn_info")}</button> : null}</div>
                </div>
                ) : <div className="text-[10px] text-muted-fg">{fmtDateTime(m.created_at)}</div>}
                </div>
              )}
            </div>
          ))}
        </div>
        </AttachmentRefresh.Provider>
        </FileLinks.Provider>
      )}
      <TurnInfoDialog agentId={agentId} turnId={turn} onClose={() => setTurn(null)} />
    </div>
  );
}
