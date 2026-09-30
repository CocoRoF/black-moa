"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, RefreshCw, Trash2 } from "@/components/icons";
import { Admin } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { useVoiceFeatures } from "@/lib/hooks";
import { friendlyError } from "@/lib/errors";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { cn, copyText } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { SettingsForm, JsonBlock } from "./common";
import * as D from "./settingsDefs";
import { Button, buttonLook } from "@/components/ui/button";
import { Field, Input, Checkbox } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { PageHeader, KeyValue } from "@/components/ui/misc";
import { Section } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";

export function AudioPage() {
  const t = useT();
  return (
    <Page>
      <PageHeader title={t("adm.audio")} description={t("adm.audio_desc")} />
      <div className="space-y-4"><SettingsForm title="STT" fields={D.sttFields(t)} prefix="stt." /><SettingsForm title="TTS" fields={D.ttsFields(t)} prefix="tts." /></div>
    </Page>
  );
}

export function SystemSettingsPage() {
  const t = useT();
  return (
    <Page>
      <PageHeader title={t("adm.settings")} description={t("adm.settings_desc")} />
      <div className="space-y-4">
        <SettingsForm title={t("adm.branding")} fields={D.brandingFields(t)} prefix="branding." />
        <SettingsForm title={t("adm.signup")} fields={D.signupFields(t)} prefix="signup." />
        {/* SMTP lives on its own page (/admin/email): the relays need provider presets and a
            test send, which the generic settings form cannot express. Google·카카오 로그인과
            연동은 [연결](/admin/connections)에 — 공급자마다 켜기·기능·콘솔 주소·설정 확인이 있다 (plan/59). */}
        <SettingsForm title="Telegram" fields={D.telegramFields()} prefix="telegram." />
        <SettingsForm title="Cloudflare Turnstile" fields={D.turnstileFields()} prefix="public.turnstile" />
        <SettingsForm title={t("adm.public_defaults")} fields={D.publicDefaultFields(t)} prefix="public.default" />
        <SettingsForm title={t("adm.credits")} fields={D.creditFields(t)} prefix="credits." />
        <SettingsForm title="Stripe" fields={D.stripeFields()} prefix="stripe." />
        <SettingsForm title={t("adm.memory")} fields={D.memoryFields(t)} prefix="memory." />
        <SettingsForm title={t("adm.legal_operator")} description={t("adm.legal_operator_desc")} fields={D.legalOperatorFields(t)} prefix="legal." />
        <SettingsForm title={t("adm.legal")} description={t("adm.legal_desc")} fields={D.legalFields(t)} prefix="legal." extra={<LegalDefaults />} />
        <SettingsForm title={t("adm.logging")} fields={D.logFields()} prefix="log." />
      </div>
    </Page>
  );
}

export function InvitesPage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "invites"], queryFn: Admin.invites });
  const [f, setF] = useState({ max_uses: 1, expires_days: 30, note: "" });
  const create = useMutation({ mutationFn: () => Admin.createInvite({ ...f, expires_days: f.expires_days || null }), onSuccess: async (r) => { qc.invalidateQueries({ queryKey: ["admin", "invites"] }); await copyText(`${window.location.origin}/signup?invite=${r.code}`); toast.success(t("adm.invite_created", { code: r.code })); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const del = useMutation({ mutationFn: (id: string) => Admin.deleteInvite(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "invites"] }) });
  return (
    <Page>
      <PageHeader title={t("adm.invites")} description={t("adm.invites_desc")} />
      <Section title={t("adm.new_invite")}>
        <div className="grid gap-3 sm:grid-cols-4 items-end">
          <Field label={t("adm.max_uses")}><Input type="number" min={1} value={f.max_uses} onChange={(e) => setF({ ...f, max_uses: Number(e.target.value) })} /></Field>
          <Field label={t("adm.expires_days")}><Input type="number" min={0} value={f.expires_days} onChange={(e) => setF({ ...f, expires_days: Number(e.target.value) })} /></Field>
          <Field label={t("credits.note")}><Input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></Field>
          <Button loading={create.isPending} onClick={() => create.mutate()}><Plus className="h-4 w-4" />{t("common.create")}</Button>
        </div>
      </Section>
      <div className="mt-4">{q.isLoading ? <Skeleton className="h-40" /> : (
        <Table><THead><tr><TH>{t("adm.code")}</TH><TH>{t("adm.uses")}</TH><TH>{t("links.expires_at")}</TH><TH>{t("credits.note")}</TH><TH>{t("credits.when")}</TH><TH></TH></tr></THead>
          <TBody>{q.data?.items.map((i) => <TR key={i.id}><TD><button type="button" className="font-mono text-xs underline" onClick={async () => { await copyText(`${window.location.origin}/signup?invite=${i.code}`); toast.success(t("common.copied")); }}>{i.code}</button></TD><TD>{i.used}/{i.max_uses}</TD><TD className="text-xs">{i.expires_at ? fmtDateTime(i.expires_at) : "–"}</TD><TD className="text-xs">{i.note}</TD><TD className="text-xs text-muted-fg">{fmtRelative(i.created_at, locale)}</TD><TD><Button size="icon-sm" variant="ghost" className="text-danger" onClick={() => del.mutate(i.id)}><Trash2 className="h-4 w-4" /></Button></TD></TR>)}</TBody></Table>
      )}</div>
    </Page>
  );
}

