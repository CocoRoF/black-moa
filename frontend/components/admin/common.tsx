"use client";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { fmtSecretTail } from "@/lib/format";
import { Admin } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Section } from "@/components/ui/card";

export interface SettingField { key: string; label: string; type: "text" | "secret" | "number" | "bool" | "select" | "textarea" | "json"; options?: { value: string; label: string }[]; hint?: string; placeholder?: string;
  /** 이 칸이 뜻이 있을 때만 보인다(예: 기능을 끄면 그 기능의 세부 설정은 접힌다). 지금 폼의 값으로 판단한다. */
  showIf?: (vals: Record<string, any>) => boolean }
type SecretView = { has_value: boolean; masked: string };

export function useAdminSettings(prefix = "") {
  return useQuery({ queryKey: ["admin", "settings", prefix], queryFn: () => Admin.settings(prefix) });
}

/** Generic settings editor over GET/PUT /api/admin/settings. Sends only changed keys; secrets only when non-empty. */
export function SettingsForm({ title, description, fields, prefix, extra, onSaved }: { title: ReactNode; description?: ReactNode; fields: SettingField[]; prefix?: string; extra?: ReactNode; onSaved?: () => void }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useAdminSettings(prefix ?? "");
  const [vals, setVals] = useState<Record<string, any>>({});
  useEffect(() => {
    if (!q.data) return;
    const v: Record<string, any> = {};
    for (const f of fields) { const raw = q.data[f.key]; v[f.key] = f.type === "secret" ? "" : f.type === "json" ? JSON.stringify(raw ?? {}, null, 2) : raw ?? (f.type === "bool" ? false : ""); }
    setVals(v);
  }, [q.data, fields]);
  const dirty = useMemo(() => fields.filter((f) => { if (!q.data) return false; const raw = q.data[f.key]; if (f.type === "secret") return !!vals[f.key]; if (f.type === "json") return vals[f.key] !== JSON.stringify(raw ?? {}, null, 2); return String(vals[f.key] ?? "") !== String(raw ?? ""); }), [fields, vals, q.data]);
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {};
      for (const f of dirty) { const v = vals[f.key]; body[f.key] = f.type === "number" ? Number(v) : f.type === "json" ? JSON.parse(v || "{}") : v; }
      return Admin.putSettings(body);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin", "settings"] }); qc.invalidateQueries({ queryKey: ["auth-status"] }); toast.success(t("common.saved")); onSaved?.(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const clear = useMutation({ mutationFn: (k: string) => Admin.clearSetting(k), onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin", "settings"] }); toast.success(t("common.saved")); } });
  return (
    <Section title={title} description={description}>
      {q.isLoading ? <Skeleton className="h-40" /> : (
        <div className="grid gap-4 sm:grid-cols-2">
          {fields.map((f) => {
            if (f.showIf && !f.showIf(vals)) return null;
            const raw = q.data?.[f.key];
            const v = vals[f.key];
            if (f.type === "bool") return <div key={f.key} className="flex items-center justify-between rounded-xl border border-border px-3 py-2.5 sm:col-span-2"><div><div className="text-sm font-medium">{f.label}</div>{f.hint ? <div className="text-xs text-muted-fg">{f.hint}</div> : null}</div><Switch checked={!!v} onChange={(x) => setVals({ ...vals, [f.key]: x })} label={f.label} /></div>;
            if (f.type === "secret") { const sv = raw as SecretView | undefined; return <Field key={f.key} label={f.label} hint={<span>{sv?.has_value ? <span className="text-success">{t("adm.secret_set")} ({fmtSecretTail(sv.masked)})</span> : t("adm.secret_unset")}{sv?.has_value ? <button type="button" className="ml-2 underline" onClick={() => clear.mutate(f.key)}>{t("adm.clear")}</button> : null}{f.hint ? ` · ${f.hint}` : ""}</span>}><Input type="password" autoComplete="off" value={v ?? ""} placeholder={sv?.has_value ? "••••••••" : f.placeholder} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} /></Field>; }
            if (f.type === "select") return <Field key={f.key} label={f.label} hint={f.hint}><Select value={v ?? ""} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })}>{f.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</Select></Field>;
            if (f.type === "textarea" || f.type === "json") return <Field key={f.key} label={f.label} hint={f.hint} className="sm:col-span-2"><Textarea value={v ?? ""} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} className={f.type === "json" ? "font-mono text-xs min-h-[120px]" : "min-h-[160px]"} /></Field>;
            return <Field key={f.key} label={f.label} hint={f.hint}><Input type={f.type === "number" ? "number" : "text"} step="any" value={v ?? ""} placeholder={f.placeholder} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} /></Field>;
          })}
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button loading={save.isPending} disabled={!dirty.length} onClick={() => save.mutate()}>{t("common.save")}</Button>
        {dirty.length ? <span className="text-xs text-muted-fg">{t("set.unsaved", { n: dirty.length })}</span> : null}
        {extra}
      </div>
    </Section>
  );
}

export function JsonBlock({ data }: { data: unknown }) {
  return <pre className="max-h-96 overflow-auto rounded-xl bg-muted p-3 font-mono text-[11px] leading-relaxed">{JSON.stringify(data, null, 2)}</pre>;
}
