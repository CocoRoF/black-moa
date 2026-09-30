"use client";
import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Building2, Check, Download, ExternalLink, KeyRound, Loader2, Mail, Plus, Search, ShieldCheck, Trash2, X } from "@/components/icons";
import { Admin, Community, type CompanyDomain, type CompanyRow, type CompanySources } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtDateTime, fmtNumber, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Select } from "@/components/ui/input";
import { Switch, SwitchRow } from "@/components/ui/switch";
import { Section } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { PageHeader, Progress, Stat } from "@/components/ui/misc";
import { Segmented } from "@/components/ui/tabs";

type Tab = "setup" | "log" | "list" | "domains";

const MARKETS = ["유가", "코스닥", "코넥스"];

function useSources() {
  return useQuery({ queryKey: ["admin", "companies", "sources"], queryFn: Admin.companySources,
                    refetchInterval: 15_000, placeholderData: keepPreviousData });
}

/** 기업정보 — three tabs, because the page answers three unrelated questions.
 *
 *  One scrolling page mixed "is it configured", "is it working" and "what did it collect".
 *  That shape buries the middle question, and for a batch collector the middle question is
 *  the whole point: an operator looking at this page is usually asking whether a
 *  collection is running right now. */
export function CompaniesPage() {
  const t = useT();
  const [tab, setTab] = useState<Tab>("setup");
  return (
    <Page>
      <PageHeader title={t("adm.companies")} description={t("adm.companies_desc")}
        action={<Segmented value={tab} onChange={(v) => setTab(v as Tab)} options={[
          { value: "setup", label: t("adm.co_tab_setup") },
          { value: "log", label: t("adm.co_tab_log") },
          { value: "list", label: t("adm.co_tab_list") },
          { value: "domains", label: t("adm.co_tab_domains") },
        ]} />} />
      {tab === "setup" ? <Setup /> : tab === "log" ? <Log /> : tab === "domains" ? <Domains /> : <Directory />}
    </Page>
  );
}

// ── 수집 설정 ────────────────────────────────────────────────────────

