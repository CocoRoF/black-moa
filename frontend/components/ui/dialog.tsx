"use client";
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "@/components/icons";
import { cn } from "@/lib/utils";
import { Button } from "./button";

function useLockBody(open: boolean) {
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [open]);
}

function useEsc(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
}

function useFocusTrap(open: boolean, ref: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    if (!open || !ref.current) return;
    const el = ref.current;
    const prevActive = document.activeElement as HTMLElement | null;
    const focusables = () => Array.from(el.querySelectorAll<HTMLElement>('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])')).filter((x) => !x.hasAttribute("disabled"));
    const first = focusables()[0];
    (first ?? el).focus({ preventScroll: true });
    const h = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const f = focusables(); if (!f.length) return;
      const a = f[0], z = f[f.length - 1];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    };
    el.addEventListener("keydown", h);
    return () => { el.removeEventListener("keydown", h); prevActive?.focus?.({ preventScroll: true }); };
  }, [open, ref]);
}

/** `bare` hands the whole card over: no title row, no padding, no footer rail. For a
 *  window whose content is the frame — a photo and the conversation beside it — a heading
 *  that names the window is a strip of chrome above the thing you came to look at.
 *
 *  `guard` is for a window with unsaved work in it: the backdrop and Escape stop closing
 *  it, so the only way out is the button that asks first. Losing what somebody typed to a
 *  stray click is not a thing a window may do. */
export function Dialog({ open, onClose, title, description, children, footer, size = "md", className, bare, guard }: { open: boolean; onClose: () => void; title?: ReactNode; description?: ReactNode; children?: ReactNode; footer?: ReactNode; size?: "sm" | "md" | "lg" | "xl"; className?: string; bare?: boolean; guard?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useLockBody(open); useEsc(open && !guard, onClose); useFocusTrap(open, ref);
  if (!open || typeof document === "undefined") return null;
  const w = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl", xl: "max-w-4xl" }[size];
  return createPortal(
    // A bottom sheet only on an actual phone: a 560px-wide desktop window used to get the
    // sheet treatment, which pinned the buttons to the very bottom edge of the screen.
    <div className="fixed inset-0 z-[100] flex items-end min-[480px]:items-center justify-center p-0 min-[480px]:p-4" role="presentation">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={guard ? undefined : onClose} />
      <div ref={ref} role="dialog" aria-modal="true" tabIndex={-1} aria-label={typeof title === "string" ? title : undefined}
        className={cn("relative w-full bg-card text-fg border border-border shadow-2xl rounded-t-2xl min-[480px]:rounded-2xl max-h-[92dvh] flex flex-col sheet-up min-[480px]:fade-up outline-none", w, className)}>
        {bare ? (
          // Outside the card on a desktop, the way a lightbox closes; tucked into the
          // corner on a phone, where there is no room beside it.
          <button type="button" onClick={onClose} aria-label="close"
                  className="absolute right-2 top-2 z-10 rounded-full bg-fg/70 p-1.5 text-bg shadow-lg backdrop-blur transition-colors hover:bg-fg min-[480px]:-right-12 min-[480px]:top-0">
            <X className="h-5 w-5" />
          </button>
        ) : null}
        {/* grab affordance, phone only */}
        {bare ? null : <div aria-hidden className="mx-auto mt-2 h-1 w-9 shrink-0 rounded-full bg-border min-[480px]:hidden" />}
        {(title || description) && !bare ? (
          <div className="flex items-start justify-between gap-3 px-5 pt-4 min-[480px]:pt-5 pb-3">
            <div className="min-w-0">
              {title ? <h2 className="text-base font-semibold">{title}</h2> : null}
              {description ? <p className="mt-1 text-sm text-muted-fg">{description}</p> : null}
            </div>
            <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="close"><X className="h-4 w-4" /></Button>
          </div>
        ) : null}
        <div className={cn("overflow-y-auto scrollbar-thin flex-1 min-h-0", bare ? "overflow-hidden rounded-t-2xl min-[480px]:rounded-2xl" : "px-5 pb-5 pt-1")}>{children}</div>
        {/* One row, primary last, everywhere: stacking put the primary above "cancel", which
            reads as the wrong order, and full-width buttons made the sheet bottom-heavy. */}
        {footer && !bare ? <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3.5 pb-[max(0.875rem,env(safe-area-inset-bottom))] min-[480px]:py-4">{footer}</div> : null}
      </div>
    </div>, document.body);
}

/** Bottom sheet on mobile, right drawer on desktop (side="right") or bottom on all (side="bottom"). */
export function Sheet({ open, onClose, title, children, side = "bottom", className, footer }: { open: boolean; onClose: () => void; title?: ReactNode; children?: ReactNode; side?: "bottom" | "right"; className?: string; footer?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const startY = useRef<number | null>(null);
  useLockBody(open); useEsc(open, onClose); useFocusTrap(open, ref);
  if (!open || typeof document === "undefined") return null;
  const isRight = side === "right";
  return createPortal(
    <div className="fixed inset-0 z-[100]" role="presentation">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div ref={ref} role="dialog" aria-modal="true" tabIndex={-1}
        onTouchStart={(e) => { startY.current = e.touches[0].clientY; }}
        onTouchEnd={(e) => { if (startY.current !== null && e.changedTouches[0].clientY - startY.current > 80 && !isRight) onClose(); startY.current = null; }}
        className={cn("absolute bg-card text-fg border-border shadow-2xl flex flex-col outline-none",
          isRight ? "top-0 right-0 h-full w-full sm:w-[440px] border-l fade-up" : "bottom-0 left-0 right-0 rounded-t-2xl border-t max-h-[90dvh] sheet-up md:left-1/2 md:right-auto md:w-[520px] md:-translate-x-1/2",
          className)}>
        {!isRight ? <div className="mx-auto mt-2 h-1.5 w-10 rounded-full bg-border" aria-hidden /> : null}
        <div className="flex items-center justify-between gap-3 px-5 pt-3 pb-2">
          {title ? <h2 className="text-base font-semibold">{title}</h2> : <span />}
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="close"><X className="h-4 w-4" /></Button>
        </div>
        <div className="px-5 pt-1 pb-[max(1.25rem,var(--sab))] overflow-y-auto scrollbar-thin flex-1 min-h-0">{children}</div>
        {footer ? <div className="px-5 pt-3 pb-[max(0.75rem,var(--sab))] border-t border-border">{footer}</div> : null}
      </div>
    </div>, document.body);
}

export function ConfirmDialog({ open, onClose, onConfirm, title, description, confirmLabel, cancelLabel, danger, loading }: { open: boolean; onClose: () => void; onConfirm: () => void | Promise<void>; title: ReactNode; description?: ReactNode; confirmLabel: string; cancelLabel: string; danger?: boolean; loading?: boolean }) {
  return (
    <Dialog open={open} onClose={onClose} title={title} description={description} size="sm"
      footer={<><Button variant="outline" onClick={onClose}>{cancelLabel}</Button><Button variant={danger ? "danger" : "primary"} loading={loading} onClick={() => void onConfirm()}>{confirmLabel}</Button></>} />
  );
}
