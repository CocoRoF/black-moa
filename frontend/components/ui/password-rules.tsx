"use client";
import { Check, X } from "@/components/icons";
import { useT } from "@/lib/i18n";
import { CLASSES_REQUIRED, PASSWORD_MIN, type PasswordVerdict } from "@/lib/password";
import { cn } from "@/lib/utils";

/** The live checklist under the password field.
 *
 *  Every rule stays on screen whether met or not: a list that hides what you have already
 *  satisfied leaves you guessing how much is left, and one that only appears on failure
 *  arrives after the mistake instead of before it. */
export function PasswordRules({ verdict, show, id = "pw-rules" }: { verdict: PasswordVerdict; show: boolean; id?: string }) {
  const t = useT();
  if (!show) return null;
  return (
    <div id={id} aria-live="polite" className="rounded-xl border border-border bg-card px-3.5 py-3 text-xs shadow-sm">
      <p className="font-medium text-fg">{t("auth.pw_title")}</p>
      <div className="mt-2"><Rule ok={verdict.longEnough} label={t("auth.pw_len", { n: PASSWORD_MIN })} /></div>
      <p className="mt-2.5 text-muted-fg">{t("auth.pw_classes", { n: CLASSES_REQUIRED })}</p>
      <div className="mt-1.5 space-y-1">
        {verdict.classes.map((c) => <Rule key={c.key} ok={c.ok} label={t(`auth.pw_${c.key}`)} />)}
      </div>
      {/* Only once it would actually be the thing standing in the way. */}
      {!verdict.notCommon ? <p className="mt-2 text-danger">{t("auth.pw_common")}</p> : null}
    </div>
  );
}

function Rule({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={cn("flex items-center gap-1.5", ok ? "text-success" : "text-muted-fg")}>
      {ok ? <Check className="h-3.5 w-3.5 shrink-0" /> : <X className="h-3.5 w-3.5 shrink-0 opacity-50" />}
      {label}
    </span>
  );
}
