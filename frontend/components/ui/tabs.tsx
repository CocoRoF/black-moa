"use client";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

// useLayoutEffect measures before paint, which is what keeps the pill from visibly jumping
// into place; on the server there is nothing to measure, so it degrades to useEffect.
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

export interface TabItem<T extends string = string> { key: T; label: ReactNode; count?: number; disabled?: boolean }
export function Tabs<T extends string>({ items, value, onChange, className, size = "md" }: { items: TabItem<T>[]; value: T; onChange: (k: T) => void; className?: string; size?: "sm" | "md" }) {
  return (
    // shrink-0 is load-bearing: a scroll container's automatic minimum size is 0, so inside a
    // flex column whose content overflows (the network page) this strip was the one item free
    // to collapse — it flattened to its 1px border while its 44px buttons overflowed under the
    // list below, which then swallowed their clicks.
    <div role="tablist" className={cn("flex shrink-0 gap-1 overflow-x-auto scroll-fade-x border-b border-border -mb-px", className)}>
      {items.map((it) => (
        <button key={it.key} role="tab" type="button" aria-selected={value === it.key} disabled={it.disabled} onClick={() => onChange(it.key)}
          className={cn("relative shrink-0 whitespace-nowrap border-b-2 font-medium transition-colors disabled:opacity-40", size === "sm" ? "px-2.5 py-1.5 text-[13px]" : "px-3 py-2 text-sm min-h-[36px]",
            value === it.key ? "border-accent text-fg" : "border-transparent text-muted-fg hover:text-fg")}>
          {it.label}
          {typeof it.count === "number" ? <span className="ml-1.5 rounded-full bg-muted px-1.5 text-[11px] text-muted-fg">{it.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange, className, size = "md", ariaLabel }: { options: { value: T; label: ReactNode; title?: string }[]; value: T; onChange: (v: T) => void; className?: string; size?: "sm" | "md"; ariaLabel?: string }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState<{ x: number; w: number } | null>(null);

  // The pill is measured from the selected button rather than drawn under it, so it can
  // slide between options. Until the measurement lands — server render, first paint — the
  // selected button carries the surface itself, which is why there is never a frame with
  // nothing marked.
  const measure = useCallback(() => {
    const wrap = wrapRef.current;
    const el = wrap?.querySelector<HTMLElement>('[data-seg-active="true"]');
    if (!wrap || !el) return;
    setPill({ x: el.offsetLeft, w: el.offsetWidth });
  }, []);

  useIsoLayoutEffect(() => {
    measure();
    const wrap = wrapRef.current;
    if (!wrap || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [measure, value, options.length]);

  return (
    <div ref={wrapRef} role="radiogroup" aria-label={ariaLabel} className={cn("relative inline-flex items-center rounded-xl bg-muted p-[3px] gap-0.5", className)}>
      {pill ? (
        <span aria-hidden className="pointer-events-none absolute inset-y-[3px] rounded-lg bg-card shadow-sm transition-[transform,width] duration-200 ease-out"
              style={{ width: pill.w, transform: `translateX(${pill.x - 3}px)`, left: 3 }} />
      ) : null}
      {options.map((o) => {
        const active = value === o.value;
        return (
          <button key={o.value} type="button" role="radio" aria-checked={active} title={o.title} data-seg-active={active} onClick={() => onChange(o.value)}
            className={cn("relative z-[1] rounded-lg font-medium transition-colors whitespace-nowrap", // A thumb needs more than a cursor does. The compact size keeps its desktop
              // proportions above sm: and grows on phones, where 31px was a miss waiting
              // to happen.
              size === "sm" ? "px-2.5 text-xs h-[26px]" : "px-3 text-[13px] h-[30px]",
              // 고른 것과 안 고른 것은 알약으로만 가른다. 글자 대비까지 크게 벌리면 같은 크기의 글자가
              // 고른 쪽만 커 보인다(흰 바탕의 검정 대 회색 바탕의 흐린 회색).
              active ? "text-fg" : "text-fg/70 hover:text-fg", active && !pill ? "bg-card shadow-sm" : "")}>{o.label}</button>
        );
      })}
    </div>
  );
}
