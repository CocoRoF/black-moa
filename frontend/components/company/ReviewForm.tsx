"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft } from "@/components/icons";
import { Companies, type Answers, type ReviewInput } from "@/lib/api";
import { ApiError, friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Segmented } from "@/components/ui/tabs";
import { Section } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/misc";
import { CompanyLogo, benefitLabel, companyHref, fitLabel, optionLabel, qLabel } from "./shared";

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return <span className="inline-flex items-center gap-2"><span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-accent/12 text-[11px] font-bold text-accent tabular-nums">{n}</span>{children}</span>;
}

const EMPTY: ReviewInput = {
  employment: "current", job_code: "", work_year: new Date().getFullYear(), title: "", pros: "", cons: "", advice: "",
  answers: {}, salary: null, experience_years: null, interview: null, benefits: [],
};

/** One question, its answers as a row of words. One tap; the chosen one fills in. */
function ChoiceRow({ q, options, value, onPick, big }: { q: string; options: string[]; value?: string; onPick: (v: string) => void; big?: boolean }) {
  const t = useT();
  return (
    <div role="radiogroup" className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = value === o;
        return (
          <button key={o} type="button" role="radio" aria-checked={on} onClick={() => onPick(o)}
            className={cn("rounded-full border transition", big ? "px-4 py-2 text-sm" : "px-3 py-1.5 text-[13px]",
              on ? "border-accent bg-accent text-accent-fg" : "border-border bg-card hover:border-accent/50 hover:bg-muted")}>
            {optionLabel(t, q, o)}
          </button>
        );
      })}
    </div>
  );
}

function MultiRow({ q, options, max, value, onChange, fit }: { q: string; options: string[]; max: number; value: string[]; onChange: (v: string[]) => void; fit?: boolean }) {
  const t = useT();
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = value.includes(o); const full = !on && value.length >= max;
        return (
          <button key={o} type="button" aria-pressed={on} disabled={full} onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}
            className={cn("rounded-full border px-3 py-1.5 text-[13px] transition disabled:opacity-40",
              on ? (fit ? "border-success bg-success/12 text-success" : "border-accent bg-accent/12 text-accent") : "border-border bg-card hover:bg-muted")}>
            {fit ? fitLabel(t, o) : optionLabel(t, q, o)}
          </button>
        );
      })}
    </div>
  );
}

/** Write or edit the reader's one review of a company (plan/40). Everything past the
 *  ratings and the two paragraphs is optional; what is filled in feeds the pay, interview
 *  and benefits tabs. */
