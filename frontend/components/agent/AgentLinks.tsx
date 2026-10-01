"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronDown, Copy, ExternalLink, Eye, Link2, Plus, QrCode, Trash2 } from "@/components/icons";
import { Agents, fetchBlobUrl, type Link as ShareLink } from "@/lib/api";
import { DateTimePicker } from "@cocorof/react-calendar";
import { useRcalTheme } from "@/lib/theme";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { cn, copyText } from "@/lib/utils";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { useObjectUrl } from "@/lib/hooks";
import { Page } from "@/components/owner/Shell";
import { useAgent } from "./AgentLayout";
import { Button, buttonLook } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Dialog, ConfirmDialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/tabs";
import { PageHeader } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { LayoutPicker, LayoutPreviewDialog } from "./LinkLayout";
import type { LinkLayout } from "@/components/public/PublicChat";

export function AgentLinks() {
  const t = useT(); const locale = useLocale(); const a = useAgent(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["links", a.id], queryFn: () => Agents.links(a.id) });
  const [create, setCreate] = useState(false);
  const [qr, setQr] = useState<ShareLink | null>(null);
  const [revoke, setRevoke] = useState<ShareLink | null>(null);
  const [preview, setPreview] = useState<{ code: string; layout: LinkLayout } | null>(null);
  const inval = () => { qc.invalidateQueries({ queryKey: ["links", a.id] }); qc.invalidateQueries({ queryKey: ["agents", a.id] }); };
  const patch = useMutation({ mutationFn: (x: { id: string; body: Record<string, unknown> }) => Agents.patchLink(x.id, x.body), onSuccess: inval, onError: (e) => toast.error(friendlyError(e, locale)) });
  const del = useMutation({ mutationFn: (id: string) => Agents.deleteLink(id), onSuccess: () => { inval(); setRevoke(null); toast.success(t("links.revoked")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const items = q.data?.items.filter((l) => l.status !== "revoked") ?? [];
  return (
    <Page>
      {/* 비서 하나에 공개 링크 하나 (plan/80). 명함·이메일·SNS 어디에 알려도 같은 주소이고, 주소나 모양은 이 링크를 고친다. */}
      <PageHeader title={t("agent.tab_links")} description={t("links.desc")} />
      {q.isLoading ? <Skeleton className="h-40" /> : items.length ? (
        <div className="max-w-2xl space-y-3">
          {items.map((l) => {
            const eff = l.effective_status ?? l.status;
            return (
              <Card key={l.id} className="p-4">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2"><span className="truncate font-semibold">{l.label || l.code}</span><Badge tone={eff === "active" ? "success" : eff === "paused" ? "warning" : "neutral"}>{t(`links.status_${eff}`)}</Badge></div>
                    <a href={l.url} target="_blank" rel="noopener noreferrer" className="mt-0.5 block truncate text-sm text-accent underline-offset-2 hover:underline">{l.url}</a>
                  </div>
                  <Switch checked={l.status === "active"} onChange={(v) => patch.mutate({ id: l.id, body: { status: v ? "active" : "paused" } })} label={t("links.toggle")} />
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="rounded-lg bg-muted py-1.5"><div className="font-semibold tabular-nums">{l.conversation_count}{l.max_conversations ? `/${l.max_conversations}` : ""}</div><div className="text-muted-fg">{t("links.conversations")}</div></div>
                  <div className="rounded-lg bg-muted py-1.5"><div className="font-semibold tabular-nums">{l.turn_count}</div><div className="text-muted-fg">{t("links.turns")}</div></div>
                  <div className="rounded-lg bg-muted py-1.5"><div className="font-semibold">{l.last_visit_at ? fmtRelative(l.last_visit_at, locale) : "–"}</div><div className="text-muted-fg">{t("links.last_visit")}</div></div>
                </div>
                {l.expires_at ? <div className="mt-2 text-xs text-muted-fg">{t("links.expires", { at: fmtDateTime(l.expires_at) })}</div> : null}
                {/* 방문자에게 보일 모양(plan/71): 채팅 · 무대. 미리보기는 PC·휴대폰 틀에 예시 대화로. */}
                <div className="mt-3 rounded-xl border border-border px-3 py-2.5">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div className="min-w-0"><div className="text-sm font-medium">{t("links.layout")}</div><div className="text-xs text-muted-fg">{t("links.layout_desc")}</div></div>
                    <Button size="sm" variant="outline" onClick={() => setPreview({ code: l.code, layout: l.settings?.layout ?? "chat" })}><Eye className="h-4 w-4" />{t("links.preview")}</Button>
                  </div>
                  <LayoutPicker value={l.settings?.layout ?? "chat"} disabled={patch.isPending}
                                onChange={(v) => patch.mutate({ id: l.id, body: { settings: { layout: v } } }, { onSuccess: () => toast.success(t("links.layout_saved")) })} />
                </div>
                <Embed code={l.code} />
                {/* plan/38: other members' secretaries may reach this one through the link, on the owner's terms. */}
                <div className="mt-3 rounded-xl border border-border px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0"><div className="text-sm font-medium">{t("links.allow_agents")}</div><div className="text-xs text-muted-fg">{t("links.allow_agents_desc")}</div></div>
                    <Switch checked={l.settings?.allow_agents ?? true} onChange={(v) => patch.mutate({ id: l.id, body: { settings: { allow_agents: v } } })} label={t("links.allow_agents")} />
                  </div>
                  {(l.settings?.allow_agents ?? true) ? (
                    <div className="mt-2 flex items-center justify-between gap-3 text-xs">
                      <span className="text-muted-fg">{t("links.findable")}</span>
                      <Switch checked={l.settings?.findable ?? true} onChange={(v) => patch.mutate({ id: l.id, body: { settings: { findable: v } } })} label={t("links.findable")} />
                    </div>
                  ) : null}
                  {(l.settings?.allow_agents ?? true) ? (
                    <div className="mt-2 flex items-center justify-between gap-3 text-xs">
                      <span className="text-muted-fg">{t("links.agent_turns_per_day")}</span>
                      <Input type="number" min={0} max={500} className="h-8 w-24 text-right" defaultValue={l.settings?.agent_turns_per_day ?? 20} key={`${l.id}:${l.settings?.agent_turns_per_day}`}
                        onBlur={(e) => { const n = Math.max(0, Math.min(500, Number(e.target.value) || 0)); if (n !== (l.settings?.agent_turns_per_day ?? 20)) patch.mutate({ id: l.id, body: { settings: { agent_turns_per_day: n } } }); }} />
                    </div>
                  ) : null}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={async () => { if (await copyText(l.url)) toast.success(t("common.copied")); }}><Copy className="h-4 w-4" />{t("links.copy_url")}</Button>
                  <Button size="sm" variant="outline" onClick={() => setQr(l)}><QrCode className="h-4 w-4" />QR</Button>
                  <a href={l.url} target="_blank" rel="noopener noreferrer" className={buttonLook("outline", "sm")}><ExternalLink className="h-4 w-4" />{t("common.open")}</a>
                  <Button size="sm" variant="ghost" className="text-danger ml-auto" onClick={() => setRevoke(l)}><Trash2 className="h-4 w-4" />{t("links.revoke")}</Button>
                </div>
              </Card>
            );
          })}
        </div>
      ) : <EmptyState icon={<Link2 />} title={t("links.empty")} description={t("links.empty_desc")} action={<Button onClick={() => setCreate(true)}><Plus className="h-4 w-4" />{t("links.new")}</Button>} />}
      <CreateLinkDialog open={create} onClose={() => setCreate(false)} agentId={a.id} onCreated={inval} />
      <QrDialog link={qr} onClose={() => setQr(null)} />
      <LayoutPreviewDialog open={!!preview} code={preview?.code ?? null} layout={preview?.layout ?? "chat"} onClose={() => setPreview(null)} />
      <ConfirmDialog open={!!revoke} onClose={() => setRevoke(null)} onConfirm={() => { if (revoke) del.mutate(revoke.id); }} title={t("links.revoke")} description={t("links.revoke_desc")} confirmLabel={t("links.revoke")} cancelLabel={t("common.cancel")} danger loading={del.isPending} />
    </Page>
  );
}

function CreateLinkDialog({ open, onClose, agentId, onCreated }: { open: boolean; onClose: () => void; agentId: string; onCreated: () => void }) {
  const t = useT(); const locale = useLocale(); const rcalTheme = useRcalTheme();
  const [mode, setMode] = useState<"auto" | "custom">("auto");
  const [label, setLabel] = useState(""); const [handle, setHandle] = useState("");
  const [expires, setExpires] = useState<Date | null>(null); const [max, setMax] = useState("");
  const [layout, setLayout] = useState<LinkLayout>("chat");
  const handleOk = mode === "auto" || /^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])$/.test(handle);
  const m = useMutation({
    mutationFn: () => Agents.createLink(agentId, { label, handle: mode === "custom" ? handle : null, expires_at: expires ? expires.toISOString() : null, max_conversations: max ? Number(max) : null, layout }),
    onSuccess: () => { onCreated(); onClose(); toast.success(t("links.created")); setLabel(""); setHandle(""); setExpires(null); setMax(""); setLayout("chat"); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <Dialog open={open} onClose={onClose} title={t("links.new")} footer={<><Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button><Button loading={m.isPending} disabled={!handleOk} onClick={() => m.mutate()}>{t("common.create")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("links.label")} hint={t("links.label_hint")}><Input value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} placeholder={t("links.label_placeholder")} /></Field>
        <Field label={t("links.handle")}>
          <Segmented value={mode} onChange={setMode} options={[{ value: "auto", label: t("links.handle_auto") }, { value: "custom", label: t("links.handle_custom") }]} className="mb-2" />
          {mode === "custom" ? <Input value={handle} onChange={(e) => setHandle(e.target.value.toLowerCase())} placeholder="my-name" invalid={!!handle && !handleOk} /> : null}
          <p className="mt-1 text-xs text-muted-fg">{mode === "custom" ? t("links.handle_rule") : t("links.handle_auto_desc")}</p>
        </Field>
        <Field label={t("links.layout")} hint={t("links.layout_create_hint")}>
          <LayoutPicker value={layout} onChange={setLayout} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("links.expires_at")} hint={t("common.optional")}>
            <DateTimePicker value={expires} onChange={setExpires} locale={locale} minDate={new Date()} minuteStep={30}
              placeholder={t("links.expires_none")} clearable className={rcalTheme} panelClassName={rcalTheme} />
          </Field>
          <Field label={t("links.max_conversations")} hint={t("common.optional")}><Input type="number" min={1} value={max} onChange={(e) => setMax(e.target.value)} /></Field>
        </div>
      </div>
    </Dialog>
  );
}

function QrDialog({ link, onClose }: { link: ShareLink | null; onClose: () => void }) {
  const t = useT();
  const url = useObjectUrl(link ? () => fetchBlobUrl(`/api/links/${link.id}/qr.png`) : null, [link?.id]);
  return (
    <Dialog open={!!link} onClose={onClose} title={link?.label || link?.code} size="sm">
      <div className="flex flex-col items-center gap-3">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {url ? <img src={url} alt="QR" className="h-64 w-64 rounded-xl border border-border bg-white p-2" /> : <Skeleton className="h-64 w-64" />}
        <div className="text-center text-sm text-muted-fg break-all">{link?.url}</div>
        {url ? <a href={url} download={`blackmoa-${link?.code}.png`} className={buttonLook("outline", "sm")}>{t("common.download")}</a> : null}
      </div>
    </Dialog>
  );
}


/** The snippet that puts this secretary on the owner's own site (plan/41 M6).
 *
 *  One line they paste where they want the button. It is shown in full rather than behind
 *  a "copy" button alone, because somebody pasting a script tag onto their site is
 *  entitled to read it first.
 */
function Embed({ code }: { code: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const snippet = `<script src="${origin}/embed.js" data-code="${code}" defer></script>`;
  return (
    <div className="mt-3 rounded-xl border border-border px-3 py-2">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between gap-3 text-left">
        <span><span className="text-sm font-medium">{t("links.embed")}</span><span className="block text-xs text-muted-fg">{t("links.embed_desc")}</span></span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-fg transition-transform", open && "rotate-180")} />
      </button>
      {open ? (
        <div className="mt-2">
          <pre className="whitespace-pre-wrap break-all rounded-lg bg-muted px-2.5 py-2 text-[11px] leading-relaxed"><code>{snippet}</code></pre>
          <div className="mt-2 flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={async () => { if (await copyText(snippet)) toast.success(t("common.copied")); }}>
              <Copy className="h-3.5 w-3.5" />{t("common.copy")}
            </Button>
            <span className="text-xs text-muted-fg">{t("links.embed_hint")}</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
