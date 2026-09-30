"use client";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BadgeCheck, Briefcase, Building2, Calendar, ChevronLeft, ChevronRight, Plus, Star, ThumbsUp, Users } from "@/components/icons";
import { Companies, type Axis, type CompanyCard as CompanyCardT } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT, type TFn } from "@/lib/i18n";
import { fmtNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

/** The pieces every company screen is built from (plan/40). One vocabulary: the same
 *  mark, the same stars, the same card, the same section heading, on every screen. */

export const companyHref = (id: string, tab?: string) => `/app/community/companies/${id}${tab ? `?tab=${tab}` : ""}`;
export const AXES: Axis[] = ["pay", "balance", "culture", "promotion", "management"];

/** "(주)카카오" → "카카오". */
export function cleanName(name: string) {
  return name.replace(/\(주\)|주식회사|㈜/g, "").trim() || name;
}

/** A company's mark. There is no picture to show — logos are not something we may fetch —
 *  so it is the building glyph on a quiet tile, the same for every company, and the name
 *  next to it does the identifying. `raised` is the header's version, sitting on a cover. */
export function CompanyLogo({ size = 44, className, raised }: { name?: string; size?: number; className?: string; raised?: boolean }) {
  return (
    <span aria-hidden className={cn("inline-flex shrink-0 select-none items-center justify-center rounded-xl border text-muted-fg",
      raised ? "border-border bg-card shadow-md" : "border-border/70 bg-muted", className)} style={{ width: size, height: size }}>
      <Building2 style={{ width: Math.round(size * 0.5), height: Math.round(size * 0.5) }} strokeWidth={1.6} />
    </span>
  );
}

export function Stars({ value, size = 14, className }: { value: number; size?: number; className?: string }) {
  const pct = Math.max(0, Math.min(100, (value / 5) * 100));
  const row = (on: boolean) => Array.from({ length: 5 }, (_, i) => (
    <Star key={i} style={{ width: size, height: size }} className={on ? "fill-warning text-warning" : "fill-border text-border"} />
  ));
  return (
    <span className={cn("relative inline-flex shrink-0", className)} aria-label={`${value.toFixed(1)} / 5`}>
      <span className="flex">{row(false)}</span>
      <span className="absolute inset-0 flex overflow-hidden" style={{ width: `${pct}%` }}>{row(true)}</span>
    </span>
  );
}

/** "★ 4.0" in green, or a quiet "no reviews yet". */
export function RatingLine({ value, count, size = "md", showCount }: { value: number; count?: number; size?: "sm" | "md" | "lg"; showCount?: boolean }) {
  const t = useT();
  const cls = { sm: "text-[13px]", md: "text-[15px]", lg: "text-2xl" }[size];
  if (!count) return <span className="text-xs text-muted-fg">{t("cx.no_stats")}</span>;
  return (
    <span className="inline-flex items-center gap-1">
      <Star className={cn("fill-success text-success", size === "lg" ? "h-5 w-5" : "h-3.5 w-3.5")} />
      <span className={cn("font-semibold tabular-nums", cls)}>{value.toFixed(1)}</span>
      {showCount ? <span className="text-xs text-muted-fg tabular-nums">({fmtNumber(count)})</span> : null}
    </span>
  );
}

/** A ring: the share in the foreground colour, the rest in the track. `null` draws the track alone. */
export function Donut({ value, label, size = 84, stroke = 8 }: { value: number | null | undefined; label: ReactNode; size?: number; stroke?: number }) {
  const r = (size - stroke) / 2; const c = 2 * Math.PI * r;
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  return (
    <div className="flex flex-col items-center gap-2 text-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={typeof label === "string" ? `${label} ${value ?? "-"}%` : undefined}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--fg)" strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${(v / 100) * c} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} className="transition-[stroke-dasharray] duration-500" />
        <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle" className="fill-fg" style={{ fontSize: size * 0.22, fontWeight: 650 }}>
          {value == null ? "–" : `${Math.round(value)}%`}
        </text>
      </svg>
      <span className="text-xs text-muted-fg">{label}</span>
    </div>
  );
}

