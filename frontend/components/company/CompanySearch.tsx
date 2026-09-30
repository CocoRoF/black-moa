"use client";
import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Briefcase, Building2, ChevronRight, MessageCircle, Search, ThumbsUp } from "@/components/icons";
import { Community, Companies } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { fmtNumber, fmtRelative } from "@/lib/format";
import { Page } from "@/components/owner/Shell";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Tabs } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { CompanyCard, CompanyTile, Pager, SectionHeading, companyHref } from "./shared";
import { CompareTray } from "./CompareTray";

type Tab = "all" | "companies" | "jobs" | "posts";

/** Search results (plan/40 screen 3): one query, three kinds of answer, and a curated
 *  row on top so the page is a place and not just a list. */
export function CompanySearch({ q, initialTab }: { q: string; initialTab?: string }) {
  const t = useT(); const locale = useLocale(); const router = useRouter();
  const [draft, setDraft] = useState(q);
  const [tab, setTab] = useState<Tab>((["all", "companies", "jobs", "posts"].includes(initialTab ?? "") ? initialTab : "all") as Tab);
  const [industry, setIndustry] = useState(""); const [region, setRegion] = useState(""); const [market, setMarket] = useState("");
  const [sort, setSort] = useState("popular"); const [page, setPage] = useState(1);
  useEffect(() => { setDraft(q); setPage(1); }, [q]);

  const all = useQuery({ queryKey: ["cx", "search", q], queryFn: () => Companies.searchAll(q), placeholderData: keepPreviousData });
  const home = useQuery({ queryKey: ["cx", "home"], queryFn: Companies.home, staleTime: 60_000 });
  const tax = useQuery({ queryKey: ["job-taxonomy"], queryFn: Community.jobTaxonomy, staleTime: 600_000 });
  const list = useQuery({
    queryKey: ["cx", "list", q, industry, region, market, sort, page],
    queryFn: () => Companies.list({ q: q.trim(), industry, region, market, sort, page }),
    enabled: tab === "companies", placeholderData: keepPreviousData,
  });
  const jobs = useQuery({ queryKey: ["cx", "jobs", q], queryFn: () => Community.jobs({ q }), enabled: tab === "jobs" });
  const posts = useQuery({ queryKey: ["cx", "posts", q], queryFn: () => Community.posts({ q, limit: 30 }), enabled: tab === "posts" });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    router.push(`/app/community/companies?q=${encodeURIComponent(draft.trim())}${tab !== "all" ? `&tab=${tab}` : ""}`);
  };
  const d = all.data;
  const shelf = home.data?.shelves[0];
  const pages = Math.max(1, Math.ceil((list.data?.total ?? 0) / (list.data?.size ?? 24)));

  return (
    <Page>
      <div className="mb-4 flex items-center gap-2">
        <Link href="/app/community/companies" className="inline-flex items-center gap-1 text-sm text-muted-fg hover:text-fg"><ArrowLeft className="h-4 w-4" />{t("cx.back_home")}</Link>
      </div>
      <form onSubmit={submit} className="relative mb-5">
        <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-fg" />
        <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={t("cx.search_ph")} aria-label={t("cx.search")} className="h-10 rounded-2xl pl-12 pr-24" />
        <Button type="submit" variant="accent" size="sm" className="absolute right-2 top-1/2 -translate-y-1/2">{t("cx.search")}</Button>
      </form>

      {q.trim() ? <h1 className="mb-3 text-xl font-semibold tracking-tight">{t("cx.results_title", { q: q.trim() })}</h1> : null}
      <Tabs value={tab} onChange={setTab} className="mb-5" items={[
        { key: "all", label: t("cx.tab_all") },
        { key: "companies", label: t("cx.tab_companies"), count: d?.companies.total },
        { key: "jobs", label: t("cx.tab_jobs"), count: d ? d.jobs.length : undefined },
        { key: "posts", label: t("cx.tab_posts"), count: d ? d.posts.length : undefined },
      ]} />

      {tab === "all" ? (
        all.isLoading || !d ? <div className="space-y-4"><Skeleton className="h-40" /><Skeleton className="h-64" /></div> : (
          <div className="space-y-9">
            {shelf ? (
              <div className="-mx-4 border-y border-border bg-muted/40 px-4 py-5 md:-mx-6 md:px-6">
                <Pager title={t(`cx.shelf_${shelf.key}`)} hint={t(["hiring", "viewed", "new_listed"].includes(shelf.key) ? "cx.shelf_fact_hint" : "cx.shelf_rated_hint")}
                  items={shelf.items} keyOf={(c) => c.id}
                  render={(c) => <CompanyTile c={c} highlight={["viewed", "new_listed"].includes(shelf.key) ? undefined : shelf.key === "hiring" ? "hiring" : shelf.key} />} />
              </div>
            ) : null}
            <section>
              <SectionTitle icon={<Building2 className="h-4 w-4" />} title={t("cx.companies_n")} n={d.companies.total} />
              {d.companies.items.length ? (
                <>
                  <div className="grid gap-3 md:grid-cols-2">{d.companies.items.map((c) => <CompanyCard key={c.id} c={c} />)}</div>
                  {d.companies.total > d.companies.items.length ? (
                    <div className="mt-4 flex justify-center"><Button variant="outline" onClick={() => setTab("companies")}>{t("cx.more_companies")}<ChevronRight className="h-4 w-4" /></Button></div>
                  ) : null}
                </>
              ) : <EmptyState plain icon={<Building2 />} title={t("cx.no_companies")} description={t("cx.no_companies_desc")} />}
            </section>
            <section>
              <SectionTitle icon={<Briefcase className="h-4 w-4" />} title={t("cx.jobs_n")} n={d.jobs.length} />
              {d.jobs.length ? (
                <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
                  {d.jobs.map((j) => (
                    <li key={j.id}>
                      <Link href={j.company_id ? companyHref(j.company_id, "hiring") : `/app/community/jobs`} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/60">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium">{j.title}</div>
                          <div className="truncate text-xs text-muted-fg">{j.company}{j.location ? ` · ${j.location}` : ""}</div>
                        </div>
                        {j.salary_min || j.salary_max ? <Badge tone="outline">{fmtNumber(j.salary_min ?? j.salary_max ?? 0)}~{fmtNumber(j.salary_max ?? j.salary_min ?? 0)}</Badge> : null}
                        <span className="text-[11px] text-muted-fg">{fmtRelative(j.created_at, locale)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : <EmptyState plain icon={<Briefcase />} title={t("cx.no_jobs")} />}
              <div className="mt-3"><Link href="/app/community/jobs" className="text-sm text-accent hover:underline">{t("cx.more_jobs")}</Link></div>
            </section>
            <section>
              <SectionTitle icon={<MessageCircle className="h-4 w-4" />} title={t("cx.posts_n")} n={d.posts.length} />
              {d.posts.length ? (
                <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
                  {d.posts.map((p) => (
                    <li key={p.id}>
                      <Link href={`/app/community/p/${p.id}`} className="block px-4 py-3 hover:bg-muted/60">
                        <div className="flex items-center gap-2"><Badge tone="neutral">{p.board}</Badge><span className="truncate text-sm font-medium">{p.title}</span></div>
                        <p className="mt-0.5 line-clamp-1 text-xs text-muted-fg">{p.excerpt}</p>
                        <div className="mt-1 flex gap-3 text-[11px] text-muted-fg"><span className="inline-flex items-center gap-1"><ThumbsUp className="h-3 w-3" />{p.like_count}</span><span className="inline-flex items-center gap-1"><MessageCircle className="h-3 w-3" />{p.comment_count}</span><span>{fmtRelative(p.created_at, locale)}</span></div>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : <EmptyState plain icon={<MessageCircle />} title={t("cx.no_posts")} />}
              <div className="mt-3"><Link href={`/app/community?q=${encodeURIComponent(q)}`} className="text-sm text-accent hover:underline">{t("cx.more_posts")}</Link></div>
            </section>
          </div>
        )
      ) : tab === "companies" ? (
        <>
          <div className="mb-4 grid grid-cols-2 gap-2 lg:grid-cols-4">
            <Select value={industry} onChange={(e) => { setIndustry(e.target.value); setPage(1); }}>
              <option value="">{t("co.all_industries")}</option>
              {(tax.data?.industries ?? []).map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
            </Select>
            <Select value={region} onChange={(e) => { setRegion(e.target.value); setPage(1); }}>
              <option value="">{t("co.all_regions")}</option>
              {(tax.data?.regions ?? []).map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </Select>
            <Select value={market} onChange={(e) => { setMarket(e.target.value); setPage(1); }}>
              <option value="">{t("co.all_markets")}</option>
              {["유가", "코스닥", "코넥스"].map((m) => <option key={m} value={m}>{m}</option>)}
            </Select>
            <Select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}>
              {["popular", "rating", "reviews", "follows", "name"].map((s) => <option key={s} value={s}>{t(`cx.sort_${s}`)}</option>)}
            </Select>
          </div>
          {list.isLoading ? <Skeleton className="h-64" /> : !list.data?.items.length ? (
            <EmptyState icon={<Building2 />} title={t("cx.no_companies")} description={t("cx.no_companies_desc")}
              action={<Button variant="outline" onClick={() => { setIndustry(""); setRegion(""); setMarket(""); setPage(1); }}>{t("co.clear")}</Button>} />
          ) : (
            <>
              <div className="mb-2 text-xs text-muted-fg tabular-nums">{t("co.count", { n: fmtNumber(list.data.total) })}</div>
              <div className="grid gap-3 md:grid-cols-2">{list.data.items.map((c) => <CompanyCard key={c.id} c={c} />)}</div>
              {pages > 1 ? (
                <div className="mt-4 flex items-center justify-center gap-2 text-xs">
                  <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>←</Button>
                  <span className="self-center tabular-nums text-muted-fg">{page} / {fmtNumber(pages)}</span>
                  <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>→</Button>
                </div>
              ) : null}
            </>
          )}
        </>
      ) : tab === "jobs" ? (
        jobs.isLoading ? <Skeleton className="h-48" /> : !jobs.data?.items.length ? <EmptyState icon={<Briefcase />} title={t("cx.no_jobs")} action={<Button variant="outline" onClick={() => router.push("/app/community/jobs")}>{t("cx.hiring_go")}</Button>} /> : (
          <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
            {jobs.data.items.map((j) => (
              <li key={j.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <Link href={j.company_id ? companyHref(j.company_id, "hiring") : "/app/community/jobs"} className="block truncate text-sm font-medium hover:text-accent">{j.title}</Link>
                  <div className="truncate text-xs text-muted-fg">{j.company_info?.name ?? j.company}{j.location ? ` · ${j.location}` : ""}{j.job_labels.length ? ` · ${j.job_labels.join(", ")}` : ""}</div>
                </div>
                {j.salary_min || j.salary_max ? <Badge tone="outline">{fmtNumber(j.salary_min ?? j.salary_max ?? 0)}~{fmtNumber(j.salary_max ?? j.salary_min ?? 0)}</Badge> : null}
                {j.apply_url ? <a href={j.apply_url} target="_blank" rel="noreferrer noopener" className="text-xs text-accent hover:underline">{t("common.open")}</a> : null}
              </li>
            ))}
          </ul>
        )
      ) : (
        posts.isLoading ? <Skeleton className="h-48" /> : !posts.data?.items.length ? <EmptyState icon={<MessageCircle />} title={t("cx.no_posts")} /> : (
          <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
            {posts.data.items.map((p) => (
              <li key={p.id}>
                <Link href={`/app/community/p/${p.id}`} className="block px-4 py-3 hover:bg-muted/60">
                  <div className="flex items-center gap-2">{p.board ? <Badge tone="neutral">{p.board.name}</Badge> : null}<span className="truncate text-sm font-medium">{p.title}</span></div>
                  <p className="mt-0.5 line-clamp-1 text-xs text-muted-fg">{p.excerpt}</p>
                  <div className="mt-1 flex gap-3 text-[11px] text-muted-fg"><span className="inline-flex items-center gap-1"><ThumbsUp className="h-3 w-3" />{p.like_count}</span><span className="inline-flex items-center gap-1"><MessageCircle className="h-3 w-3" />{p.comment_count}</span><span>{fmtRelative(p.created_at, locale)}</span></div>
                </Link>
              </li>
            ))}
          </ul>
        )
      )}
      <CompareTray />
    </Page>
  );
}

function SectionTitle({ icon, title, n }: { icon: React.ReactNode; title: string; n: number }) {
  return <SectionHeading icon={icon} title={<>{title}<span className="ml-1 text-sm font-normal text-muted-fg tabular-nums">{fmtNumber(n)}</span></>} />;
}
