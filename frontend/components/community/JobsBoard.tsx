"use client";
import { useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import Link from "next/link";
import { Briefcase, ChevronDown, ExternalLink, MapPin, Plus, Star } from "@/components/icons";
import { Community, type CommunityJob, type JobTaxonomy, type TaxonomyNode } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { fmtNumber, fmtRelative } from "@/lib/format";
import { Page } from "@/components/owner/Shell";
import { Button, buttonLook } from "@/components/ui/button";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Busy } from "@/components/ui/busy";
import { PageHeader } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import { Dialog } from "@/components/ui/dialog";
import { FilterBar, countActive, findTrail, type FilterCounts, type FilterField, type FilterValues } from "@cocorof/react-filters";
import { TaxonomyPicker } from "@/components/ui/taxonomy-picker";

const TYPES = ["fulltime", "contract", "intern", "parttime"];

/** Openings, filtered the way a person actually asks: what, where, and can I apply with
 *  the years I have. */
/** Company name completion (plan/33 §5).
 *
 *  Free text with suggestions rather than a required choice: a posting for a company that is
 *  not in the directory still has to be postable, so picking one is an improvement on
 *  typing, never a gate in front of it. Picking sets the link; typing again clears it,
 *  because the link should never describe a different company than the words above it. */
function CompanyPicker({ value, companyId, onChange }: {
  value: string; companyId: string | null;
  onChange: (company: string, companyId: string | null) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const q = useQuery({
    queryKey: ["company-suggest", value],
    queryFn: () => Community.companySuggest(value),
    enabled: open && value.trim().length >= 2,
    staleTime: 30_000,
  });
  const hits = q.data?.items ?? [];
  return (
    <div className="relative">
      <Input value={value} autoComplete="off"
        onChange={(e) => { onChange(e.target.value, null); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)} />
      {open && hits.length ? (
        <ul className="absolute z-30 mt-1 max-h-64 w-full overflow-auto rounded-xl border border-border bg-card p-1 shadow-lg">
          {hits.map((c) => (
            <li key={c.id}>
              <button type="button" className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-muted"
                onMouseDown={(e) => { e.preventDefault(); onChange(c.name, c.id); setOpen(false); }}>
                <span className="truncate font-medium">{c.name}</span>
                {c.market ? <Badge tone="outline">{c.market}</Badge> : null}
                <span className="ml-auto truncate text-[11px] text-muted-fg">{c.industry_text}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {companyId ? <input type="hidden" value={companyId} readOnly aria-label={t("job.co_linked")} /> : null}
    </div>
  );
}

export function JobsBoard() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [q, setQ] = useState(""); const [query, setQuery] = useState("");
  const [f, setF] = useState<FilterValues>({});
  const [open, setOpen] = useState(false);

  const tax = useQuery({ queryKey: ["c", "jobs", "taxonomy"], queryFn: Community.jobTaxonomy, staleTime: Infinity });
  const facets = useQuery({ queryKey: ["c", "jobs", "facets"], queryFn: Community.jobFacets, staleTime: 120_000 });
  const jobs = useQuery({
    queryKey: ["c", "jobs", query, f],
    placeholderData: keepPreviousData,
    queryFn: () => Community.jobs({
      q: query || undefined,
      region: list(f.region).join(",") || undefined,
      job: list(f.job).join(",") || undefined,
      industry: list(f.industry).join(",") || undefined,
      employment_type: list(f.type).join(",") || undefined,
      max_experience: rangeMax(f.career),
      min_salary: rangeMin(f.salary),
      max_salary: rangeMax(f.salary),
      remote: list(f.work).includes("remote") || undefined,
    }),
  });
  const close = useMutation({
    mutationFn: (id: string) => Community.closeJob(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["c", "jobs"] }); toast.success(t("job.closed")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  const fields: FilterField[] = useMemo(() => [
    { key: "job", kind: "taxonomy", label: t("job.family"), nodes: tax.data?.jobs ?? [], max: 5,
      hint: t("job.family_hint"), searchPlaceholder: t("job.family_ph") },
    { key: "region", kind: "taxonomy", label: t("job.location"), nodes: tax.data?.regions ?? [], max: 5,
      hint: t("job.location_hint"), searchPlaceholder: t("job.location_ph") },
    { key: "industry", kind: "taxonomy", label: t("job.industry"), nodes: tax.data?.industries ?? [], max: 3,
      hint: t("job.industry_hint"), searchPlaceholder: t("job.industry_ph") },
    { key: "career", kind: "range", label: t("job.career"), min: 0, max: 20, step: 1,
      unit: t("job.year_unit"), openEndedLabel: t("job.and_up"), hint: t("job.years_hint") },
    { key: "salary", kind: "range", label: t("job.pay"), min: 2000, max: 15000, step: 500,
      format: (n) => `${(n / 10000).toFixed(n % 10000 === 0 ? 0 : 1)}${t("job.eok")}`,
      openEndedLabel: t("job.and_up"), hint: t("job.salary_hint") },
    { key: "type", kind: "choice", label: t("job.type"),
      options: (tax.data?.employment_types ?? []).map((x) => ({ value: x, label: t(`job.type_${x}`) })) },
    { key: "work", kind: "choice", label: t("job.work_mode"),
      options: [{ value: "remote", label: t("job.remote") }] },
  ], [tax.data, t]);

  // The bar greys out a choice that leads nowhere, which needs the counts keyed the same
  // way its fields are.
  const counts: FilterCounts | undefined = facets.data ? {
    region: facets.data.region, job: facets.data.job, industry: facets.data.industry,
    type: facets.data.type, work: { remote: facets.data.remote },
  } : undefined;

  const filtered = countActive(f) > 0 || !!query;

  return (
    <Page>
      <PageHeader title={t("cnav.jobs")} description={t("job.desc")}
        action={<Button variant="accent" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />{t("job.post")}</Button>} />

      <FilterBar className="mb-4" fields={fields} value={f} onChange={setF} counts={counts}
        search={{ value: q, onChange: setQ, onSubmit: (v) => setQuery(v.trim()), placeholder: t("job.keyword_ph") }}
        labels={{
          apply: t("job.filter_apply"), reset: t("job.reset"), close: t("common.close"),
          search: t("com.search"), empty: t("job.facet_empty"), any: t("job.any"),
          all: t("com.all"), clearAll: t("job.reset"),
          selected: (n, max) => (max ? t("job.selected_max", { n, max }) : t("job.selected", { n })),
          limitReached: (max) => t("job.limit", { n: max }),
        }} />

      <div className="mb-3 text-sm text-muted-fg">{t("job.count", { n: fmtNumber(jobs.data?.items.length ?? 0) })}</div>

      <Busy busy={jobs.isFetching && !jobs.isLoading}>
      {jobs.isLoading ? <div className="grid gap-3 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-40" />)}</div>
        : (jobs.data?.items.length ?? 0) === 0 ? (
          <EmptyState icon={<Briefcase />} title={filtered ? t("job.no_match_title") : t("job.empty_title")}
            description={filtered ? t("job.no_match_desc") : t("job.empty_desc")}
            action={filtered
              ? <Button variant="outline" onClick={() => { setF({}); setQ(""); setQuery(""); }}>{t("job.reset")}</Button>
              : <Button variant="accent" onClick={() => setOpen(true)}>{t("job.post")}</Button>} />
        ) : (
          <ul key={`${query}:${JSON.stringify(f)}`} className="list-in grid gap-3 md:grid-cols-2">
            {jobs.data!.items.map((j) => <JobCard key={j.id} job={j} locale={locale} onClose={() => close.mutate(j.id)} />)}
          </ul>
        )}
      </Busy>

      <JobDialog open={open} onClose={() => setOpen(false)} taxonomy={tax.data}
                 onSaved={() => { setOpen(false); qc.invalidateQueries({ queryKey: ["c", "jobs"] }); }} />
    </Page>
  );
}

const list = (v: FilterValues[string]): string[] => (Array.isArray(v) ? v : []);
const rangeMin = (v: FilterValues[string]) => (v && !Array.isArray(v) && v.min != null ? v.min : undefined);
const rangeMax = (v: FilterValues[string]) => (v && !Array.isArray(v) && v.max != null ? v.max : undefined);

function JobCard({ job, locale, onClose }: { job: CommunityJob; locale: "ko" | "en"; onClose: () => void }) {
  const t = useT();
  const pay = job.salary_min || job.salary_max
    ? `${job.salary_min ? fmtNumber(job.salary_min) : "?"}~${job.salary_max ? fmtNumber(job.salary_max) : "?"}만원`
    : "";
  return (
    <li className="rounded-2xl border border-border bg-card p-4">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            {job.company_info ? (
              <Link href={`/app/community/companies/${job.company_info.id}`} className="truncate text-sm text-muted-fg hover:text-accent hover:underline">{job.company_info.name}</Link>
            ) : <span className="truncate text-sm text-muted-fg">{job.company}</span>}
            {/* Collected from the exchange and the regulator, not typed by the poster
                (plan/33 §5) — so it is worth showing and worth trusting. */}
            {job.company_info ? (
              <>
                {job.company_info.review_count ? <span className="inline-flex items-center gap-0.5 text-xs text-muted-fg"><Star className="h-3 w-3 fill-success text-success" />{job.company_info.rating.toFixed(1)}</span> : null}
                {job.company_info.market ? <Badge tone="outline">{job.company_info.market}</Badge> : null}
                {job.company_info.status === "closed" ? <Badge tone="danger">{t("job.co_closed")}</Badge> : null}
              </>
            ) : null}
          </div>
          {job.company_info ? (
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-fg">
              {job.company_info.industry_text ? <span className="truncate max-w-[220px]">{job.company_info.industry_text}</span> : null}
              {job.company_info.region_text ? <span>{job.company_info.region_text}</span> : null}
              {job.company_info.ceo ? <span>{t("job.co_ceo")} {job.company_info.ceo}</span> : null}
              {job.company_info.homepage ? (
                <a href={job.company_info.homepage} target="_blank" rel="noreferrer noopener"
                   className="inline-flex items-center gap-0.5 text-accent"
                   aria-label={`${job.company_info.name} ${t("job.co_site")}`}>
                  {t("job.co_site")}
                </a>
              ) : null}
            </div>
          ) : null}
          <h3 className="truncate text-[15px] font-semibold">{job.title}</h3>
        </div>
        <Badge tone="outline">{t(`job.type_${job.employment_type}`)}</Badge>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-fg">
        {job.location ? <span className="inline-flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{job.location}</span> : null}
        <span>{job.experience_min > 0 ? t("job.exp_years", { n: job.experience_min }) : t("job.exp_any")}</span>
        {pay ? <span>{pay}</span> : null}
        <span className="ml-auto">{fmtRelative(job.created_at, locale)}</span>
      </div>
      {job.description ? <p className="mt-2 line-clamp-3 text-sm text-muted-fg">{job.description}</p> : null}
      {job.tags?.length ? <div className="mt-2 flex flex-wrap gap-1">{job.tags.map((x) => <span key={x} className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-fg">{x}</span>)}</div> : null}
      <div className="mt-3 flex gap-2">
        {job.apply_url ? <a href={job.apply_url} target="_blank" rel="noopener noreferrer" className={buttonLook("accent", "sm")}><ExternalLink className="h-4 w-4" />{t("job.apply")}</a> : null}
        {job.is_mine ? <Button size="sm" variant="ghost" onClick={onClose}>{t("job.close")}</Button> : null}
      </div>
    </li>
  );
}

function JobDialog({ open, onClose, onSaved, taxonomy }: {
  open: boolean; onClose: () => void; onSaved: () => void; taxonomy?: JobTaxonomy;
}) {
  const t = useT(); const locale = useLocale();
  const blank = { title: "", company: "", company_id: null as string | null, employment_type: "fulltime", experience_min: 0,
                  salary_min: "", salary_max: "", tags: "", description: "", apply_url: "",
                  region_codes: [] as string[], job_codes: [] as string[], industry_codes: [] as string[], remote: false };
  const [f, setF] = useState(blank);
  const [picking, setPicking] = useState<null | "region" | "job" | "industry">(null);
  const save = useMutation({
    // A filter can only offer what a posting states, so pay, keywords and the taxonomy
    // codes are collected here: an empty field stays null instead of becoming a zero.
    mutationFn: () => Community.createJob({
      ...f, experience_min: Number(f.experience_min) || 0,
      salary_min: f.salary_min ? Number(f.salary_min) : null,
      salary_max: f.salary_max ? Number(f.salary_max) : null,
      tags: f.tags.split(",").map((x) => x.trim()).filter(Boolean).slice(0, 10),
    }),
    onSuccess: () => { toast.success(t("job.posted")); setF(blank); onSaved(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const ready = f.title.trim() && f.company.trim() && f.region_codes.length > 0 && f.job_codes.length > 0;
  const nodes = picking === "region" ? taxonomy?.regions : picking === "job" ? taxonomy?.jobs : taxonomy?.industries;
  const [draft, setDraft] = useState<string[]>([]);

  return (
    <>
    <Dialog open={open && !picking} onClose={onClose} title={t("job.post")} description={t("job.post_desc")} size="lg"
      footer={<><Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
               <Button variant="accent" loading={save.isPending} disabled={!ready} onClick={() => save.mutate()}>{t("job.publish")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("job.company")} hint={f.company_id ? t("job.co_linked") : t("job.co_link_hint")}>
          <CompanyPicker value={f.company} companyId={f.company_id}
            onChange={(company, company_id) => setF({ ...f, company, company_id })} />
        </Field>
        <Field label={t("job.title")}><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        {/* The same taxonomy the filter reads, so a posting is filed where searches look. */}
        <PickerField label={t("job.family")} codes={f.job_codes} nodes={taxonomy?.jobs} required
                     onOpen={() => { setDraft(f.job_codes); setPicking("job"); }} placeholder={t("job.pick_family")} />
        <PickerField label={t("job.location")} codes={f.region_codes} nodes={taxonomy?.regions} required
                     onOpen={() => { setDraft(f.region_codes); setPicking("region"); }} placeholder={t("job.pick_location")} />
        <PickerField label={t("job.industry")} codes={f.industry_codes} nodes={taxonomy?.industries}
                     onOpen={() => { setDraft(f.industry_codes); setPicking("industry"); }} placeholder={t("job.pick_industry")} />
        <Field label={t("job.type")}>
          <Select value={f.employment_type} onChange={(e) => setF({ ...f, employment_type: e.target.value })}>
            {(taxonomy?.employment_types ?? TYPES).map((x) => <option key={x} value={x}>{t(`job.type_${x}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("job.min_years")}><Input type="number" min={0} max={40} value={f.experience_min} onChange={(e) => setF({ ...f, experience_min: Number(e.target.value) })} /></Field>
        <Field label={t("job.apply_url")}><Input value={f.apply_url} onChange={(e) => setF({ ...f, apply_url: e.target.value })} placeholder="https://" /></Field>
        <Field label={t("job.salary_range")} hint={t("job.salary_range_hint")} className="sm:col-span-2">
          <div className="flex items-center gap-2">
            <Input type="number" min={0} step={100} value={f.salary_min} placeholder="4000" onChange={(e) => setF({ ...f, salary_min: e.target.value })} />
            <span className="text-muted-fg">~</span>
            <Input type="number" min={0} step={100} value={f.salary_max} placeholder="6000" onChange={(e) => setF({ ...f, salary_max: e.target.value })} />
          </div>
        </Field>
        <Field label={t("job.tags")} hint={t("job.tags_hint")} className="sm:col-span-2">
          <Input value={f.tags} onChange={(e) => setF({ ...f, tags: e.target.value })} placeholder="Python, AWS, SQL" />
        </Field>
        <div className="sm:col-span-2">
          <Checkbox checked={f.remote} onChange={(v) => setF({ ...f, remote: v })} label={t("job.remote_ok")} />
        </div>
        <Field label={t("job.description")} className="sm:col-span-2">
          <Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} className="min-h-[140px]" />
        </Field>
      </div>
    </Dialog>

    {/* The same dialog 내 정보 uses (plan/36): opening a category shows what is in it,
        the checkbox is what selects, and anything the tree does not have can be typed. */}
    <TaxonomyPicker open={!!picking && !!nodes} nodes={nodes}
      title={picking === "region" ? t("job.location") : picking === "job" ? t("job.family") : t("job.industry")}
      hint={t("job.pick_hint")} value={draft} max={picking === "industry" ? 3 : 5}
      onChange={(v) => setF({ ...f, [`${picking}_codes`]: v })} onClose={() => setPicking(null)} />
    </>
  );
}

/** A read-only field that opens a picker — the codes are shown as the names they mean. */
function PickerField({ label, codes, nodes, onOpen, placeholder, required }: {
  label: string; codes: string[]; nodes?: TaxonomyNode[]; onOpen: () => void; placeholder: string; required?: boolean;
}) {
  const names = nodes ? codes.map((c) => findTrail(nodes, c)?.slice(-1)[0]?.label ?? c) : codes;
  return (
    <Field label={label}>
      <button type="button" onClick={onOpen} disabled={!nodes}
        className={cn("flex h-10 w-full items-center gap-2 rounded-xl border px-3 text-left text-sm",
          names.length ? "border-border bg-card" : "border-border bg-card text-muted-fg",
          required && !names.length && "border-warning/50")}>
        <span className="min-w-0 flex-1 truncate">{names.length ? names.join(", ") : placeholder}</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-fg" />
      </button>
    </Field>
  );
}