export function AxisBars({ axes, className }: { axes: Partial<Record<Axis, number>>; className?: string }) {
  const t = useT();
  return (
    <ul className={cn("space-y-3", className)}>
      {AXES.map((a) => {
        const v = axes[a] ?? 0;
        return (
          <li key={a} className="text-xs">
            <div className="mb-1 flex items-center justify-between"><span className="text-muted-fg">{t(`cx.axis_${a}`)}</span><span className="font-semibold tabular-nums">{v ? v.toFixed(1) : "–"}</span></div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-success transition-[width] duration-500" style={{ width: `${(v / 5) * 100}%` }} /></div>
          </li>
        );
      })}
    </ul>
  );
}

export const tagLabel = (t: TFn, code: string) => t(`cx.tag_${code}`);
export const benefitLabel = (t: TFn, code: string) => t(`cx.ben_${code}`);

/** How long the company has been around, from whichever date we have. */
export function yearsSince(founded?: string | null, listed?: string | null): { n: number; y: number } | null {
  const iso = founded || listed;
  if (!iso) return null;
  const y = Number(iso.slice(0, 4));
  if (!y) return null;
  return { n: Math.max(1, new Date().getFullYear() - y + 1), y };
}

export function fmtManwon(n: number | null | undefined, locale: "ko" | "en", t: TFn) {
  if (n == null) return "–";
  return locale === "ko" ? `${fmtNumber(n)}${t("cx.manwon")}` : `₩${fmtNumber(n * 10000)}`;
}

/** The five axes as one shape. A pentagon reads as a silhouette — round and full is a
 *  company people like all round; a spike is one thing done well — where five bars read
 *  as five separate numbers. Values run 0–5 from the centre. */
