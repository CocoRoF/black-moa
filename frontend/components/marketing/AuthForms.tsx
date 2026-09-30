"use client";
import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Auth } from "@/lib/api";
import { codeMessage, friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { useAuth } from "@/stores/auth";
import { Button, buttonLook } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Mascot } from "@/components/brand/Logo";
import { PASSWORD_MIN, checkPassword } from "@/lib/password";
import { PasswordRules } from "@/components/ui/password-rules";
import { SsoButtons } from "@/components/auth/SsoButtons";
import { TermsAgree } from "@/components/auth/TermsAgree";

function safeNext(n: string | null, fallback: string) {
  return n && n.startsWith("/") && !n.startsWith("//") ? n : fallback;
}

export function LoginForm() {
  const t = useT(); const locale = useLocale();
  const router = useRouter(); const sp = useSearchParams();
  const next = safeNext(sp.get("next"), "/app");
  const { data: st } = useQuery({ queryKey: ["auth-status"], queryFn: Auth.status });
  const [email, setEmail] = useState(""); const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  // 연결로 로그인하다 돌아온 오류(?error=)도 사람 말로.
  useEffect(() => { const e = sp.get("error"); if (e) setErr(codeMessage(e, locale)); }, [sp, locale]);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      const r = await Auth.login({ email, password: pw });
      useAuth.getState().setAuth(r.access_token, r.user);
      // Admins get the same home as everyone; the console is one nav item away.
      router.replace(next);
    } catch (x) { setErr(friendlyError(x, locale)); } finally { setBusy(false); }
  };
  return (
    <AuthCard title={t("auth.login_title")} subtitle={t("auth.login_subtitle")}>
      <form method="post" onSubmit={submit} className="space-y-4" noValidate>
        <Field label={t("auth.email")} htmlFor="email"><Input id="email" type="email" autoComplete="email" inputMode="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label={t("auth.password")} htmlFor="pw"><Input id="pw" type="password" autoComplete="current-password" required value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
        {err ? <p role="alert" className="text-sm text-danger">{err}</p> : null}
        <Button type="submit" variant="accent" className="w-full" loading={busy}>{t("auth.login")}</Button>
        <SsoButtons providers={st?.sso} next={next} />
        <div className="flex justify-between text-sm text-muted-fg">
          <Link href="/forgot-password" className="hover:text-fg">{t("auth.forgot")}</Link>
          <Link href={`/signup${sp.get("next") ? `?next=${encodeURIComponent(next)}` : ""}`} className="hover:text-fg">{t("auth.no_account")}</Link>
        </div>
      </form>
    </AuthCard>
  );
}

