"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Bot, Briefcase, Calendar, ChevronRight, ExternalLink, MessageCircle, PenLine, ShieldCheck, Star, ThumbsUp, Users, Wallet } from "@/components/icons";
import { Companies, type Axis, type CompanyDetailData, type CompanyStats } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { fmtDate, fmtNumber, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Button, buttonLook } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/empty";
import { KeyValue } from "@/components/ui/misc";
import { Segmented } from "@/components/ui/tabs";
import { Section } from "@/components/ui/card";
import { coverFallback } from "@/components/profile/ProfileHeader";
import { ReviewCard } from "./ReviewCard";
import { CompareButton, CompareTray } from "./CompareTray";
import { AXES, CompanyLogo, CompanyTile, FACT_QUESTIONS, FollowButton, Pager, PeopleDots, QuickFact, Radar, SectionHeading, Stars, TagRow, benefitLabel, companyHref, factLabel, fitLabel, fmtManwon, optionLabel, topFact, yearsSince } from "./shared";

type Tab = "overview" | "reviews" | "salary" | "interview" | "benefits" | "hiring" | "community";
const TABS: Tab[] = ["overview", "reviews", "salary", "interview", "benefits", "hiring", "community"];

/** A company's page (plan/40). Laid out like a profile: who the company is on the left,
 *  what people say about it on the right. The identity column is black-moa's own panel — the
 *  cover strip, the mark on its edge, the facts underneath — and stays put while the
 *  sections change. */
export function CompanyPage({ id }: { id: string }) {
  const t = useT(); const router = useRouter(); const params = useSearchParams();
  const tab = (TABS.includes((params.get("tab") ?? "") as Tab) ? params.get("tab") : "overview") as Tab;
  const setTab = (k: Tab) => router.replace(`${companyHref(id)}${k === "overview" ? "" : `?tab=${k}`}`, { scroll: false });
  const d = useQuery({ queryKey: ["cx", "detail", id], queryFn: () => Companies.detail(id), staleTime: 30_000 });

  if (d.isLoading) return <Page><Skeleton className="h-6 w-32" /><div className="mt-4 grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]"><Skeleton className="h-96" /><Skeleton className="h-96" /></div></Page>;
  if (d.isError || !d.data) return <Page><ErrorState message={t("cx.not_found")} onRetry={() => d.refetch()} retryLabel={t("common.retry")} /></Page>;
  const { company: c, stats } = d.data;
  const write = () => router.push(`${companyHref(id)}/review`);
  const tabs: { value: Tab; label: React.ReactNode }[] = [
    { value: "overview", label: t("cx.tab_overview") },
    { value: "reviews", label: <Count label={t("cx.tab_reviews")} n={stats.n} /> },
    { value: "salary", label: <Count label={t("cx.tab_salary")} n={stats.salary?.n} /> },
    { value: "interview", label: <Count label={t("cx.tab_interview")} n={stats.interview?.n} /> },
    { value: "benefits", label: <Count label={t("cx.tab_benefits")} n={stats.benefits?.length} /> },
    { value: "hiring", label: <Count label={t("cx.tab_hiring")} n={c.open_jobs} /> },
    { value: "community", label: <Count label={t("cx.tab_community")} n={d.data.posts_count} /> },
  ];

  return (
    <Page>
      <Link href="/app/community/companies" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-fg hover:text-fg"><ArrowLeft className="h-4 w-4" />{t("cx.back_home")}</Link>
      <div className="grid items-start gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        {/* Sticky, but never taller than the viewport: a long facts card would otherwise pin
            its top and hide its bottom until the page ran out. */}
        <aside className="min-w-0 space-y-4 lg:sticky lg:top-0 lg:max-h-[calc(100dvh-4rem)] lg:overflow-y-auto lg:pb-2 lg:pr-1 scrollbar-thin">
          <IdentityCard d={d.data} onWrite={write} />
          <div className="hidden lg:block"><FactsCard d={d.data} /></div>
        </aside>
        <main className="min-w-0">
          <div className="sticky top-0 z-10 -mx-4 mb-4 bg-bg/95 px-4 py-2 backdrop-blur md:-mx-6 md:px-6 lg:mx-0 lg:px-0">
            <div className="overflow-x-auto scroll-fade-x">
              <Segmented size="sm" value={tab} onChange={setTab} options={tabs} ariaLabel={t("cx.title")} />
            </div>
          </div>
          {tab === "overview" ? <Overview id={id} d={d.data} onWrite={write} onTab={setTab} />
            : tab === "reviews" ? <ReviewsTab id={id} years={d.data.years} stats={stats} onWrite={write} />
            : tab === "salary" ? <SalaryTab id={id} onWrite={write} />
            : tab === "interview" ? <InterviewTab id={id} stats={stats} onWrite={write} />
            : tab === "benefits" ? <BenefitsTab id={id} stats={stats} onWrite={write} />
            : tab === "hiring" ? <HiringTab id={id} />
            : <CommunityTab id={id} />}
        </main>
      </div>
      <CompareTray />
    </Page>
  );
}