export function Radar({ axes, size = 240, className }: { axes: Partial<Record<Axis, number>>; size?: number; className?: string }) {
  const t = useT();
  // Wider than tall: the two side labels need room outside the pentagon, or they clip.
  const width = size + 150;
  const cx = width / 2; const cy = size / 2; const r = size * 0.36;
  const pt = (i: number, v: number) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / 5; return [cx + Math.cos(a) * r * (v / 5), cy + Math.sin(a) * r * (v / 5)] as const; };
  const ring = (v: number) => AXES.map((_, i) => pt(i, v).join(",")).join(" ");
  const shape = AXES.map((a, i) => pt(i, axes[a] ?? 0).join(",")).join(" ");
  return (
    <svg width={width} height={size} viewBox={`0 0 ${width} ${size}`} className={cn("max-w-full", className)} role="img" aria-label={AXES.map((a) => `${t(`cx.axis_${a}`)} ${(axes[a] ?? 0).toFixed(1)}`).join(", ")}>
      {[1, 2, 3, 4, 5].map((v) => <polygon key={v} points={ring(v)} fill="none" stroke="var(--border)" strokeWidth={v === 5 ? 1.25 : 1} strokeDasharray={v === 5 ? undefined : "2 3"} />)}
      {AXES.map((_, i) => { const [x, y] = pt(i, 5); return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--border)" strokeWidth={1} />; })}
      <polygon points={shape} fill="color-mix(in oklab, var(--accent) 28%, transparent)" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" className="transition-all duration-500" />
      {AXES.map((a, i) => { const [x, y] = pt(i, axes[a] ?? 0); return <circle key={a} cx={x} cy={y} r={3.5} fill="var(--card)" stroke="var(--accent)" strokeWidth={2} />; })}
      {AXES.map((a, i) => {
        const [x, y] = pt(i, 6.15); const v = axes[a] ?? 0;
        const anchor = Math.abs(x - cx) < 6 ? "middle" : x > cx ? "start" : "end";
        return (
          <text key={a} x={x} y={y} textAnchor={anchor} dominantBaseline="central" className="fill-muted-fg" style={{ fontSize: 11 }}>
            {t(`cx.axis_${a}`)}<tspan className="fill-fg" style={{ fontWeight: 650 }} dx={4}>{v ? v.toFixed(1) : "–"}</tspan>
          </text>
        );
      })}
    </svg>
  );
}

/** "n명 중 k명": a row of people, the ones who said yes filled in. Ten at most; beyond
 *  that it is ten for every hundred, and the sentence next to it says so. */
export function PeopleDots({ pct, n, className, size = 10 }: { pct: number | null | undefined; n: number; className?: string; size?: number }) {
  if (pct == null) return null;
  const total = Math.min(10, Math.max(1, n));
  const k = n <= 10 ? Math.round((pct / 100) * n) : Math.round(pct / 10);
  return (
    <span className={cn("inline-flex items-center gap-[3px]", className)} aria-hidden>
      {Array.from({ length: total }, (_, i) => <span key={i} className={cn("rounded-full", i < k ? "bg-accent" : "bg-border")} style={{ width: size, height: size }} />)}
    </span>
  );
}

/** The facts a page quotes, in order (mirrors the server's FACT_QUESTIONS). */
export const FACT_QUESTIONS = ["hours", "overtime", "vacation", "comm", "safety", "promo_basis", "stability", "pay_level"] as const;
export const qLabel = (t: TFn, q: string) => t(`cx.q_${q}`);
export const factLabel = (t: TFn, q: string) => t(`cx.fl_${q}`);
export const optionLabel = (t: TFn, q: string, o: string) => t(`cx.o_${q === "unfit" ? "fit" : q}_${o}`);
export const fitLabel = (t: TFn, o: string) => t(`cx.fit_${o}`);

/** The most common answer to a question, with how common. */
export function topFact(counts?: Record<string, number>) {
  if (!counts) return null;
  const entries = Object.entries(counts).filter(([, n]) => n > 0);
  if (!entries.length) return null;
  const total = entries.reduce((a, [, n]) => a + n, 0);
  const [opt, n] = entries.sort((a, b) => b[1] - a[1])[0];
  return { opt, n, total, pct: Math.round((100 * n) / total), entries };
}

/** Eyebrow, title, optional action — every section on these screens starts this way. */
export function SectionHeading({ eyebrow, title, icon, action, className }: { eyebrow?: ReactNode; title: ReactNode; icon?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("mb-3 flex items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        {eyebrow ? <div className="mb-0.5 text-xs text-muted-fg">{eyebrow}</div> : null}
        <h2 className="inline-flex items-center gap-1.5 text-[17px] font-semibold tracking-tight">{icon}{title}</h2>
      </div>
      {action ? <div className="flex shrink-0 items-center gap-1">{action}</div> : null}
    </div>
  );
}

export function FollowButton({ id, following, count, size = "sm", showCount, onChange, className }: {
  id: string; following: boolean; count?: number; size?: "sm" | "md"; showCount?: boolean;
  onChange?: (following: boolean, count: number) => void; className?: string;
}) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [on, setOn] = useState(following); const [n, setN] = useState(count ?? 0);
  useEffect(() => { setOn(following); }, [following]);
  useEffect(() => { if (count !== undefined) setN(count); }, [count]);
  const m = useMutation({
    mutationFn: () => Companies.follow(id),
    onSuccess: (r) => {
      setOn(r.following); setN(r.follow_count); onChange?.(r.following, r.follow_count);
      toast.success(t(r.following ? "cx.followed_toast" : "cx.unfollowed_toast"));
      qc.invalidateQueries({ queryKey: ["cx"], refetchType: "none" });
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <Button size={size} variant={on ? "secondary" : "outline"} loading={m.isPending} aria-pressed={on} className={cn("shrink-0", className)}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); m.mutate(); }}>
      {on ? <BadgeCheck className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
      {t(on ? "cx.following" : "cx.follow")}{showCount && n ? <span className="tabular-nums text-muted-fg">{fmtNumber(n)}</span> : null}
    </Button>
  );
}

export function TagRow({ tags, className, max = 4 }: { tags: string[]; className?: string; max?: number }) {
  const t = useT();
  if (!tags.length) return null;
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      {tags.slice(0, max).map((code) => (
        <span key={code} className={cn("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium",
          code === "hiring" ? "bg-accent/12 text-accent" : "bg-muted text-fg")}>{tagLabel(t, code)}</span>
      ))}
    </div>
  );
}

