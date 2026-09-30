"use client";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Copy, ExternalLink, Play, Plus, ShieldCheck, Timer, Trash2, Upload } from "@/components/icons";
import { Admin, type ClaudeAccount } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { confirm } from "@/lib/confirm";
import { friendlyError } from "@/lib/errors";
import { fmtRelative } from "@/lib/format";
import { subscribeSse } from "@/lib/sse";
import { useAuth } from "@/stores/auth";
import { Section } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Skeleton, Spinner } from "@/components/ui/skeleton";
import { Dialog } from "@/components/ui/dialog";

/** Health, at a glance. `eligible` is the only thing that decides whether traffic goes to
 *  an account, so it — not the stored status — drives the colour. */
function tone(a: ClaudeAccount): BadgeTone {
  if (!a.enabled) return "neutral";
  if (a.eligible) return "success";
  return a.ineligible_reason === "at_capacity" ? "accent" : a.status === "expired" ? "danger" : "warning";
}

/** Claude accounts, on the provider page rather than a menu of their own.
 *
 *  Adding an account is a server-side act: it creates that account's own Claude Code
 *  environment (its own HOME and CLAUDE_CONFIG_DIR) under the one Linux user the backend
 *  runs as, logs into it separately, and puts it in the rotation. Verified on the box:
 *  with a fresh HOME, `claude auth status --json` reports loggedIn:false while the
 *  configured home reports the signed-in account — the logins do not see each other. */