export function SignupForm() {
  const t = useT(); const locale = useLocale();
  const router = useRouter(); const sp = useSearchParams();
  const next = safeNext(sp.get("next"), "/app/onboarding");
  const { data: st } = useQuery({ queryKey: ["auth-status"], queryFn: Auth.status });
  const [nickname, setNickname] = useState(""); const [name, setName] = useState("");
  const [email, setEmail] = useState(""); const [pw, setPw] = useState(""); const [pw2, setPw2] = useState("");
  const [invite, setInvite] = useState(sp.get("invite") ?? ""); const [bootstrapToken, setBootstrapToken] = useState("");
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  const [agree, setAgree] = useState(false);
  const verdict = checkPassword(pw);
  const mismatch = pw2.length > 0 && pw !== pw2;
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(null);
    if (!verdict.ok) { setErr(t("err.weak_password")); return; }
    if (pw !== pw2) { setErr(t("auth.password_mismatch")); return; }
    if (!agree) { setErr(codeMessage("terms_required", locale)); return; }
    setBusy(true);
    try {
      // Keep the bootstrap credential only in component memory; never put it in
      // query params, localStorage, or sessionStorage.
      // The same four things the visitor gate asks for, so an account created from a
      // shared secretary and one created here carry the same profile.
      const signupBody = { email, password: pw, display_name: name.trim(), nickname: nickname.trim(),
                           invite_code: invite || null,
                           bootstrap_token: st?.bootstrap_token_required ? bootstrapToken || null : null,
                           agree_terms: agree };
      const r = await Auth.signup(signupBody);
      useAuth.getState().setAuth(r.access_token, r.user);
      toast.success(t("auth.welcome", { name: r.user.display_name }));
      router.replace(next);
    } catch (x) { setErr(friendlyError(x, locale)); } finally { setBusy(false); }
  };
  if (st?.signup_mode === "closed") {
    return <AuthCard title={t("auth.signup_title")} subtitle={t("err.signup_closed")}><Link href="/login" className={buttonLook("outline", "md", "w-full")}>{t("auth.login")}</Link></AuthCard>;
  }
  return (
    <AuthCard title={t("auth.signup_title")} subtitle={t("gate.tagline")}>
      {st?.bootstrap_needed ? <div role="status" className="mb-4 rounded-xl bg-accent/10 px-3 py-2 text-sm text-accent">{t("mkt.bootstrap_banner")}</div> : null}
      <form method="post" onSubmit={submit} className="space-y-4" noValidate>
        <Field label={t("gate.nickname")} htmlFor="nickname" hint={t("gate.nickname_generic_hint")}>
          <Input id="nickname" autoComplete="nickname" maxLength={60} value={nickname} onChange={(e) => setNickname(e.target.value)} />
        </Field>
        <Field label={t("gate.real_name")} htmlFor="name" hint={t("gate.real_name_hint")}>
          <Input id="name" autoComplete="name" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t("auth.email")} htmlFor="email" hint={t("gate.email_hint")}>
          <Input id="email" type="email" autoComplete="email" inputMode="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label={t("auth.password")} htmlFor="pw">
          <Input id="pw" type="password" autoComplete="new-password" required minLength={PASSWORD_MIN} value={pw}
                 onChange={(e) => setPw(e.target.value)} aria-describedby="pw-rules" />
        </Field>
        {/* Shown while typing rather than after submitting: the rule is easy to satisfy
            once you can see which half of it you are missing. */}
        <PasswordRules verdict={verdict} show={pw.length > 0} />
        <Field label={t("auth.confirm_password")} htmlFor="pw2"
               error={mismatch ? t("auth.password_mismatch") : undefined}>
          <Input id="pw2" type="password" autoComplete="new-password" required value={pw2}
                 invalid={mismatch} onChange={(e) => setPw2(e.target.value)} />
        </Field>
        {/* only when the server actually enforces it (HTTPS + no users yet) — a local install bootstraps with zero config */}
        {st?.bootstrap_token_required ? <Field label={t("auth.bootstrap_token")} htmlFor="bootstrap-token" hint={t("auth.bootstrap_token_hint")}><Input id="bootstrap-token" type="password" autoComplete="off" required value={bootstrapToken} onChange={(e) => setBootstrapToken(e.target.value)} /></Field> : null}
        {st?.signup_mode === "invite" ? <Field label={t("auth.invite_code")} htmlFor="invite"><Input id="invite" required value={invite} onChange={(e) => setInvite(e.target.value)} /></Field> : null}
        {/* 만 14세 이상 + 약관 동의 (plan/73). 연결로 가입하는 단추도 이 동의를 싣고 간다. */}
        <TermsAgree checked={agree} onChange={setAgree} />
        {err ? <p role="alert" className="text-sm text-danger">{err}</p> : null}
        <Button type="submit" variant="accent" className="w-full" loading={busy}
                disabled={!verdict.ok || pw !== pw2 || !email.trim() || !name.trim() || !agree}>{t("auth.signup")}</Button>
        {/* 첫 관리자는 비밀번호로 만든다 — 연결은 그 관리자가 [연결]에서 켠 뒤에 생긴다. */}
        {!st?.bootstrap_needed ? <SsoButtons providers={st?.sso} next={next} invite={st?.signup_mode === "invite" ? invite.trim() || null : null} agree={agree} requireAgree /> : null}
        {!st?.bootstrap_needed && st?.signup_mode === "invite" && st?.sso?.length ? <p className="text-center text-xs text-muted-fg">{t("auth.sso_invite_hint")}</p> : null}
        <div className="text-center text-sm text-muted-fg"><Link href="/login" className="hover:text-fg">{t("auth.have_account")}</Link></div>
      </form>
    </AuthCard>
  );
}

/** 연결로 들어왔지만 공급자가 이메일을 주지 않았거나(카카오는 이메일 동의가 선택이다) 인증되지 않은 이메일을 준 사람이
 *  가입을 마친다 (plan/59). 받은 이메일은 일반 가입과 같이 인증 전으로 남고, 계정 설정에서 인증한다. */