function Count({ label, n }: { label: string; n?: number | null }) {
  return <span className="inline-flex items-center gap-1">{label}{n ? <span className="rounded-full bg-muted px-1.5 text-[10px] text-muted-fg tabular-nums">{fmtNumber(n)}</span> : null}</span>;
}

/** Who the company is: the cover, the mark, the name, the score, the two things you can do. */
function IdentityCard({ d, onWrite }: { d: CompanyDetailData; onWrite: () => void }) {
  const t = useT();
  const { company: c, stats } = d;
  const age = yearsSince(c.founded_on, c.listed_on);
  return (
    <section className="overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
      <div className="h-20" style={{ background: coverFallback() }} aria-hidden />
      <div className="relative px-4 pb-4">
        <div className="-mt-8 flex items-end justify-between gap-3">
          <CompanyLogo size={64} raised className="rounded-2xl" />
          <div className="flex flex-wrap items-center justify-end gap-1.5 pb-1">
            {c.market ? <Badge tone="outline">{c.market}{c.stock_code ? ` · ${c.stock_code}` : ""}</Badge> : null}
            {c.status === "closed" ? <Badge tone="danger">{t("cx.info_closed")}</Badge> : null}
            {d.my_verified ? <Badge tone="success" title={t("cx.my_verified")}><ShieldCheck className="h-3 w-3" />{t("cx.verified_badge")}</Badge> : null}
          </div>
        </div>
        <h1 className="mt-3 text-xl font-semibold leading-tight tracking-tight">{c.name}</h1>
        <div className="mt-1 text-sm text-muted-fg">{[c.industry_text, c.region_text].filter(Boolean).join(" · ")}</div>
        <TagRow tags={c.tags} className="mt-2.5" />

        <div className="mt-4 rounded-xl border border-border px-4 py-3">
          {stats.n ? (
            <>
              <div className="flex items-end gap-1.5"><span className="text-3xl font-bold leading-none tabular-nums">{c.rating.toFixed(1)}</span><Stars value={c.rating} size={14} className="mb-0.5" /><span className="mb-0.5 ml-1 text-[11px] text-muted-fg">{t("cx.score_basis", { n: fmtNumber(stats.n) })}</span></div>
              <div className="mt-2.5 grid grid-cols-2 gap-2">
                <div className="rounded-lg bg-muted/60 px-2.5 py-1.5"><div className="text-sm font-semibold tabular-nums">{stats.recommend ?? "–"}%</div><div className="text-[11px] text-muted-fg">{t("cx.recommend_rate")}</div></div>
                <div className="rounded-lg bg-muted/60 px-2.5 py-1.5"><div className="text-sm font-semibold tabular-nums">{stats.growth ?? "–"}%</div><div className="text-[11px] text-muted-fg">{t("cx.growth_rate")}</div></div>
              </div>
            </>
          ) : (
            <div className="flex items-center gap-2 text-sm text-muted-fg"><Star className="h-4 w-4" />{t("cx.no_stats")}</div>
          )}
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2">
          <Button variant="accent" onClick={onWrite}><PenLine className="h-4 w-4" />{t(d.my_review ? "cx.edit_review" : "cx.write_review")}</Button>
          <FollowButton id={c.id} following={c.following} count={c.follow_count} size="md" showCount />
          {/* black-moa's own two: the reader's secretary can brief them on this company, and
              a company can be weighed against others (plan/40 §7). */}
          <Link href={`/app/chat?draft=${encodeURIComponent(t("cx.ask_secretary_draft", { name: c.name }))}`}
                className={buttonLook("outline", "md", "w-full")}>
            <Bot className="h-4 w-4" />{t("cx.ask_secretary")}
          </Link>
          <CompareButton id={c.id} name={c.name} className="w-full" />
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2">
          <QuickFact icon={<Calendar className="h-4 w-4" />} label={age ? `${t(c.founded_on ? "cx.info_founded" : "cx.info_listed")} ${age.y}` : t("cx.info_founded")} value={age ? t("cx.years", { n: age.n }) : "–"} />
          <QuickFact icon={<Users className="h-4 w-4" />} label={t("cx.info_employees")} value={c.employees ? t("cx.employees", { n: fmtNumber(c.employees) }) : "–"} />
          <QuickFact icon={<Briefcase className="h-4 w-4" />} label={t("cx.tab_hiring")} value={t("cx.hiring_n", { n: c.open_jobs })} accent={c.open_jobs > 0} />
          <QuickFact icon={<Star className="h-4 w-4" />} label={t("cx.followers")} value={fmtNumber(c.follow_count)} />
        </div>
      </div>
    </section>
  );
}

