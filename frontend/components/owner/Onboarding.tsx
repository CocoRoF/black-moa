"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, ArrowRight } from "@/components/icons";
import { Mascot } from "@/components/brand/Logo";
import { Agents, Auth, Chat, Users, type Persona } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { useAuth } from "@/stores/auth";
import { Page } from "./Shell";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { PersonaEditor, ModelPicker } from "@/components/agent/PersonaEditor";
import { ProfileHeader } from "@/components/profile/ProfileHeader";
import { useImageCrop } from "@/components/ui/image-crop";
import { Avatar } from "@/components/ui/misc";
import { DEFAULT_AVATAR } from "@/lib/presets";
import { AvatarPicker } from "@/components/agent/AvatarPicker";
import { EmailVerifyCard } from "./EmailVerifyCard";
import { cn } from "@/lib/utils";

const DEFAULT_PERSONA: Persona = { preset: "professional", formality: 0.8, warmth: 0.5, verbosity: 0.4, humor: 0.1, emoji: false, traits: [] };

export function Onboarding() {
  const t = useT(); const locale = useLocale(); const router = useRouter(); const qc = useQueryClient();
  const user = useAuth((s) => s.user)!;
  const [step, setStep] = useState(0);
  const [name, setName] = useState(""); const [role, setRole] = useState(""); const [language, setLanguage] = useState("auto");
  const [persona, setPersona] = useState<Persona>(DEFAULT_PERSONA);
  const [model, setModel] = useState<{ provider: string; model_id: string } | null>(null);
  const [avatar, setAvatar] = useState<string>(DEFAULT_AVATAR);
  const [cover, setCover] = useState<string | null>(null);
  const [mine, setMine] = useState<string | null>(null);       // their own photo, once uploaded
  //: 그 사진의 원본 — 자르지 않은 그대로. PC 앱의 아바타가 띄운다(plan/63).
  const [mineCharacter, setMineCharacter] = useState<string | null>(null);
  const { crop, node: cropUI } = useImageCrop();
  const coverRef = useRef<HTMLInputElement>(null);
  const pick = async (file: File, what: "photo" | "cover") => {
    const framed = await crop(file, what === "photo" ? "circle" : "cover");
    if (!framed) return;
    try {
      const [up, original] = await Promise.all([
        Chat.upload(framed, "avatar"),
        what === "photo" ? Chat.upload(file, "avatar").catch(() => null) : Promise.resolve(null),
      ]);
      if (what === "photo") { setMine(up.url); setAvatar(up.url); setMineCharacter(original?.url ?? null); } else setCover(up.url);
    } catch (e) { toast.error(friendlyError(e, locale)); }
  };
  const [busy, setBusy] = useState(false);
  const models = useQuery({ queryKey: ["models"], queryFn: Agents.models });
  // Ask for the address before the wizard, not with a 403 after it.
  const authStatus = useQuery({ queryKey: ["auth-status"], queryFn: Auth.status, staleTime: 60_000 });
  const needsVerify = !!authStatus.data?.verify_before_agent && !user.email_verified && user.role !== "admin";
  useEffect(() => { if (!model && models.data?.items.length) { const d = models.data.items.find((m) => m.is_default) ?? models.data.items[0]; setModel({ provider: d.provider, model_id: d.model_id }); } }, [models.data, model]);
  // Left empty on purpose: an empty role line renders from the current names, so renaming
  // the agent or the owner later does not leave a frozen "OO의 업무 비서" behind.

  const create = async () => {
    setBusy(true);
    try {
      const a = await Agents.create({ name: name.trim(), role_line: role.trim(), language, persona, provider: model?.provider,
                                      model_id: model?.model_id, avatar_url: avatar || null, cover_url: cover,
                                      character_url: avatar && avatar === mine ? mineCharacter : null });
      try { const u = await Users.patchMe({ onboarding_state: { agent_created: true } }); useAuth.getState().setUser(u); } catch { /* ignore */ }
      await qc.invalidateQueries({ queryKey: ["agents"] });
      toast.success(t("onb.created", { name: a.name }));
      router.replace(`/app/agents/${a.id}/chat?welcome=1`);
    } catch (e) { toast.error(friendlyError(e, locale)); } finally { setBusy(false); }
  };

  if (needsVerify) {
    return (
      <Page>
        <div className="mx-auto max-w-[560px] py-8">
          <EmailVerifyCard mailConfigured={authStatus.data?.mail_configured ?? false} onVerified={() => authStatus.refetch()} />
        </div>
      </Page>
    );
  }

  const steps = [t("onb.step1"), t("onb.step2"), t("onb.step3"), t("onb.step4")];
  const last = steps.length - 1;
  return (
    <Page className="max-w-2xl">
      <div className="mb-6 text-center">
        <div className="mx-auto inline-flex justify-center"><Mascot size={72} className="float-y" /></div>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight">{t("onb.title")}</h1>
        <p className="mt-1 text-sm text-muted-fg">{t("onb.subtitle")}</p>
      </div>
      <ol className="mb-5 flex items-center justify-center gap-2 text-xs">
        {steps.map((s, i) => (
          <li key={s} className="flex items-center gap-2">
            <span className={cn("flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold", i <= step ? "bg-accent text-accent-fg" : "bg-muted text-muted-fg")}>{i + 1}</span>
            <span className={cn("hidden sm:inline", i === step ? "font-medium" : "text-muted-fg")}>{s}</span>
            {i < steps.length - 1 ? <span className="h-px w-6 bg-border" /> : null}
          </li>
        ))}
      </ol>
      <Card className="p-5 md:p-6">
        {step === 0 ? (
          <div className="space-y-4">
            <Field label={t("onb.name")} htmlFor="name" hint={t("onb.name_hint")}><Input id="name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder={t("onb.name_placeholder")} autoFocus /></Field>
            <Field label={t("onb.role")} htmlFor="role" hint={t("onb.role_hint")}><Input id="role" value={role} maxLength={120} placeholder={t("onb.role_placeholder")} onChange={(e) => setRole(e.target.value)} /></Field>
            <Field label={t("onb.language")} htmlFor="lang"><Select id="lang" value={language} onChange={(e) => setLanguage(e.target.value)}><option value="auto">{t("lang.auto")}</option><option value="ko">{t("lang.ko")}</option><option value="en">{t("lang.en")}</option></Select></Field>
          </div>
        ) : step === 1 ? (
          <PersonaEditor value={persona} onChange={setPersona} />
        ) : step === 2 ? (
          <div className="space-y-5">
            {/* The profile itself, not a description of one: this is the card a visitor
                opens, being built. */}
            <div className="mx-auto max-w-[380px] overflow-hidden rounded-2xl border border-border">
              <ProfileHeader
                compact coverUrl={cover} avatarSrc={avatar || undefined}
                avatar={<div className={cn(avatar || cover ? "overflow-hidden rounded-full bg-card ring-4 ring-card" : "")}>
                          <Avatar mascot name={name || "?"} src={avatar} size={96} />
                        </div>}
                name={name.trim() || t("onb.name")}
                subtitle={role.trim() || t("onb.role_default", { owner: user.display_name })}
                onPickCover={() => coverRef.current?.click()}
              />
            </div>
            <Field label={t("onb.photo")} hint={t("onb.photo_hint")}>
              <AvatarPicker value={avatar} onChange={setAvatar} mine={mine} name={name}
                            onUpload={(f) => void pick(f, "photo")} />
            </Field>
            <Field label={t("onb.cover")}>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" size="sm" onClick={() => coverRef.current?.click()}>{t("set.cover")}</Button>
                {cover ? <Button variant="ghost" size="sm" onClick={() => setCover(null)}>{t("onb.cover_clear")}</Button> : null}
              </div>
            </Field>
            <input ref={coverRef} type="file" accept="image/*" hidden
                   onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void pick(f, "cover"); }} />
          </div>
        ) : (
          <ModelPicker value={model} onChange={setModel} models={models.data?.items ?? []} loading={models.isLoading} />
        )}
      </Card>
      <div className="mt-4 flex items-center justify-between">
        <Button variant="ghost" onClick={() => (step === 0 ? router.push("/app") : setStep(step - 1))}><ArrowLeft className="h-4 w-4" />{step === 0 ? t("common.cancel") : t("common.back")}</Button>
        {step < last ? <Button onClick={() => setStep(step + 1)} disabled={step === 0 && !name.trim()}>{t("common.next")}<ArrowRight className="h-4 w-4" /></Button>
          : <Button variant="accent" loading={busy} disabled={!name.trim()} onClick={create}>{t("onb.create")}</Button>}
      </div>
      {cropUI}
    </Page>
  );
}
