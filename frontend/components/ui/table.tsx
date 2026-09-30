"use client";
import { useEffect, useRef, type HTMLAttributes, type ReactNode, type TdHTMLAttributes, type ThHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Table({ className, children, ...p }: HTMLAttributes<HTMLTableElement>) {
  const ref = useRef<HTMLTableElement>(null);
  // On a phone the rows stack into cards (globals.css .tbl) and each cell needs to say
  // which column it was: the header's words, copied onto the cell as data-label.
  useEffect(() => {
    const tb = ref.current; if (!tb) return;
    const heads = [...tb.querySelectorAll(":scope > thead th")].map((th) => th.textContent?.trim() ?? "");
    tb.querySelectorAll(":scope > tbody > tr").forEach((tr) => {
      [...tr.children].forEach((td, i) => { if (heads[i]) td.setAttribute("data-label", heads[i]); else td.removeAttribute("data-label"); });
    });
  });
  return (
    <div className="w-full overflow-x-auto scrollbar-thin rounded-xl border border-border">
      <table ref={ref} className={cn("tbl w-full text-sm", className)} {...p}>{children}</table>
    </div>
  );
}
export function THead({ children }: { children: ReactNode }) { return <thead className="bg-muted/60 text-xs uppercase tracking-wide text-muted-fg">{children}</thead>; }
export function TBody({ children }: { children: ReactNode }) { return <tbody className="divide-y divide-border">{children}</tbody>; }
export function TR({ className, ...p }: HTMLAttributes<HTMLTableRowElement>) { return <tr className={cn("hover:bg-muted/40 transition-colors", className)} {...p} />; }
export function TH({ className, ...p }: ThHTMLAttributes<HTMLTableCellElement>) { return <th className={cn("px-3 py-2.5 text-left font-medium whitespace-nowrap", className)} {...p} />; }
export function TD({ className, ...p }: TdHTMLAttributes<HTMLTableCellElement>) { return <td className={cn("px-3 py-2.5 align-middle", className)} {...p} />; }