function FactsCard({ d }: { d: CompanyDetailData }) {
  const t = useT();
  const c = d.company;
  const info = [
    c.industry_text && { k: t("cx.info_industry"), v: c.industry_text },
    c.region_text && { k: t("cx.info_region"), v: c.region_text },
    c.ceo && { k: t("cx.info_ceo"), v: c.ceo },
    c.market && { k: t("cx.info_market"), v: `${c.market}${c.stock_code ? ` · ${c.stock_code}` : ""}` },
    c.listed_on && { k: t("cx.info_listed"), v: fmtDate(c.listed_on) },
    c.founded_on && { k: t("cx.info_founded"), v: fmtDate(c.founded_on) },
    c.product && { k: t("cx.info_product"), v: c.product },
    c.address && { k: t("cx.info_address"), v: c.address },
    c.phone && { k: t("cx.info_phone"), v: c.phone },
    c.fiscal_month && { k: t("cx.info_fiscal"), v: c.fiscal_month },
    c.biz_no && { k: t("cx.info_biz"), v: c.biz_no },
  ].filter(Boolean) as { k: string; v: React.ReactNode }[];
  return (
    <Section title={t("cx.facts")} action={c.homepage ? (
      <a href={c.homepage} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs text-accent hover:underline">{t("cx.info_site")}<ExternalLink className="h-3.5 w-3.5" /></a>
    ) : undefined}>
      <KeyValue items={info} className="text-[13px]" />
    </Section>
  );
}

// ── 개요 ─────────────────────────────────────────────────────────────
function Overview({ id, d, onWrite, onTab }: { id: string; d: CompanyDetailData; onWrite: () => void; onTab: (k: Tab) => void }) {
  const t = useT();
  const { stats } = d;
  const top = useQuery({ queryKey: ["cx", "reviews", id, "top2"], queryFn: () => Companies.reviews(id, { sort: "helpful", size: 2 }), enabled: stats.n > 0 });
  return (
    <div className="space-y-6">
      <StatsPanel stats={stats} years={d.years} onWrite={onWrite} />
      {d.my_job ? <MyJobPanel job={d.my_job} onTab={onTab} onWrite={onWrite} /> : null}
      {stats.n ? (
        <section>
          <SectionHeading eyebrow={t("cx.highlights_desc")} title={t("cx.highlights")} icon={<ThumbsUp className="h-4 w-4 text-accent" />}
            action={<Button size="sm" variant="ghost" onClick={() => onTab("reviews")}>{t("cx.see_reviews")}<ChevronRight className="h-4 w-4" /></Button>} />
          {top.isLoading ? <Skeleton className="h-40" /> : <div className="space-y-3">{(top.data?.items ?? []).map((r) => <ReviewCard key={r.id} r={r} />)}</div>}
        </section>
      ) : null}
      {d.related.length ? (
        <Pager title={t("cx.related")} hint={d.company.industry_text} items={d.related} keyOf={(r) => r.id} render={(r) => <CompanyTile c={r} />} />
      ) : null}
      <div className="lg:hidden"><FactsCard d={d} /></div>
    </div>
  );
}

/** The reader's own field, at this company: only black-moa knows what the reader does for a
 *  living, so only black-moa can show a company through those eyes (plan/40 §7). */
function MyJobPanel({ job, onTab, onWrite }: { job: NonNullable<CompanyDetailData["my_job"]>; onTab: (k: Tab) => void; onWrite: () => void }) {
  const t = useT(); const locale = useLocale();
  const st = job.stats;
  return (
    <section className="rounded-2xl border border-accent/30 bg-accent/5 px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs text-accent">{t("cx.my_job_desc")}</div>
          <h2 className="text-[15px] font-semibold">{t("cx.my_job_title", { job: job.label })}</h2>
        </div>
        {st ? (
          <div className="flex items-center gap-5">
            <div className="text-right"><div className="text-lg font-semibold tabular-nums"><Star className="mr-1 inline h-4 w-4 fill-success text-success" />{st.rating.toFixed(1)}</div><div className="text-[11px] text-muted-fg">{t("cx.my_job_reviews", { n: st.n })}</div></div>
            {st.salary ? <div className="text-right"><div className="text-lg font-semibold tabular-nums">{fmtManwon(st.salary.median, locale, t)}</div><div className="text-[11px] text-muted-fg">{t("cx.cmp_salary")} ({st.salary.n})</div></div> : null}
            <Button size="sm" variant="outline" onClick={() => onTab("reviews")}>{t("cx.see_reviews")}<ChevronRight className="h-4 w-4" /></Button>
          </div>
        ) : (
          <div className="flex items-center gap-3 text-sm text-muted-fg">{t("cx.my_job_empty", { job: job.label })}<Button size="sm" variant="outline" onClick={onWrite}>{t("cx.write_review")}</Button></div>
        )}
      </div>
    </section>
  );
}