/** The facts a card states in one line: how long, how big, hiring or not. */
export function FactLine({ c, className, dense }: { c: CompanyCardT; className?: string; dense?: boolean }) {
  const t = useT();
  const age = yearsSince(c.founded_on, c.listed_on);
  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-fg", className)}>
      {age ? <FactItem icon={<Calendar className="h-3.5 w-3.5" />} text={dense ? t("cx.years", { n: age.n }) : t("cx.years_since", { n: age.n, y: age.y })} /> : null}
      {c.employees ? <FactItem icon={<Users className="h-3.5 w-3.5" />} text={t("cx.employees", { n: fmtNumber(c.employees) })} /> : null}
      <FactItem icon={<Briefcase className="h-3.5 w-3.5" />} text={<span className={c.open_jobs ? "font-medium text-accent" : ""}>{t("cx.hiring_n", { n: c.open_jobs })}</span>} />
    </div>
  );
}
function FactItem({ icon, text }: { icon: ReactNode; text: ReactNode }) {
  return <span className="inline-flex items-center gap-1 whitespace-nowrap">{icon}{text}</span>;
}

/** A search result (plan/40 screen 3): what it does and where, how long it has been
 *  around and how big, whether it is hiring — and what people say it is known for. */
export function CompanyCard({ c, className }: { c: CompanyCardT; className?: string }) {
  const t = useT();
  return (
    <Link href={companyHref(c.id)} className={cn("group relative block rounded-2xl border border-border bg-card p-4 shadow-soft transition duration-150 hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-md",
      c.status === "closed" && "opacity-70", className)}>
      <div className="flex items-start gap-3.5">
        <CompanyLogo size={48} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="truncate text-[15px] font-semibold leading-tight group-hover:text-accent">{c.name}</h3>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-fg">
                <RatingLine value={c.rating} count={c.review_count} size="sm" showCount />
                {c.industry_text ? <span className="truncate">{c.industry_text}</span> : null}
                {c.region_text ? <span className="whitespace-nowrap">· {c.region_text}</span> : null}
              </div>
            </div>
            <FollowButton id={c.id} following={c.following} count={c.follow_count} />
          </div>
          <FactLine c={c} className="mt-3" />
          {c.why ? (
            <div className="mt-2 inline-flex items-center gap-1 rounded-md bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent">
              {c.why === "jobs" ? t("cx.why_jobs", { n: c.n ?? 0 }) : c.why === "reviews" ? t("cx.why_reviews", { n: c.n ?? 0 }) : t("cx.why_industry")}
            </div>
          ) : null}
          <div className="mt-3 flex items-center gap-2 border-t border-border pt-3">
            {c.tags.length ? <TagRow tags={c.tags} /> : <span className="text-xs text-muted-fg">{t("cx.no_reviews_yet")}</span>}
            {c.market ? <Badge tone="outline" className="ml-auto">{c.market}</Badge> : null}
            {c.status === "closed" ? <Badge tone="danger">{t("cx.info_closed")}</Badge> : null}
          </div>
        </div>
      </div>
    </Link>
  );
}

/** A shelf tile: name, line of work, one thing it is known for — or its plain facts while
 *  nobody has said anything yet. */
export function CompanyTile({ c, rank, highlight, className }: { c: CompanyCardT; rank?: number; highlight?: string; className?: string }) {
  const t = useT();
  const tag = highlight ?? c.tags[0];
  const age = yearsSince(c.founded_on, c.listed_on);
  return (
    <Link href={companyHref(c.id)} className={cn("group relative flex h-full w-full flex-col rounded-2xl border border-border bg-card p-3.5 shadow-soft transition duration-150 hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-md", className)}>
      {rank ? <span className="absolute -left-1.5 -top-1.5 inline-flex h-6 min-w-6 items-center justify-center rounded-full bg-primary px-1.5 text-[11px] font-bold text-primary-fg shadow-sm tabular-nums">{rank}</span> : null}
      <div className="mb-3 flex items-center gap-2.5">
        <CompanyLogo size={40} />
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold group-hover:text-accent">{c.name}</div>
          <div className="truncate text-[11px] text-muted-fg">{[c.industry_text, c.region_text].filter(Boolean).join(" · ") || c.market}</div>
        </div>
      </div>
      <div className="mt-auto flex items-center justify-between gap-2 border-t border-border pt-2.5 text-xs">
        {tag ? <span className="inline-flex items-center gap-1 font-medium text-accent"><ThumbsUp className="h-3.5 w-3.5" />{tagLabel(t, tag)}</span>
          : c.review_count ? <RatingLine value={c.rating} count={c.review_count} size="sm" showCount />
          : <span className="inline-flex items-center gap-1.5 text-muted-fg">{c.market ? <Badge tone="outline">{c.market}</Badge> : null}{age ? <span>{t("cx.years", { n: age.n })}</span> : null}</span>}
        {c.review_count && tag ? <span className="text-muted-fg tabular-nums">{t("cx.reviews_n", { n: c.review_count })}</span>
          : c.open_jobs ? <span className="font-medium text-accent">{t("cx.hiring_n", { n: c.open_jobs })}</span> : null}
      </div>
    </Link>
  );
}

