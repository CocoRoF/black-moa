"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Building2, Check, ChevronRight, Mail, Search, ShieldCheck } from "@/components/icons";
import { Community, Users, type CompanyCard as CompanyCardT, type CompanyVerifyState } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { CompanyLogo, companyHref } from "@/components/company/shared";

/** The 소속 row on 내 정보, with proof (plan/40 §10).
 *
 *  Typed, the company is a word on a profile. Proven with a work mailbox, it is the company
 *  from the directory: the dashboard's 내 회사 tab, the 재직 인증 badge on reviews, and the
 *  name here all read the same fact. The address itself is never kept. */
export function CompanyVerifyCard({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["me", "company"], queryFn: Users.company });
  const [open, setOpen] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const bust = () => { qc.invalidateQueries({ queryKey: ["me", "company"] }); qc.invalidateQueries({ queryKey: ["profile"] }); qc.invalidateQueries({ queryKey: ["cx"] }); };
  const remove = useMutation({
    mutationFn: Users.companyRemove,
    onSuccess: () => { setConfirmRemove(false); toast.success(t("profile.company_unverified_toast")); bust(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const s = q.data;
  const verified = s?.state === "verified" && s.company;
  const inFlight = s && (s.state === "code_sent" || s.state === "choose" || s.state === "propose");

  return (
    <div>
      <Input value={verified ? s.company!.name : value} disabled={!!verified} onChange={(e) => onChange(e.target.value)} />
      {verified ? (
        <div className="mt-2 rounded-xl border border-success/30 bg-success/5 p-3">
          <div className="flex items-start gap-3">
            <CompanyLogo size={40} className="rounded-xl" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <Link href={companyHref(s.company!.id)} className="text-sm font-semibold hover:underline">{s.company!.name}</Link>
                <Badge tone="success"><ShieldCheck className="h-3 w-3" />{t("profile.company_verified")}</Badge>
              </div>
              <div className="mt-0.5 text-xs text-muted-fg">
                {s.email_masked}{s.verified_at ? ` · ${t("profile.company_verified_at", { date: fmtDate(s.verified_at) })}` : ""}
              </div>
              <p className="mt-1.5 text-xs text-muted-fg">{t(s.mapping === "pending" ? "profile.company_mapping_pending" : "profile.company_verified_hint")}</p>
            </div>
            <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(true)}>{t("profile.company_unverify")}</Button>
          </div>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-dashed border-border px-3 py-2.5">
          <div className="flex min-w-0 items-center gap-2 text-xs text-muted-fg">
            <ShieldCheck className="h-4 w-4 shrink-0 text-accent" />
            <span>{inFlight ? t("profile.company_code_sent", { email: s!.email_masked ?? "" }) : t("profile.company_verify_desc")}</span>
          </div>
          <Button size="sm" variant={inFlight ? "accent" : "outline"} onClick={() => setOpen(true)} disabled={q.isLoading}>
            {t(inFlight ? "profile.company_enter_code" : "profile.company_verify_btn")}<ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
      <VerifyDialog open={open} onClose={() => setOpen(false)} initial={s} onDone={() => { setOpen(false); bust(); }} />
      <ConfirmDialog open={confirmRemove} onClose={() => setConfirmRemove(false)} onConfirm={() => remove.mutate()} loading={remove.isPending}
        title={t("profile.company_unverify")} description={t("profile.company_unverify_desc")} confirmLabel={t("profile.company_unverify")} cancelLabel={t("common.cancel")} danger />
    </div>
  );
}

type Step = "email" | "code" | "choose" | "propose";

function VerifyDialog({ open, onClose, initial, onDone }: { open: boolean; onClose: () => void; initial?: CompanyVerifyState; onDone: () => void }) {
  const t = useT(); const locale = useLocale();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [st, setSt] = useState<CompanyVerifyState | undefined>(initial);
  const [pick, setPick] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  // Reopened mid-way, the dialog starts where the person left off.
  useEffect(() => {
    if (!open) return;
    setCode(""); setPick(null); setSearch("");
    const s = initial?.state;
    setSt(initial);
    setStep(s === "code_sent" ? "code" : s === "choose" ? "choose" : s === "propose" ? "propose" : "email");
  }, [open, initial]);

  const start = useMutation({
    mutationFn: () => Users.companyStart(email.trim()),
    onSuccess: (r) => { setSt(r); setCode(""); setStep("code"); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const confirm = useMutation({
    mutationFn: (b: { code?: string; company_id?: string }) => Users.companyConfirm(b),
    onSuccess: (r) => {
      setSt(r);
      if (r.state === "verified") { toast.success(t("profile.company_done")); onDone(); }
      else if (r.state === "choose") setStep("choose");
      else if (r.state === "propose") setStep("propose");
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const suggest = useQuery({
    queryKey: ["cx", "suggest", search],
    queryFn: () => Community.companySuggest(search.trim()),
    enabled: step === "propose" && search.trim().length >= 1,
  });

  const known = st?.candidates ?? [];
  const title = t(step === "email" ? "profile.company_verify_title" : step === "code" ? "profile.company_step_code" : step === "choose" ? "profile.company_step_choose" : "profile.company_step_propose");
  const footer = step === "email" ? (
    <Button variant="accent" onClick={() => start.mutate()} disabled={!email.includes("@") || start.isPending}><Mail className="h-4 w-4" />{t("profile.company_send")}</Button>
  ) : step === "code" ? (
    <>
      <Button variant="ghost" onClick={() => { setStep("email"); }} disabled={start.isPending}>{t("profile.company_resend")}</Button>
      <Button variant="accent" onClick={() => confirm.mutate({ code: code.trim() })} disabled={code.trim().length !== 6 || confirm.isPending}>{t("profile.company_confirm")}</Button>
    </>
  ) : (
    <Button variant="accent" onClick={() => pick && confirm.mutate({ company_id: pick })} disabled={!pick || confirm.isPending}><Check className="h-4 w-4" />{t("profile.company_confirm")}</Button>
  );

  return (
    <Dialog open={open} onClose={onClose} title={title} footer={footer}>
      {step === "email" ? (
        <div className="space-y-3">
          <p className="text-sm text-muted-fg">{t("profile.company_verify_desc")}</p>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-fg">{t("profile.company_step_email")}</label>
            <Input type="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder={t("profile.company_email_ph")}
              onKeyDown={(e) => { if (e.key === "Enter" && email.includes("@")) start.mutate(); }} />
            <p className="mt-1 text-xs text-muted-fg">{t("profile.company_email_hint")}</p>
          </div>
        </div>
      ) : step === "code" ? (
        <div className="space-y-3">
          <p className="text-sm text-muted-fg">{t("profile.company_code_hint", { email: st?.email_masked ?? "" })}</p>
          <Input inputMode="numeric" autoFocus autoComplete="one-time-code" maxLength={6} value={code} className="text-center text-2xl font-semibold tracking-[0.4em] tabular-nums"
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            onKeyDown={(e) => { if (e.key === "Enter" && code.trim().length === 6) confirm.mutate({ code: code.trim() }); }} />
          <p className="rounded-xl bg-muted px-3 py-2 text-xs text-muted-fg">{t("profile.company_code_spam")}</p>
        </div>
      ) : step === "choose" ? (
        <div className="space-y-3">
          <p className="text-sm text-muted-fg">{t("profile.company_choose_desc", { domain: st?.domain ?? "" })}</p>
          <div className="space-y-1.5">{known.map((c) => <CandidateRow key={c.id} c={c} picked={pick === c.id} onPick={() => setPick(c.id)} />)}</div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-muted-fg">{t("profile.company_propose_desc", { domain: st?.domain ?? "" })}</p>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" />
            <Input autoFocus className="pl-9" value={search} onChange={(e) => { setSearch(e.target.value); setPick(null); }} placeholder={t("profile.company_search_ph")} />
          </div>
          <div className="space-y-1.5">
            {(suggest.data?.items ?? []).map((c) => (
              <CandidateRow key={c.id} c={c} picked={pick === c.id} onPick={() => setPick(c.id)} />
            ))}
            {search.trim() && suggest.data && !suggest.data.items.length ? <p className="py-3 text-center text-sm text-muted-fg">{t("profile.company_search_empty")}</p> : null}
          </div>
        </div>
      )}
    </Dialog>
  );
}

function CandidateRow({ c, picked, onPick }: { c: Pick<CompanyCardT, "id" | "name" | "market" | "industry_text" | "region_text">; picked: boolean; onPick: () => void }) {
  const t = useT();
  return (
    <button type="button" onClick={onPick} aria-pressed={picked}
      className={cn("flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors",
        picked ? "border-accent bg-accent/5" : "border-border hover:bg-muted/60")}>
      <CompanyLogo size={36} className="rounded-lg" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2"><span className="truncate text-sm font-medium">{c.name}</span>{c.market ? <Badge tone="outline">{c.market}</Badge> : null}</div>
        <div className="truncate text-xs text-muted-fg">{[c.industry_text, c.region_text].filter(Boolean).join(" · ")}</div>
      </div>
      {picked ? <span className="flex items-center gap-1 text-xs font-medium text-accent"><Check className="h-4 w-4" />{t("profile.company_pick")}</span> : <Building2 className="h-4 w-4 text-muted-fg" />}
    </button>
  );
}
