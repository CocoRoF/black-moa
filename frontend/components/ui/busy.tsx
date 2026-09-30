"use client";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** A refresh that keeps its content.
 *
 *  A list whose filter changed still holds the right shape and mostly the right rows, so
 *  replacing it with skeletons costs more than it explains. This dims what is there and
 *  runs a hairline bar over it instead — no layout shift, and the eye stays where it was. */
export function Busy({ busy, children, className }: { busy?: boolean; children: ReactNode; className?: string }) {
  return (
    <div className={cn("relative", className)}>
      {busy ? <span className="busy-bar z-[1]" aria-hidden /> : null}
      <div aria-busy={busy || undefined} className={busy ? "is-busy" : "is-idle"}>{children}</div>
    </div>
  );
}
