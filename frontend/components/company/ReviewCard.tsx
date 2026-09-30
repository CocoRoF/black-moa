"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Flag, Pencil, ShieldCheck, ThumbsDown, ThumbsUp, Trash2, TrendingDown, TrendingUp, Minus } from "@/components/icons";
import { Companies, type CompanyReview } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { fmtNumber, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { AxisBars, FACT_QUESTIONS, Stars, benefitLabel, companyHref, factLabel, fitLabel, fmtManwon, optionLabel } from "./shared";

/** One review. The byline is a job family, a status and a year — never a name.
 *  `focus` brings one section (pay, interview, benefits) to the front on the tab that is
 *  about it, so the same review reads differently on the 연봉 tab and on 리뷰. */
export function ReviewCard({ r, focus, onChanged }: { r: CompanyReview; focus?: "salary" | "interview" | "benefits"; onChanged?: () => void }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [helpful, setHelpful] = useState(r.helpful); const [n, setN] = useState(r.helpful_count);
  const [confirm, setConfirm] = useState(false); const [axesOpen, setAxesOpen] = useState(false);
  const bust = () => { qc.invalidateQueries({ queryKey: ["cx"] }); onChanged?.(); };
  const vote = useMutation({
    mutationFn: () => Companies.helpful(r.id),
    onSuccess: (x) => { setHelpful(x.helpful); setN(x.helpful_count); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const report = useMutation({
    mutationFn: () => Companies.report(r.id, "abuse"),
    onSuccess: () => toast.success(t("cx.reported")),
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const remove = useMutation({
    mutationFn: () => Companies.deleteReview(r.id),
    onSuccess: () => { toast.success(t("cx.deleted")); setConfirm(false); bust(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const iv = r.interview;
  const byline = [r.family_label || r.job_label, t(`cx.employment_${r.employment}`), `${r.work_year}`].filter(Boolean).join(" · ");

  return (
    <article className={cn("rounded-2xl border border-border bg-card p-4 shadow-soft md:p-5", r.is_mine && "border-accent/40")}>
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Stars value={r.rating} size={14} />
            <span className="text-sm font-semibold tabular-nums">{r.rating.toFixed(1)}</span>
            {r.verified ? <Badge tone="success"><ShieldCheck className="h-3 w-3" />{t("cx.verified_badge")}</Badge> : null}
            {r.is_mine ? <Badge tone="accent">{t("cx.my_review")}</Badge> : null}
          </div>
          <h3 className="mt-1 text-[15px] font-semibold leading-snug">{r.title}</h3>
          <div className="mt-0.5 text-xs text-muted-fg">{byline} · {fmtRelative(r.created_at, locale)}</div>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1">
          <Chip on={r.recommend} icon={r.recommend ? <ThumbsUp className="h-3 w-3" /> : <ThumbsDown className="h-3 w-3" />} label={t(r.recommend ? "cx.recommend_yes" : "cx.recommend_no")} />
          {r.ceo_approval != null ? <Chip on={r.ceo_approval} label={t(r.ceo_approval ? "cx.ceo_yes" : "cx.ceo_no")} /> : null}
          <Chip on={r.growth === "up"} neutral={r.growth === "flat"} label={t(`cx.growth_${r.growth}`)}
            icon={r.growth === "up" ? <TrendingUp className="h-3 w-3" /> : r.growth === "down" ? <TrendingDown className="h-3 w-3" /> : <Minus className="h-3 w-3" />} />
        </div>
      </header>

      {focus === "salary" && r.salary ? (
        <div className="mt-3 rounded-xl bg-warning/10 px-3 py-2 text-sm">
          <span className="font-semibold">{fmtManwon(r.salary, locale, t)}</span>
          {r.experience_years != null ? <span className="ml-2 text-muted-fg">{t("cx.experience_chip", { n: r.experience_years })}</span> : null}
        </div>
      ) : null}
      {focus === "interview" && iv && (iv.difficulty || iv.result || iv.questions || iv.process) ? (
        <div className="mt-3 space-y-1.5 rounded-xl bg-muted/60 px-3 py-2.5 text-sm">
          <div className="flex flex-wrap gap-1.5">
            {iv.difficulty ? <Badge tone="outline">{t("cx.interview_difficulty")} · {t(`cx.difficulty_${iv.difficulty}`)}</Badge> : null}
            {iv.result ? <Badge tone={iv.result === "pass" ? "success" : iv.result === "fail" ? "danger" : "neutral"}>{t(`cx.interview_result_${iv.result}`)}</Badge> : null}
          </div>
          {iv.questions ? <p><span className="text-muted-fg">{t("cx.interview_questions")}: </span>{iv.questions}</p> : null}
          {iv.process ? <p><span className="text-muted-fg">{t("cx.interview_process")}: </span>{iv.process}</p> : null}
        </div>
      ) : null}
      {focus === "benefits" && r.benefits.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">{r.benefits.map((b) => <Badge key={b} tone="success">{benefitLabel(t, b)}</Badge>)}</div>
      ) : null}

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Block label={t("cx.pros")} tone="success" text={r.pros} />
        <Block label={t("cx.cons")} tone="danger" text={r.cons} />
      </div>
      {r.advice ? <div className="mt-2"><Block label={t("cx.advice")} tone="neutral" text={r.advice} /></div> : null}

      {!focus && Object.keys(r.answers ?? {}).length ? (
        <div className="mt-3 rounded-xl bg-muted/50 px-3 py-2.5">
          <div className="mb-1.5 text-[11px] font-semibold text-muted-fg">{t("cx.rc_facts")}</div>
          <div className="flex flex-wrap gap-1.5">
            {r.answers.again ? <span className="inline-flex items-center gap-1 rounded-md bg-accent/12 px-2 py-0.5 text-[11px] font-medium text-accent">{t("cx.rc_again")} · {optionLabel(t, "again", String(r.answers.again))}</span> : null}
            {FACT_QUESTIONS.filter((q) => typeof r.answers[q] === "string").map((q) => (
              <span key={q} className="inline-flex items-center gap-1 rounded-md bg-card px-2 py-0.5 text-[11px] ring-1 ring-border"><span className="text-muted-fg">{factLabel(t, q)}</span> {optionLabel(t, q, String(r.answers[q]))}</span>
            ))}
            {Array.isArray(r.answers.flex) ? r.answers.flex.map((o) => <span key={o} className="rounded-md bg-card px-2 py-0.5 text-[11px] ring-1 ring-border">{optionLabel(t, "flex", o)}</span>) : null}
          </div>
          {Array.isArray(r.answers.fit) && r.answers.fit.length ? <div className="mt-1.5 text-[11px] text-muted-fg">{t("cx.glance_fit")}: <span className="text-fg">{r.answers.fit.map((o) => fitLabel(t, o)).join(" · ")}</span></div> : null}
          {Array.isArray(r.answers.unfit) && r.answers.unfit.length ? <div className="text-[11px] text-muted-fg">{t("cx.glance_unfit")}: <span className="text-fg">{r.answers.unfit.map((o) => fitLabel(t, o)).join(" · ")}</span></div> : null}
        </div>
      ) : null}
      {!focus ? (
        <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
          {r.salary ? <Badge tone="warning">{t("cx.salary_chip", { n: fmtNumber(r.salary) })}</Badge> : null}
          {iv?.result ? <Badge tone="outline">{t("cx.tab_interview")} · {t(`cx.interview_result_${iv.result}`)}</Badge> : null}
          {r.benefits.slice(0, 4).map((b) => <Badge key={b} tone="neutral">{benefitLabel(t, b)}</Badge>)}
          {r.benefits.length > 4 ? <Badge tone="neutral">+{r.benefits.length - 4}</Badge> : null}
        </div>
      ) : null}

      <footer className="mt-3 flex flex-wrap items-center gap-1 border-t border-border pt-2.5 text-xs">
        {Object.keys(r.answers ?? {}).length ? <span className="px-1 text-[11px] text-muted-fg" /> : (
          <button type="button" onClick={() => setAxesOpen((v) => !v)} className="rounded-full px-2 py-1 text-muted-fg hover:bg-muted hover:text-fg" aria-expanded={axesOpen} title={t("cx.rc_legacy")}>
            {t("cx.form_ratings")}
          </button>
        )}
        <span className="ml-auto flex items-center gap-1">
          {r.is_mine ? (
            <>
              <Link href={`${companyHref(r.company_id)}/review`} className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-muted-fg hover:bg-muted hover:text-fg"><Pencil className="h-3.5 w-3.5" />{t("common.edit")}</Link>
              <button type="button" onClick={() => setConfirm(true)} className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-muted-fg hover:bg-muted hover:text-danger"><Trash2 className="h-3.5 w-3.5" />{t("common.delete")}</button>
            </>
          ) : (
            <>
              <button type="button" onClick={() => report.mutate()} disabled={report.isPending} className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-muted-fg hover:bg-muted hover:text-fg"><Flag className="h-3.5 w-3.5" />{t("cx.report")}</button>
              <Button size="sm" variant={helpful ? "secondary" : "outline"} aria-pressed={helpful} loading={vote.isPending} onClick={() => vote.mutate()}>
                <ThumbsUp className={cn("h-3.5 w-3.5", helpful && "fill-current")} />{t("cx.helpful")}{n ? <span className="tabular-nums text-muted-fg">{n}</span> : null}
              </Button>
            </>
          )}
        </span>
      </footer>
      {axesOpen ? <AxisBars axes={r.axes} className="mt-3 rounded-xl bg-muted/50 p-3" /> : null}
      <ConfirmDialog open={confirm} onClose={() => setConfirm(false)} onConfirm={() => remove.mutate()} title={t("cx.delete_review")}
        description={t("cx.delete_review_desc")} confirmLabel={t("common.delete")} cancelLabel={t("common.cancel")} danger loading={remove.isPending} />
    </article>
  );
}

function Chip({ on, neutral, icon, label }: { on: boolean; neutral?: boolean; icon?: React.ReactNode; label: string }) {
  return <Badge tone={neutral ? "neutral" : on ? "success" : "danger"}>{icon}{label}</Badge>;
}

function Block({ label, tone, text }: { label: string; tone: "success" | "danger" | "neutral"; text: string }) {
  const bar = { success: "bg-success", danger: "bg-danger", neutral: "bg-muted-fg" }[tone];
  return (
    <div className="flex gap-2.5">
      <span aria-hidden className={cn("mt-1 h-auto w-1 shrink-0 rounded-full", bar)} />
      <div className="min-w-0">
        <div className="text-[11px] font-semibold text-muted-fg">{label}</div>
        <p className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed">{text}</p>
      </div>
    </div>
  );
}
