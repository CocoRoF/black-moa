"use client";
import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarDays, CheckCircle2, Copy, ExternalLink, ShieldCheck, XCircle } from "@/components/icons";
import { Admin, type AdminConnection, type ConnectionCheck } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtSecretTail } from "@/lib/format";
import { copyText } from "@/lib/utils";
import { confirm } from "@/lib/confirm";
import { Page } from "@/components/owner/Shell";
import { Section } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox, Field, Input } from "@/components/ui/input";
import { SwitchRow } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Segmented } from "@/components/ui/tabs";
import { PageHeader } from "@/components/ui/misc";
import { ProviderIcon } from "@/components/integrations/ProviderIcon";
import { HolidaysPanel } from "./HolidaysPanel";

/** 관리자 [연결] (plan/59). 공급자(Google · 카카오 …)마다 한 장.
 *
 *  관리자가 공급자 콘솔에서 앱을 만들고, 받은 키를 여기 넣고, 여기 적힌 주소를 콘솔에 등록하고, 켜면
 *  로그인 버튼과 데이터 연동이 그대로 작동한다. 틀리기 쉬운 곳(주소·동의항목)은 이 화면이 알려 주고,
 *  [설정 확인]이 공급자에게 직접 물어 키가 맞는지 가른다. */
export function ConnectionsPage() {
  const t = useT(); const router = useRouter(); const path = usePathname(); const sp = useSearchParams();
  const q = useQuery({ queryKey: ["admin", "connections"], queryFn: Admin.connections });
  const providers = q.data?.providers ?? [];
  const asked = sp.get("p");
  // 공급자 뒤에 [공휴일] — 로그인 공급자는 아니지만 관리자가 잇는 바깥 자료다 (plan/60).
  const holidays = asked === "holidays";
  const current = holidays ? undefined : providers.find((p) => p.id === asked) ?? providers[0];
  return (
    <Page>
      <PageHeader title={t("adm.connections")} description={t("conn.desc")} />
      {q.isLoading || (!current && !holidays) ? <Skeleton className="h-96" /> : (
        <div className="space-y-4">
          <Segmented ariaLabel={t("adm.connections")} value={holidays ? "holidays" : current!.id} onChange={(v) => router.replace(`${path}?p=${v}`, { scroll: false })}
            options={[...providers.map((p) => ({ value: p.id, label: <span className="inline-flex items-center gap-1.5"><ProviderIcon provider={p.id} size={16} />{p.label}{p.ready ? <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden /> : null}</span> })),
              { value: "holidays", label: <span className="inline-flex items-center gap-1.5"><CalendarDays className="h-4 w-4 text-danger" />{t("hol.tab")}</span> }]} />
          {holidays ? <HolidaysPanel /> : <ProviderPanel key={current!.id} p={current!} siteUrl={q.data!.site_url} />}
        </div>
      )}
    </Page>
  );
}

