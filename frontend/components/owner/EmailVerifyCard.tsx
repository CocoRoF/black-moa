"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { MailCheck, ShieldAlert } from "@/components/icons";
import { Auth } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { CODE_LENGTH, normalizeCode } from "@/lib/otp";
import { useAuth } from "@/stores/auth";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";

/** Verify this account's address before it can own a secretary.
 *
 *  Signing up is one step on purpose. This is the second one, and it appears where the
 *  restriction actually bites — in front of "create a secretary" — rather than as a 403
 *  after the wizard has been filled in.
 */
export function EmailVerifyCard({ mailConfigured, onVerified }: { mailConfigured: boolean; onVerified?: () => void }) {
  const t = useT(); const locale = useLocale();
  const user = useAuth((s) => s.user);
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const send = useMutation({
    mutationFn: Auth.sendVerification,
    onSuccess: () => { setSent(true); toast.success(t("settings.verify_sent")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const verify = useMutation({
    mutationFn: () => Auth.verifyEmail(code.trim()),
    onSuccess: async () => { setCode(""); const u = await Auth.me(); useAuth.getState().setUser(u); toast.success(t("settings.verified")); onVerified?.(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <Card className="p-5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 text-warning"><ShieldAlert className="h-5 w-5" /></span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold">{t("verify.title")}</h2>
          <p className="mt-1 text-sm text-muted-fg">{t("verify.why", { email: user?.email ?? "" })}</p>
          {!mailConfigured ? (
            <p className="mt-3 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">{t("verify.no_mail")}</p>
          ) : (
            <div className="mt-4 space-y-3">
              <Button variant={sent ? "outline" : "accent"} loading={send.isPending} onClick={() => send.mutate()}>
                <MailCheck className="h-4 w-4" />{sent ? t("verify.resend") : t("verify.send")}
              </Button>
              {sent ? (
                <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); verify.mutate(); }}>
                  <Field label={t("verify.code")} className="min-w-[160px]">
                    <Input value={code} onChange={(e) => setCode(normalizeCode(e.target.value))} inputMode="numeric"
                           autoComplete="one-time-code" placeholder="000000" className="font-mono tracking-widest" />
                  </Field>
                  <Button type="submit" loading={verify.isPending} disabled={code.length < CODE_LENGTH}>{t("verify.submit")}</Button>
                </form>
              ) : null}
              {sent ? <p className="text-xs text-muted-fg">{t("verify.spam_hint")}</p> : null}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
