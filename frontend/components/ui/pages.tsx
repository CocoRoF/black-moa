"use client";
import { ChevronLeft, ChevronRight } from "@/components/icons";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/** Turning pages.
 *
 *  For a shelf somebody looks through rather than a river they scroll: my own writing,
 *  somebody's grid of posts. One page is one screenful, and the number says where you are
 *  so going back to the thing you saw a minute ago is possible at all. Draws nothing when
 *  there is only one page.
 */
export function Pages({ page, pages, onGo, className }: {
  page: number; pages: number; onGo: (n: number) => void; className?: string;
}) {
  const t = useT();
  if (pages <= 1) return null;
  const step = (n: number) => { onGo(Math.min(pages, Math.max(1, n))); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const btn = "rounded-lg border border-border p-2 text-muted-fg hover:border-accent hover:text-accent disabled:opacity-40 disabled:hover:border-border disabled:hover:text-muted-fg";
  return (
    <div className={cn("mt-4 flex items-center justify-center gap-3", className)}>
      <button type="button" aria-label={t("common.prev")} disabled={page <= 1} onClick={() => step(page - 1)} className={btn}>
        <ChevronLeft className="h-4 w-4" />
      </button>
      <span className="text-sm tabular-nums text-muted-fg">{page} / {pages}</span>
      <button type="button" aria-label={t("common.next")} disabled={page >= pages} onClick={() => step(page + 1)} className={btn}>
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}
