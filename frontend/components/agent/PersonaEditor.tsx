"use client";
import { useQuery } from "@tanstack/react-query";
import { Check, Sparkles, X } from "@/components/icons";
import { Agents, type ModelInfo, type Persona } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Field, Input, Textarea } from "@/components/ui/input";
import { TagInput } from "@/components/ui/misc";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { fmtCredits } from "@/lib/format";

export function PersonaEditor({ value, onChange, advanced }: { value: Persona; onChange: (p: Persona) => void; advanced?: boolean }) {
  const t = useT();
  const presets = useQuery({ queryKey: ["personas"], queryFn: Agents.presets, staleTime: 600_000 });
  const set = (patch: Partial<Persona>) => onChange({ ...value, ...patch });
  return (
    <div className="space-y-5">
      <div>
        <div className="mb-2 text-sm font-medium">{t("persona.preset")}</div>
        {presets.isLoading ? <Skeleton className="h-24" /> : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {presets.data?.items.map((p) => (
              <button key={p.id} type="button" aria-pressed={value.preset === p.id}
                onClick={() => set({ preset: p.id, formality: p.formality, warmth: p.warmth, verbosity: p.verbosity, humor: p.humor, emoji: p.emoji, traits: p.traits })}
                className={cn("rounded-xl border p-3 text-left transition-colors min-h-[64px]", value.preset === p.id ? "border-accent bg-accent/8" : "border-border hover:bg-muted")}>
                <div className="flex items-center justify-between text-sm font-medium">{p.label}{value.preset === p.id ? <Check className="h-4 w-4 text-accent" /> : null}</div>
                <div className="mt-0.5 text-xs text-muted-fg">{p.description}</div>
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Slider label={t("persona.formality")} leftLabel={t("persona.formality_lo")} rightLabel={t("persona.formality_hi")} value={value.formality ?? 0.5} onChange={(v) => set({ formality: v })} />
        <Slider label={t("persona.warmth")} leftLabel={t("persona.warmth_lo")} rightLabel={t("persona.warmth_hi")} value={value.warmth ?? 0.5} onChange={(v) => set({ warmth: v })} />
        <Slider label={t("persona.verbosity")} leftLabel={t("persona.verbosity_lo")} rightLabel={t("persona.verbosity_hi")} value={value.verbosity ?? 0.5} onChange={(v) => set({ verbosity: v })} />
        {advanced ? <Slider label={t("persona.humor")} leftLabel={t("persona.humor_lo")} rightLabel={t("persona.humor_hi")} value={value.humor ?? 0.2} onChange={(v) => set({ humor: v })} /> : null}
      </div>
      <div className="flex items-center justify-between rounded-xl border border-border px-4 py-3">
        <div><div className="text-sm font-medium">{t("persona.emoji")}</div><div className="text-xs text-muted-fg">{t("persona.emoji_desc")}</div></div>
        <Switch checked={!!value.emoji} onChange={(v) => set({ emoji: v })} label={t("persona.emoji")} />
      </div>
      {advanced ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("persona.self_reference")}><Input value={value.self_reference ?? ""} onChange={(e) => set({ self_reference: e.target.value })} placeholder="저" /></Field>
          <Field label={t("persona.address_owner_as")}><Input value={value.address_owner_as ?? ""} onChange={(e) => set({ address_owner_as: e.target.value })} placeholder="OO님" /></Field>
          <Field label={t("persona.traits")} className="sm:col-span-2"><TagInput value={value.traits ?? []} onChange={(v) => set({ traits: v })} placeholder={t("persona.traits_placeholder")} /></Field>
          <Field label={t("persona.catchphrases")} className="sm:col-span-2"><TagInput value={value.catchphrases ?? []} onChange={(v) => set({ catchphrases: v })} placeholder={t("persona.catchphrases_placeholder")} /></Field>
          <Field label={t("persona.extra")} hint={t("persona.extra_hint")} className="sm:col-span-2"><Textarea maxLength={600} value={value.extra ?? ""} onChange={(e) => set({ extra: e.target.value })} /></Field>
          <Field label={t("persona.taboo")} hint={t("persona.taboo_hint")} className="sm:col-span-2"><TagInput value={value.taboo ?? []} onChange={(v) => set({ taboo: v.slice(0, 10) })} placeholder={t("persona.taboo_placeholder")} /></Field>
          <div className="sm:col-span-2">
            <div className="mb-1 flex items-center justify-between"><span className="text-sm font-medium">{t("persona.examples")}</span>{(value.examples ?? []).length < 4 ? <button type="button" className="text-xs text-accent" onClick={() => set({ examples: [...(value.examples ?? []), { user: "", assistant: "" }] })}>+ {t("common.add")}</button> : null}</div>
            <p className="mb-2 text-xs text-muted-fg">{t("persona.examples_hint")}</p>
            <div className="space-y-2">
              {(value.examples ?? []).map((ex, i) => (
                <div key={i} className="grid gap-2 rounded-xl border border-border p-2.5 sm:grid-cols-2">
                  <Textarea maxLength={300} value={ex.user} placeholder={t("persona.example_user")} onChange={(e) => set({ examples: (value.examples ?? []).map((x, j) => (j === i ? { ...x, user: e.target.value } : x)) })} className="min-h-[56px]" />
                  <div className="flex gap-2">
                    <Textarea maxLength={300} value={ex.assistant} placeholder={t("persona.example_assistant")} onChange={(e) => set({ examples: (value.examples ?? []).map((x, j) => (j === i ? { ...x, assistant: e.target.value } : x)) })} className="min-h-[56px] flex-1" />
                    <button type="button" aria-label={t("common.delete")} className="self-start rounded-lg p-1.5 text-muted-fg hover:bg-muted" onClick={() => set({ examples: (value.examples ?? []).filter((_, j) => j !== i) })}><X className="h-4 w-4" /></button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function ModelPicker({ value, onChange, models, loading }: { value: { provider: string; model_id: string } | null; onChange: (v: { provider: string; model_id: string }) => void; models: ModelInfo[]; loading?: boolean }) {
  const t = useT();
  if (loading) return <Skeleton className="h-40" />;
  if (!models.length) return <p className="text-sm text-muted-fg">{t("model.none")}</p>;
  return (
    <div className="space-y-2" role="radiogroup" aria-label={t("model.title")}>
      {models.map((m) => {
        const sel = value?.provider === m.provider && value?.model_id === m.model_id;
        return (
          <button key={`${m.provider}/${m.model_id}`} type="button" role="radio" aria-checked={sel} onClick={() => onChange({ provider: m.provider, model_id: m.model_id })}
            className={cn("flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-colors", sel ? "border-accent bg-accent/8" : "border-border hover:bg-muted")}>
            <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded-full border", sel ? "border-accent bg-accent text-accent-fg" : "border-border")}>{sel ? <Check className="h-3 w-3" /> : null}</span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-1.5 text-sm font-medium">{m.display_name}
                {m.is_default ? <Badge tone="accent"><Sparkles className="h-3 w-3" />{t("model.recommended")}</Badge> : null}
                {m.supports_thinking ? <Badge>{t("model.thinking")}</Badge> : null}
                {m.supports_vision ? <Badge>{t("model.vision")}</Badge> : null}
              </div>
              <div className="text-xs text-muted-fg">{m.provider} · {m.model_id} · {Math.round(m.context_window / 1000)}k ctx</div>
            </div>
            <div className="text-right text-xs text-muted-fg shrink-0">
              <div>{t("model.price_in", { n: fmtCredits(m.credit_per_1k_input) })}</div>
              <div>{t("model.price_out", { n: fmtCredits(m.credit_per_1k_output) })}</div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