export function SsoCompleteForm() {
  const t = useT(); const locale = useLocale();
  const router = useRouter(); const sp = useSearchParams();
  const token = sp.get("t") ?? "";
  const pend = useQuery({ queryKey: ["sso-pending", token], queryFn: () => Auth.ssoPending(token), enabled: !!token, retry: false });
  const [name, setName] = useState(""); const [email, setEmail] = useState(""); const [invite, setInvite] = useState("");
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  const [agree, setAgree] = useState(false);
  useEffect(() => {
    if (!pend.data) return;
    setName((v) => v || pend.data.name);
    setEmail((v) => v || pend.data.email_hint);
  }, [pend.data]);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(null); setBusy(true);
    try {
      const r = await Auth.ssoComplete({ token, email: email.trim(), display_name: name.trim(), invite_code: invite.trim() || null, agree_terms: agree });
      useAuth.getState().setAuth(r.access_token, r.user);
      toast.success(t("auth.welcome", { name: r.user.display_name }));
      router.replace(r.next && r.next !== "/app" ? r.next : "/app/onboarding");
    } catch (x) { setErr(friendlyError(x, locale)); } finally { setBusy(false); }
  };
  if (!token || pend.isError) {
    return (
      <AuthCard title={t("auth.sso_complete_title")} subtitle={codeMessage("invalid_state", locale)}>
        <Link href="/login" className={buttonLook("outline", "md", "w-full")}>{t("auth.back_to_login")}</Link>
      </AuthCard>
    );
  }
  const label = pend.data?.provider_label ?? "";
  return (
    <AuthCard title={t("auth.sso_complete_title")} subtitle={label ? t("auth.sso_complete_sub", { name: label }) : undefined}>
      <form method="post" onSubmit={submit} className="space-y-4" noValidate>
        <Field label={t("gate.real_name")} htmlFor="name" hint={t("gate.real_name_hint")}>
          <Input id="name" autoComplete="name" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t("auth.email")} htmlFor="email" hint={t("auth.sso_email_hint")}>
          <Input id="email" type="email" autoComplete="email" inputMode="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        {pend.data?.invite_needed ? <Field label={t("auth.invite_code")} htmlFor="invite"><Input id="invite" required value={invite} onChange={(e) => setInvite(e.target.value)} /></Field> : null}
        <TermsAgree checked={agree} onChange={setAgree} />
        {err ? <p role="alert" className="text-sm text-danger">{err}</p> : null}
        <Button type="submit" variant="accent" className="w-full" loading={busy || pend.isLoading}
                disabled={!email.trim() || !name.trim() || (!!pend.data?.invite_needed && !invite.trim()) || !agree}>{t("auth.sso_complete_submit")}</Button>
        <div className="text-center text-sm text-muted-fg"><Link href="/login" className="hover:text-fg">{t("auth.have_account")}</Link></div>
      </form>
    </AuthCard>
  );
}

export function ForgotForm() {
  const t = useT(); const locale = useLocale();
  const [email, setEmail] = useState(""); const [busy, setBusy] = useState(false); const [done, setDone] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true);
    try { await Auth.forgot(email); setDone(true); } catch (x) { toast.error(friendlyError(x, locale)); } finally { setBusy(false); }
  };
  return (
    <AuthCard title={t("auth.forgot_title")} subtitle={t("auth.forgot_subtitle")}>
      {done ? <p role="status" className="text-sm">{t("auth.forgot_sent")}</p> : (
        <form method="post" onSubmit={submit} className="space-y-4">
          <Field label={t("auth.email")} htmlFor="email"><Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Button type="submit" className="w-full" loading={busy}>{t("auth.send_reset")}</Button>
        </form>
      )}
      <div className="mt-4 text-center text-sm text-muted-fg"><Link href="/login" className="hover:text-fg">{t("auth.back_to_login")}</Link></div>
    </AuthCard>
  );
}

