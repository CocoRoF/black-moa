"use client";
import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, ArrowRight, Check, Sparkles } from "@/components/icons";
import { Admin } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Button, buttonLook } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/misc";
import { Section } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ProviderKeyCards } from "./Providers";
import { ClaudeAccounts } from "./ClaudePool";
import { SettingsForm } from "./common";
import * as D from "./settingsDefs";

export function SetupWizard() {
  const t = useT(); const locale = useLocale(); const router = useRouter(); const qc = useQueryClient();
  const [step, setStep] = useState(0);
  const models = useQuery({ queryKey: ["admin", "models"], queryFn: Admin.models });
  const plans = useQuery({ queryKey: ["admin", "plans"], queryFn: Admin.plans });
  const seed = useMutation({ mutationFn: () => Admin.seedModels(false), onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["admin", "models"] }); toast.success(t("adm.seeded", { n: r.added })); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const complete = useMutation({ mutationFn: Admin.setupComplete, onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin"] }); toast.success(t("adm.setup_done")); router.replace("/admin"); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const steps = ["claude", "keys", "audio", "models", "plans", "signup"];
  return (
    <Page>
      <PageHeader title={t("adm.setup")} description={t("adm.setup_desc")} action={<Button variant="ghost" onClick={() => complete.mutate()} loading={complete.isPending}>{t("adm.skip_setup")}</Button>} />
      <ol className="mb-5 flex flex-wrap items-center gap-2 text-xs">
        {steps.map((s, i) => <li key={s} className="flex items-center gap-2"><button type="button" onClick={() => setStep(i)} className={cn("flex h-7 items-center gap-1.5 rounded-full px-2.5 font-medium", i === step ? "bg-accent text-accent-fg" : i < step ? "bg-success/15 text-success" : "bg-muted text-muted-fg")}>{i < step ? <Check className="h-3 w-3" /> : <span>{i + 1}</span>}{t(`adm.setup_${s}`)}</button>{i < steps.length - 1 ? <span className="h-px w-3 bg-border" /> : null}</li>)}
      </ol>
      <div className="space-y-4">
        {step === 0 ? <ClaudeAccounts /> : null}
        {step === 1 ? <Section title={t("adm.setup_keys")} description={t("adm.setup_keys_desc")}><ProviderKeyCards /></Section> : null}
        {step === 2 ? <><SettingsForm title={t("adm.embedding")} fields={D.embeddingFields(t)} prefix="embedding." /><SettingsForm title="STT" fields={D.sttFields(t)} prefix="stt." /><SettingsForm title="TTS" fields={D.ttsFields(t)} prefix="tts." /></> : null}
        {step === 3 ? (
          <Section title={t("adm.models")} description={t("adm.setup_models_desc")}>
            <div className="mb-3 flex flex-wrap items-center gap-2"><Button variant="outline" loading={seed.isPending} onClick={() => seed.mutate()}><Sparkles className="h-4 w-4" />{t("adm.seed")}</Button><Link href="/admin/models" className={buttonLook("ghost", "md")}>{t("adm.open_models")}</Link></div>
            <div className="flex flex-wrap gap-1.5">{models.data?.items.map((m) => <Badge key={m.id} tone={m.enabled ? (m.is_default ? "accent" : "success") : "neutral"}>{m.display_name}{m.is_default ? " ★" : ""}</Badge>)}{models.data && !models.data.items.length ? <span className="text-sm text-muted-fg">{t("model.none")}</span> : null}</div>
          </Section>
        ) : null}
        {step === 4 ? (
          <Section title={t("adm.plans")} description={t("adm.setup_plans_desc")}>
            <div className="flex flex-wrap gap-1.5">{plans.data?.items.map((p) => <Badge key={p.id} tone={p.is_default ? "accent" : "outline"}>{p.name} · {p.monthly_credits}cr · {p.max_agents} agents</Badge>)}</div>
            <div className="mt-3"><Link href="/admin/plans" className={buttonLook("ghost", "md")}>{t("adm.open_plans")}</Link></div>
            <SettingsForm title={t("adm.credits")} fields={D.creditFields(t)} prefix="credits." />
          </Section>
        ) : null}
        {step === 5 ? <><SettingsForm title={t("adm.branding")} fields={D.brandingFields(t)} prefix="branding." /><SettingsForm title={t("adm.signup")} fields={D.signupFields(t)} prefix="signup." /></> : null}
      </div>
      <div className="mt-5 flex items-center justify-between">
        <Button variant="ghost" disabled={step === 0} onClick={() => setStep(step - 1)}><ArrowLeft className="h-4 w-4" />{t("common.back")}</Button>
        {step < steps.length - 1 ? <Button onClick={() => setStep(step + 1)}>{t("common.next")}<ArrowRight className="h-4 w-4" /></Button> : <Button variant="accent" loading={complete.isPending} onClick={() => complete.mutate()}><Check className="h-4 w-4" />{t("adm.finish_setup")}</Button>}
      </div>
    </Page>
  );
}
