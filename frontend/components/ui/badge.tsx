import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger" | "outline";
const tones: Record<BadgeTone, string> = {
  neutral: "bg-muted text-muted-fg",
  accent: "bg-accent/12 text-accent",
  success: "bg-success/12 text-success",
  warning: "bg-warning/15 text-warning",
  danger: "bg-danger/12 text-danger",
  outline: "border border-border text-muted-fg",
};
export function Badge({ tone = "neutral", className, ...p }: HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }) {
  return <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium leading-5 whitespace-nowrap", tones[tone], className)} {...p} />;
}
export function StatusDot({ tone = "neutral", className }: { tone?: BadgeTone; className?: string }) {
  const c = { neutral: "bg-muted-fg", accent: "bg-accent", success: "bg-success", warning: "bg-warning", danger: "bg-danger", outline: "bg-border" }[tone];
  return <span aria-hidden className={cn("inline-block h-2 w-2 rounded-full", c, className)} />;
}
