"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bell, Mail, MessageCircle, Plus, Send, Trash2, Webhook } from "@/components/icons";
import { Integrations, Notifications, type Channel, type Rule } from "@/lib/api";
import { connectProvider } from "@/lib/connect";
import { KakaoIcon } from "@/components/integrations/ProviderIcon";
import { useLocale, useT } from "@/lib/i18n";
import { codeMessage, friendlyError } from "@/lib/errors";
import { fmtDateTime } from "@/lib/format";
import { Page } from "./Shell";
import { Card, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Checkbox } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Dialog } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { PageHeader } from "@/components/ui/misc";
import { Tabs } from "@/components/ui/tabs";
import { confirm } from "@/lib/confirm";

const ICONS: Record<string, React.ReactNode> = { email: <Mail />, telegram: <Send />, slack: <MessageCircle />, discord: <MessageCircle />, webhook: <Webhook />, kakao: <KakaoIcon size={20} /> };

/** 채널 카드에 보일 설정 한 줄. 카카오톡은 받는 계정 이름만 — 연결 번호는 읽는 사람에게 뜻이 없다. */
function configLine(c: Channel): string {
  if (c.kind === "kakao") return String(c.config?.account ?? "");
  return Object.entries(c.config ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ");
}

export function NotificationsPage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [tab, setTab] = useState<"channels" | "rules" | "log">("channels");
  const ch = useQuery({ queryKey: ["notif", "channels"], queryFn: Notifications.channels });
  const rules = useQuery({ queryKey: ["notif", "rules"], queryFn: Notifications.rules });
  const log = useQuery({ queryKey: ["notif", "log"], queryFn: Notifications.log, enabled: tab === "log" });
  const [add, setAdd] = useState<string | null>(null);
  const [tg, setTg] = useState<{ code: string; instructions: string; bot_username: string } | null>(null);
  const inval = () => qc.invalidateQueries({ queryKey: ["notif"] });
  const patchCh = useMutation({ mutationFn: (x: { id: string; b: Record<string, unknown> }) => Notifications.patchChannel(x.id, x.b), onSuccess: inval });
  const delCh = useMutation({ mutationFn: (id: string) => Notifications.deleteChannel(id), onSuccess: inval });
  const test = useMutation({ mutationFn: (id: string) => Notifications.testChannel(id), onSuccess: (r) => (r.ok ? toast.success(t("notif.test_ok")) : toast.error(r.error ?? t("notif.test_fail"))), onError: (e) => toast.error(friendlyError(e, locale)) });
  const tgLink = useMutation({ mutationFn: Notifications.telegramLink, onSuccess: (r) => setTg(r), onError: (e) => toast.error(friendlyError(e, locale)) });
  const channels = ch.data?.items ?? [];
  // 카카오톡 "나에게 보내기" (plan/59): 관리자가 [연결 → 카카오]에서 메시지 기능을 줬을 때만.
  const integ = useQuery({ queryKey: ["integrations"], queryFn: Integrations.list, staleTime: 60_000 });
  const kakaoOffered = !!integ.data?.providers.find((p) => p.id === "kakao")?.capabilities.some((c) => c.id === "talk_message");
  const kakaoConn = integ.data?.connections.find((c) => c.provider === "kakao");
  const hasKakao = channels.some((c) => c.kind === "kakao");
  const router = useRouter(); const sp = useSearchParams();
  const back = "/app/notifications?add=kakao";
  const addKakao = useMutation({
    mutationFn: async () => {
      if (!kakaoConn) { await connectProvider("kakao", ["talk_message"], back); return "away"; }
      if (!kakaoConn.capabilities.includes("talk_message")) {
        const r = await Integrations.patch(kakaoConn.id, [...kakaoConn.capabilities, "talk_message"], back);
        if (r.consent_url) { window.location.assign(r.consent_url); return "away"; }
      }
      await Notifications.createChannel({ kind: "kakao", config: { connection_id: kakaoConn.id }, label: t("notif.kind_kakao") });
      return "made";
    },
    onSuccess: (r) => { if (r === "made") { inval(); qc.invalidateQueries({ queryKey: ["integrations"] }); toast.success(t("notif.kakao_added")); } },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  // 카카오 동의를 마치고 돌아왔으면 채널을 바로 만든다 — 같은 버튼을 두 번 누르게 하지 않는다.
  const resumed = useRef(false);
  useEffect(() => {
    if (sp.get("add") !== "kakao" || resumed.current || !integ.data || !ch.data) return;
    resumed.current = true;
    router.replace("/app/notifications", { scroll: false });
    const err = sp.get("error");
    if (err) { toast.error(codeMessage(err, locale)); return; }
    if (!hasKakao && kakaoConn?.capabilities.includes("talk_message")) addKakao.mutate();
  }, [sp, integ.data, ch.data]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Page>
      <PageHeader title={t("nav.notifications")} description={t("notif.desc")} />
      <Tabs value={tab} onChange={setTab} items={[{ key: "channels", label: t("notif.channels"), count: channels.length }, { key: "rules", label: t("notif.rules") }, { key: "log", label: t("notif.log") }]} className="mb-4" />
      {tab === "channels" ? (
        <div className="space-y-3">
          {ch.isLoading ? <Skeleton className="h-40" /> : channels.map((c) => (
            <Card key={c.id} className="p-4">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 text-muted-fg [&>svg]:h-5 [&>svg]:w-5">{ICONS[c.kind]}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{c.label || t(`notif.kind_${c.kind}`)}</span><Badge tone="outline">{t(`notif.kind_${c.kind}`)}</Badge>{c.verified_at ? <Badge tone="success">{t("notif.verified")}</Badge> : <Badge tone="warning">{t("notif.unverified")}</Badge>}</div>
                  <div className="truncate text-xs text-muted-fg">{configLine(c)}</div>
                  {c.last_error ? <div className="mt-1 text-xs text-danger">{c.last_error}</div> : null}
                </div>
                <Switch checked={c.enabled} onChange={(v) => patchCh.mutate({ id: c.id, b: { enabled: v } })} label={t("notif.enabled")} />
              </div>
              {/* 확인되지 않은 곳으로는 알림이 나가지 않는다. 그러니 그 사실과 다음에
                  할 일이 카드 안에 있어야 한다. 메일은 그 주소로 간 코드로, 나머지는
                  [테스트 발송]이 닿는 것으로 확인된다. */}
              {!c.verified_at ? <VerifyBox ch={c} onDone={inval} /> : null}
              <div className="mt-3 flex gap-2">
                {c.kind !== "email" || c.verified_at ? (
                  <Button size="sm" variant="outline" loading={test.isPending && test.variables === c.id} onClick={() => test.mutate(c.id)}>{t("notif.test")}</Button>
                ) : null}
                <Button size="sm" variant="ghost" className="text-danger ml-auto" onClick={async () => { if (await confirm({ title: t("common.confirm_delete"), danger: true, confirmLabel: t("common.delete") })) delCh.mutate(c.id); }}><Trash2 className="h-4 w-4" /></Button>
              </div>
            </Card>
          ))}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setAdd("email")}><Plus className="h-4 w-4" />{t("notif.kind_email")}</Button>
            <Button variant="outline" loading={tgLink.isPending} onClick={() => tgLink.mutate()}><Plus className="h-4 w-4" />{t("notif.kind_telegram")}</Button>
            {kakaoOffered && !hasKakao ? <Button variant="outline" loading={addKakao.isPending} onClick={() => addKakao.mutate()}><Plus className="h-4 w-4" />{t("notif.kind_kakao")}</Button> : null}
            <Button variant="outline" onClick={() => setAdd("slack")}><Plus className="h-4 w-4" />Slack</Button>
            <Button variant="outline" onClick={() => setAdd("discord")}><Plus className="h-4 w-4" />Discord</Button>
            <Button variant="outline" onClick={() => setAdd("webhook")}><Plus className="h-4 w-4" />Webhook</Button>
          </div>
        </div>
      ) : tab === "rules" ? <RulesTable rules={rules.data?.items ?? []} channels={channels} events={ch.data?.events ?? []} onChanged={inval} loading={rules.isLoading} />
        : (
          <Card><CardBody className="pt-5">{log.isLoading ? <Skeleton className="h-40" /> : log.data?.items.length ? (
            <Table><THead><tr><TH>{t("credits.when")}</TH><TH>{t("notif.event")}</TH><TH>{t("notif.channel")}</TH><TH>{t("turn.status")}</TH></tr></THead>
              <TBody>{log.data.items.map((n) => <TR key={n.id}><TD className="text-xs text-muted-fg whitespace-nowrap">{fmtDateTime(n.created_at)}</TD><TD>{t(`notif.ev_${n.event}`) === `notif.ev_${n.event}` ? n.event : t(`notif.ev_${n.event}`)}</TD><TD className="text-xs">{channels.find((c) => c.id === n.channel_id)?.label ?? channels.find((c) => c.id === n.channel_id)?.kind ?? "–"}</TD><TD><Badge tone={n.status === "sent" ? "success" : n.status === "failed" ? "danger" : "neutral"}>{n.status}</Badge>{n.error ? <div className="text-[10px] text-danger">{n.error}</div> : null}</TD></TR>)}</TBody></Table>
          ) : <p className="text-sm text-muted-fg">{t("notif.log_empty")}</p>}</CardBody></Card>
        )}
      <AddChannelDialog kind={add} onClose={() => setAdd(null)} onCreated={inval} />
      <Dialog open={!!tg} onClose={() => setTg(null)} title={t("notif.kind_telegram")} size="sm" footer={<Button onClick={() => { setTg(null); inval(); }}>{t("common.done")}</Button>}>
        {tg ? <div className="space-y-3 text-sm"><p>{tg.instructions}</p>{tg.bot_username ? <a className="text-accent underline" href={`https://t.me/${tg.bot_username}?start=${tg.code}`} target="_blank" rel="noopener noreferrer">t.me/{tg.bot_username}</a> : null}<div className="rounded-xl bg-muted p-3 text-center font-mono text-lg tracking-widest">{tg.code}</div><p className="text-xs text-muted-fg">{t("notif.telegram_hint")}</p></div> : null}
      </Dialog>
    </Page>
  );
}

/** 이 주소가 당신 것인지 묻는 자리.
 *
 *  주소는 어디든 적을 수 있다. 다만 거기로 간 코드를 가져와야 그 주소로 알림이 나간다.
 *  증명 없이 보낼 수 있으면 채널 하나로 남에게 메일을 보내는 통로가 되기 때문이다. */
function VerifyBox({ ch, onDone }: { ch: Channel; onDone: () => void }) {
  const t = useT(); const locale = useLocale();
  const [code, setCode] = useState("");
  const send = useMutation({ mutationFn: () => Notifications.sendChannelCode(ch.id),
    onSuccess: () => toast.success(t("notif.code_sent")), onError: (e) => toast.error(friendlyError(e, locale)) });
  const ok = useMutation({ mutationFn: () => Notifications.verifyChannel(ch.id, code.trim()),
    onSuccess: () => { toast.success(t("notif.verified")); setCode(""); onDone(); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  if (ch.kind !== "email") {
    return <p className="mt-3 rounded-xl bg-muted px-3 py-2 text-xs text-muted-fg">{t("notif.verify_by_test")}</p>;
  }
  return (
    <div className="mt-3 rounded-xl border border-border bg-muted/40 p-3">
      <p className="text-xs text-muted-fg">{t("notif.verify_hint")}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
               inputMode="numeric" placeholder={t("verify.code")} className="h-9 w-[120px] text-center tracking-widest" />
        <Button size="sm" loading={ok.isPending} disabled={code.trim().length < 6} onClick={() => ok.mutate()}>{t("notif.verify_do")}</Button>
        <Button size="sm" variant="ghost" loading={send.isPending} onClick={() => send.mutate()}>{t("notif.code_resend")}</Button>
      </div>
    </div>
  );
}

function AddChannelDialog({ kind, onClose, onCreated }: { kind: string | null; onClose: () => void; onCreated: () => void }) {
  const t = useT(); const locale = useLocale();
  const [label, setLabel] = useState(""); const [url, setUrl] = useState(""); const [address, setAddress] = useState(""); const [secret, setSecret] = useState("");
  const m = useMutation({
    mutationFn: () => Notifications.createChannel({ kind: kind!, label, config: kind === "email" ? { to: address } : kind === "webhook" ? { url, secret } : { url } }),
    onSuccess: () => { onCreated(); onClose(); setLabel(""); setUrl(""); setAddress(""); setSecret(""); }, onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <Dialog open={!!kind} onClose={onClose} title={t("notif.add_channel")} size="sm" footer={<><Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button><Button loading={m.isPending} onClick={() => m.mutate()}>{t("common.add")}</Button></>}>
      <div className="space-y-3">
        <Field label={t("notif.label")}><Input value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
        {kind === "email" ? <Field label={t("auth.email")}><Input type="email" value={address} onChange={(e) => setAddress(e.target.value)} /></Field> : <Field label={kind === "webhook" ? "URL" : `${kind} Webhook URL`}><Input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" /></Field>}
        {kind === "webhook" ? <Field label={t("notif.signing_secret")} hint={t("common.optional")}><Input value={secret} onChange={(e) => setSecret(e.target.value)} /></Field> : null}
      </div>
    </Dialog>
  );
}

function RulesTable({ rules, channels, events, onChanged, loading }: { rules: Rule[]; channels: Channel[]; events: string[]; onChanged: () => void; loading: boolean }) {
  const t = useT(); const locale = useLocale();
  const [edit, setEdit] = useState<Partial<Rule> | null>(null);
  const save = useMutation({ mutationFn: (r: Partial<Rule>) => (r.id ? Notifications.patchRule(r.id, { event: r.event, channel_ids: r.channel_ids ?? [], enabled: r.enabled ?? true, quiet_hours: r.quiet_hours ?? {}, min_urgency: r.min_urgency ?? 0 }) : Notifications.createRule({ event: r.event, channel_ids: r.channel_ids ?? [], enabled: r.enabled ?? true, quiet_hours: r.quiet_hours ?? {}, min_urgency: r.min_urgency ?? 0 })), onSuccess: () => { onChanged(); setEdit(null); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const del = useMutation({ mutationFn: (id: string) => Notifications.deleteRule(id), onSuccess: onChanged });
  const evLabel = (e: string) => (t(`notif.ev_${e}`) === `notif.ev_${e}` ? e : t(`notif.ev_${e}`));
  const qh = (edit?.quiet_hours ?? {}) as { start?: string; end?: string };
  return (
    <div>
      <div className="mb-3 flex justify-end"><Button onClick={() => setEdit({ event: events[0], channel_ids: [], enabled: true, min_urgency: 0, quiet_hours: {} })}><Plus className="h-4 w-4" />{t("notif.add_rule")}</Button></div>
      {loading ? <Skeleton className="h-40" /> : (
        <Table><THead><tr><TH>{t("notif.event")}</TH><TH>{t("notif.channels")}</TH><TH>{t("notif.min_urgency")}</TH><TH>{t("notif.quiet_hours")}</TH><TH>{t("notif.enabled")}</TH><TH></TH></tr></THead>
          <TBody>{rules.map((r) => { const q = (r.quiet_hours ?? {}) as { start?: string; end?: string }; return (
            <TR key={r.id}><TD className="text-sm font-medium">{evLabel(r.event)}</TD><TD><div className="flex flex-wrap gap-1">{r.channel_ids.map((id) => { const c = channels.find((x) => x.id === id); return <Badge key={id} tone="outline">{c?.label || c?.kind || "?"}</Badge>; })}{!r.channel_ids.length ? <span className="text-xs text-muted-fg">–</span> : null}</div></TD><TD className="tabular-nums">{r.min_urgency}</TD><TD className="text-xs">{q.start && q.end ? `${q.start}–${q.end}` : "–"}</TD><TD><Badge tone={r.enabled ? "success" : "neutral"}>{r.enabled ? "on" : "off"}</Badge></TD>
              <TD><div className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => setEdit(r)}>{t("common.edit")}</Button><Button size="sm" variant="ghost" className="text-danger" onClick={() => del.mutate(r.id)}><Trash2 className="h-4 w-4" /></Button></div></TD></TR>); })}</TBody></Table>
      )}
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? t("notif.edit_rule") : t("notif.add_rule")} size="sm" footer={<><Button variant="outline" onClick={() => setEdit(null)}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => edit && save.mutate(edit)}>{t("common.save")}</Button></>}>
        {edit ? <div className="space-y-3">
          <Field label={t("notif.event")}><Select value={edit.event} disabled={!!edit.id} onChange={(e) => setEdit({ ...edit, event: e.target.value })}>{events.map((e) => <option key={e} value={e}>{evLabel(e)}</option>)}</Select></Field>
          <div><div className="mb-1 text-sm font-medium">{t("notif.channels")}</div><div className="space-y-1">{channels.map((c) => <Checkbox key={c.id} checked={(edit.channel_ids ?? []).includes(c.id)} onChange={(v) => setEdit({ ...edit, channel_ids: v ? [...(edit.channel_ids ?? []), c.id] : (edit.channel_ids ?? []).filter((x) => x !== c.id) })} label={`${c.label || t(`notif.kind_${c.kind}`)} (${c.kind})`} />)}{!channels.length ? <p className="text-xs text-muted-fg">{t("notif.no_channels")}</p> : null}</div></div>
          <Field label={t("notif.min_urgency")} hint={t("notif.urgency_hint")}><Select value={String(edit.min_urgency ?? 0)} onChange={(e) => setEdit({ ...edit, min_urgency: Number(e.target.value) })}>{[0, 1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}</Select></Field>
          <div className="grid grid-cols-2 gap-3"><Field label={t("notif.quiet_start")}><Input type="time" value={qh.start ?? ""} onChange={(e) => setEdit({ ...edit, quiet_hours: { ...qh, start: e.target.value } })} /></Field><Field label={t("notif.quiet_end")}><Input type="time" value={qh.end ?? ""} onChange={(e) => setEdit({ ...edit, quiet_hours: { ...qh, end: e.target.value } })} /></Field></div>
          <div className="flex items-center justify-between"><span className="text-sm">{t("notif.enabled")}</span><Switch checked={edit.enabled ?? true} onChange={(v) => setEdit({ ...edit, enabled: v })} /></div>
        </div> : null}
      </Dialog>
      <div className="mt-2 text-xs text-muted-fg flex items-center gap-1"><Bell className="h-3 w-3" />{t("notif.rules_hint")}</div>
    </div>
  );
}