export function ReviewForm({ id }: { id: string }) {
  const t = useT(); const locale = useLocale(); const router = useRouter(); const qc = useQueryClient();
  const d = useQuery({ queryKey: ["cx", "detail", id], queryFn: () => Companies.detail(id) });
  const meta = useQuery({ queryKey: ["cx", "meta"], queryFn: Companies.meta, staleTime: Infinity });
  const [f, setF] = useState<ReviewInput>(EMPTY);
  const [answers, setAnswers] = useState<Answers>({});
  const pick = (q: string, v: string) => setAnswers((a) => ({ ...a, [q]: v }));
  const pickMulti = (q: string, v: string[]) => setAnswers((a) => { const n = { ...a }; if (v.length) n[q] = v; else delete n[q]; return n; });
  const [difficulty, setDifficulty] = useState(0); const [result, setResult] = useState(""); const [questions, setQuestions] = useState(""); const [process, setProcess] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const mine = d.data?.my_review;
  useEffect(() => {
    if (!mine) return;
    setF({ employment: mine.employment, job_code: mine.job_code, work_year: mine.work_year, title: mine.title, pros: mine.pros, cons: mine.cons, advice: mine.advice,
           answers: {}, salary: mine.salary, experience_years: mine.experience_years, interview: null, benefits: mine.benefits });
    setAnswers(mine.answers ?? {});
    setDifficulty(mine.interview.difficulty ?? 0); setResult(mine.interview.result ?? ""); setQuestions(mine.interview.questions ?? ""); setProcess(mine.interview.process ?? "");
  }, [mine]);

  const minText = meta.data?.min_text ?? 10;
  const again = (meta.data?.questions ?? []).find((q) => q.code === "again");
  const years = useMemo(() => { const y = meta.data?.year_now ?? new Date().getFullYear(); return Array.from({ length: 15 }, (_, i) => y - i); }, [meta.data]);
  const groups = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const b of meta.data?.benefits ?? []) m.set(b.group, [...(m.get(b.group) ?? []), b.code]);
    return [...m.entries()];
  }, [meta.data]);
  const set = <K extends keyof ReviewInput>(k: K, v: ReviewInput[K]) => setF((p) => ({ ...p, [k]: v }));

  const save = useMutation({
    mutationFn: () => Companies.writeReview(id, {
      ...f, answers,
      interview: difficulty || result || questions.trim() || process.trim()
        ? { difficulty: difficulty || null, result: result || null, questions: questions.trim(), process: process.trim() } : null,
    }),
    onSuccess: () => {
      toast.success(t(mine ? "cx.form_updated" : "cx.form_saved"));
      qc.invalidateQueries({ queryKey: ["cx"] });
      router.push(companyHref(id, "reviews"));
    },
    onError: (e) => {
      if (e instanceof ApiError) {
        const field = (e.detail as { field?: string } | undefined)?.field;
        if (e.code === "review_too_short" && (field === "pros" || field === "cons")) return setErr(t(`cx.form_err_${field}`, { n: minText }));
        if (e.code === "review_unanswered") { const q = (e.detail as { questions?: string[] } | undefined)?.questions?.[0]; return setErr(q ? t("cx.form_err_answer", { q: qLabel(t, q) }) : t("cx.form_err_rating")); }
        if (e.code === "review_invalid") return setErr(t("cx.form_err_rating"));
        if (e.code === "community_needs_verified_email") return setErr(t("cx.form_err_verify"));
        if (e.code === "review_hidden") return setErr(t("cx.form_err_hidden"));
      }
      setErr(friendlyError(e, locale));
    },
  });

  const submit = () => {
    setErr(null);
    const missing = (meta.data?.questions ?? []).find((q) => q.required && !answers[q.code]);
    if (missing) return setErr(t("cx.form_err_answer", { q: qLabel(t, missing.code) }));
    if (f.pros.trim().length < minText) return setErr(t("cx.form_err_pros", { n: minText }));
    if (f.cons.trim().length < minText) return setErr(t("cx.form_err_cons", { n: minText }));
    save.mutate();
  };

  if (d.isLoading || !d.data) return <Page><Skeleton className="h-96" /></Page>;
  const c = d.data.company;

  return (
    <Page>
      <Link href={companyHref(id)} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-fg hover:text-fg"><ArrowLeft className="h-4 w-4" />{c.name}</Link>
      <PageHeader title={t(mine ? "cx.form_edit_title" : "cx.form_title", { name: c.name })} description={t("cx.form_desc")}
        lead={<CompanyLogo size={40} className="mr-2" />} />

      <div className="space-y-5">
        <Section title={<Step n={1}>{t("cx.form_basic")}</Step>}>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t("cx.form_employment")}>
              <Segmented value={f.employment} onChange={(v) => set("employment", v)} className="w-full [&>button]:flex-1"
                options={[{ value: "current", label: t("cx.employment_current") }, { value: "former", label: t("cx.employment_former") }]} />
            </Field>
            <Field label={t("cx.form_job")}>
              <Select value={f.job_code} onChange={(e) => set("job_code", e.target.value)} searchThreshold={8}>
                <option value="">{t("cx.form_job_none")}</option>
                {(meta.data?.job_families ?? []).map((fam) => (
                  <optgroup key={fam.value} label={fam.label}>
                    <option value={fam.value}>{fam.label}</option>
                    {(fam.children ?? []).map((ch) => <option key={ch.value} value={ch.value}>{ch.label}</option>)}
                  </optgroup>
                ))}
              </Select>
            </Field>
            <Field label={t("cx.form_year")}>
              <Select value={String(f.work_year)} onChange={(e) => set("work_year", Number(e.target.value))}>
                {years.map((y) => <option key={y} value={String(y)}>{y}</option>)}
              </Select>
            </Field>
          </div>
        </Section>

        <Section title={<Step n={2}>{t("cx.form_ratings")}</Step>} description={t("cx.form_answers_desc")}>
          <div className="space-y-5">
            {/* The one answer that becomes the score, first and alone. */}
            {again ? (
              <div className={cn("rounded-xl border px-4 py-3", answers.again ? "border-accent/40 bg-accent/5" : "border-dashed border-border bg-muted/40")}>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div className="text-sm font-semibold">{qLabel(t, "again")} <span className="ml-1 rounded-md bg-accent/12 px-1.5 py-0.5 text-[10px] font-medium text-accent">{t("cx.form_required")}</span></div>
                  <div className="text-[11px] text-muted-fg">{t("cx.form_again_hint")}</div>
                </div>
                <ChoiceRow q="again" options={again.options} value={answers.again as string | undefined} onPick={(v) => pick("again", v)} big />
              </div>
            ) : null}
            {(meta.data?.areas ?? []).map((area) => (
              <div key={area} className="rounded-xl border border-border px-4 py-3">
                <div className="mb-2 flex items-baseline gap-2"><h4 className="text-sm font-semibold">{t(`cx.axis_${area}`)}</h4><span className="text-[11px] text-muted-fg">{t(`cx.axis_hint_${area}`)}</span></div>
                <div className="space-y-3">
                  {(meta.data?.questions ?? []).filter((q) => q.area === area).map((q) => (
                    <div key={q.code}>
                      <div className="mb-1 text-[13px]">{qLabel(t, q.code)}{q.required ? <span className="ml-1.5 rounded-md bg-accent/12 px-1.5 py-0.5 text-[10px] font-medium text-accent">{t("cx.form_required")}</span> : null}</div>
                      {q.multi
                        ? <MultiRow q={q.code} options={q.options} max={q.max ?? 9} value={(answers[q.code] as string[] | undefined) ?? []} onChange={(v) => pickMulti(q.code, v)} />
                        : <ChoiceRow q={q.code} options={q.options} value={answers[q.code] as string | undefined} onPick={(v) => pick(q.code, v)} />}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {(["fit", "unfit"] as const).map((k) => { const q = (meta.data?.questions ?? []).find((x) => x.code === k); return q ? (
              <div key={k}>
                <div className="mb-1 text-[13px] font-medium">{qLabel(t, k)} <span className="text-[11px] font-normal text-muted-fg">{t("cx.form_fit_hint", { n: q.max ?? 3 })}</span></div>
                <MultiRow q={k} options={q.options} max={q.max ?? 3} value={(answers[k] as string[] | undefined) ?? []} onChange={(v) => pickMulti(k, v)} fit />
              </div>
            ) : null; })}
          </div>
        </Section>

        <Section title={<Step n={3}>{t("cx.form_text")}</Step>}>
          <div className="space-y-3">
            <Field label={t("cx.form_title_ph")}><Input value={f.title} maxLength={120} onChange={(e) => set("title", e.target.value)} placeholder={t("cx.form_title_ph")} /></Field>
            <Field label={t("cx.pros")} hint={t("cx.form_min", { n: minText })}><Textarea value={f.pros} maxLength={3000} onChange={(e) => set("pros", e.target.value)} placeholder={t("cx.form_pros_ph")} /></Field>
            <Field label={t("cx.cons")} hint={t("cx.form_min", { n: minText })}><Textarea value={f.cons} maxLength={3000} onChange={(e) => set("cons", e.target.value)} placeholder={t("cx.form_cons_ph")} /></Field>
            <Field label={t("cx.advice")} hint={t("cx.form_optional")}><Textarea value={f.advice} maxLength={3000} onChange={(e) => set("advice", e.target.value)} placeholder={t("cx.form_advice_ph")} className="min-h-[64px]" /></Field>
          </div>
        </Section>

        <div className="pt-2">
          <h2 className="text-[15px] font-semibold"><Step n={4}>{t("cx.form_optional_group")}</Step></h2>
          <p className="mt-0.5 text-sm text-muted-fg">{t("cx.form_optional_desc")}</p>
        </div>
        <Section title={`${t("cx.form_salary")} · ${t("cx.form_optional")}`} description={t("cx.form_salary_desc")}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("cx.form_salary")}>
              <div className="relative"><Input type="number" min={100} max={1000000} step={100} value={f.salary ?? ""} placeholder={t("cx.form_salary_ph")}
                onChange={(e) => set("salary", e.target.value ? Number(e.target.value) : null)} className="pr-14" /><span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-fg">{t("cx.manwon")}</span></div>
            </Field>
            <Field label={t("cx.form_experience")}>
              <div className="relative"><Input type="number" min={0} max={50} value={f.experience_years ?? ""} placeholder={t("cx.form_experience_ph")}
                onChange={(e) => set("experience_years", e.target.value ? Number(e.target.value) : null)} className="pr-10" /><span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-fg">{t("cx.form_year_unit")}</span></div>
            </Field>
          </div>
        </Section>

        <Section title={`${t("cx.form_interview")} · ${t("cx.form_optional")}`}>
          <div className="space-y-3">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t("cx.form_interview_difficulty")}>
                <Segmented size="sm" value={String(difficulty)} onChange={(v) => setDifficulty(Number(v))} className="w-full [&>button]:flex-1"
                  options={[{ value: "0", label: "–" }, ...[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n), title: t(`cx.difficulty_${n}`) }))]} />
              </Field>
              <Field label={t("cx.form_interview_result")}>
                <Segmented size="sm" value={result} onChange={setResult} className="w-full [&>button]:flex-1"
                  options={[{ value: "", label: t("cx.form_interview_none") }, ...["pass", "fail", "pending"].map((r) => ({ value: r, label: t(`cx.interview_result_${r}`) }))]} />
              </Field>
            </div>
            <Textarea value={questions} maxLength={2000} onChange={(e) => setQuestions(e.target.value)} placeholder={t("cx.form_interview_questions_ph")} className="min-h-[64px]" />
            <Textarea value={process} maxLength={2000} onChange={(e) => setProcess(e.target.value)} placeholder={t("cx.form_interview_process_ph")} className="min-h-[64px]" />
          </div>
        </Section>

        <Section title={`${t("cx.form_benefits")} · ${t("cx.form_optional")}`}>
          <div className="space-y-3">
            {groups.map(([g, codes]) => (
              <div key={g}>
                <div className="mb-1.5 text-[11px] font-semibold text-muted-fg">{t(`cx.beng_${g}`)}</div>
                <div className="flex flex-wrap gap-1.5">
                  {codes.map((code) => {
                    const on = f.benefits.includes(code);
                    return (
                      <button key={code} type="button" aria-pressed={on} onClick={() => set("benefits", on ? f.benefits.filter((x) => x !== code) : [...f.benefits, code])}
                        className={cn("rounded-full border px-3 py-1.5 text-sm transition", on ? "border-success bg-success/12 text-success" : "border-border hover:bg-muted")}>
                        {benefitLabel(t, code)}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </Section>

        <div className="bottom-bar sticky bottom-0 -mx-4 border-t border-border bg-bg/95 px-4 py-3 backdrop-blur md:-mx-6 md:px-6">
          <div className="flex items-center gap-3">
            {err ? <p role="alert" className="min-w-0 flex-1 text-sm text-danger">{err}</p> : <span className="min-w-0 flex-1 truncate text-xs text-muted-fg">{t("cx.form_desc")}</span>}
            <Button variant="outline" onClick={() => router.push(companyHref(id))}>{t("common.cancel")}</Button>
            <Button variant="accent" loading={save.isPending} onClick={submit}>{t(mine ? "cx.form_update" : "cx.form_submit")}</Button>
          </div>
        </div>
      </div>
    </Page>
  );
}
