"use client";
import { cn } from "@/lib/utils";

export function Slider({ value, onChange, min = 0, max = 1, step = 0.05, label, leftLabel, rightLabel, className, id }: { value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; label?: string; leftLabel?: string; rightLabel?: string; className?: string; id?: string }) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div className={cn("w-full", className)}>
      {label ? <div className="flex items-center justify-between text-sm mb-1"><span className="font-medium">{label}</span><span className="text-muted-fg tabular-nums text-xs">{Math.round(value * 100)}</span></div> : null}
      <input id={id} type="range" min={min} max={max} step={step} value={value} aria-label={label} onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-11 cursor-pointer appearance-none bg-transparent [&::-webkit-slider-runnable-track]:h-2 [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-6 [&::-webkit-slider-thumb]:w-6 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-card [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-accent [&::-webkit-slider-thumb]:shadow [&::-webkit-slider-thumb]:-mt-2 [&::-moz-range-track]:h-2 [&::-moz-range-track]:rounded-full [&::-moz-range-thumb]:h-6 [&::-moz-range-thumb]:w-6 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-card [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-accent"
        style={{ background: `linear-gradient(to right, var(--accent) ${pct}%, var(--border) ${pct}%)`, borderRadius: 999, height: 8 }} />
      {(leftLabel || rightLabel) ? <div className="flex justify-between text-[11px] text-muted-fg mt-1"><span>{leftLabel}</span><span>{rightLabel}</span></div> : null}
    </div>
  );
}
