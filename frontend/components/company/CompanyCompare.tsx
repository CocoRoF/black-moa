"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowLeftRight, X } from "@/components/icons";
import { Companies, type Axis, type CompareItem } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { fmtNumber } from "@/lib/format";
import { COMPARE_MAX, compareStore, useCompare } from "@/lib/compare";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Button, buttonLook } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { PageHeader } from "@/components/ui/misc";
import { AXES, CompanyLogo, FACT_QUESTIONS, FollowButton, RatingLine, benefitLabel, companyHref, factLabel, fmtManwon, optionLabel, tagLabel, topFact, yearsSince } from "./shared";

/** Companies side by side (plan/40 §7). Rows are what people ask when they weigh two
 *  offers; the best value in each row is marked, so the table reads without arithmetic. */
export function CompanyCompare() {
  const t = useT(); const locale = useLocale();
  const params = useSearchParams();
  const tray = useCompare();
  const ids = (params.get("ids") ?? "").split(",").map((s) => s.trim()).filter(Boolean).slice(0, COMPARE_MAX);
  const useIds = ids.length ? ids : tray.map((p) => p.id);
  const q = useQuery({ queryKey: ["cx", "compare", useIds.join(",")], queryFn: () => Companies.compare(useIds), enabled: useIds.length > 0 });
  const items = q.data?.items ?? [];

  const best = (pick: (c: CompareItem) => number | null | undefined, higher = true) => {
    const vals = items.map(pick).map((v) => (v == null ? null : Number(v)));
    const present = vals.filter((v): v is number => v != null);
    if (present.length < 2) return -1;
    const target = higher ? Math.max(...present) : Math.min(...present);
    return present.filter((v) => v === target).length === 1 ? vals.indexOf(target) : -1;
  };
  const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v)}%`);
  const rows: { key: string; label: string; cell: (c: CompareItem) => React.ReactNode; best?: number }[] = [
    { key: "rating", label: t("cx.cmp_rating"), cell: (c) => <RatingLine value={c.stats.rating} count={c.stats.n} size="md" showCount />, best: best((c) => (c.stats.n ? c.stats.rating : null)) },
    ...AXES.map((a: Axis) => ({ key: a, label: t(`cx.axis_${a}`), cell: (c: CompareItem) => <AxisCell v={c.stats.axes?.[a]} />, best: best((c) => c.stats.axes?.[a] ?? null) })),
    { key: "recommend", label: t("cx.cmp_recommend"), cell: (c) => pct(c.stats.recommend), best: best((c) => c.stats.recommend) },
    { key: "ceo", label: t("cx.cmp_ceo"), cell: (c) => pct(c.stats.ceo), best: best((c) => c.stats.ceo) },
    { key: "growth", label: t("cx.cmp_growth"), cell: (c) => pct(c.stats.growth), best: best((c) => c.stats.growth) },
    { key: "salary", label: t("cx.cmp_salary"), cell: (c) => c.stats.salary ? <span>{fmtManwon(c.stats.salary.median, locale, t)}<span className="ml-1 text-xs text-muted-fg">({c.stats.salary.n})</span></span> : "–", best: best((c) => c.stats.salary?.median) },
    { key: "interview", label: t("cx.cmp_interview"), cell: (c) => c.stats.interview?.difficulty ? `${c.stats.interview.difficulty.toFixed(1)} · ${t(`cx.difficulty_${Math.round(c.stats.interview.difficulty)}`)}` : "–" },
    { key: "pass", label: t("cx.cmp_pass"), cell: (c) => pct(c.stats.interview?.pass_rate), best: best((c) => c.stats.interview?.pass_rate) },
    ...FACT_QUESTIONS.slice(0, 6).map((q) => ({ key: `fact_${q}`, label: factLabel(t, q), cell: (c: CompareItem) => { const top = topFact(c.stats.facts?.[q]); return top ? <span>{optionLabel(t, q, top.opt)} <span className="text-xs text-muted-fg tabular-nums">{top.pct}%</span></span> : "–"; } })),
    { key: "benefits", label: t("cx.cmp_benefits"), cell: (c) => c.stats.benefits.length ? <div className="flex flex-wrap gap-1">{c.stats.benefits.slice(0, 5).map((b) => <Badge key={b} tone="neutral">{benefitLabel(t, b)}</Badge>)}</div> : "–" },
    { key: "hiring", label: t("cx.cmp_hiring"), cell: (c) => <span className={c.open_jobs ? "font-medium text-accent" : ""}>{t("cx.hiring_n", { n: c.open_jobs })}</span>, best: best((c) => c.open_jobs) },
    { key: "employees", label: t("cx.cmp_employees"), cell: (c) => c.employees ? t("cx.employees", { n: fmtNumber(c.employees) }) : "–", best: best((c) => c.employees) },
    { key: "age", label: t("cx.cmp_age"), cell: (c) => { const a = yearsSince(c.founded_on, c.listed_on); return a ? t("cx.years_since", { n: a.n, y: a.y }) : "–"; } },
    { key: "market", label: t("cx.cmp_market"), cell: (c) => c.market ? `${c.market}${c.stock_code ? ` · ${c.stock_code}` : ""}` : "–" },
    { key: "followers", label: t("cx.cmp_followers"), cell: (c) => fmtNumber(c.follow_count), best: best((c) => c.follow_count) },
  ];

  return (
    <Page>
      <Link href="/app/community/companies" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-fg hover:text-fg"><ArrowLeft className="h-4 w-4" />{t("cx.back_home")}</Link>
      <PageHeader title={t("cx.compare_title")} description={t("cx.compare_desc")}
        lead={<span className="mr-1 inline-flex h-9 w-9 items-center justify-center rounded-xl bg-accent/12 text-accent"><ArrowLeftRight className="h-5 w-5" /></span>}
        action={items.length ? <Button variant="outline" onClick={() => compareStore.clear()}>{t("cx.compare_clear")}</Button> : undefined} />
      {!useIds.length ? (
        <EmptyState icon={<ArrowLeftRight />} title={t("cx.compare_empty")} description={t("cx.compare_empty_desc", { n: COMPARE_MAX })}
          action={<Link href="/app/community/companies" className={buttonLook("accent", "md")}>{t("cx.back_home")}</Link>} />
      ) : q.isLoading ? <Skeleton className="h-96" /> : (
        <div className="overflow-x-auto rounded-2xl border border-border bg-card shadow-soft">
          <table className="w-full min-w-[640px] border-collapse text-sm">
            <thead>
              <tr className="align-top">
                <th className="w-40 border-b border-border px-4 py-4 text-left text-xs font-semibold text-muted-fg" />
                {items.map((c) => (
                  <th key={c.id} className="border-b border-l border-border px-4 py-4 text-left font-normal">
                    <div className="flex items-start gap-2.5">
                      <CompanyLogo size={40} />
                      <div className="min-w-0 flex-1">
                        <Link href={companyHref(c.id)} className="block truncate text-[15px] font-semibold hover:text-accent">{c.name}</Link>
                        <div className="truncate text-xs text-muted-fg">{[c.industry_text, c.region_text].filter(Boolean).join(" · ")}</div>
                        {c.tags.length ? <div className="mt-1.5 flex flex-wrap gap-1">{c.tags.slice(0, 3).map((x) => <Badge key={x} tone="neutral">{tagLabel(t, x)}</Badge>)}</div> : null}
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          <FollowButton id={c.id} following={c.following} count={c.follow_count} />
                          <Button size="sm" variant="ghost" aria-label={t("common.delete")} onClick={() => compareStore.remove(c.id)}><X className="h-4 w-4" /></Button>
                        </div>
                      </div>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className="border-b border-border last:border-b-0">
                  <th scope="row" className="px-4 py-3 text-left text-xs font-medium text-muted-fg">{r.label}</th>
                  {items.map((c, i) => (
                    <td key={c.id} className={cn("border-l border-border px-4 py-3 tabular-nums", r.best === i && "bg-success/8 font-semibold")}>{r.cell(c)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Page>
  );
}

function AxisCell({ v }: { v?: number }) {
  if (!v) return <span>–</span>;
  return (
    <div className="flex items-center gap-2">
      <span className="w-8">{v.toFixed(1)}</span>
      <span className="h-1.5 w-20 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-success" style={{ width: `${(v / 5) * 100}%` }} /></span>
    </div>
  );
}
