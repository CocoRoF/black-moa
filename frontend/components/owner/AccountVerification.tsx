"use client";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AtSign, BadgeCheck, IdCard, Mail, ShieldAlert } from "@/components/icons";
import { Auth, Users } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { CODE_LENGTH, normalizeCode } from "@/lib/otp";
import { useAuth } from "@/stores/auth";
import { Page } from "./Shell";
import { ConnectionCards } from "./IntegrationsView";
import { Section } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/misc";
import { cn } from "@/lib/utils";

/** Two different questions live here, and they were previously scattered.
 *
 *  Verification is about this account being a real, reachable person — the thing billing
 *  and account recovery need. Connections are about other services the secretary may act
 *  through. Neither belongs in "settings" next to the theme switch.
 */
export function AccountVerificationPage() {
  const t = useT(); const locale = useLocale();
  const user = useAuth((s) => s.user)!;
  const status = useQuery({ queryKey: ["auth-status"], queryFn: Auth.status, staleTime: 60_000 });
  const [code, setCode] = useState(""); const [sent, setSent] = useState(false);
  const [name, setName] = useState(user.display_name); const [nickname, setNickname] = useState(user.nickname ?? "");

  const refreshUser = async () => { const u = await Auth.me(); useAuth.getState().setUser(u); return u; };
  const send = useMutation({
    mutationFn: Auth.sendVerification,
    onSuccess: () => { setSent(true); toast.success(t("settings.verify_sent")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const verify = useMutation({
    mutationFn: () => Auth.verifyEmail(code),
    onSuccess: async () => { setCode(""); await refreshUser(); toast.success(t("settings.verified")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const saveNames = useMutation({
    mutationFn: () => Users.patchMe({ display_name: name.trim(), nickname: nickname.trim(), confirm_name: true }),
    onSuccess: async () => { await refreshUser(); toast.success(t("verify.name_saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  const mailConfigured = status.data?.mail_configured ?? false;
  const emailDone = user.email_verified;
  const nameDone = user.name_confirmed && name.trim() === user.display_name;

  // 연결은 여기 한 곳이다 (plan/81). 다른 화면의 [연결에서 관리]나 연결을 마치고 돌아왔을 때는 그 칸을 바로 보인다.
  const sp = useSearchParams();
  useEffect(() => {
    if (window.location.hash !== "#connections" && !sp.get("connected") && !sp.get("error")) return;
    const id = window.setTimeout(() => document.getElementById("connections")?.scrollIntoView({ block: "start", behavior: "smooth" }), 300);
    return () => window.clearTimeout(id);
  }, [sp]);

  return (
    <Page>
      <PageHeader title={t("nav.account")} description={t("verify.page_desc")} />
      <div className="space-y-4">
        <Section title={t("verify.section_identity")} description={t("verify.section_identity_desc")}>
          <div className="space-y-4">
            {/* Email first: it is what actually gates creating a secretary. */}
            <div className="rounded-2xl border border-border p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Mail className="h-4 w-4 text-muted-fg" />
                <span className="font-medium">{t("verify.email_title")}</span>
                <span className="truncate text-sm text-muted-fg">{user.email}</span>
                <Badge tone={emailDone ? "success" : "warning"} className="ml-auto">
                  {emailDone ? <><BadgeCheck className="h-3.5 w-3.5" />{t("verify.done")}</> : t("verify.pending")}
                </Badge>
              </div>
              {emailDone ? null : !mailConfigured ? (
                <p className="mt-3 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">{t("verify.no_mail")}</p>
              ) : (
                <div className="mt-3 space-y-3">
                  <Button variant={sent ? "outline" : "accent"} size="sm" loading={send.isPending} onClick={() => send.mutate()}>
                    {sent ? t("verify.resend") : t("verify.send")}
                  </Button>
                  {sent ? (
                    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); verify.mutate(); }}>
                      <Field label={t("verify.code")} className="min-w-[150px]">
                        {/* Whatever arrives — a pasted line from the mail, spaces, "인증 코드: "
                            — the field keeps the digits and nothing else. maxLength alone
                            would truncate "0 2 2 1 3 9" to three characters. */}
                        <Input value={code} onChange={(e) => setCode(normalizeCode(e.target.value))} inputMode="numeric"
                               autoComplete="one-time-code" placeholder="000000" className="font-mono tracking-widest" />
                      </Field>
                      <Button type="submit" size="sm" loading={verify.isPending} disabled={code.length < CODE_LENGTH}>{t("verify.submit")}</Button>
                    </form>
                  ) : null}
                  {sent ? <p className="text-xs text-muted-fg">{t("verify.spam_hint")}</p> : null}
                </div>
              )}
            </div>

            {/* Between the address that proves who you are and the name that says who you
                are: the address your secretary writes from. */}
            <MailHandleCard verified={emailDone} />

            {/* The legal name, kept apart from the nickname a secretary uses. */}
            <div className="rounded-2xl border border-border p-4">
              <div className="flex flex-wrap items-center gap-2">
                <IdCard className="h-4 w-4 text-muted-fg" />
                <span className="font-medium">{t("verify.name_title")}</span>
                <Badge tone={nameDone ? "success" : "warning"} className="ml-auto">
                  {nameDone ? <><BadgeCheck className="h-3.5 w-3.5" />{t("verify.confirmed")}</> : t("verify.unconfirmed")}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-muted-fg">{t("verify.name_desc")}</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <Field label={t("gate.real_name")} hint={t("gate.real_name_hint")}>
                  <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoComplete="name" />
                </Field>
                <Field label={t("gate.nickname")} hint={t("verify.nickname_hint")}>
                  <Input value={nickname} onChange={(e) => setNickname(e.target.value)} maxLength={60} autoComplete="nickname" placeholder={user.display_name} />
                </Field>
              </div>
              <Button className="mt-3" size="sm" variant={nameDone ? "outline" : "accent"} loading={saveNames.isPending}
                      disabled={!name.trim()} onClick={() => saveNames.mutate()}>{t("verify.name_confirm")}</Button>
            </div>

            {!emailDone ? (
              <p className="flex items-start gap-2 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />{t("verify.blocked_note")}
              </p>
            ) : null}
          </div>
        </Section>

        {/* 연결 카드는 그 자체가 카드라 한 겹 더 싸지 않는다. */}
        <section id="connections" className="scroll-mt-4 space-y-3 pt-4">
          <div className="px-1">
            <h2 className="text-[15px] font-semibold leading-tight">{t("verify.section_connections")}</h2>
            <p className="mt-1 text-sm text-muted-fg">{t("verify.section_connections_desc")}</p>
          </div>
          <ConnectionCards />
        </section>
      </div>
    </Page>
  );
}

/** Claiming the local part of a sending address.
 *
 *  It is checked as it is typed, and always shown as the whole address — an id on its own
 *  means nothing until you can see the mailbox it makes. The check races against other
 *  people claiming the same word, so the server holds a unique constraint and this is only
 *  here to answer before the save rather than after. */
function MailHandleCard({ verified }: { verified: boolean }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const current = useQuery({ queryKey: ["mail-handle"], queryFn: () => Users.mailHandle() });
  const [draft, setDraft] = useState("");
  const [typed, setTyped] = useState(false);

  useEffect(() => { if (current.data && !typed) setDraft(current.data.handle); }, [current.data, typed]);

  const probe = useDebounced(draft, 350);
  const check = useQuery({
    queryKey: ["mail-handle", "check", probe],
    queryFn: () => Users.mailHandle(probe),
    enabled: typed && probe.length > 0 && probe !== (current.data?.handle ?? ""),
  });

  const save = useMutation({
    mutationFn: () => Users.setMailHandle(draft.trim()),
    onSuccess: (r) => { toast.success(t("verify.handle_saved", { address: r.address })); setTyped(false); qc.invalidateQueries({ queryKey: ["mail-handle"] }); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  const domain = current.data?.domain ?? "";
  const result = check.data?.check;
  const unchanged = draft.trim() === (current.data?.handle ?? "");
  const preview = (result?.address) || (draft.trim() && domain ? `${draft.trim().toLowerCase()}@${domain}` : "");

  return (
    <div className="rounded-2xl border border-border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <AtSign className="h-4 w-4 text-muted-fg" />
        <span className="font-medium">{t("verify.handle_title")}</span>
        {current.data?.address ? <span className="truncate text-sm text-muted-fg">{current.data.address}</span> : null}
        <Badge tone={current.data?.handle ? "success" : "neutral"} className="ml-auto">
          {current.data?.handle ? <><BadgeCheck className="h-3.5 w-3.5" />{t("verify.handle_set")}</> : t("verify.handle_unset")}
        </Badge>
      </div>
      <p className="mt-2 text-sm text-muted-fg">{t("verify.handle_desc")}</p>

      {!verified ? (
        <p className="mt-3 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">{t("verify.handle_needs_email")}</p>
      ) : (
        <form className="mt-3 space-y-2" onSubmit={(e) => { e.preventDefault(); if (draft.trim() && !unchanged) save.mutate(); }}>
          <div className="flex flex-wrap items-end gap-2">
            {/* The domain sits inside the field rather than floating between the input and
                the button: it is part of the address being written, not a separate control,
                and putting it in the box is what lets the button line up with the input. */}
            <Field label={t("verify.handle_label")} className="min-w-[220px] flex-1">
              <div className="flex h-10 items-center rounded-xl border border-border bg-input pr-3 focus-within:outline-2 focus-within:outline-ring">
                <input value={draft} onChange={(e) => { setTyped(true); setDraft(e.target.value.toLowerCase()); }}
                       placeholder="haryeom" spellCheck={false} autoComplete="off" aria-label={t("verify.handle_label")}
                       className="h-full min-w-0 flex-1 rounded-xl bg-transparent px-3.5 font-mono text-[15px] text-fg outline-none placeholder:text-muted-fg/70" />
                <span className="shrink-0 text-sm text-muted-fg">@{domain || "…"}</span>
              </div>
            </Field>
            <Button type="submit" loading={save.isPending}
                    disabled={!draft.trim() || unchanged || (typed && result ? !result.ok : false)}>
              {t("common.save")}
            </Button>
          </div>
          {/* One line that always says what the address will be, or why it cannot be. */}
          <p className={cn("text-xs", result && !result.ok ? "text-danger" : "text-muted-fg")}>
            {result && !result.ok ? result.message
              : preview ? t("verify.handle_preview", { address: preview })
              : t("verify.handle_hint")}
          </p>
        </form>
      )}
    </div>
  );
}

/** Waits for the typing to stop before asking the server. */
function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => { const id = setTimeout(() => setSettled(value), ms); return () => clearTimeout(id); }, [value, ms]);
  return settled;
}
