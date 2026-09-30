"use client";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, FlaskConical, History, RotateCcw, Trash2, Wand2 } from "@/components/icons";
import { Studio, type Agent, type Persona, type RelationshipParams, type StudioDraft, type StudioVerify } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtCredits, fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { SwitchRow } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/components/chat/Markdown";
import { confirm } from "@/lib/confirm";

export const REL_DEFAULTS: RelationshipParams = { pace: "normal", address_evolves: true, emotional_range: 0.5 };

export function draftOf(d: Agent): StudioDraft {
  return { name: d.name, role_line: d.role_line, persona: d.persona, custom_instructions: d.custom_instructions, language: d.language };
}

/* ── first meeting scene ─────────────────────────────────────────────────── */

export function FirstMeetingField({ value, onChange }: { value: Persona; onChange: (p: Persona) => void }) {
  const t = useT();
  const tpl = useQuery({ queryKey: ["studio", "first-meeting"], queryFn: Studio.firstMeetingTemplates, staleTime: 600_000 });
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {tpl.data?.items.map((x) => (
          <button key={x.id} type="button" onClick={() => onChange({ ...value, first_meeting: x.text })}
            className={cn("rounded-full border px-3 py-1.5 text-xs transition-colors", value.first_meeting === x.text ? "border-accent bg-accent/8 text-accent" : "border-border hover:bg-muted")}>{x.label}</button>
        ))}
      </div>
      <Textarea value={value.first_meeting ?? ""} maxLength={600} onChange={(e) => onChange({ ...value, first_meeting: e.target.value })} placeholder={t("studio.first_meeting_placeholder")} className="min-h-[88px]" />
      <div className="mt-1 text-right text-xs text-muted-fg">{(value.first_meeting ?? "").length}/600</div>
    </div>
  );
}

/* ── relationship parameters ─────────────────────────────────────────────── */

export function RelationshipSettings({ value, onChange, advanced }: { value: Persona; onChange: (p: Persona) => void; advanced: boolean }) {
  const t = useT();
  const r = { ...REL_DEFAULTS, ...(value.relationship ?? {}) } as Required<Omit<RelationshipParams, "pace">> & RelationshipParams;
  const set = (patch: Partial<RelationshipParams>) => onChange({ ...value, relationship: { ...r, ...patch } });
  return (
    <div className="space-y-4">
      {/* 관계가 자라는 빠르기는 여기서 정하지 않는다. 그 관계를 맺는 사람이 속도를 고를 수
          있으면 그건 관계가 아니라 설정이다 (plan/45 §0). 말투는 빚되 사이는 못 빚는다.

          먼저 말 걸기도 같은 이유로 여기서 사라졌다. 비서가 먼저 말을 건다는 것은
          제품의 리듬이고, 그 리듬은 관리자가 일괄로 정한다 (plan/54 §1). */}
      {advanced ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Slider label={t("studio.rel_emotional")} leftLabel={t("studio.rel_emotional_lo")} rightLabel={t("studio.rel_emotional_hi")} value={r.emotional_range} onChange={(v) => set({ emotional_range: v })} />
          <div className="sm:pt-6"><SwitchRow title={t("studio.rel_address")} description={t("studio.rel_address_desc")} checked={r.address_evolves} onChange={(v) => set({ address_evolves: v })} /></div>
        </div>
      ) : null}
    </div>
  );
}

/* ── personality verification ────────────────────────────────────────────── */

