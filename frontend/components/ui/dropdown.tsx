"use client";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

export interface MenuItem { key: string; label: ReactNode; icon?: ReactNode; onSelect?: () => void; danger?: boolean; disabled?: boolean; separator?: boolean }

/** Portaled dropdown (fixed positioning) so it is never clipped or covered by sibling
 *  stacking contexts (backdrop-blur headers, virtualized lists).
 *
 *  Above a dialog (100) and below the question a menu item may ask (120): a menu opened
 *  from inside a window has to be pressable, and it is closed by the time anything is
 *  asked. It sat under the window before, drawn and dead. */
/** `menuClassName` 은 떠오르는 차림표에 붙는다. 차림표는 body 로 나가므로 부르는 곳의 `.dark` 같은 범위를 물려받지
 *  못한다 — 어두운 무대처럼 범위가 다른 곳은 여기로 넘긴다. */
export function DropdownMenu({ trigger, items, align = "end", className, menuClassName }: { trigger: ReactNode; items: MenuItem[]; align?: "start" | "end"; className?: string; menuClassName?: string }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left?: number; right?: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!open || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    setPos(align === "end" ? { top: r.bottom + 4, right: Math.max(8, window.innerWidth - r.right) } : { top: r.bottom + 4, left: Math.max(8, r.left) });
  }, [open, align]);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent | TouchEvent) => { const t = e.target as Node; if (!ref.current?.contains(t) && !menuRef.current?.contains(t)) setOpen(false); };
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const close = () => setOpen(false);
    document.addEventListener("mousedown", h); document.addEventListener("touchstart", h); window.addEventListener("keydown", k);
    window.addEventListener("resize", close); window.addEventListener("scroll", close, true);
    return () => { document.removeEventListener("mousedown", h); document.removeEventListener("touchstart", h); window.removeEventListener("keydown", k); window.removeEventListener("resize", close); window.removeEventListener("scroll", close, true); };
  }, [open]);
  return (
    <div ref={ref} className={cn("relative inline-block", className)}>
      <div onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open}>{trigger}</div>
      {open && pos && typeof document !== "undefined" ? createPortal(
        <div ref={menuRef} role="menu" style={{ position: "fixed", top: pos.top, left: pos.left, right: pos.right }} className={cn("z-[110] min-w-[180px] max-w-[calc(100vw-16px)] rounded-xl border border-border bg-card p-1 shadow-xl fade-up text-fg", menuClassName)}>
          {items.map((it) => it.separator ? <div key={it.key} className="my-1 h-px bg-border" /> : (
            <button key={it.key} role="menuitem" type="button" disabled={it.disabled} onClick={() => { setOpen(false); it.onSelect?.(); }}
              className={cn("flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm min-h-[40px] hover:bg-muted disabled:opacity-40", it.danger && "text-danger")}>
              {it.icon ? <span className="shrink-0 [&>svg]:h-4 [&>svg]:w-4">{it.icon}</span> : null}
              <span className="truncate">{it.label}</span>
            </button>
          ))}
        </div>, document.body) : null}
    </div>
  );
}
