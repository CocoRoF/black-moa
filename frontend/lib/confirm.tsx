"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle } from "@/components/icons";
import { translate } from "@/lib/i18n";
import { useAuth } from "@/stores/auth";
import { cn } from "@/lib/utils";

/** Asking before something irreversible, the way `toast()` announces after it.
 *
 *  Imperative on purpose: a question belongs at the moment of the decision, inside the
 *  handler that is about to act, not hoisted into component state that every caller has to
 *  invent. `if (await confirm({...}))` reads as the sentence it is.
 *
 *  The browser's own `confirm()` would do this in one line and is wrong here: it is modal
 *  to the whole tab, unstyleable, says "memo-ora.com says", and on iOS Safari it can be
 *  suppressed entirely — a question the user never sees, answered `false`.
 */
export interface ConfirmOptions {
  title: ReactNode;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Red confirm button, for anything destructive or one-way. */
  danger?: boolean;
  icon?: ReactNode;
}

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };

let emit: ((p: Pending | null) => void) | null = null;
const queue: Pending[] = [];

/** Resolves true if the person confirmed, false for cancel, Escape or the backdrop. */
export function confirm(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    const pending: Pending = { ...options, resolve };
    // Without a host mounted the question cannot be asked, and answering it "yes" on the
    // caller's behalf is the one thing this must never do.
    if (!emit) { resolve(false); return; }
    queue.push(pending);
    if (queue.length === 1) emit(pending);
  });
}

function next() {
  queue.shift();
  emit?.(queue[0] ?? null);
}

/** Mount once, beside the toaster. */
export function ConfirmHost() {
  // 이 창은 화면 틀(LocaleProvider) 바깥에 있다 — 사용자가 고른 말을 직접 읽는다.
  const locale = useAuth((s) => s.user?.locale) ?? "ko";
  const t = (key: string) => translate(locale, key);
  const [pending, setPending] = useState<Pending | null>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    emit = setPending;
    return () => { emit = null; };
  }, []);

  useEffect(() => {
    if (!pending) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    confirmRef.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); answer(false); }
      if (e.key === "Enter" && document.activeElement === confirmRef.current) return;
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending]);

  if (!pending || typeof document === "undefined") return null;

  function answer(ok: boolean) {
    pending?.resolve(ok);
    next();
  }

  return createPortal(
    <div className="fixed inset-0 z-[120] flex items-end justify-center p-0 sm:items-center sm:p-4" role="presentation">
      <div className="absolute inset-0 bg-black/45 backdrop-blur-[2px]" onClick={() => answer(false)} />
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title"
           className="sheet-up sm:fade-up relative w-full max-w-[400px] rounded-t-2xl border border-border bg-card p-5 shadow-2xl sm:rounded-2xl">
        <div className="flex gap-3.5">
          <span className={cn("mt-0.5 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl",
                              pending.danger ? "bg-danger/12 text-danger" : "bg-accent/12 text-accent")}>
            {pending.icon ?? <AlertTriangle className="h-5 w-5" />}
          </span>
          <div className="min-w-0 flex-1">
            <h2 id="confirm-title" className="text-[15px] font-semibold leading-snug">{pending.title}</h2>
            {pending.description ? <p className="mt-1.5 text-sm leading-relaxed text-muted-fg">{pending.description}</p> : null}
          </div>
        </div>
        {/* Confirm last, the way every other footer in the app orders its actions. */}
        <div className="mt-5 flex gap-2">
          <button type="button" onClick={() => answer(false)}
                  className="h-11 flex-1 rounded-xl border border-border bg-card text-sm font-medium hover:bg-muted">
            {pending.cancelLabel ?? t("common.cancel")}
          </button>
          <button ref={confirmRef} type="button" onClick={() => answer(true)}
                  className={cn("h-11 flex-1 rounded-xl text-sm font-medium text-accent-fg transition-opacity hover:opacity-90",
                                pending.danger ? "bg-danger text-danger-fg" : "bg-accent")}>
            {pending.confirmLabel ?? t("common.confirm")}
          </button>
        </div>
      </div>
    </div>, document.body);
}
