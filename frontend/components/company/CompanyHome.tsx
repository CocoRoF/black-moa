"use client";
import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Building2, ChevronRight, Clock, Flame, Landmark, PenLine, Search, ShieldCheck, Sparkles, Star, TrendingUp, Users, Wallet } from "@/components/icons";
import { Companies, type AreaPick, type Axis, type CompanyReview } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { fmtNumber, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Tabs } from "@/components/ui/tabs";
import { coverFallback } from "@/components/profile/ProfileHeader";
import { CompanyCard, CompanyLogo, CompanyTile, Pager, SectionHeading, Stars, cleanName, companyHref, optionLabel } from "./shared";
import { CompareTray } from "./CompareTray";

/** The first screen of 기업정보 (plan/40 §1): a dashboard, not a list.
 *
 *  Who is popular, where pay gets talked about, what touches the reader's own job — and a
 *  search box to reach the other five thousand. Every row is honest about where it comes
 *  from: rated shelves need enough reviews to mean anything; until then the exchange's own
 *  facts (hiring, newly listed, most viewed) keep the page from opening on nothing. */
export function CompanyHome() {
  const t = useT(); const router = useRouter();
  const [q, setQ] = useState("");
  const home = useQuery({ queryKey: ["cx", "home"], queryFn: Companies.home, staleTime: 60_000 });
  const [mineTab, setMineTab] = useState<"for_me" | "following" | "my_company">("for_me");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const s = q.trim();
    if (s) router.push(`/app/community/companies?q=${encodeURIComponent(s)}`);
  };

  const d = home.data;
  return (
    <Page>
      {/* The hero: Memora's own cover, the title, and the one control that matters. */}
      <section className="relative mb-8 overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
        <div className="absolute inset-x-0 top-0 h-[104px]" style={{ background: coverFallback() }} aria-hidden />
        <div className="relative px-5 pb-5 pt-6 md:px-8 md:pb-7 md:pt-8">
          <div className="text-xs font-medium text-white/80">{t("cx.hero_eyebrow")}</div>
          <h1 className="mt-1 inline-flex items-center gap-2 text-2xl font-semibold tracking-tight text-white md:text-3xl"><Building2 className="h-6 w-6" />{t("cx.title")}</h1>
          <form onSubmit={submit} className="relative mt-5">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-fg" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("cx.search_ph")} aria-label={t("cx.search")}
              className="h-14 rounded-2xl border-border/60 pl-12 pr-24 text-base shadow-md" />
            <Button type="submit" variant="accent" size="sm" className="absolute right-2 top-1/2 -translate-y-1/2">{t("cx.search")}</Button>
          </form>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-xs text-muted-fg">
            <span>{t("cx.search_hint")}</span>
            {d ? (
              <span className="ml-auto inline-flex items-center gap-3 tabular-nums">
                <span><b className="font-semibold text-fg">{fmtNumber(d.totals.companies)}</b> {t("cx.stat_companies")}</span>
                <span><b className="font-semibold text-fg">{fmtNumber(d.totals.reviews)}</b> {t("cx.stat_reviews")}</span>
              </span>
            ) : null}
          </div>
        </div>
      </section>

      {home.isLoading || !d ? (
        <div className="space-y-8"><Skeleton className="h-44" /><Skeleton className="h-56" /><Skeleton className="h-64" /></div>
      ) : (
        <div className="space-y-10">
          {/* 인기 */}
          <Pager title={t("cx.popular")} hint={t("cx.popular_desc")} icon={<Flame className="h-4 w-4 text-danger" />}
            action={<Link href="/app/community/companies?q=&tab=companies" className="mr-2 text-xs text-muted-fg hover:text-fg">{t("cx.see_all")}</Link>}
            items={d.popular} keyOf={(c) => c.id} render={(c, i) => <CompanyTile c={c} rank={i + 1} />} />

          {/* 우리 다섯 영역, 영역마다 TOP 회사 */}
          <section>
            <SectionHeading eyebrow={t("cx.areas_desc")} title={t("cx.areas_title")} icon={<Sparkles className="h-4 w-4 text-accent" />} />
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {d.areas.map((a) => <AreaBoard key={a.key} area={a.key} items={a.items} onWrite={d.popular[0] ? () => router.push(`${companyHref(d.popular[0].id)}/review`) : undefined} />)}
              <div className="flex flex-col justify-center rounded-2xl border border-dashed border-border px-5 py-6 text-sm text-muted-fg">
                <div className="font-medium text-fg">{t("cx.areas_how")}</div>
                <p className="mt-1">{t("cx.areas_how_desc")}</p>
              </div>
            </div>
          </section>

          {/* 내 직군 / 팔로우 / 내 회사 */}
          <section className="rounded-2xl border border-border bg-card shadow-soft">
            <Tabs value={mineTab} onChange={setMineTab} className="px-3 pt-1" items={[
              { key: "for_me", label: t("cx.tab_for_me"), count: d.for_me.items.length || undefined },
              { key: "following", label: t("cx.tab_following"), count: d.following.length || undefined },
              { key: "my_company", label: t("cx.tab_my_company") },
            ]} />
            <div className="p-4 md:p-5">
              {mineTab === "for_me" ? (
                d.for_me.needs_profile ? (
                  <Hero title={t("cx.for_me_title")} description={t("cx.for_me_needs")}
                    action={<Button variant="accent" onClick={() => router.push("/app/profile")}>{t("cx.for_me_set")}<ChevronRight className="h-4 w-4" /></Button>} />
                ) : d.for_me.items.length ? (
                  <>
                    <div className="mb-3 text-sm text-muted-fg">{t("cx.for_me_sub", { jobs: (d.for_me.job_labels ?? []).join("·") })}</div>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{d.for_me.items.map((c) => <CompanyCard key={c.id} c={c} />)}</div>
                  </>
                ) : (
                  <EmptyState plain icon={<Sparkles />} title={t("cx.for_me_empty")} description={t("cx.for_me_empty_desc")} />
                )
              ) : mineTab === "following" ? (
                d.following.length ? (
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{d.following.map((c) => <CompanyCard key={c.id} c={c} />)}</div>
                ) : (
                  <EmptyState plain icon={<Star />} title={t("cx.following_empty")} description={t("cx.following_empty_desc")} />
                )
              ) : (
                !d.my_company ? (
                  <Hero title={t("cx.tab_my_company")} description={t("cx.my_company_empty")}
                    action={<Button variant="accent" onClick={() => router.push("/app/profile")}>{t("cx.set_company")}<ChevronRight className="h-4 w-4" /></Button>} />
                ) : d.my_company.company ? (
                  <div>
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-fg">
                      {d.my_company.verified
                        ? <span className="inline-flex items-center gap-1 text-success"><ShieldCheck className="h-3.5 w-3.5" />{t("cx.my_company_verified")}</span>
                        : <span>{t("cx.my_company_unverified")}</span>}
                      {!d.my_company.verified ? <Button size="sm" variant="outline" onClick={() => router.push("/app/profile")}>{t("cx.verify_company")}<ChevronRight className="h-3.5 w-3.5" /></Button> : null}
                    </div>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3"><CompanyCard c={d.my_company.company} /></div>
                  </div>
                ) : (
                  <EmptyState plain icon={<Building2 />} title={t("cx.my_company_unmatched", { name: d.my_company.name })} description={t("cx.my_company_unmatched_desc")}
                    action={<Button variant="outline" onClick={() => router.push(`/app/community/companies?q=${encodeURIComponent(cleanName(d.my_company!.name))}`)}>{t("cx.find_it")}</Button>} />
                )
              )}
            </div>
          </section>

          {/* 최근 리뷰 */}
          <section>
            <SectionHeading eyebrow={t("cx.recent_reviews_desc")} title={t("cx.recent_reviews")} icon={<PenLine className="h-4 w-4 text-accent" />} />
            {d.recent_reviews.length ? (
              <ul className="grid gap-3 md:grid-cols-2">{d.recent_reviews.map((r) => <RecentReview key={r.id} r={r} />)}</ul>
            ) : (
              <EmptyState plain icon={<PenLine />} title={t("cx.no_stats")} description={t("cx.no_stats_desc")}
                action={d.popular[0] ? <Button variant="outline" onClick={() => router.push(`${companyHref(d.popular[0].id)}/review`)}>{t("cx.write_first")}</Button> : undefined} />
            )}
          </section>
        </div>
      )}
      <CompareTray />
    </Page>
  );
}

