"use client";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Copy, Link2, MessageSquare, Pause, Play, Settings2 } from "@/components/icons";
import { Agents, Chat } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { fmtCredits, fmtMs, fmtRelative } from "@/lib/format";
import { copyText } from "@/lib/utils";
import { friendlyError } from "@/lib/errors";
import { Page } from "@/components/owner/Shell";
import { useAgent } from "./AgentLayout";
import { Stat } from "@/components/ui/misc";
import { Button, buttonLook } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function AgentOverview() {
  const t = useT(); const locale = useLocale(); const a = useAgent(); const qc = useQueryClient();
  const st = a.stats ?? {};
  const convs = useQuery({ queryKey: ["conversations", a.id, "all"], queryFn: () => Chat.conversations(a.id) });
  const act = useMutation({ mutationFn: (x: "pause" | "resume") => Agents.action(a.id, x), onSuccess: () => { qc.invalidateQueries({ queryKey: ["agents"] }); toast.success(t("common.saved")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  return (
    <Page>
      <div className="mb-4 flex flex-wrap gap-2">
        <Link href={`/app/chat?a=${a.id}`} className={buttonLook("primary", "md")}><MessageSquare className="h-4 w-4" />{t("agent.tab_chat")}</Link>
        <Link href={`/app/agents/${a.id}/settings`} className={buttonLook("outline", "md")}><Settings2 className="h-4 w-4" />{t("agent.tab_settings")}</Link>
        <Link href={`/app/agents/${a.id}/links`} className={buttonLook("outline", "md")}><Link2 className="h-4 w-4" />{t("agent.tab_links")}</Link>
        {a.status === "active" ? <Button variant="outline" loading={act.isPending} onClick={() => act.mutate("pause")}><Pause className="h-4 w-4" />{t("agent.pause")}</Button>
          : a.status === "paused" ? <Button variant="accent" loading={act.isPending} onClick={() => act.mutate("resume")}><Play className="h-4 w-4" />{t("agent.resume")}</Button> : null}
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat label={t("agents.stat_conv_total")} value={st.conversations_total ?? 0} />
        <Stat label={t("agents.stat_conv7")} value={st.visitor_conversations_7d ?? 0} />
        <Stat label={t("agents.stat_turns7")} value={st.turns_7d ?? 0} />
        <Stat label={t("agents.stat_credits7")} value={fmtCredits(st.credits_7d ?? 0)} />
        <Stat label={t("agents.stat_ttft")} value={fmtMs(st.avg_ttft_ms)} />
        <Stat label={t("agents.stat_unanswered")} value={st.unanswered_questions ?? 0} />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={t("agent.tab_links")} action={<Link href={`/app/agents/${a.id}/links`} className="text-xs text-accent">{t("common.manage")}</Link>} />
          <CardBody>
            {a.links?.length ? <ul className="space-y-2">{a.links.map((l) => (
              <li key={l.id} className="flex items-center gap-2 rounded-xl border border-border px-3 py-2">
                <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{l.label || l.code}</div><div className="truncate text-xs text-muted-fg">{l.url}</div></div>
                <Badge tone={l.status === "active" ? "success" : "neutral"}>{t(`links.status_${l.status}`)}</Badge>
                <Button variant="ghost" size="icon-sm" aria-label={t("common.copy")} onClick={async () => { if (await copyText(l.url)) toast.success(t("common.copied")); }}><Copy className="h-4 w-4" /></Button>
              </li>
            ))}</ul> : <p className="text-sm text-muted-fg">{t("links.empty")}</p>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t("agent.recent_conversations")} action={<Link href={`/app/conversations?agent=${a.id}`} className="text-xs text-accent">{t("common.view_all")}</Link>} />
          <CardBody>
            {convs.data?.items.length ? <ul className="divide-y divide-border">{convs.data.items.slice(0, 8).map((c) => (
              <li key={c.id}><Link href={c.audience === "owner" ? `/app/chat?a=${a.id}&c=${c.id}` : `/app/conversations?agent=${a.id}&c=${c.id}`} className="flex items-center gap-2 py-2 hover:bg-muted/40 rounded-lg px-1">
                <Badge tone={c.audience === "owner" ? "accent" : "neutral"}>{t(`conv.audience_${c.audience}`)}</Badge>
                <span className="min-w-0 flex-1 truncate text-sm">{c.title || c.summary || t("conv.untitled")}</span>
                <span className="text-xs text-muted-fg shrink-0">{fmtRelative(c.last_message_at ?? c.created_at, locale)}</span>
              </Link></li>
            ))}</ul> : <p className="text-sm text-muted-fg">{t("conv.empty")}</p>}
          </CardBody>
        </Card>
      </div>
    </Page>
  );
}
