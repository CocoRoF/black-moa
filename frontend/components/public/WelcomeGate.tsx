"use client";
import { useState } from "react";
import { LogIn, UserPlus } from "@/components/icons";
import { post } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { useT, type Locale } from "@/lib/i18n";
import { checkPassword } from "@/lib/password";
import { PasswordRules } from "@/components/ui/password-rules";
import { useAuth, type User } from "@/stores/auth";
import { Avatar } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { TermsAgree } from "@/components/auth/TermsAgree";
import { AiNotice } from "./AiNotice";

export type GateChoice = { mode: "anon" } | { mode: "account"; token: string; user: User };

/** The door to someone's secretary.
 *
 *  A shared link used to drop every arrival straight into an anonymous session, so the
 *  secretary had to ask who it was talking to and the visitor had no way to be recognised
 *  next time. Signing in is offered first, anonymous stays one click away — the point is to
 *  give the choice, not to force an account.
 */
export function WelcomeGate({ agentName, ownerName, avatarUrl, accent, shape, locale, canSignUp, onDone }: {
  agentName: string; ownerName: string; avatarUrl: string | null;
  accent?: string; shape?: string;
  locale: Locale;
  /** Invite-only and closed installs must not offer a button that can only fail. */
  canSignUp: boolean;
  onDone: (c: GateChoice) => void;
}) {
  const t = useT();
  const [mode, setMode] = useState<"choose" | "login" | "signup">("choose");
  const [email, setEmail] = useState(""); const [pw, setPw] = useState(""); const [pw2, setPw2] = useState("");
  const verdict = checkPassword(pw);
  const [name, setName] = useState(""); const [nickname, setNickname] = useState("");
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const [agree, setAgree] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const path = mode === "signup" ? "/api/auth/signup" : "/api/auth/login";
      const body = mode === "signup" ? { email, password: pw, display_name: name.trim(), nickname: nickname.trim(), agree_terms: agree } : { email, password: pw };
      const r = await post<{ access_token: string; user: User }>(path, body, { auth: false });
      useAuth.getState().setAuth(r.access_token, r.user);
      onDone({ mode: "account", token: r.access_token, user: r.user });
    } catch (x) {
      setErr(friendlyError(x, locale));
    } finally {
      setBusy(false);
    }
  };

  return (
    // The gate is the first thing a shared link shows, and on a phone it is usually the
    // only thing. It used to be a flex box with `overflow: visible`, so the signup form —
    // 851px of it once the password rules open — hung 22px off the top of an 844px screen
    // with no way to scroll up to the title. On a smaller phone the submit button goes
    // with it. The scroll now belongs to the backdrop and the row keeps `min-h-full`, so
    // a short card still sits where it should and a tall one simply scrolls.
    <div className="fixed inset-0 z-50 overflow-y-auto overscroll-contain bg-bg/80 backdrop-blur-sm">
      <div className="flex min-h-full items-end justify-center sm:items-center sm:p-4">
        {/* A sheet on a phone, a dialog on anything wider: at 390px a floating card with
            side margins reads as marooned, and its buttons sit further from the thumb. */}
        <div className="w-full rounded-t-2xl border-t border-border bg-card p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-xl sm:max-w-[420px] sm:rounded-2xl sm:border sm:pb-5">
        {/* Whose secretary this is answers "should I go in"; it has nothing to do with
            filling in an account form, so it stays on the door only. */}
        {mode === "choose" ? (
          <div className="flex items-center gap-3">
            <Avatar mascot name={agentName} src={avatarUrl} size={44} accent={accent} shape={shape} />
            <div className="min-w-0">
              <div className="truncate text-[15px] font-semibold">{agentName}</div>
              <div className="truncate text-xs text-muted-fg">{t("gate.subtitle", { owner: ownerName })}</div>
            </div>
          </div>
        ) : (
          <h2 className="text-[15px] font-semibold">{mode === "signup" ? t("gate.signup_title") : t("gate.login_title")}</h2>
        )}

        {mode === "choose" ? (
          <div className="mt-5 space-y-2">
            <p className="text-sm text-muted-fg">{t("gate.tagline")}</p>
            {canSignUp ? <Button variant="accent" className="w-full" onClick={() => setMode("signup")}><UserPlus className="h-4 w-4" />{t("gate.signup")}</Button> : null}
            <Button variant={canSignUp ? "outline" : "accent"} className="w-full" onClick={() => setMode("login")}><LogIn className="h-4 w-4" />{t("gate.login")}</Button>
            <Button variant="ghost" className="w-full" onClick={() => onDone({ mode: "anon" })}>{t("gate.anon")}</Button>
            {/* 들어가기 전에: 상대는 AI 이고, 나눈 말은 주인에게 간다 (plan/73, 인공지능 기본법 제31조). */}
            <AiNotice ownerName={ownerName} className="pt-2" />
          </div>
        ) : (
          <form className="mt-5 space-y-3" onSubmit={submit}>
            <p className="text-sm text-muted-fg">{t("gate.tagline")}</p>
            {/* The card opens with the secretary's face, so a bare "이름" field read as
                "become 제니's assistant". Signing up is joining the service; say so. */}
            {mode === "signup" ? (
              <>
                <Field label={t("gate.nickname")} hint={t("gate.nickname_hint", { agent: agentName })}>
                  <Input value={nickname} onChange={(e) => setNickname(e.target.value)} maxLength={60} autoComplete="nickname" />
                </Field>
                <Field label={t("gate.real_name")} hint={t("gate.real_name_hint")}>
                  <Input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} autoComplete="name" />
                </Field>
              </>
            ) : null}
            <Field label={t("auth.email")} hint={t("gate.email_hint")}>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
            </Field>
            <Field label={t("auth.password")} hint={mode === "signup" ? undefined : t("gate.pw_login_hint")}>
              <Input type="password" value={pw} onChange={(e) => setPw(e.target.value)} required minLength={8}
                     autoComplete={mode === "signup" ? "new-password" : "current-password"}
                     aria-describedby={mode === "signup" ? "gate-pw-rules" : undefined} />
            </Field>
            {err ? <p role="alert" className="text-xs text-danger">{err}</p> : null}
            {mode === "signup" ? (
              <>
                <PasswordRules verdict={verdict} show={pw.length > 0} id="gate-pw-rules" />
                <Field label={t("auth.confirm_password")} error={pw2 && pw !== pw2 ? t("auth.password_mismatch") : undefined}>
                  <Input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} required
                         invalid={!!pw2 && pw !== pw2} autoComplete="new-password" />
                </Field>
                <TermsAgree checked={agree} onChange={setAgree} id="gate-agree-terms" />
              </>
            ) : null}
            <Button type="submit" variant="accent" className="w-full" loading={busy}
                    disabled={mode === "signup" && (!verdict.ok || pw !== pw2 || !agree)}>{mode === "signup" ? t("gate.signup_do") : t("gate.login_do")}</Button>
            <div className="flex items-center justify-between text-xs">
              <button type="button" className="text-muted-fg underline" onClick={() => { setMode("choose"); setErr(""); }}>{t("common.back")}</button>
              <button type="button" className="text-muted-fg underline" onClick={() => onDone({ mode: "anon" })}>{t("gate.anon")}</button>
            </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
