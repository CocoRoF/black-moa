"use client";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, ExternalLink, Lock, Mail, Send, XCircle } from "@/components/icons";
import { Admin } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtSecretTail } from "@/lib/format";
import { SMTP_PRESETS, encryptionFor, presetById } from "@/lib/smtpPresets";
import { useAdminSettings } from "./common";
import { Page } from "@/components/owner/Shell";
import { Section } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/misc";

type SecretView = { has_value: boolean; masked: string };

/** Mail settings, apart from the rest of the system settings.
 *
 *  These relays all authenticate with a token and all expect a fixed literal in the
 *  username field, which is the single most common way this is misconfigured. Picking a
 *  provider fills in what only its documentation would have told you.
 */
export function EmailPage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useAdminSettings("smtp.");
  const saved = q.data;

  const [provider, setProvider] = useState("cloudflare");
  const [host, setHost] = useState(""); const [port, setPort] = useState("465");
  const [user, setUser] = useState(""); const [secret, setSecret] = useState("");
  const [from, setFrom] = useState(""); const [fromAgent, setFromAgent] = useState(""); const [noTls, setNoTls] = useState(false);
  const [to, setTo] = useState("");
  const [result, setResult] = useState<{ ok: boolean; error?: string } | null>(null);

  useEffect(() => {
    if (!saved) return;
    const h = String(saved["smtp.host"] ?? "");
    const match = SMTP_PRESETS.find((p) => p.host && p.host === h);
    setProvider(String(saved["smtp.provider"] || match?.id || (h ? "custom" : "cloudflare")));
    setHost(h); setPort(String(saved["smtp.port"] ?? 465));
    setUser(String(saved["smtp.user"] ?? "")); setFrom(String(saved["smtp.from"] ?? "")); setFromAgent(String(saved["smtp.from_agent"] ?? ""));
    setNoTls(saved["smtp.use_tls"] === false);
    setSecret("");
  }, [saved]);

  const preset = presetById(provider);
  const pickProvider = (id: string) => {
    setProvider(id);
    const p = presetById(id);
    if (p.host) { setHost(p.host); setPort(String(p.port)); }
    if (p.user !== null) setUser(p.user);
    else if (presetById(provider).user !== null) setUser("");
  };

  const enc = encryptionFor(Number(port) || 0);
  const secretSet = (saved?.["smtp.password"] as SecretView | undefined)?.has_value;
  const dirty = useMemo(() => !saved || !!secret ||
    // The provider is *inferred* from the host on installs configured before this page
    // existed. Treating that inference as an edit left the form permanently dirty, which
    // also blocked the test send.
    (!!saved["smtp.provider"] && provider !== String(saved["smtp.provider"])) ||
    host !== String(saved["smtp.host"] ?? "") ||
    port !== String(saved["smtp.port"] ?? "") ||
    user !== String(saved["smtp.user"] ?? "") ||
    from !== String(saved["smtp.from"] ?? "") ||
    fromAgent !== String(saved["smtp.from_agent"] ?? "") ||
    noTls === (saved["smtp.use_tls"] !== false), [saved, secret, provider, host, port, user, from, fromAgent, noTls]);

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        "smtp.provider": provider, "smtp.host": host.trim(), "smtp.port": Number(port),
        "smtp.user": user.trim(), "smtp.from": from.trim(), "smtp.from_agent": fromAgent.trim(), "smtp.use_tls": !noTls,
      };
      if (secret) body["smtp.password"] = secret;   // an empty box means "keep what is stored"
      return Admin.putSettings(body);
    },
    onSuccess: () => { setSecret(""); qc.invalidateQueries({ queryKey: ["admin", "settings"] }); qc.invalidateQueries({ queryKey: ["auth-status"] }); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const test = useMutation({
    mutationFn: () => Admin.smtpTest(to.trim()),
    onSuccess: (r) => {
      setResult(r);
      if (r.ok) toast.success(t("email.test_ok"));
      else toast.error(r.error ?? t("email.test_fail"));
    },
    onError: (e) => { setResult({ ok: false, error: friendlyError(e, locale) }); toast.error(friendlyError(e, locale)); },
  });

  return (
    <Page>
      <PageHeader title={t("adm.email")} description={t("adm.email_desc")} />
      {q.isLoading ? <Skeleton className="h-64" /> : (
        <div className="space-y-4">
          <Section title={t("email.relay")} description={preset.docs ? (
            <a href={preset.docs} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
              {t("email.docs", { name: preset.label })}<ExternalLink className="h-3.5 w-3.5" />
            </a>
          ) : undefined}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t("email.provider")} className="sm:col-span-2">
                <Select value={provider} onChange={(e) => pickProvider(e.target.value)}>
                  {SMTP_PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label || t("email.custom")}</option>)}
                </Select>
              </Field>
              <Field label={t("email.host")}>
                <Input value={host} onChange={(e) => setHost(e.target.value)} placeholder="smtp.example.com" spellCheck={false} />
              </Field>
              <Field label={t("email.port")} hint={enc === "ssl" ? t("email.enc_ssl") : t("email.enc_starttls")}>
                <Input type="number" value={port} onChange={(e) => setPort(e.target.value)} />
              </Field>
              <Field label={t("email.user")} hint={t(preset.userHintKey)}>
                <div className="relative">
                  <Input value={user} onChange={(e) => setUser(e.target.value)} spellCheck={false}
                         readOnly={preset.user !== null} className={preset.user !== null ? "pr-9 text-muted-fg" : undefined} />
                  {preset.user !== null ? <Lock className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" /> : null}
                </div>
              </Field>
              <Field label={t(preset.secretLabelKey)}
                     hint={secretSet ? <span className="text-success">{t("adm.secret_set")} ({fmtSecretTail((saved?.["smtp.password"] as SecretView).masked)})</span> : t("adm.secret_unset")}>
                <Input type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)}
                       placeholder={secretSet ? "••••••••" : undefined} />
              </Field>
              <Field label={t("email.from")} hint={t("email.from_hint")} className="sm:col-span-2">
                <Input value={from} onChange={(e) => setFrom(e.target.value)} placeholder="Memora <no-reply@memo-ora.com>" spellCheck={false} />
              </Field>
              {/* A second mailbox, because the two kinds of mail mean different things to
                  whoever gets them: one is a notice nobody should answer, the other is a
                  message a person wrote and expects a reply to. */}
              <Field label={t("email.from_agent")} hint={t("email.from_agent_hint")} className="sm:col-span-2">
                <Input value={fromAgent} onChange={(e) => setFromAgent(e.target.value)} placeholder="Memora <memora@memo-ora.com>" spellCheck={false} />
              </Field>
              {/* Port 465 is implicit TLS and never negotiates STARTTLS, so offering the
                  switch there would be a control that does nothing. */}
              {enc === "starttls" ? (
                <div className="sm:col-span-2"><Checkbox checked={noTls} onChange={setNoTls} label={t("email.no_starttls")} /></div>
              ) : null}
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button variant={dirty ? "accent" : "outline"} disabled={!dirty || !host.trim() || !from.trim()} loading={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button>
              {!secretSet && !secret ? <span className="text-xs text-warning">{t("email.need_secret")}</span> : null}
            </div>
          </Section>

          <Section title={t("email.test")} description={t("email.test_desc")}>
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t("email.test_to")} className="min-w-[240px] flex-1">
                <Input type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="you@example.com" />
              </Field>
              <Button variant="outline" disabled={!to.trim() || dirty} loading={test.isPending} onClick={() => test.mutate()}>
                <Send className="h-4 w-4" />{t("email.test_send")}
              </Button>
            </div>
            {dirty ? <p className="mt-2 text-xs text-warning">{t("email.save_first")}</p> : null}
            {result ? (
              <div className={`mt-3 flex items-start gap-2 rounded-xl border px-3 py-2 text-xs ${result.ok ? "border-success/40 bg-success/10 text-success" : "border-danger/40 bg-danger/10 text-danger"}`}>
                {result.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
                <span className="min-w-0 break-words">{result.ok ? t("email.test_ok") : result.error}</span>
              </div>
            ) : null}
            {/* The one failure that looks like a credential problem but is not. */}
            <p className="mt-3 text-xs text-muted-fg"><Mail className="mr-1 inline h-3.5 w-3.5" />{t("email.note_domain")}</p>
          </Section>

          <Section title={t("email.status")}>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge tone={host && from && secretSet ? "success" : "warning"}>{host && from && secretSet ? t("email.ready") : t("email.incomplete")}</Badge>
              <span className="text-muted-fg">{t("email.status_desc")}</span>
            </div>
          </Section>
        </div>
      )}
    </Page>
  );
}