function Setup() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [perRun, setPerRun] = useState<string | null>(null);
  const src = useSources();

  const save = useMutation({
    mutationFn: (v: Record<string, unknown>) => Admin.putSettings(v),
    onSuccess: () => {
      toast.success(t("common.saved")); setKeys({}); setPerRun(null);
      qc.invalidateQueries({ queryKey: ["admin", "companies"] });
      // 기업 기능을 켜고 끄면 이 화면의 탭·프로필도 곧바로 따라간다 (plan/71).
      qc.invalidateQueries({ queryKey: ["auth-status"] });
      qc.invalidateQueries({ queryKey: ["profile"] });
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const collect = useMutation({
    mutationFn: (source: string) => Admin.collectCompanies(source),
    onSuccess: () => { toast.success(t("adm.co_queued")); qc.invalidateQueries({ queryKey: ["admin", "companies"] }); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  const d = src.data;
  if (!d) return <Skeleton className="h-72" />;
  const c = d.coverage;

  return (
    <div className="space-y-4">
      {/* 기업 기능 전체의 스위치 (plan/71). 수집과는 따로다 — 꺼도 관리자는 여기서 목록을 모으고 볼 수 있다. */}
      <Section title={t("adm.co_feature")} description={t("adm.co_feature_desc")}
        action={<Badge tone={d.enabled ? "success" : "neutral"}>{t(d.enabled ? "adm.co_feature_on" : "adm.co_feature_off")}</Badge>}>
        <SwitchRow title={t("adm.co_enabled")} description={t(d.enabled ? "adm.co_enabled_on" : "adm.co_enabled_off")}
          checked={d.enabled} disabled={save.isPending} onChange={(v) => save.mutate({ "companies.enabled": v })} />
      </Section>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={t("adm.co_total")} value={fmtNumber(c.total)} icon={<Building2 />} />
        <Stat label={t("adm.co_f_visible")} value={fmtNumber(c.visible)} hint={t("adm.co_visible_hint")} />
        <Stat label={t("adm.co_f_listed")} value={fmtNumber(c.listed)} />
        <Stat label={t("adm.co_f_closed")} value={fmtNumber(c.fields.closed)}
              className={c.fields.closed ? "border-warning/40" : ""} />
      </div>

      {/* Completeness, which is the number that tells you what to run next. Size does not. */}
      <Section title={t("adm.co_coverage")} description={t("adm.co_coverage_desc")}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Object.keys(c.filled_by).map((field) => {
            const pct = c.pct[field] ?? 0;
            const by = c.filled_by[field];
            const s = d.sources.find((x) => x.source === by);
            return (
              <div key={field} className="rounded-xl border border-border p-3">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-medium">{t(`adm.co_f_${field}`)}</span>
                  <span className="tabular-nums text-xs text-muted-fg">
                    {fmtNumber(c.fields[field])} / {fmtNumber(c.of[field] ?? 0)} · {pct}%
                  </span>
                </div>
                <Progress className="mt-1.5" value={pct} max={100}
                  tone={pct >= 95 ? "success" : pct >= 50 ? "accent" : "warning"} />
                <div className="mt-1 text-[11px] text-muted-fg">
                  {s && !s.key_set ? t("adm.co_gap_needs", { label: s.label }) : t("adm.co_gap_from", { label: s?.label ?? by })}
                  {c.of[field] !== c.total ? <span className="ml-1">· {t("adm.co_of_listed")}</span> : null}
                </div>
              </div>
            );
          })}
        </div>
      </Section>

      <Section title={t("adm.co_sources")} description={t("adm.co_sources_desc")}
        action={
          <label className="flex items-center gap-2 text-xs text-muted-fg">
            {t("adm.co_auto")}
            <Switch checked={d.auto_collect} label={t("adm.co_auto")}
              onChange={(v) => save.mutate({ "companies.auto_collect": v })} />
          </label>
        }>
        <div className="space-y-3">
          {d.sources.map((s) => (
            <SourceCard key={s.source} s={s} perRun={perRun} setPerRun={setPerRun} keys={keys} setKeys={setKeys}
              dartPerRun={d.dart_per_run} dailyLimit={d.dart_daily_limit} spentToday={d.dart_spent_today}
              remaining={Math.max(0, (c.of.biz_no ?? 0) - (c.fields.biz_no ?? 0))}
              onSave={(v) => save.mutate(v)} saving={save.isPending}
              onCollect={() => collect.mutate(s.source)} collecting={collect.isPending && collect.variables === s.source} />
          ))}
        </div>
      </Section>
    </div>
  );
}

function SourceCard({ s, keys, setKeys, perRun, setPerRun, dartPerRun, dailyLimit, spentToday, remaining, onSave, saving, onCollect, collecting }: {
  s: CompanySources["sources"][number];
  keys: Record<string, string>; setKeys: (v: Record<string, string>) => void;
  perRun: string | null; setPerRun: (v: string) => void;
  dartPerRun: number; dailyLimit: number; spentToday: number; remaining: number;
  onSave: (v: Record<string, unknown>) => void; saving: boolean;
  onCollect: () => void; collecting: boolean;
}) {
  const t = useT(); const locale = useLocale();
  const r = s.last_run;
  const blocked = !s.key_set;
  const running = !!r?.running;
  const failed = !blocked && !running && r && r.ok === false;
  const per = Number(perRun ?? dartPerRun) || 0;
  // A day can only ever spend the allowance, however large the per-run number is, so the
  // estimate is based on the smaller of the two. Using per_run alone promised a 20,000-a-day
  // pace the allowance does not permit.
  const perDay = Math.min(per, dailyLimit) || 0;
  const days = perDay && remaining ? Math.ceil(remaining / perDay) : 0;
  const leftToday = Math.max(0, dailyLimit - spentToday);

  return (
    <div className={cn("rounded-xl border p-3", failed ? "border-danger/40 bg-danger/5"
      : blocked ? "border-warning/30 bg-warning/5" : running ? "border-accent/40 bg-accent/5" : "border-border")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{s.label}</span>
        {s.needs_key === null ? <Badge tone="success">{t("adm.co_no_key")}</Badge>
          : s.key_set ? <Badge tone="success"><Check className="h-3 w-3" />{t("adm.co_key_set")}</Badge>
            : <Badge tone="warning"><X className="h-3 w-3" />{t("adm.co_key_missing")}</Badge>}
        {running ? <Badge tone="accent"><Loader2 className="h-3 w-3 animate-spin" />{t("adm.co_running")}</Badge> : null}
        <Button className="ml-auto" size="sm" variant="outline" disabled={blocked || running} loading={collecting}
          onClick={onCollect}><Download className="h-4 w-4" />{t("adm.co_collect")}</Button>
      </div>
      <div className="mt-1 text-xs text-muted-fg">{s.note}</div>

      {s.needs_key ? (
        <div className="mt-2.5">
          <div className="mb-1 inline-flex items-center gap-1 text-xs text-muted-fg">
            <KeyRound className="h-3.5 w-3.5" /><code className="font-mono">{s.needs_key}</code>
          </div>
          <div className="flex items-center gap-2">
            <Input className="flex-1" type="password" autoComplete="off"
              placeholder={s.key_set ? "••••••••" : t("adm.co_key_placeholder")}
              value={keys[s.needs_key] ?? ""}
              onChange={(e) => setKeys({ ...keys, [s.needs_key!]: e.target.value })} />
            <Button className="shrink-0" loading={saving} disabled={!keys[s.needs_key]}
              onClick={() => onSave({ [s.needs_key!]: keys[s.needs_key!] })}>{t("common.save")}</Button>
          </div>
          {s.where ? (
            <a href={s.where.split(" ")[0]} target="_blank" rel="noreferrer noopener"
              className="mt-1 inline-block text-xs text-muted-fg underline">{s.where}</a>
          ) : null}
        </div>
      ) : null}

      {s.source === "dart" ? (
        <div className="mt-2.5 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-fg">{t("adm.co_per_run")}</span>
            <Input className="w-28" type="number" min={100} max={20000} step={100}
              value={perRun ?? String(dartPerRun)} onChange={(e) => setPerRun(e.target.value)} />
            <Button size="sm" variant="outline" loading={saving}
              disabled={perRun === null || Number(perRun) === dartPerRun}
              onClick={() => onSave({ "companies.dart_per_run": Number(perRun) })}>{t("common.save")}</Button>
            <span className="text-[11px] text-muted-fg">{t("adm.co_per_run_hint", { limit: fmtNumber(dailyLimit) })}</span>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px] tabular-nums">
            <span className={leftToday ? "text-muted-fg" : "text-warning"}>
              {t("adm.co_today", { spent: fmtNumber(spentToday), limit: fmtNumber(dailyLimit), left: fmtNumber(leftToday) })}
            </span>
            <Progress className="h-1.5 w-32" value={spentToday} max={dailyLimit}
              tone={leftToday ? "accent" : "warning"} />
          </div>
          {/* What the number means in days — arithmetic an operator should not have to do
              in their head after choosing it. */}
          {days ? (
            <div className={cn("text-[11px] tabular-nums", days > 120 ? "text-warning" : "text-muted-fg")}>
              {t("adm.co_per_run_eta", { left: fmtNumber(remaining), days: fmtNumber(days) })}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-2 text-xs tabular-nums">
        {!r ? <span className="text-muted-fg">{t("adm.co_never")}</span> : (
          <span className={failed ? "text-danger" : "text-muted-fg"}>
            {fmtRelative(r.at, locale)} ·{" "}
            {running ? t("adm.co_running")
              : r.ok ? t("adm.co_ran", { fetched: r.fetched, created: r.created, updated: r.updated, sec: r.seconds ?? 0 })
                : r.error}
          </span>
        )}
      </div>
    </div>
  );
}

// ── 수집 로그 ────────────────────────────────────────────────────────

/** Is it working? The queue first, because that is the live answer, then every run.
 *
 *  A run used to be invisible while it happened: the row lived in the job's uncommitted
 *  transaction, so a three-minute collection showed the *previous* run the whole time and
 *  an operator could not tell "working" from "nothing happened". */
function Log() {
  const t = useT(); const locale = useLocale();
  const q = useQuery({ queryKey: ["admin", "companies", "runs"], queryFn: Admin.companyRuns,
                       refetchInterval: 5_000, placeholderData: keepPreviousData });
  const d = q.data;
  if (!d) return <Skeleton className="h-72" />;

  const live = d.queue.filter((x) => x.status === "running" || x.status === "queued");
  return (
    <div className="space-y-4">
      <Section title={<span className="inline-flex items-center gap-2">
        {t("adm.co_queue")}{live.length ? <Badge tone="accent">{live.length}</Badge> : null}
      </span>} description={t("adm.co_queue_desc")}>
        {!d.queue.length ? (
          <p className="py-6 text-center text-sm text-muted-fg">{t("adm.co_queue_empty")}</p>
        ) : (
          <div className="max-h-[34vh] overflow-y-auto overflow-x-auto scrollbar-thin">
          <Table><THead><tr>
            <TH>{t("adm.co_job")}</TH><TH>{t("turn.status")}</TH><TH>{t("adm.co_source")}</TH>
            <TH className="text-right">{t("adm.attempts")}</TH><TH className="text-right">{t("adm.co_elapsed")}</TH>
            <TH>{t("adm.error")}</TH>
          </tr></THead>
            <TBody>{d.queue.map((j) => (
              <TR key={j.id} className={j.status === "running" ? "bg-accent/5" : ""}>
                <TD className="font-mono text-[11px]">{j.kind}</TD>
                <TD>
                  <Badge tone={j.status === "running" ? "accent" : j.status === "queued" ? "warning"
                    : j.status === "done" ? "success" : "danger"}>
                    {j.status === "running" ? <Loader2 className="h-3 w-3 animate-spin" /> : null}{j.status}
                  </Badge>
                </TD>
                <TD className="text-xs">{j.source ?? "–"}</TD>
                <TD className="text-right tabular-nums">{j.attempts}</TD>
                <TD className="text-right tabular-nums text-xs">
                  {j.running_s != null ? `${Math.round(j.running_s)}s` : j.run_at ? fmtRelative(j.run_at, locale) : "–"}
                </TD>
                <TD className="max-w-[220px] truncate text-xs text-danger" title={j.error ?? ""}>{j.error}</TD>
              </TR>
            ))}</TBody></Table>
          </div>
        )}
      </Section>

      <Section title={t("adm.co_history")} description={t("adm.co_history_desc")}>
        {/* Bounded and scrolled inside, so the page never grows past the window. */}
        <div className="max-h-[52vh] overflow-y-auto overflow-x-auto scrollbar-thin">
          <Table><THead><tr>
            <TH>{t("adm.co_source")}</TH><TH>{t("adm.co_started")}</TH>
            <TH className="text-right">{t("adm.co_took")}</TH><TH className="text-right">{t("adm.co_fetched")}</TH>
            <TH className="text-right">{t("adm.co_new")}</TH><TH className="text-right">{t("adm.co_upd")}</TH>
            <TH>{t("turn.status")}</TH>
          </tr></THead>
            <TBody>{d.runs.map((r) => (
              <TR key={r.id} className={r.running ? "bg-accent/5" : ""}>
                <TD className="text-xs font-medium">{r.source}</TD>
                <TD className="whitespace-nowrap text-xs text-muted-fg">{fmtDateTime(r.at)}</TD>
                <TD className="text-right tabular-nums text-xs">{r.seconds != null ? `${r.seconds}s` : "–"}</TD>
                <TD className="text-right tabular-nums">{fmtNumber(r.fetched)}</TD>
                <TD className="text-right tabular-nums">{fmtNumber(r.created)}</TD>
                <TD className="text-right tabular-nums">{fmtNumber(r.updated)}</TD>
                <TD className="max-w-[240px]">
                  {r.running ? <Badge tone="accent"><Loader2 className="h-3 w-3 animate-spin" />{t("adm.co_running")}</Badge>
                    : r.ok ? <Badge tone="success">{t("adm.co_ok")}</Badge>
                      : <span className="truncate text-xs text-danger" title={r.error ?? ""}>{r.error}</span>}
                </TD>
              </TR>
            ))}
              {!d.runs.length ? <TR><TD colSpan={7} className="py-8 text-center text-sm text-muted-fg">{t("adm.co_never")}</TD></TR> : null}
            </TBody></Table>
        </div>
      </Section>
    </div>
  );
}

// ── 기업 목록 ────────────────────────────────────────────────────────

/** The table, bounded to the window. A page of fifty rows that grows past the viewport
 *  puts the pager below the fold, which is where you need it after reading the rows. */
function Directory() {
  const t = useT();
  const [q, setQ] = useState(""); const [market, setMarket] = useState("");
  const [region, setRegion] = useState(""); const [industry, setIndustry] = useState("");
  const [page, setPage] = useState(1);

  const tax = useQuery({ queryKey: ["job-taxonomy"], queryFn: Community.jobTaxonomy, staleTime: 600_000 });
  const list = useQuery({
    queryKey: ["admin", "companies", "list", q, market, region, industry, page],
    queryFn: () => Admin.companies({ q, market, region, industry, page }),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((list.data?.total ?? 0) / (list.data?.size ?? 50)));
  const set = (fn: () => void) => { fn(); setPage(1); };

  return (
    <Section title={t("adm.co_directory")}>
      <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" />
          <Input className="w-full pl-8" placeholder={t("adm.co_search")} value={q}
            onChange={(e) => set(() => setQ(e.target.value))} />
        </div>
        <Select value={market} onChange={(e) => set(() => setMarket(e.target.value))}>
          <option value="">{t("adm.co_all_markets")}</option>
          {MARKETS.map((m) => <option key={m} value={m}>{m}</option>)}
        </Select>
        <Select value={region} onChange={(e) => set(() => setRegion(e.target.value))}>
          <option value="">{t("adm.co_all_regions")}</option>
          {(tax.data?.regions ?? []).map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </Select>
        <Select value={industry} onChange={(e) => set(() => setIndustry(e.target.value))}>
          <option value="">{t("adm.co_all_industries")}</option>
          {(tax.data?.industries ?? []).map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
        </Select>
      </div>

      {list.isLoading ? <Skeleton className="h-60" /> : (
        <>
          {/* The rows scroll inside their own box; the count and the pager stay put. */}
          <div className="max-h-[58vh] overflow-y-auto overflow-x-auto scrollbar-thin">
            <Table><THead><tr>
              <TH>{t("adm.co_name")}</TH><TH>{t("adm.co_market")}</TH><TH>{t("adm.co_industry")}</TH>
              <TH>{t("adm.co_region")}</TH><TH>{t("adm.co_ceo")}</TH><TH></TH>
            </tr></THead>
              <TBody>
                {list.data?.items.map((c: CompanyRow) => (
                  <TR key={c.id} className={c.status === "closed" ? "opacity-60" : ""}>
                    <TD>
                      <div className="font-medium">{c.name}</div>
                      {c.stock_code ? <div className="font-mono text-[11px] text-muted-fg">{c.stock_code}</div> : null}
                    </TD>
                    <TD>{c.market ? <Badge tone="outline">{c.market}</Badge> : null}</TD>
                    <TD className="max-w-[240px]">
                      <div className="truncate text-xs" title={c.industry_text}>{c.industry_text}</div>
                      {c.industry_codes.map((k) => <Badge key={k} tone="accent" className="mt-0.5 mr-1">{k}</Badge>)}
                    </TD>
                    <TD className="text-xs">{c.region_text}</TD>
                    <TD className="max-w-[140px] truncate text-xs" title={c.ceo}>{c.ceo}</TD>
                    <TD>
                      <div className="flex items-center gap-1">
                        {c.status === "closed" ? <Badge tone="danger">{t("adm.co_closed")}</Badge> : null}
                        {c.homepage ? (
                          <a href={c.homepage} target="_blank" rel="noreferrer noopener"
                            className="text-muted-fg hover:text-accent" aria-label={c.name}>
                            <ExternalLink className="h-3.5 w-3.5" />
                          </a>
                        ) : null}
                      </div>
                    </TD>
                  </TR>
                ))}
                {!list.data?.items.length ? <TR><TD colSpan={6} className="py-8 text-center text-sm text-muted-fg">{t("adm.co_empty")}</TD></TR> : null}
              </TBody></Table>
          </div>
          <div className="mt-3 flex items-center justify-between text-xs text-muted-fg">
            <span className="tabular-nums">{t("adm.co_count", { n: list.data?.total ?? 0 })}</span>
            {pages > 1 ? (
              <div className="flex gap-2">
                <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>←</Button>
                <span className="self-center tabular-nums">{page} / {fmtNumber(pages)}</span>
                <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>→</Button>
              </div>
            ) : null}
          </div>
        </>
      )}
    </Section>
  );
}


/** Which mail domain belongs to which company (plan/40 §10). Most come from the homepage
 *  the exchange lists; members propose the rest, and this is where a person says yes. */
function Domains() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const claims = useQuery({ queryKey: ["admin", "companies", "claims"], queryFn: Admin.domainClaims });
  const bust = () => { qc.invalidateQueries({ queryKey: ["admin", "companies", "claims"] }); qc.invalidateQueries({ queryKey: ["admin", "companies", "domains"] }); };
  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "reject" }) => Admin.decideDomainClaim(id, action),
    onSuccess: bust, onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const [q, setQ] = useState(""); const [picked, setPicked] = useState<CompanyRow | null>(null);
  const found = useQuery({
    queryKey: ["admin", "companies", "list", q, "", "", "", 1],
    queryFn: () => Admin.companies({ q }), enabled: q.trim().length >= 1, placeholderData: keepPreviousData,
  });
  return (
    <div className="space-y-4">
      <Section title={t("adm.co_claims")} description={t("adm.co_claims_desc")}>
        {claims.isLoading ? <Skeleton className="h-24" /> : !claims.data?.items.length ? (
          <p className="py-4 text-center text-sm text-muted-fg">{t("adm.co_claims_empty")}</p>
        ) : (
          <div className="overflow-x-auto"><Table><THead><tr><TH>{t("adm.co_domain")}</TH><TH>{t("adm.co_name")}</TH><TH></TH><TH></TH></tr></THead>
            <TBody>{claims.data.items.map((c) => (
              <TR key={c.id}>
                <TD className="font-mono text-xs">{c.domain}</TD>
                <TD><div className="font-medium">{c.company_name}</div><div className="text-xs text-muted-fg">{[c.market, c.industry_text].filter(Boolean).join(" · ")}</div></TD>
                <TD className="text-xs text-muted-fg">{t("adm.co_claims_n", { n: c.claims })}</TD>
                <TD><div className="flex justify-end gap-1">
                  <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: c.id, action: "reject" })} disabled={decide.isPending}><X className="h-3.5 w-3.5" />{t("adm.co_reject")}</Button>
                  <Button size="sm" variant="accent" onClick={() => decide.mutate({ id: c.id, action: "approve" })} disabled={decide.isPending}><Check className="h-3.5 w-3.5" />{t("adm.co_approve")}</Button>
                </div></TD>
              </TR>
            ))}</TBody></Table></div>
        )}
        {claims.data ? <p className="mt-3 text-xs text-muted-fg"><ShieldCheck className="mr-1 inline h-3.5 w-3.5 text-success" />{t("adm.co_domains_confirmed", { n: fmtNumber(claims.data.confirmed) })}</p> : null}
      </Section>
      <Section title={t("adm.co_domains")} description={t("adm.co_domains_desc")}>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" />
          <Input className="w-full pl-8" placeholder={t("adm.co_pick_company")} value={q} onChange={(e) => { setQ(e.target.value); setPicked(null); }} />
        </div>
        {!picked && q.trim() ? (
          <div className="mt-2 divide-y divide-border rounded-xl border border-border">
            {(found.data?.items ?? []).slice(0, 8).map((c) => (
              <button key={c.id} type="button" onClick={() => setPicked(c)} className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-muted/60">
                <Building2 className="h-4 w-4 text-muted-fg" /><span className="font-medium">{c.name}</span>
                <span className="text-xs text-muted-fg">{[c.market, c.industry_text].filter(Boolean).join(" · ")}</span>
              </button>
            ))}
            {found.data && !found.data.items.length ? <p className="px-3 py-3 text-sm text-muted-fg">{t("adm.co_empty")}</p> : null}
          </div>
        ) : null}
        {picked ? <DomainList company={picked} /> : null}
      </Section>
    </div>
  );
}

function DomainList({ company }: { company: CompanyRow }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [domain, setDomain] = useState("");
  const q = useQuery({ queryKey: ["admin", "companies", "domains", company.id], queryFn: () => Admin.companyDomains(company.id) });
  const bust = () => { qc.invalidateQueries({ queryKey: ["admin", "companies", "domains", company.id] }); qc.invalidateQueries({ queryKey: ["admin", "companies", "claims"] }); };
  const add = useMutation({ mutationFn: () => Admin.addCompanyDomain(company.id, domain.trim()), onSuccess: () => { setDomain(""); bust(); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const remove = useMutation({ mutationFn: (id: string) => Admin.removeCompanyDomain(company.id, id), onSuccess: bust, onError: (e) => toast.error(friendlyError(e, locale)) });
  const src = (d: CompanyDomain) => t(`adm.co_domain_src_${d.source}`);
  return (
    <div className="mt-3 rounded-xl border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><span className="text-sm font-semibold">{company.name}</span>{company.homepage ? <span className="ml-2 text-xs text-muted-fg">{company.homepage}</span> : null}</div>
      </div>
      <div className="mt-2 space-y-1.5">
        {q.isLoading ? <Skeleton className="h-10" /> : !q.data?.items.length ? <p className="py-2 text-sm text-muted-fg">{t("adm.co_domain_empty")}</p> : q.data.items.map((d) => (
          <div key={d.id} className="flex items-center gap-2 rounded-lg bg-muted/50 px-3 py-1.5 text-sm">
            <Mail className="h-3.5 w-3.5 text-muted-fg" /><span className="font-mono text-xs">{d.domain}</span>
            <Badge tone={d.status === "confirmed" ? "success" : "warning"}>{d.status === "confirmed" ? src(d) : t("adm.co_domain_pending")}</Badge>
            <Button size="icon-sm" variant="ghost" className="ml-auto" aria-label={t("common.delete")} onClick={() => remove.mutate(d.id)} disabled={remove.isPending}><Trash2 className="h-3.5 w-3.5" /></Button>
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-2">
        <Input value={domain} onChange={(e) => setDomain(e.target.value)} placeholder={t("adm.co_domain_add_ph")} className="flex-1 font-mono text-xs"
          onKeyDown={(e) => { if (e.key === "Enter" && domain.trim()) add.mutate(); }} />
        <Button variant="outline" onClick={() => add.mutate()} disabled={!domain.trim() || add.isPending}><Plus className="h-4 w-4" />{t("adm.co_domain_add")}</Button>
      </div>
    </div>
  );
}