/** Plan limits, in the order an admin thinks about them: what it costs, then what it
 *  allows. The keys are the columns of `plans`; the labels are what a person calls them —
 *  the form used to print the column names, so "turn cost cap credits" was the UI. */
/** What a plan actually decides (plan/34): what it grants, and what it may hold. How hard
 *  a secretary may be worked is set on the secretary, and the credit balance is the limit
 *  that applies to everything. */
const PLAN_FIELDS = [
  { k: "monthly_credits", label: "adm.plan_credits" },
  { k: "max_agents", label: "adm.plan_agents" },
  { k: "max_share_links", label: "adm.plan_links" },
  { k: "max_storage_mb", label: "adm.plan_knowledge" },
] as const;
const PLAN_FEATURES = [
  { k: "web_search", label: "adm.feat_web_search" },
  { k: "voice", label: "adm.feat_voice" },
  { k: "google", label: "adm.feat_google" },
] as const;
const NEW_PLAN = { code: "", name: "", monthly_credits: 1000, max_agents: 1, max_share_links: 2, max_storage_mb: 1024,
                   features: { web_search: false, voice: true, google: true }, models: [] as string[], is_default: false };

export function PlansPage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  // 서비스가 음성을 끄면 요금제의 "음성 대화" 도 보이지 않는다(값은 그대로 둔다, plan/67).
  const voiceOn = useVoiceFeatures();
  const features = PLAN_FEATURES.filter((f) => f.k !== "voice" || voiceOn.stt || voiceOn.tts);
  const q = useQuery({ queryKey: ["admin", "plans"], queryFn: Admin.plans });
  // The pool: what the catalog has turned on. A plan may narrow it, never widen it.
  const pool = useQuery({ queryKey: ["admin", "models"], queryFn: Admin.models });
  const [edit, setEdit] = useState<any | null>(null);
  const save = useMutation({ mutationFn: (p: any) => (p.id ? Admin.patchPlan(p.id, p) : Admin.createPlan(p)), onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin", "plans"] }); setEdit(null); toast.success(t("common.saved")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const poolItems = (pool.data?.items ?? []).filter((m: any) => m.enabled);
  const nameOf = (key: string) => poolItems.find((m: any) => `${m.provider}:${m.model_id}` === key)?.display_name ?? key;
  const modelsLabel = (p: any) => (p.models?.length ? p.models.map(nameOf).join(", ") : t("adm.plan_models_all"));
  return (
    <Page>
      <PageHeader title={t("adm.plans")} description={t("adm.plans_desc")} action={<Button onClick={() => setEdit({ ...NEW_PLAN, features: { ...NEW_PLAN.features }, models: [] })}><Plus className="h-4 w-4" />{t("adm.add_plan")}</Button>} />
      {q.isLoading ? <Skeleton className="h-40" /> : (
        <Table>
          <THead><tr><TH>{t("adm.plan_code")}</TH><TH>{t("adm.plan_name")}</TH>{PLAN_FIELDS.map((f) => <TH key={f.k}>{t(f.label)}</TH>)}<TH>{t("adm.plan_features")}</TH><TH>{t("adm.plan_models_col")}</TH><TH>{t("adm.m_default")}</TH><TH></TH></tr></THead>
          <TBody>{q.data?.items.map((p) => (
            <TR key={p.id}>
              <TD className="font-mono text-xs">{p.code}</TD>
              <TD>{p.name}</TD>
              {PLAN_FIELDS.map((f) => <TD key={f.k} className="tabular-nums text-xs">{p[f.k]}</TD>)}
              <TD className="text-xs">{features.filter((f) => p.features?.[f.k]).map((f) => t(f.label)).join(", ") || "—"}</TD>
              <TD className="max-w-[220px] truncate text-xs" title={modelsLabel(p)}>{modelsLabel(p)}</TD>
              <TD>{p.is_default ? <Badge tone="accent">{t("adm.m_default")}</Badge> : null}</TD>
              <TD><Button size="sm" variant="ghost" onClick={() => setEdit({ ...p, features: { ...(p.features ?? {}) }, models: [...(p.models ?? [])] })}>{t("common.edit")}</Button></TD>
            </TR>
          ))}</TBody>
        </Table>
      )}
      <Dialog open={!!edit} onClose={() => setEdit(null)} size="lg" title={edit?.id ? `${edit.name} · ${t("common.edit")}` : t("adm.add_plan")}
        footer={<><Button variant="outline" onClick={() => setEdit(null)}>{t("common.cancel")}</Button><Button loading={save.isPending} disabled={!edit?.code || !edit?.name} onClick={() => save.mutate(edit)}>{t("common.save")}</Button></>}>
        {edit ? (
          <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("adm.plan_code")} hint={edit.id ? undefined : t("adm.plan_code_hint")}>
                <Input value={edit.code} disabled={!!edit.id} onChange={(e) => setEdit({ ...edit, code: e.target.value })} placeholder="free" />
              </Field>
              <Field label={t("adm.plan_name")}><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} placeholder="Free" /></Field>
            </div>
            <div>
              <div className="mb-2 text-sm font-medium">{t("adm.plan_limits")}</div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {PLAN_FIELDS.map((f) => (
                  <Field key={f.k} label={t(f.label)}>
                    <Input type="number" value={edit[f.k] ?? 0} onChange={(e) => setEdit({ ...edit, [f.k]: Number(e.target.value) })} />
                  </Field>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-2 text-sm font-medium">{t("adm.plan_features")}</div>
              <div className="flex flex-wrap gap-4">
                {features.map((f) => <Checkbox key={f.k} checked={!!edit.features?.[f.k]} onChange={(v) => setEdit({ ...edit, features: { ...edit.features, [f.k]: v } })} label={t(f.label)} />)}
              </div>
            </div>
            <PlanModels pool={poolItems} value={edit.models ?? []} onChange={(models) => setEdit({ ...edit, models })} />
            <div className="border-t border-border pt-4">
              <Checkbox checked={!!edit.is_default} onChange={(v) => setEdit({ ...edit, is_default: v })} label={t("adm.plan_default")} />
              <p className="mt-1 text-xs text-muted-fg">{t("adm.plan_default_hint")}</p>
            </div>
          </div>
        ) : null}
      </Dialog>
    </Page>
  );
}

/** Which of the pool this plan may use. Empty is not "none" — it is "all of it", which is
 *  what a plan nobody has thought about should do, and it keeps a newly added model
 *  reaching every plan without four separate edits. */
function PlanModels({ pool, value, onChange }: { pool: any[]; value: string[]; onChange: (v: string[]) => void }) {
  const t = useT();
  const all = value.length === 0;
  const toggle = (key: string) => onChange(value.includes(key) ? value.filter((v) => v !== key) : [...value, key]);
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{t("adm.plan_models")}</span>
        <Badge tone={all ? "accent" : "outline"}>{all ? t("adm.plan_models_all") : t("adm.plan_models_n", { n: value.length })}</Badge>
        {!all ? <Button size="sm" variant="ghost" onClick={() => onChange([])}>{t("adm.plan_models_all")}</Button> : null}
      </div>
      <p className="mb-2 text-xs text-muted-fg">{t("adm.plan_models_hint")}</p>
      {pool.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border p-3 text-sm text-muted-fg">{t("adm.plan_pool_empty")}</p>
      ) : (
        <ul className="grid gap-1.5 sm:grid-cols-2">
          {pool.map((m) => {
            const key = `${m.provider}:${m.model_id}`;
            const on = all || value.includes(key);
            return (
              <li key={key}>
                <label className={cn("flex cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2 text-sm transition-colors",
                                     on ? "border-accent/50 bg-accent/5" : "border-border hover:bg-muted/50")}>
                  <Checkbox checked={value.includes(key)} onChange={() => toggle(key)} />
                  <span className="min-w-0 flex-1 truncate">{m.display_name}</span>
                  <Badge tone="outline" className="shrink-0">{m.provider}</Badge>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function HealthPage() {
  const t = useT(); const locale = useLocale();
  const q = useQuery({ queryKey: ["admin", "health"], queryFn: Admin.health, refetchInterval: 15_000 });
  const d = q.data;
  return (
    <Page>
      <PageHeader title={t("adm.health")} description={t("adm.health_desc")} action={<Button variant="outline" onClick={() => q.refetch()} loading={q.isFetching}><RefreshCw className="h-4 w-4" />{t("common.refresh")}</Button>} />
      {q.isLoading || !d ? <Skeleton className="h-60" /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Section title="/health"><KeyValue items={Object.entries(d.live ?? {}).map(([k, v]) => ({ k, v: typeof v === "object" ? JSON.stringify(v) : String(v) }))} /></Section>
          <Section title="/health/ready"><KeyValue items={Object.entries(d.ready ?? {}).map(([k, v]) => ({ k, v: <Badge tone={v === "ok" || v === "present" ? "success" : v === "unknown" ? "neutral" : typeof v === "number" ? "outline" : "danger"}>{String(v)}</Badge> }))} /></Section>
          <Section title="Claude Code"><JsonBlock data={d.claude} /></Section>
          <Section title={t("adm.recent_failed_turns")}>
            {d.recent_failed_turns?.length ? <ul className="space-y-1.5 text-xs">{d.recent_failed_turns.map((x: any) => <li key={x.id} className="rounded-lg border border-danger/30 bg-danger/5 p-2"><div className="flex items-center gap-2"><Badge tone="danger">{x.code}</Badge><span className="text-muted-fg">{x.provider}/{x.model_id}</span><span className="ml-auto text-muted-fg">{fmtRelative(x.at, locale)}</span></div><div className="mt-1 break-all font-mono">{x.message}</div></li>)}</ul> : <p className="text-sm text-muted-fg">{t("adm.no_failed")}</p>}
          </Section>
        </div>
      )}
    </Page>
  );
}

export function AuditPage() {
  const t = useT();
  const [action, setAction] = useState("");
  const q = useQuery({ queryKey: ["admin", "audit", action], queryFn: () => Admin.audit({ action: action || undefined }) });
  return (
    <Page>
      <PageHeader title={t("adm.audit")} description={t("adm.audit_desc")} />
      <div className="mb-3 max-w-xs"><Input placeholder={t("adm.filter_action")} value={action} onChange={(e) => setAction(e.target.value)} /></div>
      {q.isLoading ? <Skeleton className="h-60" /> : (
        <Table><THead><tr><TH>{t("credits.when")}</TH><TH>{t("adm.action")}</TH><TH>{t("adm.actor")}</TH><TH>{t("adm.target")}</TH><TH>IP</TH><TH>{t("adm.col_meta")}</TH></tr></THead>
          <TBody>{q.data?.items.map((a) => <TR key={a.id}><TD className="whitespace-nowrap text-xs text-muted-fg">{fmtDateTime(a.created_at)}</TD><TD><Badge tone="outline">{a.action}</Badge></TD><TD className="font-mono text-[11px]">{a.actor_kind}:{a.actor_id?.slice(0, 8)}</TD><TD className="font-mono text-[11px]">{a.target_type ? `${a.target_type}:${String(a.target_id ?? "").slice(0, 8)}` : ""}</TD><TD className="text-xs">{a.ip}</TD><TD className="max-w-[300px] truncate font-mono text-[11px] text-muted-fg">{a.meta ? JSON.stringify(a.meta) : ""}</TD></TR>)}</TBody></Table>
      )}
    </Page>
  );
}

/** 기본 문서를 고쳐 쓰고 싶을 때: 원문(자리표시 그대로)을 복사해 위 칸에 붙여 넣는다. 공개 화면은 새 창으로 본다. */
function LegalDefaults() {
  const t = useT(); const locale = useLocale();
  const copy = useMutation({
    mutationFn: async (kind: "terms" | "privacy") => { const r = await Admin.legalDefault(kind); await copyText(r.text); },
    onSuccess: () => toast.success(t("adm.legal_default_copied")),
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <Button variant="outline" size="sm" loading={copy.isPending && copy.variables === "terms"} onClick={() => copy.mutate("terms")}>{t("adm.legal_copy_terms")}</Button>
      <Button variant="outline" size="sm" loading={copy.isPending && copy.variables === "privacy"} onClick={() => copy.mutate("privacy")}>{t("adm.legal_copy_privacy")}</Button>
      <a href="/terms" target="_blank" rel="noopener" className={buttonLook("ghost", "sm")}>{t("adm.legal_view_terms")}</a>
      <a href="/privacy" target="_blank" rel="noopener" className={buttonLook("ghost", "sm")}>{t("adm.legal_view_privacy")}</a>
    </div>
  );
}
