"use client";
import { cn } from "@/lib/utils";

export function Switch({ checked, onChange, disabled, label, className, id }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: string; className?: string; id?: string }) {
  return (
    <button id={id} type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}
      className={cn("tap-area inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2 disabled:opacity-50", checked ? "bg-accent" : "bg-border", className)}>
      <span className={cn("inline-block h-5 w-5 rounded-full bg-white shadow transition-transform", checked ? "translate-x-6" : "translate-x-1")} />
    </button>
  );
}

export function SwitchRow({ title, description, checked, onChange, disabled }: { title: string; description?: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 min-h-[44px]">
      <div className="min-w-0">
        <div className="text-sm font-medium">{title}</div>
        {description ? <div className="text-xs text-muted-fg mt-0.5">{description}</div> : null}
      </div>
      <Switch checked={checked} onChange={onChange} disabled={disabled} label={title} />
    </div>
  );
}