export function ResetForm() {
  const t = useT(); const locale = useLocale(); const sp = useSearchParams(); const router = useRouter();
  const token = sp.get("token") ?? "";
  const [pw, setPw] = useState(""); const [pw2, setPw2] = useState(""); const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(null);
    if (!checkPassword(pw).ok) return setErr(t("err.weak_password"));
    if (pw !== pw2) return setErr(t("auth.password_mismatch"));
    setBusy(true);
    try { await Auth.reset(token, pw); toast.success(t("auth.reset_done")); router.replace("/login"); } catch (x) { setErr(friendlyError(x, locale)); } finally { setBusy(false); }
  };
  return (
    <AuthCard title={t("auth.reset_title")} subtitle={token ? undefined : t("err.token_invalid")}>
      <form method="post" onSubmit={submit} className="space-y-4">
        <Field label={t("auth.new_password")} htmlFor="pw"><Input id="pw" type="password" autoComplete="new-password" required value={pw} onChange={(e) => setPw(e.target.value)} aria-describedby="reset-pw-rules" /></Field>
        <PasswordRules verdict={checkPassword(pw)} show={pw.length > 0} id="reset-pw-rules" />
        <Field label={t("auth.confirm_password")} htmlFor="pw2" error={pw2 && pw !== pw2 ? t("auth.password_mismatch") : undefined}>
          <Input id="pw2" type="password" autoComplete="new-password" required value={pw2} invalid={!!pw2 && pw !== pw2} onChange={(e) => setPw2(e.target.value)} />
        </Field>
        {err ? <p role="alert" className="text-sm text-danger">{err}</p> : null}
        <Button type="submit" className="w-full" loading={busy} disabled={!token}>{t("auth.reset_submit")}</Button>
      </form>
    </AuthCard>
  );
}

/** Full-viewport backdrop for the auth pages.
 *  Anchored to the viewport, not to the card column: an absolutely positioned glow
 *  inside `max-w-md` gets clipped to that column and reads as a rectangle behind the
 *  card. Blooms are asymmetric and heavily blurred so the falloff never shows a seam,
 *  and dark mode carries its own opacities (the same values read as a flat void on
 *  near-black). */
function AuthBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0" style={{ background: "linear-gradient(180deg, color-mix(in oklab, var(--brand-sky) 10%, transparent), transparent 60%)" }} />
      <div className="absolute left-1/2 top-[38%] h-[900px] w-[1180px] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-80 blur-[120px] dark:opacity-70"
        style={{ background: "radial-gradient(closest-side, color-mix(in oklab, var(--brand-sky) 40%, transparent), transparent 72%)" }} />
      <div className="absolute left-[-16%] bottom-[-18%] h-[640px] w-[640px] rounded-full opacity-60 blur-[120px] dark:opacity-55"
        style={{ background: "radial-gradient(closest-side, color-mix(in oklab, var(--accent) 42%, transparent), transparent 72%)" }} />
      <div className="absolute right-[-14%] top-[8%] h-[600px] w-[600px] rounded-full opacity-50 blur-[120px] dark:opacity-45"
        style={{ background: "radial-gradient(closest-side, color-mix(in oklab, #7dd3fc 45%, transparent), transparent 72%)" }} />
    </div>
  );
}

/** The shape of an auth card before its form is there.
 *
 *  A boundary that renders nothing on the server and everything on the client is a page
 *  that arrives twice, and the second one is a surprise to React: the login page reported
 *  a hydration mismatch about once in sixteen loads. It also flashed white on a slow
 *  phone. Now the card is on the screen either way and only the form fills in. */
export function AuthSkeleton() {
  return (
    <div className="relative mx-auto max-w-md px-4 py-10 md:py-16">
      <Card className="border-border/70 bg-card/80 p-6 shadow-xl shadow-sky-500/10 backdrop-blur-xl md:p-8">
        <div className="mb-4 flex justify-center"><Mascot size={64} /></div>
        <div className="mx-auto h-8 w-40 rounded-lg bg-muted" />
        <div className="mt-6 space-y-4">
          <div className="h-16 rounded-xl bg-muted/70" />
          <div className="h-16 rounded-xl bg-muted/70" />
          <div className="h-11 rounded-xl bg-muted" />
        </div>
      </Card>
    </div>
  );
}

function AuthCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="relative mx-auto max-w-md px-4 py-10 md:py-16">
      <AuthBackdrop />
      <Card className="border-border/70 bg-card/80 p-6 shadow-xl shadow-sky-500/10 backdrop-blur-xl md:p-8">
        <div className="mb-4 flex justify-center"><Mascot size={64} /></div>
        <h1 className="text-2xl font-semibold tracking-tight text-center">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-muted-fg text-center">{subtitle}</p> : null}
        <div className="mt-6">{children}</div>
      </Card>
    </div>
  );
}
