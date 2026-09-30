"use client";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, RefreshCw } from "@/components/icons";
import { Admin } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { CUSTOM_MODEL, EMBEDDING_MODELS, EMBEDDING_PROVIDERS, findModel } from "@/lib/embeddingModels";
import { useAdminSettings } from "./common";
import { Page } from "@/components/owner/Shell";
import { Section } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/misc";
import { confirm } from "@/lib/confirm";

/** The embedding settings are a matched set: a model name only works with the dimension it
 *  produces, and a mismatch is not rejected on save — it fails later, per document, as
 *  vectors the column will not take. So the model is picked from a list and the dimension
 *  follows it, with free text kept for models we do not know yet. */
export function EmbeddingPage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useAdminSettings("embedding.");
  const saved = q.data ?? {};

  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [customModel, setCustomModel] = useState("");
  const [dim, setDim] = useState("");
  const [credit, setCredit] = useState("");

  useEffect(() => {
    if (!q.data) return;
    const p = String(q.data["embedding.provider"] ?? "openai");
    const m = String(q.data["embedding.model"] ?? "");
    setProvider(p);
    const known = findModel(p, m);
    setModel(known ? m : m ? CUSTOM_MODEL : "");
    setCustomModel(known ? "" : m);
    setDim(String(q.data["embedding.dim"] ?? ""));
    setCredit(String(q.data["embedding.credit_per_1k"] ?? ""));
  }, [q.data]);

  const known = model === CUSTOM_MODEL ? undefined : findModel(provider, model);
  const modelName = model === CUSTOM_MODEL ? customModel.trim() : model;

  const pickProvider = (p: string) => {
    setProvider(p);
    const first = EMBEDDING_MODELS[p]?.[0];
    if (first) { setModel(first.id); setDim(String(first.dims[0])); }
    else { setModel(CUSTOM_MODEL); }
  };
  const pickModel = (id: string) => {
    setModel(id);
    const m = findModel(provider, id);
    if (m) setDim(String(m.dims[0]));
  };

  const dirty = useMemo(() => (
    provider !== String(saved["embedding.provider"] ?? "") ||
    modelName !== String(saved["embedding.model"] ?? "") ||
    dim !== String(saved["embedding.dim"] ?? "") ||
    credit !== String(saved["embedding.credit_per_1k"] ?? "")
  ), [provider, modelName, dim, credit, saved]);
  // Changing what a vector means invalidates every vector already stored.
  const reindexNeeded = provider !== String(saved["embedding.provider"] ?? "") ||
    modelName !== String(saved["embedding.model"] ?? "") || dim !== String(saved["embedding.dim"] ?? "");

  const save = useMutation({
    mutationFn: () => Admin.putSettings({
      "embedding.provider": provider, "embedding.model": modelName,
      "embedding.dim": Number(dim), "embedding.credit_per_1k": Number(credit),
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin", "settings"] }); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const re = useMutation({
    mutationFn: Admin.reindex,
    onSuccess: (r) => toast.success(t("adm.reindex_queued", { n: r.queued })),
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  const models = EMBEDDING_MODELS[provider] ?? [];
  return (
    <Page>
      <PageHeader title={t("adm.embedding")} description={t("adm.embedding_desc")} />
      <Section title={t("adm.embedding")}>
        {q.isLoading ? <Skeleton className="h-40" /> : (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t("adm.emb_provider")}>
                <Select value={provider} onChange={(e) => pickProvider(e.target.value)}>
                  {EMBEDDING_PROVIDERS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                </Select>
              </Field>
              <Field label={t("adm.emb_model")} hint={known ? t("adm.emb_model_known") : t("adm.emb_model_custom_hint")}>
                <Select value={model} onChange={(e) => pickModel(e.target.value)}>
                  {models.map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
                  <option value={CUSTOM_MODEL}>{t("adm.emb_model_custom")}</option>
                </Select>
              </Field>
              {model === CUSTOM_MODEL ? (
                <Field label={t("adm.emb_model_name")} className="sm:col-span-2">
                  <Input value={customModel} onChange={(e) => setCustomModel(e.target.value)} placeholder="text-embedding-3-small" />
                </Field>
              ) : null}
              <Field label={t("adm.emb_dim")} hint={known ? t("adm.emb_dim_auto") : t("adm.emb_dim_hint")}>
                {known ? (
                  <Select value={dim} onChange={(e) => setDim(e.target.value)}>
                    {known.dims.map((d, i) => <option key={d} value={String(d)}>{d}{i === 0 ? ` · ${t("adm.emb_dim_native")}` : ""}</option>)}
                  </Select>
                ) : (
                  <Input type="number" value={dim} onChange={(e) => setDim(e.target.value)} placeholder="1536" />
                )}
              </Field>
              <Field label={t("adm.emb_credit")}>
                <Input type="number" step="0.001" value={credit} onChange={(e) => setCredit(e.target.value)} />
              </Field>
            </div>
            {dirty && reindexNeeded ? (
              <p className="flex items-start gap-2 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{t("adm.emb_reindex_warn")}
              </p>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
              <Button variant={dirty ? "accent" : "outline"} disabled={!dirty || !modelName || !dim} loading={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button>
              <Button variant="outline" loading={re.isPending} onClick={async () => { if (await confirm({ title: t("adm.reindex_confirm"), confirmLabel: t("common.confirm") })) re.mutate(); }}>
                <RefreshCw className="h-4 w-4" />{t("adm.reindex")}
              </Button>
            </div>
          </div>
        )}
      </Section>
    </Page>
  );
}
