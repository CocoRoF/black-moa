"use client";
import Link from "next/link";
import { toast } from "sonner";
import { ArrowLeftRight, Check, Plus, X } from "@/components/icons";
import { useT } from "@/lib/i18n";
import { COMPARE_MAX, compareStore, useCompare } from "@/lib/compare";
import { cn } from "@/lib/utils";
import { Button, buttonLook } from "@/components/ui/button";

/** The button on a company: in the tray or not. */
export function CompareButton({ id, name, size = "md", className }: { id: string; name: string; size?: "sm" | "md"; className?: string }) {
  const t = useT();
  const picked = useCompare().some((e) => e.id === id);
  const onClick = (e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation();
    const r = compareStore.toggle({ id, name });
    if (r === "full") toast.error(t("cx.compare_full", { n: COMPARE_MAX }));
    else if (r === "added") toast.success(t("cx.compare_added"));
  };
  return (
    <Button size={size} variant={picked ? "secondary" : "outline"} aria-pressed={picked} onClick={onClick} className={className}>
      {picked ? <Check className="h-4 w-4" /> : <ArrowLeftRight className="h-4 w-4" />}{t(picked ? "cx.compare_remove" : "cx.compare_add")}
    </Button>
  );
}

/** The tray itself: a bar that appears at the bottom once there is something in it,
 *  with the picks as chips and one way forward. Rendered by every company screen. */
export function CompareTray({ className }: { className?: string }) {
  const t = useT();
  const picks = useCompare();
  if (!picks.length) return null;
  return (
    <div className={cn("bottom-bar sticky bottom-0 z-20 mt-6 -mx-4 border-t border-border bg-card/95 px-4 py-2.5 backdrop-blur md:-mx-6 md:px-6", className)} role="region" aria-label={t("cx.compare_tray")}>
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted-fg"><ArrowLeftRight className="h-3.5 w-3.5" />{t("cx.compare_tray")} <span className="tabular-nums">{picks.length}/{COMPARE_MAX}</span></span>
        <ul className="flex flex-wrap items-center gap-1.5">
          {picks.map((p) => (
            <li key={p.id} className="inline-flex items-center gap-1 rounded-full border border-border bg-bg px-2.5 py-1 text-xs">
              <span className="max-w-[140px] truncate">{p.name}</span>
              <button type="button" aria-label={`${t("common.delete")} ${p.name}`} onClick={() => compareStore.remove(p.id)} className="text-muted-fg hover:text-fg"><X className="h-3 w-3" /></button>
            </li>
          ))}
          {picks.length < COMPARE_MAX ? <li className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2.5 py-1 text-xs text-muted-fg"><Plus className="h-3 w-3" />{COMPARE_MAX - picks.length}</li> : null}
        </ul>
        <span className="ml-auto flex items-center gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => compareStore.clear()}>{t("cx.compare_clear")}</Button>
          {/* 버튼 모양을 입은 링크. 링크 안의 버튼은 누를 것이 둘이고, 어느 브라우저도
              그대로 두지 않는 markup 이다. */}
          {picks.length < 2
            ? <span className={buttonLook("accent", "sm", "pointer-events-none opacity-50")}>{t("cx.compare_view")}</span>
            : <Link href={`/app/community/companies/compare?ids=${picks.map((p) => p.id).join(",")}`}
                    className={buttonLook("accent", "sm")}>{t("cx.compare_view")}</Link>}
        </span>
      </div>
    </div>
  );
}
