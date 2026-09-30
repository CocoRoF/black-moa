import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Mascot } from "@/components/brand/Logo";

/** Friendly empty state: the Memora mark with the section icon as a small badge. `plain` hides it. */
export function EmptyState({ icon, title, description, action, className, plain }: { icon?: ReactNode; title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string; plain?: boolean }) {
  return (
    <div className={cn("flex flex-col items-center justify-center text-center rounded-2xl border border-dashed border-border px-6 py-10", className)}>
      {/* The mark alone. It used to sit on a tinted disc with the section icon badged onto
          the corner — a composition built around the character illustration this replaced.
          Against the M both read as parts of a logo that does not exist. */}
      {!plain ? <div className="mb-3"><Mascot size={64} /></div>
        : icon ? <div className="mb-3 text-muted-fg [&>svg]:h-8 [&>svg]:w-8">{icon}</div> : null}
      <div className="text-[15px] font-medium">{title}</div>
      {description ? <p className="mt-1 max-w-sm text-sm text-muted-fg">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry, retryLabel }: { message: string; onRetry?: () => void; retryLabel?: string }) {
  return (
    <div role="alert" className="rounded-2xl border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger flex items-center justify-between gap-3">
      <span>{message}</span>
      {onRetry ? <button type="button" onClick={onRetry} className="underline underline-offset-2 shrink-0">{retryLabel ?? "Retry"}</button> : null}
    </div>
  );
}