const AREA_ICON: Record<Axis, React.ReactNode> = {
  pay: <Wallet className="h-4 w-4" />, balance: <Clock className="h-4 w-4" />, culture: <Users className="h-4 w-4" />,
  promotion: <TrendingUp className="h-4 w-4" />, management: <Landmark className="h-4 w-4" />,
};

/** One area's board: the five companies people rate highest for it, each with its score
 *  and the fact that headlines the area ("급여 업계보다 높아요 · 80%"). The count is
 *  always shown, so a 5.0 from one person reads as what it is. */
function AreaBoard({ area, items, onWrite }: { area: Axis; items: AreaPick[]; onWrite?: () => void }) {
  const t = useT();
  const label = t(`cx.axis_${area}`);
  return (
    <section className="flex flex-col rounded-2xl border border-border bg-card shadow-soft">
      <div className="flex items-center gap-2 px-4 pt-4">
        <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-accent/12 text-accent">{AREA_ICON[area]}</span>
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold">{t("cx.area_top", { area: label })}</h3>
          <div className="text-[11px] text-muted-fg">{t(`cx.axis_hint_${area}`)}</div>
        </div>
      </div>
      {items.length ? (
        <ol className="mt-3 flex-1 divide-y divide-border">
          {items.map((c, i) => (
            <li key={c.id}>
              <Link href={companyHref(c.id)} className="flex items-center gap-3 px-4 py-2.5 transition hover:bg-muted/60">
                <span className={cn("w-5 text-center text-sm font-bold tabular-nums", i === 0 ? "text-accent" : "text-muted-fg")}>{i + 1}</span>
                <CompanyLogo size={32} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2"><span className="truncate text-sm font-medium">{c.name}</span><span className="shrink-0 text-[11px] text-muted-fg">{t("cx.reviews_n", { n: c.review_count })}</span></div>
                  <div className="truncate text-[11px] text-muted-fg">{c.fact ? <>{optionLabel(t, c.fact.question, c.fact.option)} <span className="tabular-nums">{c.fact.pct}%</span></> : c.industry_text}</div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-sm font-semibold tabular-nums">{c.score.toFixed(1)}</div>
                  <div className="mt-0.5 h-1 w-12 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-success" style={{ width: `${(c.score / 5) * 100}%` }} /></div>
                </div>
              </Link>
            </li>
          ))}
        </ol>
      ) : (
        <div className="mx-4 mb-4 mt-3 flex flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-border px-4 py-6 text-center">
          <div className="text-sm font-medium">{t("cx.area_empty", { area: label })}</div>
          <div className="mt-0.5 text-xs text-muted-fg">{t("cx.area_empty_desc")}</div>
          {onWrite ? <Button size="sm" variant="outline" className="mt-3" onClick={onWrite}>{t("cx.write_first")}</Button> : null}
        </div>
      )}
    </section>
  );
}

