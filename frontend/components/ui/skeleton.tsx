import { cn } from "@/lib/utils";
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-lg bg-muted", className)} />;
}
export function SkeletonRows({ n = 3, className }: { n?: number; className?: string }) {
  return <div className={cn("space-y-2", className)}>{Array.from({ length: n }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>;
}
export function Spinner({ className }: { className?: string }) {
  return <span role="status" aria-label="loading" className={cn("inline-block h-5 w-5 animate-spin rounded-full border-2 border-border border-t-accent", className)} />;
}