/** 한눈에 보기, said the way a secretary would say it: a shape for the five axes, a row
 *  of people for who recommends, and sentences for the rest — strongest side, weakest
 *  side, pay, whether it moved since last year. No dials. */
function StatsPanel({ stats, years, onWrite }: { stats: CompanyStats; years: string[]; onWrite: () => void }) {
  const t = useT(); const locale = useLocale();
  const [year, setYear] = useState<string>("all");
  const y = year === "all" ? null : stats.by_year?.[year];
  // A company nobody has reviewed carries {n: 0} and nothing else: every field below
  // has to survive that shape, because the hooks run before the empty state returns.
  const axes = useMemo(() => ((y?.axes ?? stats.axes) ?? {}) as Partial<Record<Axis, number>>, [y, stats.axes]);
  const n = y ? y.n : stats.n ?? 0;
  const ranked = useMemo(() => AXES.filter((a) => axes[a]).sort((a, b) => (axes[b] ?? 0) - (axes[a] ?? 0)), [axes]);
  const rating = y ? y.rating : stats.rating ?? 0;
  const recommend = y ? y.recommend : stats.recommend ?? null;
  const best = ranked[0]; const worst = ranked.length > 1 ? ranked[ranked.length - 1] : undefined;
  const sortedYears = Object.keys(stats.by_year ?? {}).sort();
  const trend = useMemo(() => {
    if (sortedYears.length < 2) return null;
    const cur = sortedYears[sortedYears.length - 1]; const prev = sortedYears[sortedYears.length - 2];
    const d = Math.round(((stats.by_year?.[cur]?.rating ?? 0) - (stats.by_year?.[prev]?.rating ?? 0)) * 10) / 10;
    return { cur, prev, d };
  }, [sortedYears, stats.by_year]);
  const dist = stats.dist ?? null;
  const distMax = dist ? Math.max(1, ...Object.values(dist)) : 1;
  const facts = stats.facts ?? {};
  const factRows = FACT_QUESTIONS.map((q) => ({ q, top: topFact(facts[q]) })).filter((x) => x.top);
  const fitTop = topFacts(facts.fit, 3); const unfitTop = topFacts(facts.unfit, 2);
  const againTop = topFact(facts.again);
  const againYes = facts.again ? (facts.again.must ?? 0) + (facts.again.probably ?? 0) : 0;
  const k = recommend == null ? 0 : n <= 10 ? Math.round((recommend / 100) * n) : Math.round(recommend / 10);

  if (!stats.n) return <StatsEmpty onWrite={onWrite} />;
  return (
    <section className="rounded-2xl border border-border bg-card shadow-soft">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5">
        <div>
          <h2 className="text-[15px] font-semibold">{t("cx.at_a_glance")}</h2>
          <p className="mt-0.5 text-xs text-muted-fg">
            {t("cx.current_former", { c: stats.employment?.current ?? 0, f: stats.employment?.former ?? 0 })}
            {stats.verified_n ? <span className="ml-1.5 inline-flex items-center gap-1 text-success"><ShieldCheck className="h-3 w-3" />{t("cx.verified_n", { n: stats.verified_n })}</span> : null}
          </p>
        </div>
        {years.length ? (
          <Select value={year} onChange={(e) => setYear(e.target.value)} className="w-36" aria-label={t("cx.work_year")}>
            <option value="all">{t("cx.all_years")}</option>{years.map((yy) => <option key={yy} value={yy}>{yy}</option>)}
          </Select>
        ) : null}
      </div>
      <div className="px-5 pb-5 pt-3">
        {!n ? <p className="text-sm text-muted-fg">{t("cx.reviews_filter_empty")}</p> : (
          <div className="grid gap-6 md:grid-cols-[auto_minmax(0,1fr)] md:gap-8">
            <div className="flex flex-col items-center">
              <div className="flex items-end gap-2">
                <span className="text-5xl font-bold leading-none tabular-nums">{rating.toFixed(1)}</span>
                <div className="pb-1"><Stars value={rating} size={16} /><div className="mt-0.5 text-[11px] text-muted-fg">{year === "all" ? t("cx.score_basis", { n: fmtNumber(n) }) : t("cx.stats_year_n", { y: year, n })}</div></div>
              </div>
              <Radar axes={axes} size={250} className="-mt-1" />
            </div>
            <ul className="space-y-3.5 self-center text-sm leading-relaxed">
              {recommend != null ? (
                <li>
                  <PeopleDots pct={recommend} n={n} className="mb-1.5" />
                  <div>{n <= 10 ? t("cx.glance_recommend_n", { n, k }) : t("cx.glance_recommend_scaled", { k })} <span className="text-muted-fg">({recommend}%)</span></div>
                </li>
              ) : null}
              {best ? (
                <li>
                  {worst ? t("cx.glance_best_worst", { best: t(`cx.axis_${best}`), worst: t(`cx.axis_${worst}`) }) : t("cx.glance_best", { best: t(`cx.axis_${best}`) })}
                  <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">
                    <Badge tone="success">{t(`cx.axis_${best}`)} {(axes[best] ?? 0).toFixed(1)}</Badge>
                    {worst ? <Badge tone="warning">{t(`cx.axis_${worst}`)} {(axes[worst] ?? 0).toFixed(1)}</Badge> : null}
                  </span>
                </li>
              ) : null}
              {year === "all" && (stats.ceo != null || stats.growth != null) ? (
                <li className="flex flex-wrap gap-x-5 gap-y-1">
                  {stats.ceo != null ? <span><PeopleDots pct={stats.ceo} n={stats.n} size={7} className="mr-1.5" />{t("cx.glance_ceo", { p: stats.ceo })}</span> : null}
                  {stats.growth != null ? <span><PeopleDots pct={stats.growth} n={stats.n} size={7} className="mr-1.5" />{t("cx.glance_growth", { p: stats.growth })}</span> : null}
                </li>
              ) : null}
              {year === "all" && stats.salary ? <li>{t("cx.glance_salary", { v: fmtManwon(stats.salary.median, locale, t), n: stats.salary.n })}</li> : null}
              {year === "all" && trend ? (
                <li className={cn(trend.d > 0 ? "text-success" : trend.d < 0 ? "text-warning" : "")}>
                  {trend.d > 0 ? t("cx.glance_trend_up", { prev: trend.prev, cur: trend.cur, d: Math.abs(trend.d).toFixed(1) })
                    : trend.d < 0 ? t("cx.glance_trend_down", { prev: trend.prev, cur: trend.cur, d: Math.abs(trend.d).toFixed(1) })
                    : t("cx.glance_trend_flat", { prev: trend.prev, cur: trend.cur })}
                </li>
              ) : null}
              {year === "all" && againTop ? <li>{t("cx.glance_again", { n: againTop.total, k: againYes })}</li> : null}
              {year === "all" && dist ? (
                <li>
                  <div className="mb-1 text-[11px] text-muted-fg">{t("cx.glance_dist")}</div>
                  <div className="space-y-1">
                    {["5", "4", "3", "2", "1"].map((sv) => (
                      <div key={sv} className="flex items-center gap-2 text-xs">
                        <span className="w-6 tabular-nums text-muted-fg">{sv}★</span>
                        <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-warning" style={{ width: `${((dist[sv] ?? 0) / distMax) * 100}%` }} /></span>
                        <span className="w-6 text-right tabular-nums">{dist[sv] ?? 0}</span>
                      </div>
                    ))}
                  </div>
                </li>
              ) : null}
            </ul>
          </div>
        )}
        {year === "all" && factRows.length ? (
          <div className="mt-5 border-t border-border pt-4">
            <div className="mb-2.5 flex items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold">{t("cx.glance_facts")}</h3>
              <span className="text-[11px] text-muted-fg">{t("cx.glance_facts_desc", { n: stats.answered ?? 0 })}</span>
            </div>
            <ul className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
              {factRows.map(({ q, top }) => (
                <li key={q} className="text-sm">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-muted-fg">{factLabel(t, q)}</span>
                    <span className="font-medium">{optionLabel(t, q, top!.opt)} <span className="text-xs font-normal text-muted-fg tabular-nums">{top!.pct}%</span></span>
                  </div>
                  <div className="mt-1 flex h-1.5 w-full gap-px overflow-hidden rounded-full bg-muted">
                    {[...top!.entries].sort((a, b) => b[1] - a[1]).map(([o, n], i) => <span key={o} className={cn("h-full", i === 0 ? "bg-accent" : "bg-border")} style={{ width: `${(n / top!.total) * 100}%` }} title={`${optionLabel(t, q, o)} ${n}`} />)}
                  </div>
                </li>
              ))}
            </ul>
            {fitTop.length || unfitTop.length ? (
              <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
                {fitTop.length ? <div><span className="mr-2 text-muted-fg">{t("cx.glance_fit")}</span>{fitTop.map((f) => <Badge key={f.opt} tone="success" className="mr-1">{fitLabel(t, f.opt)} {f.n}</Badge>)}</div> : null}
                {unfitTop.length ? <div><span className="mr-2 text-muted-fg">{t("cx.glance_unfit")}</span>{unfitTop.map((f) => <Badge key={f.opt} tone="warning" className="mr-1">{fitLabel(t, f.opt)} {f.n}</Badge>)}</div> : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function topFacts(counts: Record<string, number> | undefined, k: number) {
  return Object.entries(counts ?? {}).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]).slice(0, k).map(([opt, n]) => ({ opt, n }));
}

/** No reviews yet: one sentence, one button. Nothing pretends to be data. */
function StatsEmpty({ onWrite }: { onWrite: () => void }) {
  const t = useT();
  return (
    <section className="flex flex-col items-start gap-3 rounded-2xl border border-border bg-card px-6 py-7 shadow-soft sm:flex-row sm:items-center">
      <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/12 text-accent"><PenLine className="h-5 w-5" /></span>
      <div className="min-w-0 flex-1">
        <h3 className="text-[15px] font-semibold">{t("cx.no_stats")}</h3>
        <p className="mt-0.5 text-sm text-muted-fg">{t("cx.no_stats_desc")} {t("cx.form_desc")}</p>
      </div>
      <Button variant="accent" onClick={onWrite} className="shrink-0"><PenLine className="h-4 w-4" />{t("cx.write_review")}</Button>
    </section>
  );
}

// ── 리뷰 ─────────────────────────────────────────────────────────────
function ReviewsTab({ id, years, stats, onWrite }: { id: string; years: string[]; stats: CompanyStats; onWrite: () => void }) {
  const t = useT();
  const [sort, setSort] = useState("helpful"); const [year, setYear] = useState(""); const [job, setJob] = useState(""); const [page, setPage] = useState(1);
  const families = Object.keys(stats.by_job ?? {});
  const meta = useQuery({ queryKey: ["cx", "meta"], queryFn: Companies.meta, staleTime: Infinity, enabled: families.length > 0 });
  const label = (code: string) => meta.data?.job_families.find((f) => f.value === code)?.label ?? code;
  const q = useQuery({
    queryKey: ["cx", "reviews", id, sort, year, job, page],
    queryFn: () => Companies.reviews(id, { sort, year: year ? Number(year) : null, job, page }),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((q.data?.total ?? 0) / (q.data?.size ?? 10)));
  if (!stats.n) return <EmptyState icon={<PenLine />} title={t("cx.reviews_empty")} description={t("cx.no_stats_desc")} action={<Button variant="accent" onClick={onWrite}>{t("cx.write_review")}</Button>} />;
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Segmented size="sm" value={sort} onChange={(v) => { setSort(v); setPage(1); }}
          options={["helpful", "new", "high", "low"].map((s) => ({ value: s, label: t(`cx.sort_${s}`) }))} />
        <Select value={year} onChange={(e) => { setYear(e.target.value); setPage(1); }} className="w-32">
          <option value="">{t("cx.all_years")}</option>{years.map((y) => <option key={y} value={y}>{y}</option>)}
        </Select>
        {families.length ? (
          <Select value={job} onChange={(e) => { setJob(e.target.value); setPage(1); }} className="w-40">
            <option value="">{t("cx.all_jobs")}</option>{families.map((f) => <option key={f} value={f}>{label(f)} ({stats.by_job[f].n})</option>)}
          </Select>
        ) : null}
      </div>
      {q.isLoading ? <Skeleton className="h-64" /> : !q.data?.items.length ? <EmptyState plain icon={<PenLine />} title={t("cx.reviews_filter_empty")} /> : (
        <div className="space-y-3">{q.data.items.map((r) => <ReviewCard key={r.id} r={r} />)}</div>
      )}
      {pages > 1 ? (
        <div className="mt-4 flex items-center justify-center gap-2 text-xs">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>←</Button>
          <span className="tabular-nums text-muted-fg">{page} / {pages}</span>
          <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>→</Button>
        </div>
      ) : null}
    </div>
  );
}

// ── 연봉 ─────────────────────────────────────────────────────────────
function SalaryTab({ id, onWrite }: { id: string; onWrite: () => void }) {
  const t = useT(); const locale = useLocale();
  const q = useQuery({ queryKey: ["cx", "salary", id], queryFn: () => Companies.salary(id) });
  if (q.isLoading) return <Skeleton className="h-64" />;
  const s = q.data?.summary;
  if (!s) return <EmptyState icon={<Wallet />} title={t("cx.salary_empty_tab")} description={t("cx.salary_empty_tab_desc")} action={<Button variant="accent" onClick={onWrite}>{t("cx.write_review")}</Button>} />;
  const bands = Object.entries(s.bands ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const byJob = Object.entries(q.data!.by_job).sort(([, a], [, b]) => b.n - a.n);
  return (
    <div className="space-y-5">
      <Section title={t("cx.salary_title")} description={t("cx.salary_n", { n: s.n })}>
        <div className="grid grid-cols-3 gap-2">
          <Stat label={t("cx.salary_median")} value={fmtManwon(s.median, locale, t)} big />
          <Stat label={t("cx.salary_avg")} value={fmtManwon(s.avg, locale, t)} />
          <Stat label={t("cx.salary_range")} value={`${fmtNumber(s.min)}~${fmtNumber(s.max)}`} />
        </div>
        <div className="mt-5 grid gap-5 md:grid-cols-2">
          {bands.length ? (
            <div>
              <div className="mb-2 text-xs font-semibold text-muted-fg">{t("cx.salary_by_band")}</div>
              <div className="grid grid-cols-2 gap-2">
                {bands.map(([k, v]) => (
                  <div key={k} className="rounded-xl border border-border px-3 py-2.5">
                    <div className="text-[11px] text-muted-fg">{t(`cx.band_${k}`)}<span className="ml-1 tabular-nums">({v.n})</span></div>
                    <div className="mt-0.5 text-sm font-semibold tabular-nums">{fmtManwon(v.median, locale, t)}</div>
                    {v.n > 1 ? <div className="text-[11px] text-muted-fg tabular-nums">{fmtNumber(v.min)}~{fmtNumber(v.max)}</div> : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {byJob.length ? (
            <div>
              <div className="mb-2 text-xs font-semibold text-muted-fg">{t("cx.salary_by_job")}</div>
              <ul className="divide-y divide-border rounded-xl border border-border text-sm">
                {byJob.map(([code, v]) => (
                  <li key={code} className="flex items-center justify-between px-3 py-2">
                    <span>{q.data!.job_labels[code] ?? code}<span className="ml-1 text-xs text-muted-fg">({v.n})</span></span>
                    <span className="font-medium tabular-nums">{fmtManwon(v.salary.median, locale, t)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </Section>
      <div>
        <SectionHeading title={<>{t("cx.salary_reviews")}<span className="ml-1 text-sm font-normal text-muted-fg tabular-nums">{q.data!.total}</span></>} />
        <div className="space-y-3">{q.data!.reviews.map((r) => <ReviewCard key={r.id} r={r} focus="salary" />)}</div>
      </div>
    </div>
  );
}

function Stat({ label, value, big }: { label: string; value: string; big?: boolean }) {
  return (
    <div className="rounded-xl bg-muted/60 px-3 py-3">
      <div className="text-[11px] text-muted-fg">{label}</div>
      <div className={cn("mt-0.5 font-semibold tabular-nums", big ? "text-xl text-accent" : "text-base")}>{value}</div>
    </div>
  );
}

// ── 면접 ─────────────────────────────────────────────────────────────
function InterviewTab({ id, stats, onWrite }: { id: string; stats: CompanyStats; onWrite: () => void }) {
  const t = useT();
  const q = useQuery({ queryKey: ["cx", "reviews", id, "interview"], queryFn: () => Companies.reviews(id, { kind: "interview", sort: "new", size: 50 }) });
  const iv = stats.interview;
  if (!iv?.n) return <EmptyState icon={<MessageCircle />} title={t("cx.interview_empty")} description={t("cx.interview_empty_desc")} action={<Button variant="accent" onClick={onWrite}>{t("cx.write_review")}</Button>} />;
  return (
    <div className="space-y-5">
      <Section title={t("cx.interview_title")} description={t("cx.interview_n", { n: iv.n })}>
        <div className="grid grid-cols-2 gap-2 sm:max-w-md">
          <div className="rounded-xl bg-muted/60 px-3 py-3">
            <div className="text-[11px] text-muted-fg">{t("cx.interview_difficulty")}</div>
            <div className="mt-0.5 flex items-center gap-2"><span className="text-xl font-semibold tabular-nums">{iv.difficulty?.toFixed(1) ?? "–"}</span>{iv.difficulty ? <Badge tone="outline">{t(`cx.difficulty_${Math.round(iv.difficulty)}`)}</Badge> : null}</div>
          </div>
          <div className="rounded-xl bg-muted/60 px-3 py-3">
            <div className="text-[11px] text-muted-fg">{t("cx.interview_pass")}</div>
            <div className="mt-0.5 flex items-center gap-2"><span className="text-xl font-semibold tabular-nums">{iv.pass_rate == null ? "–" : `${iv.pass_rate}%`}</span><PeopleDots pct={iv.pass_rate} n={iv.n} size={8} /></div>
          </div>
        </div>
      </Section>
      {q.isLoading ? <Skeleton className="h-48" /> : <div className="space-y-3">{(q.data?.items ?? []).map((r) => <ReviewCard key={r.id} r={r} focus="interview" />)}</div>}
    </div>
  );
}

// ── 복지 ─────────────────────────────────────────────────────────────
function BenefitsTab({ id, stats, onWrite }: { id: string; stats: CompanyStats; onWrite: () => void }) {
  const t = useT();
  const meta = useQuery({ queryKey: ["cx", "meta"], queryFn: Companies.meta, staleTime: Infinity });
  const q = useQuery({ queryKey: ["cx", "reviews", id, "benefits"], queryFn: () => Companies.reviews(id, { kind: "benefits", sort: "new", size: 50 }) });
  const list = stats.benefits ?? [];
  if (!list.length) return <EmptyState icon={<ThumbsUp />} title={t("cx.benefits_empty")} description={t("cx.benefits_empty_desc")} action={<Button variant="accent" onClick={onWrite}>{t("cx.write_review")}</Button>} />;
  const group = (code: string) => meta.data?.benefits.find((b) => b.code === code)?.group ?? "";
  const groups = new Map<string, { code: string; n: number }[]>();
  for (const b of list) { const g = group(b.code); groups.set(g, [...(groups.get(g) ?? []), b]); }
  const max = Math.max(...list.map((b) => b.n), 1);
  return (
    <div className="space-y-5">
      <Section title={t("cx.benefits_title")}>
        <div className="grid gap-4 sm:grid-cols-2">
          {[...groups.entries()].map(([g, items]) => (
            <div key={g}>
              {g ? <div className="mb-1.5 text-[11px] font-semibold text-muted-fg">{t(`cx.beng_${g}`)}</div> : null}
              <ul className="space-y-1.5">
                {items.map((b) => (
                  <li key={b.code} className="text-sm">
                    <div className="flex items-center justify-between"><span>{benefitLabel(t, b.code)}</span><span className="text-xs text-muted-fg tabular-nums">{t("cx.benefits_n", { n: b.n })}</span></div>
                    <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-success" style={{ width: `${(b.n / max) * 100}%` }} /></div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Section>
      <div>
        <SectionHeading title={<>{t("cx.benefits_reviews")}<span className="ml-1 text-sm font-normal text-muted-fg tabular-nums">{q.data?.total ?? ""}</span></>} />
        {q.isLoading ? <Skeleton className="h-48" /> : <div className="space-y-3">{(q.data?.items ?? []).map((r) => <ReviewCard key={r.id} r={r} focus="benefits" />)}</div>}
      </div>
    </div>
  );
}

// ── 채용 ─────────────────────────────────────────────────────────────
function HiringTab({ id }: { id: string }) {
  const t = useT(); const locale = useLocale(); const router = useRouter();
  const q = useQuery({ queryKey: ["cx", "jobs-of", id], queryFn: () => Companies.jobs(id) });
  if (q.isLoading) return <Skeleton className="h-48" />;
  if (!q.data?.items.length) return <EmptyState icon={<Briefcase />} title={t("cx.hiring_empty")} description={t("cx.hiring_empty_desc")} action={<Button variant="outline" onClick={() => router.push("/app/community/jobs")}>{t("cx.hiring_go")}</Button>} />;
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
      {q.data.items.map((j) => (
        <li key={j.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{j.title}</div>
            <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-muted-fg">
              {j.location ? <span>{j.location}</span> : null}
              {j.job_labels.length ? <span>{j.job_labels.join(", ")}</span> : null}
              <span>{t(`job.type_${j.employment_type}`)}</span>
              <span>{fmtRelative(j.created_at, locale)}</span>
            </div>
          </div>
          {j.salary_min || j.salary_max ? <Badge tone="outline">{fmtNumber(j.salary_min ?? j.salary_max ?? 0)}~{fmtNumber(j.salary_max ?? j.salary_min ?? 0)}</Badge> : null}
          {j.apply_url ? <a href={j.apply_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs text-accent hover:underline">{t("common.open")}<ExternalLink className="h-3 w-3" /></a> : null}
        </li>
      ))}
    </ul>
  );
}

// ── 커뮤니티 ─────────────────────────────────────────────────────────
function CommunityTab({ id }: { id: string }) {
  const t = useT(); const locale = useLocale(); const router = useRouter();
  const q = useQuery({ queryKey: ["cx", "posts-of", id], queryFn: () => Companies.posts(id) });
  if (q.isLoading) return <Skeleton className="h-48" />;
  if (!q.data?.items.length) return <EmptyState icon={<MessageCircle />} title={t("cx.posts_empty")} action={<Button variant="outline" onClick={() => router.push("/app/community/write")}>{t("cx.posts_write")}</Button>} />;
  return (
    <div>
      <p className="mb-3 text-xs text-muted-fg">{t("cx.posts_desc")}</p>
      <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
        {q.data.items.map((p) => (
          <li key={p.id}>
            <Link href={`/app/community/p/${p.id}`} className="block px-4 py-3 hover:bg-muted/60">
              <div className="flex items-center gap-2">{p.board ? <Badge tone="neutral">{p.board}</Badge> : null}<span className="truncate text-sm font-medium">{p.title}</span></div>
              <p className="mt-0.5 line-clamp-1 text-xs text-muted-fg">{p.excerpt}</p>
              <div className="mt-1 flex gap-3 text-[11px] text-muted-fg"><span className="inline-flex items-center gap-1"><ThumbsUp className="h-3 w-3" />{p.like_count}</span><span className="inline-flex items-center gap-1"><MessageCircle className="h-3 w-3" />{p.comment_count}</span><span>{fmtRelative(p.created_at, locale)}</span></div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