function Hero({ title, description, action }: { title: string; description: string; action: React.ReactNode }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-dashed border-border bg-muted/40 px-6 py-10 text-center">
      <span className="mx-auto mb-3 block h-1.5 w-20 rounded-full bg-gradient-to-r from-brand-sky to-brand-violet" aria-hidden />
      <h3 className="text-lg font-semibold tracking-tight">{title}</h3>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-fg">{description}</p>
      <div className="mt-5 flex justify-center">{action}</div>
    </div>
  );
}

function RecentReview({ r }: { r: CompanyReview }) {
  const t = useT(); const locale = useLocale();
  return (
    <li>
      <Link href={companyHref(r.company_id, "reviews")} className={cn("flex gap-3 rounded-2xl border border-border bg-card p-3.5 shadow-soft transition hover:border-accent/40")}>
        <CompanyLogo size={40} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2"><span className="truncate text-sm font-semibold">{r.company?.name}</span><Stars value={r.rating} size={12} /><span className="text-xs font-semibold tabular-nums">{r.rating.toFixed(1)}</span></div>
          <div className="mt-0.5 line-clamp-1 text-sm">{r.title}</div>
          <div className="mt-1 text-[11px] text-muted-fg">
            {[r.family_label, t(`cx.employment_${r.employment}`), `${r.work_year}`].filter(Boolean).join(" · ")} · {fmtRelative(r.created_at, locale)}
          </div>
        </div>
      </Link>
    </li>
  );
}
