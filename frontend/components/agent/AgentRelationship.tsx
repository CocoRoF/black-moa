"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BookOpen, Brain, Flame, MessageSquare, Send, Sparkles, Trophy, Trash2 } from "@/components/icons";
import { Agents, Relationships, type JournalEntry, type ProactiveStatus, type Relationship, type RelationshipStage } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtDate, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { useAgent } from "./AgentLayout";
import { FactStatement } from "@/components/chat/FactStatement";
import { Button, buttonLook } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Segmented } from "@/components/ui/tabs";
import { Select } from "@/components/ui/input";
import { Avatar } from "@/components/ui/misc";
import { confirm } from "@/lib/confirm";

const STAGE_TONE: Record<RelationshipStage, string> = { new: "text-muted-fg", familiar: "text-accent", trusted: "text-success", companion: "text-warning" };

/** The ring that says how far the pair has come — one arc, no dashboard. */
export function StageRing({ score, stage, size = 128, children }: { score: number; stage: RelationshipStage; size?: number; children?: React.ReactNode }) {
  const r = (size - 12) / 2; const c = 2 * Math.PI * r;
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={6} className="text-border" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={6} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - Math.max(0.01, Math.min(1, score)))} className={cn("transition-[stroke-dashoffset] duration-700", STAGE_TONE[stage])} />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">{children}</div>
    </div>
  );
}

