"use client";
import type { ReactNode } from "react";
import { cn, initials } from "@/lib/utils";
import { BRAND } from "@/lib/brand";

/** `mascot`: secretary avatars fall back to the black-moa mark instead of initials when there is no image. */
export function Avatar({ name, src, size = 40, className, shape = "circle", accent, mascot }: { name?: string | null; src?: string | null; size?: number; className?: string; shape?: "circle" | "rounded" | string; accent?: string; mascot?: boolean }) {
  const r = shape === "circle" ? "rounded-full" : "rounded-xl";
  const style = { width: size, height: size, fontSize: Math.max(11, size * 0.4), background: accent ? `color-mix(in oklab, ${accent} 18%, transparent)` : undefined, color: accent };
  // eslint-disable-next-line @next/next/no-img-element
  if (src) return <img src={src} alt={name ?? ""} width={size} height={size} className={cn("object-cover shrink-0", r, className)} style={{ width: size, height: size }} />;
  if (mascot) {
    return (
      <span aria-hidden className={cn("inline-flex shrink-0 items-center justify-center select-none", className)} style={{ width: size, height: size }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={BRAND.characterIcon} alt="" width={247} height={195} className="block h-auto w-full" draggable={false} />
      </span>
    );
  }
  return <span aria-hidden className={cn("inline-flex shrink-0 items-center justify-center font-semibold bg-accent/15 text-accent select-none", r, className)} style={style}>{initials(name)}</span>;
}

export function Progress({ value, max = 1, className, tone = "accent" }: { value: number; max?: number; className?: string; tone?: "accent" | "danger" | "warning" | "success" }) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  const c = { accent: "bg-accent", danger: "bg-danger", warning: "bg-warning", success: "bg-success" }[tone];
  return <div role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} className={cn("h-2 w-full overflow-hidden rounded-full bg-muted", className)}><div className={cn("h-full rounded-full transition-[width]", c)} style={{ width: `${pct}%` }} /></div>;
}

export function Stat({ label, value, hint, icon, className }: { label: ReactNode; value: ReactNode; hint?: ReactNode; icon?: ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-2xl border border-border bg-card p-4", className)}>
      <div className="flex items-center justify-between text-xs text-muted-fg"><span>{label}</span>{icon ? <span className="[&>svg]:h-4 [&>svg]:w-4">{icon}</span> : null}</div>
      <div className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-muted-fg">{hint}</div> : null}
    </div>
  );
}

/** `lead` sits to the left of the title — a back arrow for a page that is a step inside
 *  another one, so it does not need a second heading of its own to be one. */
export function PageHeader({ title, description, action, back, lead, className }: { title: ReactNode; description?: ReactNode; action?: ReactNode; back?: ReactNode; lead?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 mb-5", className)}>
      <div className="flex min-w-0 items-center gap-1.5">
        {lead}
        <div className="min-w-0">
          {back}
          <h1 className="text-xl md:text-2xl font-semibold tracking-tight">{title}</h1>
          {description ? <p className="mt-1 text-sm text-muted-fg">{description}</p> : null}
        </div>
      </div>
      {action ? <div className="flex flex-wrap gap-2 shrink-0">{action}</div> : null}
    </div>
  );
}

export function TagInput({ value, onChange, placeholder, id }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; id?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-border bg-input px-2 py-1 min-h-[40px] focus-within:outline-2 focus-within:outline-ring">
      {value.map((t, i) => (
        <span key={`${t}-${i}`} className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-xs">
          {t}<button type="button" aria-label={`remove ${t}`} onClick={() => onChange(value.filter((_, j) => j !== i))} className="text-muted-fg hover:text-fg">×</button>
        </span>
      ))}
      <input id={id} className="flex-1 min-w-[100px] bg-transparent px-1.5 py-1 text-sm outline-none" placeholder={placeholder}
        onKeyDown={(e) => {
          const el = e.currentTarget;
          // 한글을 치는 중의 Enter 는 글자를 확정하는 Enter 다. 그것으로 칸을 닫으면
          // 반만 쓴 낱말이 태그가 된다.
          if (((e.key === "Enter" && !e.nativeEvent.isComposing) || e.key === ",") && el.value.trim()) { e.preventDefault(); onChange([...value, el.value.trim()]); el.value = ""; }
          else if (e.key === "Backspace" && !el.value && value.length) onChange(value.slice(0, -1));
        }}
        onBlur={(e) => { const v = e.currentTarget.value.trim(); if (v) { onChange([...value, v]); e.currentTarget.value = ""; } }} />
    </div>
  );
}

export function KeyValue({ items, className }: { items: { k: ReactNode; v: ReactNode }[]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm", className)}>
      {items.map((it, i) => (<div key={i} className="contents"><dt className="text-muted-fg">{it.k}</dt><dd className="min-w-0 break-words">{it.v}</dd></div>))}
    </dl>
  );
}

export function Bars({ data, height = 120, className, format, emptyLabel }: { data: { label: string; value: number; secondary?: number }[]; height?: number; className?: string; format?: (v: number) => string; emptyLabel?: string }) {
  const peak = Math.max(...data.map((d) => Math.max(d.value, d.secondary ?? 0)), 0);
  const max = Math.max(1, peak);
  const w = 100; const bw = data.length ? w / data.length : w;
  // Bars alone leave a chart with one busy day looking broken. A baseline, two gridlines and
  // the peak value give the empty space a scale to be empty against.
  const grid = [0.25, 0.5, 0.75, 1];
  return (
    <div className={cn("relative", className)}>
      <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }} role="img" aria-label={emptyLabel}>
        {grid.map((g) => (
          <line key={g} x1={0} x2={w} y1={height - g * (height - 4)} y2={height - g * (height - 4)}
            stroke="var(--border)" strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={g === 1 ? 0.9 : 0.5} strokeDasharray={g === 1 ? undefined : "3 3"} />
        ))}
        <line x1={0} x2={w} y1={height} y2={height} stroke="var(--border)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        {data.map((d, i) => {
          const h = (d.value / max) * (height - 4);
          const h2 = ((d.secondary ?? 0) / max) * (height - 4);
          return (
            <g key={i}>
              <title>{`${d.label}: ${format ? format(d.value) : d.value}`}</title>
              {d.secondary ? <rect x={i * bw + bw * 0.15} y={height - h2} width={bw * 0.7} height={h2} fill="var(--fg)" opacity={0.22} /> : null}
              <rect x={i * bw + bw * 0.15} y={height - h} width={bw * 0.7} height={h} fill="var(--accent)" opacity={0.9} />
            </g>
          );
        })}
      </svg>
      {/* top-left: the busiest day is usually the most recent one, on the right */}
      {peak > 0 ? <span className="pointer-events-none absolute left-0 top-0 rounded bg-card/80 px-1 text-[10px] tabular-nums text-muted-fg">{format ? format(peak) : peak}</span> : null}
      {peak === 0 && emptyLabel ? (
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-muted-fg">{emptyLabel}</span>
      ) : null}
    </div>
  );
}