function ProviderPanel({ p, siteUrl }: { p: AdminConnection; siteUrl: string }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const put = (next: AdminConnection) => {
    qc.setQueryData<{ site_url: string; providers: AdminConnection[] }>(["admin", "connections"], (old) =>
      old ? { ...old, providers: old.providers.map((x) => (x.id === next.id ? next : x)) } : old);
    qc.invalidateQueries({ queryKey: ["auth-status"] });
    qc.invalidateQueries({ queryKey: ["integrations"] });
  };
  const save = useMutation({
    mutationFn: (b: Parameters<typeof Admin.saveConnection>[1]) => Admin.saveConnection(p.id, b),
    onSuccess: (r) => { put(r); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  const toggleEnabled = async (on: boolean) => {
    if (!on && p.stats.connections > 0 && !(await confirm({
      title: t("conn.off_title", { name: p.label }), description: t("conn.off_desc", { n: p.stats.connections, m: p.stats.login_only }),
      confirmLabel: t("conn.turn_off"), danger: true }))) return;
    save.mutate({ enabled: on });
  };
  const toggleLogin = async (on: boolean) => {
    if (!on && p.stats.login_only > 0 && !(await confirm({
      title: t("conn.login_off_title"), description: t("conn.login_off_desc", { n: p.stats.login_only }),
      confirmLabel: t("conn.turn_off"), danger: true }))) return;
    save.mutate({ login: on });
  };
  const toggleFeature = async (id: string, on: boolean) => {
    if (!on && p.stats.connections > 0 && !(await confirm({
      title: t("conn.feature_off_title", { name: t(`integ.cap_${id}`) }), description: t("conn.feature_off_desc"),
      confirmLabel: t("conn.turn_off"), danger: true }))) return;
    save.mutate({ features: on ? [...p.features, id] : p.features.filter((x) => x !== id) });
  };

  return (
    <div className="space-y-4">
      <Section title={<span className="inline-flex items-center gap-2"><ProviderIcon provider={p.id} size={20} />{p.label}</span>}
        description={t(`conn.about_${p.id}`)}
        action={<Badge tone={p.ready ? "success" : p.enabled ? "warning" : "neutral"}>{p.ready ? t("conn.st_on") : p.enabled ? t("conn.st_incomplete") : t("conn.st_off")}</Badge>}>
        <div className="divide-y divide-border">
          <SwitchRow title={t("conn.enable")} description={p.missing.length ? t("conn.enable_needs_keys") : t("conn.enable_desc")}
            checked={p.enabled} disabled={save.isPending || (!p.enabled && p.missing.length > 0)} onChange={toggleEnabled} />
          <SwitchRow title={t("conn.login")} description={t("conn.login_desc")} checked={p.login} disabled={save.isPending} onChange={toggleLogin} />
        </div>
        <p className="mt-2 text-xs text-muted-fg">
          {t("conn.stats", { ids: p.stats.identities, conns: p.stats.connections })}
          {p.stats.connections_by_status.expired ? ` · ${t("conn.stats_expired", { n: p.stats.connections_by_status.expired })}` : ""}
        </p>
      </Section>

      <KeysSection p={p} onSaved={put} />

      <Section title={t("conn.register_title")} description={t(`conn.register_desc_${p.id}`)}
        action={p.console_url ? <a href={p.console_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm text-accent hover:underline">{t("conn.console")}<ExternalLink className="h-3.5 w-3.5" /></a> : null}>
        <div className="space-y-2">
          <CopyRow label={t("conn.redirect_login")} value={p.redirect_uris.login} />
          <CopyRow label={t("conn.redirect_connect")} value={p.redirect_uris.connect} />
          <CopyRow label={p.id === "kakao" ? t("conn.site_domain") : t("conn.js_origin")} value={siteUrl} />
        </div>
      </Section>

      <Section title={t("conn.features_title")} description={t("conn.features_desc")}>
        <div className="space-y-1">
          {p.capabilities.map((c) => (
            <div key={c.id} className="flex flex-wrap items-center gap-x-3">
              <Checkbox checked={p.features.includes(c.id)} disabled={save.isPending} onChange={(v) => void toggleFeature(c.id, v)} label={t(`integ.cap_${c.id}`)} />
              <span className="text-xs text-muted-fg">{t(`conn.cap_note_${p.id}_${c.id}`)}</span>
              <code className="ml-auto rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-fg">{c.scopes.join(", ")}</code>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-fg">{t("conn.login_scopes", { scopes: p.login_scopes.join(", ") })}</p>
      </Section>

      <Section title={t("conn.guide_title")}>
        <ol className="list-decimal space-y-1.5 pl-5 text-sm">
          {GUIDE[p.id]?.map((k) => <li key={k}>{t(k)}</li>)}
        </ol>
      </Section>
    </div>
  );
}

const GUIDE: Record<string, string[]> = {
  google: ["conn.g1", "conn.g2", "conn.g3", "conn.g4", "conn.g5"],
  kakao: ["conn.k1", "conn.k2", "conn.k3", "conn.k4", "conn.k5", "conn.k6", "conn.k7"],
};

/** 앱 키와 공급자마다 다른 칸. 비밀은 비워 두면 그대로 두고, [설정 확인]은 저장된 값으로 묻는다. */
function KeysSection({ p, onSaved }: { p: AdminConnection; onSaved: (next: AdminConnection) => void }) {
  const t = useT(); const locale = useLocale();
  const initial = useMemo(() => Object.fromEntries(p.fields.map((f) => [f.key, f.kind === "secret" ? "" : f.value ?? (f.kind === "bool" ? false : "")])),
    [p.fields]);
  const [vals, setVals] = useState<Record<string, string | boolean>>(initial);
  useEffect(() => { setVals(initial); }, [initial]);
  const [result, setResult] = useState<ConnectionCheck | null>(null);
  const dirty = p.fields.some((f) => (f.kind === "secret" ? !!vals[f.key] : vals[f.key] !== initial[f.key]));
  const save = useMutation({
    mutationFn: () => {
      const values: Record<string, string | boolean> = {};
      for (const f of p.fields) {
        if (f.kind === "secret") { if (vals[f.key]) values[f.key] = String(vals[f.key]); }
        else if (vals[f.key] !== initial[f.key]) values[f.key] = vals[f.key];
      }
      return Admin.saveConnection(p.id, { values });
    },
    onSuccess: (r) => { onSaved(r); setResult(null); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const clearSecret = useMutation({
    mutationFn: (key: string) => Admin.saveConnection(p.id, { clear: [key] }),
    onSuccess: (r) => { onSaved(r); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const check = useMutation({
    mutationFn: () => Admin.checkConnection(p.id),
    onSuccess: (r) => setResult(r),
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const text = p.fields.filter((f) => f.kind !== "bool");
  const bools = p.fields.filter((f) => f.kind === "bool");
  return (
    <Section title={t("conn.keys_title")} description={t(`conn.keys_desc_${p.id}`)}>
      <div className="grid gap-4 sm:grid-cols-2">
        {text.map((f) => (
          <Field key={f.key} htmlFor={`conn-${p.id}-${f.key}`} label={<>{t(`conn.f_${p.id}_${f.key}`)}{f.required ? null : <span className="ml-1 text-xs font-normal text-muted-fg">{t("common.optional")}</span>}</>}
            hint={f.kind === "secret"
              ? (f.has_value ? <span className="inline-flex flex-wrap items-center gap-2"><span className="text-success">{t("adm.secret_set")} ({fmtSecretTail(f.masked)})</span>
                  {!f.required || !p.enabled ? <button type="button" className="text-xs text-danger hover:underline" onClick={() => clearSecret.mutate(f.key)}>{t("conn.clear")}</button> : null}</span>
                : t(`conn.h_${p.id}_${f.key}`))
              : t(`conn.h_${p.id}_${f.key}`)}>
            <Input id={`conn-${p.id}-${f.key}`} type={f.kind === "secret" ? "password" : "text"} autoComplete="off" spellCheck={false}
              value={String(vals[f.key] ?? "")} placeholder={f.kind === "secret" && f.has_value ? "••••••••" : undefined}
              onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} />
          </Field>
        ))}
      </div>
      {bools.length ? (
        <div className="mt-3 divide-y divide-border rounded-xl border border-border px-3">
          {bools.map((f) => (
            <SwitchRow key={f.key} title={t(`conn.f_${p.id}_${f.key}`)} description={t(`conn.h_${p.id}_${f.key}`)}
              checked={!!vals[f.key]} onChange={(v) => setVals({ ...vals, [f.key]: v })} />
          ))}
        </div>
      ) : null}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button variant={dirty ? "accent" : "outline"} disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button>
        <Button variant="outline" disabled={dirty} loading={check.isPending} onClick={() => check.mutate()}><ShieldCheck className="h-4 w-4" />{t("conn.check")}</Button>
        {dirty ? <span className="text-xs text-warning">{t("conn.save_first")}</span> : null}
      </div>
      {result ? (
        <div className={`mt-3 flex items-start gap-2 rounded-xl border px-3 py-2 text-sm ${result.ok ? "border-success/40 bg-success/10 text-success" : "border-danger/40 bg-danger/10 text-danger"}`}>
          {result.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
          <div className="min-w-0">
            <div>{t(`conn.chk_${CHECK_CODES.includes(result.code) ? result.code : "other"}`)}</div>
            {!result.ok && result.detail ? <div className="mt-0.5 break-words text-xs opacity-80">{result.detail}</div> : null}
          </div>
        </div>
      ) : null}
    </Section>
  );
}

const CHECK_CODES = ["ok", "missing", "invalid_client", "invalid_secret", "redirect_uri", "login_disabled", "unreachable"];

function CopyRow({ label, value }: { label: string; value: string }) {
  const t = useT();
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border px-3 py-2">
      <span className="w-full text-xs text-muted-fg sm:w-44 sm:shrink-0">{label}</span>
      <code className="min-w-0 flex-1 break-all text-xs">{value}</code>
      <Button size="icon-sm" variant="ghost" aria-label={t("common.copy")}
        onClick={async () => { if (await copyText(value)) toast.success(t("common.copied")); }}><Copy className="h-4 w-4" /></Button>
    </div>
  );
}
