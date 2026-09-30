"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Download, Plus, Sparkles, Trash2 } from "@/components/icons";
import { Admin } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { Page } from "@/components/owner/Shell";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Checkbox } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Dialog } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { PageHeader } from "@/components/ui/misc";
import { confirm } from "@/lib/confirm";

const PROVIDERS = ["claude_code", "anthropic", "openai", "gemini"];
const EMPTY = { provider: "claude_code", model_id: "", display_name: "", cli_alias: "", context_window: 200000, max_output: 8192, supports_thinking: false, supports_vision: true, credit_per_1k_input: 0, credit_per_1k_output: 0, credit_per_1k_cache_read: 0, enabled: true, is_default: false, sort_order: 100 };

/** Module scope on purpose: declared inside the page this was a new component type on
 *  every render, so a background refetch mid-edit would remount the cell and discard
 *  what was being typed (the same defect that cost the profile form its cursor). */
function NumCell({ m, k, onPatch }: { m: any; k: string; onPatch: (id: string, b: Record<string, unknown>) => void }) {
  return <Input type="number" step="any" className="h-8 w-24 px-2 text-xs" defaultValue={m[k]}
    onBlur={(e) => { const v = Number(e.target.value); if (v !== m[k]) onPatch(m.id, { [k]: v }); }} />;
}