export function ClaudeAccounts() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  // Live-ish: in-flight counts and cooldowns move on their own, and an operator watching
  // this page during an incident should not have to reload to see the pool recover.
  const q = useQuery({ queryKey: ["admin", "claude-pool"], queryFn: Admin.claudePool, refetchInterval: 10_000 });
  const env = useQuery({ queryKey: ["admin", "providers"], queryFn: Admin.providers });
  const [addOpen, setAddOpen] = useState(false);
  const inval = () => qc.invalidateQueries({ queryKey: ["admin"] });
  const settings = useMutation({
    mutationFn: (b: { enabled?: boolean; strategy?: string }) => Admin.claudePoolSettings(b),
    onSuccess: () => { inval(); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  const pool = q.data;
  const cc = env.data?.claude_code;
  const many = (pool?.counts.total ?? 0) > 1;
  const ready = pool?.accounts.filter((a) => a.usable).length ?? 0;
  return (
    <>
      <Section
        title={<span className="inline-flex items-center gap-2">Claude Code
          {pool ? <Badge tone={ready > 0 ? "success" : "danger"}>{ready > 0 ? t("adm.cc_signed_in", { n: ready }) : t("adm.missing")}</Badge> : null}</span>}
        description={t("adm.cc_desc")}
        action={<Button variant="accent" onClick={() => setAddOpen(true)}><Plus className="h-4 w-4" />{t("adm.pool_add")}</Button>}
      >
        {q.isLoading || !pool ? <Skeleton className="h-40" /> : (
          <div className="space-y-4">
            {/* The environment, once. It is the same binary for every account, so repeating
                it on each card would be noise. */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-fg">
              <span>{t("adm.cc_version")} <span className="text-fg">{cc?.version ?? "–"}</span></span>
              <span className="font-mono">{cc?.binary ?? ""}</span>
            </div>

            {/* One list. There used to be a card for "the login" and a pool beside it, and
                an operator had to work out which of the two was answering turns before
                they could do anything. An install with one account is just a list of one. */}
            <ul className="space-y-3">
              {pool.accounts.map((a) => <AccountCard key={a.id} account={a} soleAccount={pool.accounts.length === 1} />)}
            </ul>

            {/* Only worth a control when there is something to distribute. */}
            {many ? (
              <div className="rounded-2xl border border-border p-4">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="min-w-[240px] flex-1">
                    <Label htmlFor="pool-strategy">{t("adm.pool_strategy")}</Label>
                    <Select id="pool-strategy" value={pool.strategy} onChange={(e) => settings.mutate({ strategy: e.target.value })}>
                      {pool.strategies.map((s) => <option key={s} value={s}>{t(`adm.pool_strategy_${s}`)}</option>)}
                    </Select>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs text-muted-fg">
                    <span>{t("adm.pool_eligible")} <span className="text-fg tabular-nums">{pool.counts.eligible}</span></span>
                    <span>{t("adm.pool_in_flight")} <span className="text-fg tabular-nums">{pool.counts.in_flight}</span></span>
                  </div>
                </div>
                <p className="mt-2 text-xs text-muted-fg">{t(`adm.pool_strategy_help_${pool.strategy}`)}</p>
              </div>
            ) : null}

            {ready === 0 ? <p className="text-xs text-danger">{t("adm.cc_none_signed_in")}</p>
              : pool.counts.eligible === 0 ? <p className="text-xs text-danger">{t("adm.pool_none_eligible")}</p> : null}
          </div>
        )}
      </Section>

      <AddAccountDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </>
  );
}

function AddAccountDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [label, setLabel] = useState(""); const [email, setEmail] = useState("");
  const [authMode, setAuthMode] = useState("oauth");
  const [weight, setWeight] = useState(1); const [maxc, setMaxc] = useState(4);
  const create = useMutation({
    mutationFn: () => Admin.claudeAccountCreate({ label, email: email || null, auth_mode: authMode, weight, max_concurrency: maxc }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin"] });
      setLabel(""); setEmail(""); onClose();
      toast.success(t("adm.pool_added"));
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <Dialog open={open} onClose={onClose} title={t("adm.pool_add")} description={t("adm.pool_add_desc")}
            footer={<><Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
                     <Button loading={create.isPending} disabled={!label.trim()} onClick={() => create.mutate()}>{t("common.add")}</Button></>}>
      <div className="space-y-3">
        <Field label={t("adm.pool_label")} hint={t("adm.pool_label_hint")}>
          <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="team-main" maxLength={64} />
        </Field>
        <Field label={t("adm.pool_email")} hint={t("adm.pool_email_hint")}>
          <Input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ops@example.com" autoComplete="off" />
        </Field>
        <Field label={t("adm.cc_mode")}>
          <Select value={authMode} onChange={(e) => setAuthMode(e.target.value)}>
            <option value="oauth">{t("adm.cc_mode_oauth")}</option>
            <option value="console">{t("adm.cc_mode_console")}</option>
            <option value="setup_token">{t("adm.cc_mode_setup_token")}</option>
            <option value="api_key">{t("adm.cc_mode_api_key")}</option>
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("adm.pool_weight")} hint={t("adm.pool_weight_hint")}>
            <Input type="number" min={1} max={1000} value={weight} onChange={(e) => setWeight(Number(e.target.value) || 1)} />
          </Field>
          <Field label={t("adm.pool_concurrency")} hint={t("adm.pool_concurrency_hint")}>
            <Input type="number" min={1} max={64} value={maxc} onChange={(e) => setMaxc(Number(e.target.value) || 1)} />
          </Field>
        </div>
      </div>
    </Dialog>
  );
}

interface LoginState {
  lines: { kind: string; text: string }[];
  url?: string; awaiting: boolean; done: boolean; ok?: boolean; exitCode?: number | null; error?: string;
}

function AccountCard({ account: a, soleAccount }: { account: ClaudeAccount; soleAccount?: boolean }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [importOpen, setImportOpen] = useState(false); const [json, setJson] = useState("");
  const [editing, setEditing] = useState(false);
  const [weight, setWeight] = useState(a.weight); const [maxc, setMaxc] = useState(a.max_concurrency);
  const [probe, setProbe] = useState<{ ok: boolean; error?: string; ms?: number } | null>(null);
  const [login, setLogin] = useState<LoginState | null>(null);
  const [inputText, setInputText] = useState("");
  const unsub = useRef<(() => void) | null>(null);
  const codeRef = useRef<HTMLInputElement | null>(null);
  const inval = () => qc.invalidateQueries({ queryKey: ["admin"] });
  useEffect(() => () => { unsub.current?.(); }, []);

  const patch = useMutation({
    mutationFn: (b: Record<string, unknown>) => Admin.claudeAccountPatch(a.id, b),
    onSuccess: () => { inval(); setEditing(false); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const imp = useMutation({
    mutationFn: () => Admin.claudeAccountImport(a.id, json),
    onSuccess: () => { inval(); setImportOpen(false); setJson(""); toast.success(t("adm.cc_imported")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const probeM = useMutation({
    mutationFn: () => Admin.claudeAccountProbe(a.id),
    onSuccess: (r) => { setProbe(r); inval(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const clearCd = useMutation({
    mutationFn: () => Admin.claudeAccountClearCooldown(a.id),
    onSuccess: () => { inval(); toast.success(t("adm.pool_cooldown_cleared")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const remove = useMutation({
    mutationFn: () => Admin.claudeAccountDelete(a.id),
    onSuccess: () => { inval(); toast.success(t("adm.pool_removed")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const sendInput = useMutation({
    mutationFn: (text: string) => Admin.claudeAccountLoginInput(a.id, text),
    onSuccess: () => setInputText(""),
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const cancelLogin = useMutation({
    mutationFn: () => Admin.claudeAccountLoginCancel(a.id),
    onSuccess: () => { unsub.current?.(); setLogin(null); },
  });

  const subscribe = () => {
    unsub.current?.();
    unsub.current = subscribeSse(`/api/admin/providers/claude-code/accounts/${a.id}/login/events`, useAuth.getState().token, (event, data) => {
      const kind = (event || data?.kind || "log") as string;
      const text = typeof data === "string" ? data : (data?.text ?? "");
      setLogin((p) => {
        const base: LoginState = p ?? { lines: [], done: false, awaiting: false };
        return {
          ...base,
          lines: kind === "done" ? base.lines : [...base.lines, { kind, text }].slice(-200),
          url: kind === "url" ? text : base.url ?? /https?:\/\/\S+/.exec(text)?.[0],
          awaiting: kind === "prompt" ? true : kind === "input" ? false : base.awaiting,
          done: kind === "done" || base.done,
          ok: kind === "done" ? !!data?.ok : base.ok,
          exitCode: kind === "done" ? (data?.exit_code ?? null) : base.exitCode,
          error: kind === "error" ? text : base.error,
        };
      });
      if (kind === "prompt") setTimeout(() => codeRef.current?.focus(), 50);
      if (kind === "done") { inval(); toast[data?.ok ? "success" : "error"](t(data?.ok ? "adm.cc_login_done" : "adm.cc_login_failed")); }
    }, () => setLogin((p) => (p ? { ...p, done: true } : p)));
  };
  const adopt = (s: { lines?: { kind: string; text: string }[]; url?: string | null; awaiting_input?: boolean; done?: boolean; ok?: boolean; exit_code?: number | null }) =>
    setLogin({ lines: s.lines ?? [], url: s.url ?? undefined, awaiting: !!s.awaiting_input, done: !!s.done, ok: s.ok, exitCode: s.exit_code ?? null });
  const start = useMutation({
    mutationFn: () => Admin.claudeAccountLoginStart(a.id, a.email),
    onSuccess: (snap) => { setInputText(""); adopt(snap); subscribe(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  // A reload in the middle of a login must not orphan the box that takes the code.
  useEffect(() => {
    let alive = true;
    Admin.claudeAccountLoginState(a.id).then((s) => { if (alive && s.running) { adopt(s); subscribe(); } }).catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a.id]);

  const browserLogin = a.auth_mode === "oauth" || a.auth_mode === "console";
  const stateLabel = !a.enabled ? t("adm.pool_state_disabled")
    : a.eligible ? t("adm.pool_state_ready")
    : t(`adm.pool_reason_${a.ineligible_reason ?? "unknown"}`);

  return (
    <li className="rounded-2xl border border-border p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{a.label}</span>
            <Badge tone={tone(a)}>{stateLabel}</Badge>
            {a.in_flight > 0 ? <Badge tone="accent">{t("adm.pool_sessions", { n: a.in_flight })}</Badge> : null}
          </div>
          <div className="mt-0.5 text-xs text-muted-fg">
            {[a.email, a.subscription, a.rate_limit_tier,
              a.session_expires_at ? t("adm.cc_expires_in", { rel: fmtRelative(a.session_expires_at, locale) }) : null]
              .filter(Boolean).join(" · ") || t("adm.pool_not_signed_in")}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button variant="ghost" size="sm" onClick={() => patch.mutate({ enabled: !a.enabled })}>
            {a.enabled ? t("adm.pool_disable_one") : t("adm.pool_enable_one")}
          </Button>
          {/* The provider always has one row: removing the last would leave nothing to
              authenticate against. Sign it in again instead. */}
          <Button variant="ghost" size="icon" aria-label={t("common.delete")} disabled={soleAccount}
                  title={soleAccount ? t("adm.pool_last_account") : undefined}
                  onClick={async () => {
                    if (await confirm({ title: t("adm.pool_delete_confirm", { label: a.label }), description: t("adm.pool_delete_desc"), danger: true, confirmLabel: t("common.delete") })) remove.mutate();
                  }}><Trash2 className="h-4 w-4 text-danger" /></Button>
        </div>
      </div>
      <div className="space-y-4">
        {a.cooldown_until ? (
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-warning/40 bg-warning/5 p-3 text-sm">
            <Timer className="h-4 w-4 text-warning" />
            <span>{t("adm.pool_cooling", { until: fmtRelative(a.cooldown_until, locale) })}</span>
            <Button variant="outline" size="sm" loading={clearCd.isPending} onClick={() => clearCd.mutate()}>{t("adm.pool_clear_cooldown")}</Button>
          </div>
        ) : null}
        {a.last_error ? <p className="text-xs text-danger break-words">{a.last_error}</p> : null}

        <div className="flex flex-wrap items-center gap-2">
          {browserLogin
            ? <Button variant="accent" loading={start.isPending} disabled={!!login && !login.done} onClick={() => start.mutate()}>
                <Play className="h-4 w-4" />{t("adm.cc_device_login")}
              </Button>
            : <span className="text-xs text-muted-fg">{t("adm.cc_no_browser_login")}</span>}
          <Button variant="outline" onClick={() => setImportOpen(true)}><Upload className="h-4 w-4" />{t("adm.cc_import_json")}</Button>
          <Button variant="outline" loading={probeM.isPending} onClick={() => probeM.mutate()}><ShieldCheck className="h-4 w-4" />{t("adm.cc_probe")}</Button>
          <Button variant="ghost" onClick={() => { setEditing((v) => !v); setWeight(a.weight); setMaxc(a.max_concurrency); }}>{t("adm.pool_tuning")}</Button>
        </div>

        {editing ? (
          <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border p-3">
            <Field className="w-32" label={t("adm.pool_weight")}>
              <Input type="number" min={1} max={1000} value={weight} onChange={(e) => setWeight(Number(e.target.value) || 1)} />
            </Field>
            <Field className="w-32" label={t("adm.pool_concurrency")}>
              <Input type="number" min={1} max={64} value={maxc} onChange={(e) => setMaxc(Number(e.target.value) || 1)} />
            </Field>
            <Button loading={patch.isPending} onClick={() => patch.mutate({ weight, max_concurrency: maxc })}>{t("common.save")}</Button>
          </div>
        ) : null}

        {probe ? (
          <p className={cn("text-xs", probe.ok ? "text-success" : "text-danger")}>
            {probe.ok ? t("adm.pool_probe_ok", { ms: probe.ms ?? 0 }) : `${t("adm.pool_probe_fail")} — ${probe.error ?? ""}`}
          </p>
        ) : null}

        {login ? (
          <div className={cn("rounded-xl border p-3", login.done ? (login.ok ? "border-success/40 bg-success/5" : "border-danger/40 bg-danger/5") : "border-border bg-muted/40")}>
            <div className="flex items-center justify-between gap-3 text-sm font-medium">
              <span className="inline-flex items-center gap-2">
                {login.done ? null : <Spinner className="h-4 w-4" />}
                {login.done ? (login.ok ? t("adm.cc_login_ok") : `${t("adm.cc_login_failed")}${login.exitCode != null ? ` (exit ${login.exitCode})` : ""}`) : t("adm.cc_login_session")}
              </span>
              {!login.done
                ? <button type="button" className="text-xs text-danger underline" onClick={() => cancelLogin.mutate()}>{t("common.cancel")}</button>
                : <button type="button" className="text-xs text-muted-fg underline" onClick={() => { unsub.current?.(); setLogin(null); }}>{t("common.close")}</button>}
            </div>
            {!login.done && login.url ? (
              <div className="mt-3 flex items-center gap-2">
                <a href={login.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-w-0 flex-1 items-center gap-1.5 rounded-lg bg-accent/10 px-3 py-2 text-sm text-accent">
                  <ExternalLink className="h-4 w-4 shrink-0" /><span className="truncate">{login.url}</span>
                </a>
                <Button variant="outline" size="sm" onClick={() => { navigator.clipboard?.writeText(login.url!); toast.success(t("common.copied")); }}><Copy className="h-4 w-4" />{t("common.copy")}</Button>
              </div>
            ) : null}
            {!login.done ? (
              <form className="mt-2 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); const v = inputText.trim(); if (v) sendInput.mutate(v); }}>
                <Input ref={codeRef} value={inputText} onChange={(e) => setInputText(e.target.value)} placeholder={t("adm.cc_input_placeholder")}
                       autoComplete="off" spellCheck={false} className="min-w-[240px] flex-1 font-mono text-xs" />
                <Button type="submit" loading={sendInput.isPending} disabled={!inputText.trim()}>{t("common.send")}</Button>
              </form>
            ) : null}
            <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-bg/60 p-2 font-mono text-[11px] leading-relaxed text-muted-fg">{login.lines.map((l) => l.text).join("\n") || "…"}</pre>
          </div>
        ) : null}
      </div>

      <Dialog open={importOpen} onClose={() => setImportOpen(false)} title={t("adm.cc_import_json")} description={t("adm.cc_import_desc")}
              footer={<><Button variant="outline" onClick={() => setImportOpen(false)}>{t("common.cancel")}</Button>
                       <Button loading={imp.isPending} disabled={!json.trim()} onClick={() => imp.mutate()}>{t("adm.import")}</Button></>}>
        <Textarea value={json} onChange={(e) => setJson(e.target.value)} className="min-h-[220px] font-mono text-xs"
                  placeholder='{"claudeAiOauth": {"accessToken": "...", "refreshToken": "...", "expiresAt": 0}}' />
      </Dialog>
    </li>
  );
}