export function AgentRelationship() {
  const t = useT(); const locale = useLocale(); const a = useAgent(); const qc = useQueryClient();
  const rel = useQuery({ queryKey: ["relationship", a.id], queryFn: () => Relationships.get(a.id) });
  const journal = useQuery({ queryKey: ["relationship", a.id, "journal"], queryFn: () => Relationships.journal(a.id) });
  const [filter, setFilter] = useState<"all" | "post" | "fact" | "note" | "milestone">("all");
  // "Say something now": the job id we are watching, and where it is (queued → writing → sent/skipped).
  const [job, setJob] = useState<{ id: string; phase: ProactiveStatus["phase"]; elapsed: number } | null>(null);
  const jobStart = useRef<number>(0);
  const say = useMutation({
    mutationFn: () => Relationships.sayNow(a.id),
    onSuccess: (r) => { if (r.job_id) { jobStart.current = Date.now(); setJob({ id: r.job_id, phase: "queued", elapsed: 0 }); } },
    onError: (e: any) => {
      if (e?.code === "too_soon") { toast(t("rel.gate_toast")); qc.invalidateQueries({ queryKey: ["relationship", a.id] }); }
      else toast.error(friendlyError(e, locale));
    },
  });
  useEffect(() => {
    if (!job || job.phase === "sent" || job.phase === "skipped" || job.phase === "failed") return;
    const id = window.setInterval(async () => {
      try {
        const st = await Relationships.proactiveStatus(a.id, job.id);
        setJob({ id: job.id, phase: st.phase, elapsed: st.elapsed_s });
        if (st.phase === "sent") {
          toast.success(t("rel.say_arrived"));
          qc.invalidateQueries({ queryKey: ["conversations", a.id] }); qc.invalidateQueries({ queryKey: ["relationship", a.id] });
        } else if (st.phase === "skipped") {
          toast(t(`rel.skip_${st.skipped ?? "nothing_to_say"}`) === `rel.skip_${st.skipped}` ? t("rel.skip_nothing_to_say") : t(`rel.skip_${st.skipped ?? "nothing_to_say"}`));
          qc.invalidateQueries({ queryKey: ["relationship", a.id] });
        } else if (st.phase === "failed") {
          toast.error(st.error || t("rel.say_failed"));
        }
      } catch { /* transient; keep polling */ }
      if (Date.now() - jobStart.current > 180_000) { setJob(null); toast(t("rel.say_slow")); }
    }, 3000);
    return () => window.clearInterval(id);
  }, [job, a.id, qc, t]);
  // The quiet window counts down on screen without a refetch.
  const [, tick] = useState(0);
  useEffect(() => { const id = window.setInterval(() => tick((n) => n + 1), 30_000); return () => window.clearInterval(id); }, []);
  const mood = useMutation({
    mutationFn: (state: string) => Relationships.patch(a.id, { mood: { state, reason: "", hours: 24 } }),
    onSuccess: (r) => { qc.setQueryData(["relationship", a.id], r); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const patchFact = useMutation({ mutationFn: (id: string) => Agents.patchFact(id, { status: "rejected" }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["relationship", a.id] }); qc.invalidateQueries({ queryKey: ["facts", a.id] }); toast.success(t("rel.forgot")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const delNote = useMutation({ mutationFn: (e: { id: string; ns: string }) => Agents.deleteNote(a.id, e.ns, e.id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["relationship", a.id] }); qc.invalidateQueries({ queryKey: ["memory", a.id] }); }, onError: (e) => toast.error(friendlyError(e, locale)) });

  const items = useMemo(() => (journal.data?.items ?? []).filter((e) => filter === "all" || e.type === filter), [journal.data, filter]);
  const r = rel.data;

  if (rel.isLoading || !r) return <Page><Skeleton className="h-40" /><Skeleton className="mt-4 h-60" /></Page>;
  const p = r.progress;

  return (
    <Page>
      <div className="grid gap-4 lg:grid-cols-3">
        {/* ── who we are to each other ── */}
        <Card className="lg:col-span-2">
          <CardBody className="pt-5">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
              <StageRing score={r.score} stage={r.stage} size={136}>
                <Avatar mascot name={a.name} src={a.avatar_url} size={92} accent={a.theme?.accent} shape={a.theme?.avatar_shape} />
              </StageRing>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-xl font-semibold">{r.started_at ? t("rel.title_days", { name: a.name, n: r.days_together }) : t("rel.title_new", { name: a.name })}</h1>
                  <Badge tone={r.stage === "new" ? "neutral" : r.stage === "familiar" ? "accent" : r.stage === "trusted" ? "success" : "warning"}>{t(`rel.stage_${r.stage}`)}</Badge>
                </div>
                <p className="mt-1 text-sm text-muted-fg">{t(`rel.stage_desc_${r.stage}`)}</p>
                <ol className="mt-3 flex items-center gap-1.5" aria-label={t("rel.stages")}>
                  {r.stages.map((s, i) => (
                    <li key={s} className="flex items-center gap-1.5">
                      <span className={cn("rounded-full px-2.5 py-1 text-xs font-medium", i <= r.stage_index ? "bg-fg text-bg" : "bg-muted text-muted-fg")}>{t(`rel.stage_${s}`)}</span>
                      {i < r.stages.length - 1 ? <span className={cn("h-px w-4", i < r.stage_index ? "bg-fg" : "bg-border")} /> : null}
                    </li>
                  ))}
                </ol>
                {/* 지금 우리 사이의 온도. 쌓은 것과 다르다: 오래 비면 식는다 (plan/45 §4). */}
                <Warmth r={r} />
                {p ? (
                  <div className="mt-3">
                    <div className="flex items-center justify-between text-xs text-muted-fg"><span>{t("rel.next_stage", { stage: t(`rel.stage_${p.stage}`) })}</span><span className="tabular-nums">{Math.round(p.ratio * 100)}%</span></div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-accent transition-[width] duration-700" style={{ width: `${Math.max(2, p.ratio * 100)}%` }} /></div>
                  </div>
                ) : <p className="mt-3 text-xs text-muted-fg">{t("rel.max_stage")}</p>}
              </div>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat icon={<MessageSquare className="h-4 w-4" />} label={t("rel.stat_turns")} value={r.turns} />
              <Stat icon={<Flame className="h-4 w-4" />} label={t("rel.stat_streak")} value={r.streak_days} hint={t("rel.stat_active_days", { n: r.active_days })} />
              <Stat icon={<Brain className="h-4 w-4" />} label={t("rel.stat_facts")} value={r.facts_remembered} />
              <Stat icon={<Trophy className="h-4 w-4" />} label={t("rel.stat_milestones")} value={r.milestones.length} />
            </div>
          </CardBody>
        </Card>

        {/* ── the secretary speaks first ── */}
        <div className="space-y-4">
          <Card>
            <CardHeader title={t("rel.proactive_title")} description={t("rel.proactive_desc")} />
            <CardBody>
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-fg">{t("rel.proactive_status")}</span>
                <Badge tone={r.proactive.enabled ? "success" : "neutral"}>{r.proactive.enabled ? t("rel.proactive_on") : t("rel.proactive_off")}</Badge>
              </div>
              <div className="mt-2 flex items-center justify-between text-sm">
                <span className="text-muted-fg">{t("rel.proactive_last")}</span>
                <span>{r.proactive.last_at ? `${t(`chat.proactive_${r.proactive.last_kind || "checkin"}`)} · ${fmtRelative(r.proactive.last_at, locale)}` : t("rel.proactive_never")}</span>
              </div>
              {(() => {
                const quietLeft = r.proactive.quiet_until ? Math.max(0, Math.ceil((new Date(r.proactive.quiet_until).getTime() - Date.now()) / 60000)) : 0;
                const busy = say.isPending || (job !== null && (job.phase === "queued" || job.phase === "writing"));
                return (
                  <>
                    <Button className="mt-4 w-full" variant="accent" loading={busy} disabled={a.status !== "active" || quietLeft > 0} onClick={() => say.mutate()}>
                      <Send className="h-4 w-4" />{busy ? t("rel.phase_writing") : t("rel.say_now")}
                    </Button>
                    {quietLeft > 0 ? <p className="mt-2 text-xs text-muted-fg">{t("rel.gate_wait", { n: quietLeft })}</p> : null}
                  </>
                );
              })()}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title={t("rel.mood_title")} description={t("rel.mood_desc")} />
            <CardBody>
              <Select value={r.mood?.state ?? ""} onChange={(e) => mood.mutate(e.target.value)}>
                {r.moods.map((m) => <option key={m || "none"} value={m}>{m ? t(`rel.mood_${m}`) : t("rel.mood_none")}</option>)}
              </Select>
              {r.mood?.expires_at ? <p className="mt-1.5 text-xs text-muted-fg">{t("rel.mood_until", { when: fmtRelative(r.mood.expires_at, locale) })}</p> : null}
            </CardBody>
          </Card>
        </div>
      </div>

      {/* ── shared journal ── */}
      <div className="mt-5">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div><h2 className="text-base font-semibold inline-flex items-center gap-1.5"><BookOpen className="h-4 w-4" />{t("rel.journal")}</h2><p className="text-xs text-muted-fg">{t("rel.journal_desc")}</p></div>
          <Segmented size="sm" value={filter} onChange={setFilter} options={[{ value: "all", label: t("common.all") }, { value: "post", label: t("rel.j_post") }, { value: "fact", label: t("rel.j_fact") }, { value: "note", label: t("rel.j_note") }, { value: "milestone", label: t("rel.j_milestone") }]} />
        </div>
        {journal.isLoading ? <Skeleton className="h-40" /> : items.length ? (
          <ol className="relative space-y-3 border-l border-border pl-5">
            {items.map((e) => <JournalRow key={`${e.type}:${e.id}`} e={e} onForget={(id) => patchFact.mutate(id)} onDeleteNote={(id, ns) => delNote.mutate({ id, ns })} />)}
          </ol>
        ) : <EmptyState icon={<Sparkles />} title={t("rel.journal_empty")} description={t("rel.journal_empty_desc")} action={<Link href={`/app/chat?a=${a.id}`} className={buttonLook("accent", "md")}><MessageSquare className="h-4 w-4" />{t("agent.tab_chat")}</Link>} />}
      </div>
    </Page>
  );
}

function Stat({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: number; hint?: string }) {
  return (
    <div className="rounded-xl bg-muted px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-fg">{icon}{label}</div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums">{value}</div>
      {hint ? <div className="text-[11px] text-muted-fg">{hint}</div> : null}
    </div>
  );
}

/** 지금 우리 사이의 온도 (plan/45 §4).
 *
 *  쌓은 것(자격)은 내려가지 않고 이것은 내려간다. 둘 중 낮은 쪽이 단계라, 오래 쌓은
 *  사이도 오래 비면 멀어지고 며칠 이야기하면 제자리로 온다. 수를 크게 띄우지 않는다:
 *  숫자가 커지면 사람은 글이 아니라 숫자를 쓴다. */
function Warmth({ r }: { r: Relationship }) {
  const t = useT();
  const cooling = r.idle_days !== null && r.idle_days > r.grace_days;
  const behind = r.stages.indexOf(r.warmth_stage) < r.stages.indexOf(r.earned_stage);
  return (
    <div className="mt-3">
      <div className="flex items-center justify-between text-xs text-muted-fg">
        <span>{t("rel.warmth")}</span>
        <span className={cn("tabular-nums", cooling && "text-warning")}>{Math.round(r.affinity)}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full transition-[width] duration-700", cooling ? "bg-warning" : "bg-success")}
             style={{ width: `${Math.max(2, r.affinity)}%` }} />
      </div>
      <p className="mt-1 text-[11px] text-muted-fg">
        {behind ? t("rel.warmth_behind", { stage: t(`rel.stage_${r.earned_stage}`) })
         : cooling ? t("rel.warmth_cooling", { n: r.idle_days ?? 0 }) : t("rel.warmth_ok")}
      </p>
    </div>
  );
}

function JournalRow({ e, onForget, onDeleteNote }: { e: JournalEntry; onForget: (id: string) => void; onDeleteNote: (id: string, ns: string) => void }) {
  const t = useT(); const locale = useLocale();
  const dot = e.type === "milestone" ? "bg-warning" : e.type === "note" ? "bg-accent"
            : e.type === "post" ? "bg-fg/40" : "bg-success";
  return (
    <li className="relative">
      <span className={cn("absolute -left-[26px] top-2 h-2.5 w-2.5 rounded-full ring-4 ring-bg", dot)} />
      <div className="rounded-xl border border-border bg-card px-3.5 py-2.5">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1 text-sm">
            {e.type === "fact" ? <FactStatement subject={e.subject} predicate={e.predicate} object={e.object} /> : null}
            {e.type === "note" ? <><div className="font-medium">{e.title}</div><p className="mt-0.5 line-clamp-3 whitespace-pre-wrap text-xs text-muted-fg">{e.body}</p></> : null}
            {e.type === "milestone" ? <div className="inline-flex items-center gap-1.5 font-medium"><Trophy className="h-3.5 w-3.5 text-warning" />{t(`rel.ms_${e.key}`) === `rel.ms_${e.key}` ? e.key : t(`rel.ms_${e.key}`)}</div> : null}
            {/* 내가 적어 둔 것도 우리 사이의 일이다. 글을 백 편 써도 여기 한 줄도 없으면
                한 일이 어디로 갔는지 알 길이 없다 (plan/45 §7). */}
            {e.type === "post" ? <p className="line-clamp-3 whitespace-pre-wrap">{e.body || (e.images ? t("feed.photos_n", { n: e.images }) : "")}</p> : null}
          </div>
          {e.type === "fact" ? <Button size="sm" variant="ghost" className="shrink-0 text-muted-fg" onClick={async () => { if (await confirm({ title: t("rel.forget_confirm"), confirmLabel: t("rel.forget") })) onForget(e.id); }}>{t("rel.forget")}</Button> : null}
          {e.type === "note" ? <Button size="icon-sm" variant="ghost" aria-label={t("common.delete")} className="shrink-0 text-muted-fg" onClick={async () => { if (await confirm({ title: t("mem.delete_confirm"), danger: true, confirmLabel: t("common.delete") })) onDeleteNote(e.id, e.namespace); }}><Trash2 className="h-4 w-4" /></Button> : null}
        </div>
        <div className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-fg">
          <Badge tone="outline">{t(`rel.j_${e.type}`)}</Badge>{e.type === "fact" ? <Badge tone="outline">{e.kind}</Badge> : null}
          {e.type === "post" ? <>{e.visibility !== "public" ? <Badge tone="neutral">{t(`blog.vis_${e.visibility}`)}</Badge> : null}
            {e.read ? <span className="text-[11px] text-muted-fg">{t("rel.j_post_read")}</span> : null}</> : null}
          <span className="ml-auto" title={fmtDate(e.at)}>{fmtRelative(e.at, locale)}</span>
        </div>
      </div>
    </li>
  );
}