function Meter({ label, intended, perceived }: { label: string; intended: number | null | undefined; perceived: number | undefined }) {
  const i = typeof intended === "number" ? intended : null; const p = typeof perceived === "number" ? perceived : null;
  const gap = i !== null && p !== null ? Math.abs(i - p) : null;
  return (
    <div>
      <div className="flex items-center justify-between text-xs"><span>{label}</span>{gap !== null ? <span className={cn("tabular-nums", gap > 0.34 ? "text-danger" : gap > 0.2 ? "text-warning" : "text-success")}>Δ {Math.round(gap * 100)}</span> : null}</div>
      <div className="relative mt-1 h-2 rounded-full bg-muted">
        {i !== null ? <span className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 bg-fg" style={{ left: `${i * 100}%` }} title="intended" /> : null}
        {p !== null ? <span className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent" style={{ left: `${p * 100}%` }} title="perceived" /> : null}
      </div>
    </div>
  );
}

export function VerifyDialog({ agent, draft, open, onClose }: { agent: Agent; draft: StudioDraft; open: boolean; onClose: () => void }) {
  const t = useT(); const locale = useLocale();
  const [r, setR] = useState<StudioVerify | null>(null);
  const run = useMutation({ mutationFn: () => Studio.verify(agent.id, draft), onSuccess: setR, onError: (e) => toast.error(friendlyError(e, locale)) });
  useEffect(() => { if (open) { setR(null); run.mutate(); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const tone = r?.verdict === "consistent" ? "success" : r?.verdict === "drifting" ? "warning" : r?.verdict === "off" ? "danger" : "neutral";
  return (
    <Dialog open={open} onClose={onClose} title={<span className="inline-flex items-center gap-1.5"><FlaskConical className="h-4 w-4 text-accent" />{t("studio.verify")}</span>} description={t("studio.verify_desc")} size="lg"
      footer={<><Button variant="outline" onClick={onClose}>{t("common.close")}</Button><Button loading={run.isPending} onClick={() => run.mutate()}><RotateCcw className="h-4 w-4" />{t("studio.verify_again")}</Button></>}>
      {run.isPending ? <div className="space-y-3"><Skeleton className="h-16" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div> : r ? (
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-xl border border-border p-3">
            <Badge tone={tone}>{r.verdict ? t(`studio.verdict_${r.verdict}`) : "–"}</Badge>
            <p className="text-sm">{r.one_line || t("studio.verify_no_judge")}</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Meter label={t("persona.formality")} intended={r.intended.formality} perceived={r.perceived.formality} />
            <Meter label={t("persona.warmth")} intended={r.intended.warmth} perceived={r.perceived.warmth} />
            <Meter label={t("persona.humor")} intended={r.intended.humor} perceived={r.perceived.humor} />
            <Meter label={t("persona.verbosity")} intended={r.intended.verbosity} perceived={r.perceived.verbosity} />
          </div>
          <p className="text-[11px] text-muted-fg">{t("studio.meter_legend")}</p>
          {r.issues.length ? <ul className="list-disc space-y-1 pl-5 text-sm">{r.issues.map((x, i) => <li key={i}>{x}</li>)}</ul> : null}
          <div className="space-y-2">
            {r.probes.map((p) => (
              <details key={p.key} className="rounded-xl border border-border" open={p.key === "first"}>
                <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{t(`studio.probe_${p.key}`)} <span className="ml-1 text-xs font-normal text-muted-fg">— {p.question}</span></summary>
                <div className="px-3 pb-3"><Markdown text={p.answer} className="text-sm" /></div>
              </details>
            ))}
          </div>
          <div className="text-right text-[11px] text-muted-fg">{fmtCredits(r.credits)} cr</div>
        </div>
      ) : null}
    </Dialog>
  );
}

/* ── versions ────────────────────────────────────────────────────────────── */

export function VersionsSection({ agent }: { agent: Agent }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["versions", agent.id], queryFn: () => Studio.versions(agent.id) });
  const [editing, setEditing] = useState<{ id: string; label: string } | null>(null);
  const restore = useMutation({ mutationFn: (vid: string) => Studio.restoreVersion(agent.id, vid), onSuccess: (a) => { qc.setQueryData(["agents", agent.id], a); qc.invalidateQueries({ queryKey: ["agents"] }); qc.invalidateQueries({ queryKey: ["versions", agent.id] }); toast.success(t("studio.restored")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const label = useMutation({ mutationFn: (x: { id: string; label: string }) => Studio.labelVersion(agent.id, x.id, x.label), onSuccess: () => { qc.invalidateQueries({ queryKey: ["versions", agent.id] }); setEditing(null); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const del = useMutation({ mutationFn: (vid: string) => Studio.deleteVersion(agent.id, vid), onSuccess: () => qc.invalidateQueries({ queryKey: ["versions", agent.id] }), onError: (e) => toast.error(friendlyError(e, locale)) });
  if (q.isLoading) return <Skeleton className="h-20" />;
  const items = q.data?.items ?? [];
  if (!items.length) return <p className="text-sm text-muted-fg">{t("studio.versions_empty")}</p>;
  return (
    <ul className="divide-y divide-border">
      {items.map((v, i) => (
        <li key={v.id} className="flex flex-wrap items-center gap-2 py-2.5">
          <History className="h-4 w-4 shrink-0 text-muted-fg" />
          <div className="min-w-0 flex-1">
            {editing?.id === v.id ? (
              <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); label.mutate(editing); }}>
                <Input autoFocus value={editing.label} maxLength={80} onChange={(e) => setEditing({ id: v.id, label: e.target.value })} className="h-8" />
                <Button type="submit" size="sm" loading={label.isPending}><Check className="h-4 w-4" /></Button>
              </form>
            ) : (
              <button type="button" className="truncate text-left text-sm font-medium hover:underline" onClick={() => setEditing({ id: v.id, label: v.label })}>{v.label || t("studio.version_auto")}</button>
            )}
            <div className="truncate text-xs text-muted-fg">{fmtDateTime(v.created_at)} · {v.summary.name}{v.summary.preset ? ` · ${v.summary.preset}` : ""}{v.summary.role_line ? ` · ${v.summary.role_line}` : ""} · {t("studio.custom_len", { n: v.summary.custom_len })}</div>
          </div>
          {i === 0 ? <Badge tone="accent">{t("studio.version_latest")}</Badge> : null}
          <Button size="sm" variant="outline" loading={restore.isPending && restore.variables === v.id} onClick={async () => { if (await confirm({ title: t("studio.restore_confirm"), confirmLabel: t("common.restore") })) restore.mutate(v.id); }}><Wand2 className="h-3.5 w-3.5" />{t("common.restore")}</Button>
          <Button size="icon-sm" variant="ghost" aria-label={t("common.delete")} onClick={() => del.mutate(v.id)}><Trash2 className="h-4 w-4" /></Button>
        </li>
      ))}
    </ul>
  );
}
