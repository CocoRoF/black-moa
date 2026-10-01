"use client";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeftRight, Plus, Square } from "@/components/icons";
import { Agents, Relays, type Relay } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtCredits, fmtDateTime, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, Sheet } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { confirm } from "@/lib/confirm";

/* Secretary-to-secretary conversations (plan/38): the ledger of every exchange one of my
   secretaries had with someone else's, whichever side mine was on. */

export function RelaysPanel({ agentId, openId, onOpenChange }: { agentId?: string; openId: string | null; onOpenChange: (id: string | null) => void }) {
  const t = useT(); const locale = useLocale();
  const q = useQuery({ queryKey: ["relays", agentId ?? "all"], queryFn: () => Relays.list(agentId ? { agent_id: agentId } : {}),
    refetchInterval: (query) => (query.state.data?.items.some((r) => r.status === "open") ? 5000 : false) });
  const [create, setCreate] = useState(false);
  const items = q.data?.items ?? [];
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-fg">{t("relay.desc")}</p>
        <Button size="sm" onClick={() => setCreate(true)}><Plus className="h-4 w-4" />{t("relay.new")}</Button>
      </div>
      {q.isLoading ? <Skeleton className="h-40" /> : items.length ? (
        <ul className="divide-y divide-border rounded-2xl border border-border bg-card">
          {items.map((r) => (
            <li key={r.id}>
              <button type="button" onClick={() => onOpenChange(r.id)} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/50">
                <Badge tone={r.role === "initiator" ? "accent" : "neutral"}>{t(`relay.role_${r.role}`)}</Badge>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {r.role === "initiator" ? t("relay.line_initiator", { mine: r.my_agent_name, peer: r.peer_agent_name, who: r.peer_owner_name }) : t("relay.line_target", { mine: r.my_agent_name, peer: r.peer_agent_name, who: r.peer_owner_name })}
                  </div>
                  <div className="truncate text-xs text-muted-fg">{r.purpose || r.opener}</div>
                </div>
                <StatusBadge r={r} />
                <span className="hidden shrink-0 text-xs text-muted-fg sm:inline">{t("relay.messages_n", { n: r.message_count })}</span>
                <span className="shrink-0 text-xs text-muted-fg">{fmtRelative(r.last_message_at ?? r.created_at, locale)}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : <EmptyState icon={<ArrowLeftRight />} title={t("relay.empty")} description={t("relay.empty_desc")} action={<Button onClick={() => setCreate(true)}>{t("relay.new")}</Button>} />}
      <RelaySheet id={openId} onClose={() => onOpenChange(null)} />
      <NewRelayDialog open={create} onClose={() => setCreate(false)} defaultAgent={agentId} onCreated={(r) => { setCreate(false); q.refetch(); onOpenChange(r.id); }} />
    </div>
  );
}

function StatusBadge({ r }: { r: Relay }) {
  const t = useT();
  if (r.status === "open") return <Badge tone="success">{t("relay.status_open")}</Badge>;
  const good = r.close_reason === "done" || r.close_reason === "max_messages";
  return <Badge tone={good ? "neutral" : "warning"}>{t(`relay.reason_${r.close_reason}`) === `relay.reason_${r.close_reason}` ? t("relay.status_closed") : t(`relay.reason_${r.close_reason}`)}</Badge>;
}

export function RelaySheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["relay", id], queryFn: () => Relays.get(id!), enabled: !!id, refetchInterval: (query) => (query.state.data?.status === "open" ? 4000 : false) });
  const stop = useMutation({ mutationFn: () => Relays.stop(id!), onSuccess: () => { q.refetch(); qc.invalidateQueries({ queryKey: ["relays"] }); toast.success(t("relay.stopped")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const d = q.data;
  return (
    <Sheet open={!!id} onClose={onClose} side="right" title={d ? t("relay.sheet_title", { a: d.names.initiator_agent, b: d.names.target_agent }) : "…"}
      footer={d?.status === "open" ? <div className="flex justify-end"><Button variant="outline" loading={stop.isPending} onClick={async () => { if (await confirm({ title: t("relay.stop_confirm"), confirmLabel: t("relay.stop"), danger: true })) stop.mutate(); }}><Square className="h-4 w-4" />{t("relay.stop")}</Button></div> : undefined}>
      {!d ? <Skeleton className="h-60" /> : (
        <div className="space-y-4">
          <div className="rounded-xl bg-muted px-3 py-2 text-sm">
            <div className="flex flex-wrap items-center gap-2"><StatusBadge r={d} /><span className="text-xs text-muted-fg">{t("relay.messages_n", { n: d.message_count })} / {d.max_messages}</span><span className="text-xs text-muted-fg">· {t("relay.my_credits", { n: fmtCredits(d.my_credits) })}</span></div>
            {d.purpose ? <p className="mt-1.5"><span className="text-muted-fg">{t("relay.purpose")}:</span> {d.purpose}</p> : null}
            {d.status === "closed" && d.summary ? <p className="mt-1.5"><span className="text-muted-fg">{t("relay.summary")}:</span> {d.summary}</p> : null}
            <p className="mt-1 text-[11px] text-muted-fg">{d.names.initiator_agent} ({d.names.initiator_owner}) → {d.names.target_agent} ({d.names.target_owner}) · {fmtDateTime(d.created_at)}</p>
          </div>
          <ol className="space-y-2">
            {d.messages.map((m) => (
              <li key={m.seq} className={cn("flex", m.side === "system" ? "justify-center" : m.mine ? "justify-end" : "justify-start")}>
                {m.side === "system" ? <span className="rounded-full bg-muted px-3 py-1 text-[11px] text-muted-fg">{m.content}</span> : (
                  <div className={cn("max-w-[88%] rounded-2xl px-3 py-2 text-sm", m.mine ? "bg-accent text-accent-fg" : "border border-border bg-card")}>
                    <div className={cn("mb-0.5 text-[11px] font-medium", m.mine ? "text-accent-fg/80" : "text-muted-fg")}>{m.agent_name}{m.kind === "close" ? ` · ${t("relay.kind_close")}` : ""}</div>
                    <p className="whitespace-pre-wrap">{m.content}</p>
                    <div className="mt-1 text-[10px] opacity-60">{fmtDateTime(m.created_at)}</div>
                  </div>
                )}
              </li>
            ))}
            {d.status === "open" ? <li className="text-center text-xs text-muted-fg">{t("relay.in_progress")}</li> : null}
          </ol>
        </div>
      )}
    </Sheet>
  );
}

function NewRelayDialog({ open, onClose, defaultAgent, onCreated }: { open: boolean; onClose: () => void; defaultAgent?: string; onCreated: (r: Relay) => void }) {
  const t = useT(); const locale = useLocale();
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => Agents.list() });
  const [agent, setAgent] = useState(defaultAgent ?? "");
  const [target, setTarget] = useState(""); const [message, setMessage] = useState(""); const [purpose, setPurpose] = useState(""); const [max, setMax] = useState(8);
  useEffect(() => { if (!agent && agents.data?.items[0]) setAgent(defaultAgent ?? agents.data.items[0].id); }, [agents.data, agent, defaultAgent]);
  const m = useMutation({
    mutationFn: () => Relays.start(agent, { target: target.trim(), message: message.trim(), purpose: purpose.trim(), max_messages: max }),
    onSuccess: (r) => { setTarget(""); setMessage(""); setPurpose(""); onCreated(r); toast(r.status === "open" ? t("relay.sent") : t(`relay.reason_${r.close_reason}`)); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <Dialog open={open} onClose={onClose} title={t("relay.new")} description={t("relay.new_desc")}
      footer={<><Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button><Button loading={m.isPending} disabled={!agent || !target.trim() || !message.trim()} onClick={() => m.mutate()}>{t("common.send")}</Button></>}>
      <div className="space-y-3">
        <Field label={t("relay.f_agent")}><Select value={agent} onChange={(e) => setAgent(e.target.value)}>{(agents.data?.items ?? []).filter((a) => a.status === "active").map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
        <Field label={t("relay.f_target")} hint={t("relay.f_target_hint")}><Input value={target} onChange={(e) => setTarget(e.target.value)} placeholder="https://black.memo-ora.com/secretary/…" /></Field>
        <Field label={t("relay.f_message")}><Textarea value={message} maxLength={2000} onChange={(e) => setMessage(e.target.value)} className="min-h-[96px]" placeholder={t("relay.f_message_placeholder")} /></Field>
        <div className="grid gap-3 sm:grid-cols-[1fr_120px]">
          <Field label={t("relay.f_purpose")} hint={t("common.optional")}><Input value={purpose} maxLength={200} onChange={(e) => setPurpose(e.target.value)} /></Field>
          <Field label={t("relay.f_max")}><Input type="number" min={2} max={20} value={max} onChange={(e) => setMax(Math.max(2, Math.min(20, Number(e.target.value) || 8)))} /></Field>
        </div>
      </div>
    </Dialog>
  );
}