const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;
const PAGER_GAP = 12;

/** A row of cards that turns pages instead of scrolling: as many whole cards as fit the
 *  width, and ‹ › to see the next set. Nothing is ever cut at the edge — the count of
 *  columns comes from measuring the row, so every card is fully on screen or not at all.
 *  Until the row has been measured (server render) it holds its height with a skeleton. */
export function Pager<T>({ title, hint, icon, action, items, render, keyOf, minTile = 224, minTileSm = 160, className }: {
  title: ReactNode; hint?: ReactNode; icon?: ReactNode; action?: ReactNode; items: T[];
  render: (item: T, index: number) => ReactNode; keyOf: (item: T) => string; minTile?: number; minTileSm?: number; className?: string;
}) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);
  const [perPage, setPerPage] = useState<number | null>(null);
  const [page, setPage] = useState(0);
  useIsoLayoutEffect(() => {
    const el = ref.current; if (!el) return;
    const measure = () => {
      const w = el.clientWidth; if (!w) return;
      const min = window.innerWidth < 640 ? minTileSm : minTile;
      setPerPage(Math.max(1, Math.floor((w + PAGER_GAP) / (min + PAGER_GAP))));
    };
    measure();
    const ro = new ResizeObserver(measure); ro.observe(el);
    return () => ro.disconnect();
  }, [minTile, minTileSm]);
  const n = perPage ?? 4;
  const pages = Math.max(1, Math.ceil(items.length / n));
  const cur = Math.min(page, pages - 1);
  const slice = items.slice(cur * n, cur * n + n);
  return (
    <section className={cn("min-w-0", className)}>
      <SectionHeading eyebrow={hint} title={title} icon={icon} action={
        <>
          {action}
          {pages > 1 ? <span className="mr-1 text-xs text-muted-fg tabular-nums">{t("cx.page_of", { a: cur + 1, b: pages })}</span> : null}
          <Button size="icon-sm" variant="outline" aria-label="previous" disabled={cur === 0} onClick={() => setPage(cur - 1)}><ChevronLeft className="h-4 w-4" /></Button>
          <Button size="icon-sm" variant="outline" aria-label="next" disabled={cur >= pages - 1} onClick={() => setPage(cur + 1)}><ChevronRight className="h-4 w-4" /></Button>
        </>
      } />
      <div ref={ref} className="min-w-0">
        {perPage === null ? (
          <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
            {Array.from({ length: Math.min(n, items.length) }, (_, i) => <div key={i} className="h-[108px] animate-pulse rounded-2xl bg-muted" />)}
          </div>
        ) : (
          <div key={cur} className="fade-up grid gap-3" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
            {slice.map((it, i) => <div key={keyOf(it)} className="min-w-0">{render(it, cur * n + i)}</div>)}
          </div>
        )}
      </div>
    </section>
  );
}

/** A number with a caption, for a strip of quick facts. */
export function QuickFact({ label, value, icon, accent }: { label: ReactNode; value: ReactNode; icon?: ReactNode; accent?: boolean }) {
  return (
    <div className="flex min-w-0 items-center gap-2.5 rounded-xl bg-muted/60 px-3 py-2.5">
      {icon ? <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-card text-muted-fg">{icon}</span> : null}
      <div className="min-w-0">
        <div className={cn("truncate text-sm font-semibold tabular-nums", accent && "text-accent")}>{value}</div>
        <div className="truncate text-[11px] text-muted-fg">{label}</div>
      </div>
    </div>
  );
}