export function ModelsPage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "models"], queryFn: Admin.models });
  const [add, setAdd] = useState<typeof EMPTY | null>(null);
  const [discProv, setDiscProv] = useState("claude_code"); const [disc, setDisc] = useState<string[] | null>(null); const [discAliases, setDiscAliases] = useState<string[]>([]); const [discNote, setDiscNote] = useState("");
  const inval = () => { qc.invalidateQueries({ queryKey: ["admin", "models"] }); qc.invalidateQueries({ queryKey: ["models"] }); };
  const patch = useMutation({ mutationFn: (x: { id: string; b: Record<string, unknown> }) => Admin.patchModel(x.id, x.b), onSuccess: inval, onError: (e) => toast.error(friendlyError(e, locale)) });
  const del = useMutation({ mutationFn: (id: string) => Admin.deleteModel(id), onSuccess: inval });
  const seed = useMutation({ mutationFn: (ow: boolean) => Admin.seedModels(ow), onSuccess: (r) => {
    inval();
    const extra = [r.alias_repaired ? t("adm.seed_alias_fixed", { n: r.alias_repaired }) : "", r.default_moved ? t("adm.seed_default_moved", { m: r.default_moved }) : ""].filter(Boolean).join(" · ");
    toast.success(extra ? `${t("adm.seeded", { n: r.added })} · ${extra}` : t("adm.seeded", { n: r.added }));
  }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const discover = useMutation({ mutationFn: () => Admin.discover(discProv), onSuccess: (r) => { setDisc(r.items); setDiscAliases(r.aliases ?? []); setDiscNote(r.note ?? ""); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const create = useMutation({ mutationFn: (b: Record<string, unknown>) => Admin.createModel(b), onSuccess: () => { inval(); setAdd(null); toast.success(t("common.saved")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const items = q.data?.items ?? [];
  return (
    <Page full>
      <PageHeader title={t("adm.models")} description={`${t("adm.models_desc")} ${t("adm.model_pool_hint")}`} action={<>
        <Button variant="outline" loading={seed.isPending} onClick={() => seed.mutate(false)}><Sparkles className="h-4 w-4" />{t("adm.seed")}</Button>
        <Button onClick={() => setAdd({ ...EMPTY })}><Plus className="h-4 w-4" />{t("adm.add_model")}</Button>
      </>} />
      {/* A toolbar strip across the top of the table: an icon tile, what this does and
          what it will do, then the controls at the right edge. Everything on one baseline
          at one height — the version before this stacked a tiny label above the select,
          which pushed it off the row and left the middle of the card empty. */}
      <section className="mb-4 rounded-2xl border border-border bg-card px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-3">
          {/* 44px, the height these controls actually are: the select is a component with
              its own CSS, so asking for h-9 shrank nothing and only broke the row. */}
          <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-fg">
            <Download className="h-4 w-4" />
          </span>
          <div className="min-w-[12rem] flex-1">
            <h2 className="text-sm font-medium leading-5">{t("adm.discover")}</h2>
            <p className="truncate text-xs leading-4 text-muted-fg">{discNote || t("adm.discover_desc")}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Select value={discProv} onChange={(e) => { setDiscProv(e.target.value); setDisc(null); }} className="w-40" aria-label={t("adm.provider_pick")}>
              {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </Select>
            <Button variant="outline" className="shrink-0" loading={discover.isPending} onClick={() => discover.mutate()}>{t("adm.discover_run")}</Button>
          </div>
        </div>
        {disc ? (
          <div className="mt-3 space-y-3 border-t border-border pt-3">
            {disc.length ? (
              <div>
                <p className="mb-1.5 text-xs text-muted-fg">{t("adm.discover_found", { n: disc.length })}</p>
                <div className="flex flex-wrap gap-1.5">{disc.map((id) => {
                  const exists = items.some((m) => m.model_id === id && m.provider === discProv);
                  return <button key={id} type="button" disabled={exists} onClick={() => setAdd({ ...EMPTY, provider: discProv, model_id: id, display_name: id })}
                    className="rounded-full border border-border px-2.5 py-1 font-mono text-xs hover:border-accent hover:text-accent disabled:opacity-40 disabled:hover:border-border disabled:hover:text-fg">{id}{exists ? " ✓" : ""}</button>;
                })}</div>
              </div>
            ) : <p className="text-xs text-muted-fg">{t("adm.discover_none")}</p>}
            {/* An alias is not another model — it is "whatever the newest one of that line is",
                resolved by the CLI at launch, so it keeps working across releases. */}
            {discAliases.length ? (
              <div>
                <p className="mb-1.5 text-xs text-muted-fg">{t("adm.discover_aliases")}</p>
                <div className="flex flex-wrap gap-1.5">{discAliases.map((a) => {
                  const exists = items.some((m) => m.model_id === a && m.provider === discProv);
                  return <button key={a} type="button" disabled={exists} onClick={() => setAdd({ ...EMPTY, provider: discProv, model_id: a, cli_alias: a, display_name: `${a} — ${t("adm.latest")}` })}
                    className="rounded-full border border-accent/50 bg-accent/10 px-2.5 py-1 font-mono text-xs text-accent hover:bg-accent/20 disabled:opacity-40">{a}{exists ? " ✓" : ""}</button>;
                })}</div>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
      {q.isLoading ? <Skeleton className="h-60" /> : (
        <Table>
          <THead><tr><TH>{t("adm.m_provider")}</TH><TH>{t("adm.m_model")}</TH><TH>{t("adm.m_display")}</TH><TH>{t("adm.col_ctx")}</TH><TH>{t("adm.col_in")}</TH><TH>{t("adm.col_out")}</TH><TH>{t("adm.col_cache")}</TH><TH>{t("adm.col_think")}</TH><TH>{t("adm.col_vision")}</TH><TH>{t("adm.model_pool")}</TH><TH>{t("adm.m_default")}</TH><TH>{t("adm.col_sort")}</TH><TH></TH></tr></THead>
          <TBody>{items.map((m) => (
            <TR key={m.id}>
              <TD><Badge tone="outline">{m.provider}</Badge></TD>
              <TD className="whitespace-nowrap font-mono text-xs">{m.model_id}{m.cli_alias ? <div className="text-muted-fg">alias: {m.cli_alias}</div> : null}</TD>
              <TD><Input className="h-8 w-44 px-2 text-xs" defaultValue={m.display_name} onBlur={(e) => e.target.value !== m.display_name && patch.mutate({ id: m.id, b: { display_name: e.target.value } })} /></TD>
              <TD className="text-xs tabular-nums">{Math.round(m.context_window / 1000)}k</TD>
              <TD><NumCell onPatch={(id, b) => patch.mutate({ id, b })} m={m} k="credit_per_1k_input" /></TD><TD><NumCell onPatch={(id, b) => patch.mutate({ id, b })} m={m} k="credit_per_1k_output" /></TD><TD><NumCell onPatch={(id, b) => patch.mutate({ id, b })} m={m} k="credit_per_1k_cache_read" /></TD>
              <TD><Checkbox checked={m.supports_thinking} onChange={(v) => patch.mutate({ id: m.id, b: { supports_thinking: v } })} /></TD>
              <TD><Checkbox checked={m.supports_vision} onChange={(v) => patch.mutate({ id: m.id, b: { supports_vision: v } })} /></TD>
              <TD><Switch checked={m.enabled} onChange={(v) => patch.mutate({ id: m.id, b: { enabled: v } })} aria-label={t("adm.model_pool")} /></TD>
              <TD><input type="radio" name="default-model" checked={m.is_default} onChange={() => patch.mutate({ id: m.id, b: { is_default: true } })} aria-label={t("adm.m_default")} className="h-4 w-4 accent-[var(--accent)]" /></TD>
              <TD><NumCell onPatch={(id, b) => patch.mutate({ id, b })} m={m} k="sort_order" /></TD>
              <TD><Button size="icon-sm" variant="ghost" className="text-danger" aria-label={t("common.delete")} onClick={async () => { if (await confirm({ title: t("common.confirm_delete"), danger: true, confirmLabel: t("common.delete") })) del.mutate(m.id); }}><Trash2 className="h-4 w-4" /></Button></TD>
            </TR>
          ))}</TBody>
        </Table>
      )}
      <Dialog open={!!add} onClose={() => setAdd(null)} title={t("adm.add_model")} footer={<><Button variant="outline" onClick={() => setAdd(null)}>{t("common.cancel")}</Button><Button loading={create.isPending} disabled={!add?.model_id || !add?.display_name} onClick={() => add && create.mutate({ ...add, cli_alias: add.cli_alias || null })}>{t("common.add")}</Button></>}>
        {add ? <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("adm.m_provider")}><Select value={add.provider} onChange={(e) => setAdd({ ...add, provider: e.target.value })}>{PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}</Select></Field>
          <Field label={t("adm.m_model")}><Input value={add.model_id} onChange={(e) => setAdd({ ...add, model_id: e.target.value })} /></Field>
          <Field label={t("adm.m_display")}><Input value={add.display_name} onChange={(e) => setAdd({ ...add, display_name: e.target.value })} /></Field>
          <Field label={t("adm.m_alias")} hint={t("common.optional")}><Input value={add.cli_alias} onChange={(e) => setAdd({ ...add, cli_alias: e.target.value })} /></Field>
          <Field label={t("adm.m_ctx_window")}><Input type="number" value={add.context_window} onChange={(e) => setAdd({ ...add, context_window: Number(e.target.value) })} /></Field>
          <Field label={t("adm.m_max_output")}><Input type="number" value={add.max_output} onChange={(e) => setAdd({ ...add, max_output: Number(e.target.value) })} /></Field>
          <Field label={t("adm.m_credit_in")}><Input type="number" step="any" value={add.credit_per_1k_input} onChange={(e) => setAdd({ ...add, credit_per_1k_input: Number(e.target.value) })} /></Field>
          <Field label={t("adm.m_credit_out")}><Input type="number" step="any" value={add.credit_per_1k_output} onChange={(e) => setAdd({ ...add, credit_per_1k_output: Number(e.target.value) })} /></Field>
          <Field label={t("adm.m_credit_cache")}><Input type="number" step="any" value={add.credit_per_1k_cache_read} onChange={(e) => setAdd({ ...add, credit_per_1k_cache_read: Number(e.target.value) })} /></Field>
          <Field label={t("adm.col_sort")}><Input type="number" value={add.sort_order} onChange={(e) => setAdd({ ...add, sort_order: Number(e.target.value) })} /></Field>
          <div className="flex flex-wrap gap-4 sm:col-span-2"><Checkbox checked={add.supports_thinking} onChange={(v) => setAdd({ ...add, supports_thinking: v })} label={t("adm.m_think")} /><Checkbox checked={add.supports_vision} onChange={(v) => setAdd({ ...add, supports_vision: v })} label={t("adm.m_vision")} /><Checkbox checked={add.enabled} onChange={(v) => setAdd({ ...add, enabled: v })} label={t("adm.model_pool")} /><Checkbox checked={add.is_default} onChange={(v) => setAdd({ ...add, is_default: v })} label={t("adm.m_default")} /></div>
        </div> : null}
      </Dialog>
    </Page>
  );
}
