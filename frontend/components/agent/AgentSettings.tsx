"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Archive, ArchiveRestore, Eye, FlaskConical, Pause, Play, Trash2, Upload } from "@/components/icons";
import { Agents, Chat, type Agent } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { useVoiceFeatures } from "@/lib/hooks";
import { friendlyError } from "@/lib/errors";
import { Page } from "@/components/owner/Shell";
import { useAgent } from "./AgentLayout";
import { PersonaEditor, ModelPicker } from "./PersonaEditor";
import { DisclosureEditor } from "./DisclosureEditor";
import { Section } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SwitchRow, Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Dialog } from "@/components/ui/dialog";
import { Segmented } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar } from "@/components/ui/misc";
import { useImageCrop } from "@/components/ui/image-crop";
import { AvatarPicker } from "@/components/agent/AvatarPicker";
import { coverFallback } from "@/components/profile/ProfileHeader";
import { cn, storageGet, storageSet } from "@/lib/utils";
import { FirstMeetingField, RelationshipSettings, VerifyDialog, VersionsSection, draftOf } from "./StudioPanels";

/** 비서가 **외부인과의 대화에서 하는 일** (plan/57). 나와의 대화에서는 모든 기능이 늘 켜져 있고,
 *  외부인에게 무엇을 쓰는지(지식·인맥·스케줄·기억·웹 검색)는 비서의 [지식] 탭 한 곳에서 정한다. */
const CAPS = ["voice", "leave_message", "meeting_request"];
const ACCENTS = ["#1a5fe0", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#8b5cf6", "#111318"];
const KEYS: (keyof Agent)[] = ["name", "role_line", "avatar_url", "cover_url", "character_url", "language", "persona", "provider", "model_id", "thinking_enabled", "custom_instructions", "capabilities", "disclosure_policy", "greeting", "suggested_questions", "theme", "voice", "visitor_settings", "turn_cost_cap_credits", "daily_credit_cap", "monthly_credit_cap"];

export function AgentSettings() {
  const t = useT(); const locale = useLocale(); const agent = useAgent(); const qc = useQueryClient(); const router = useRouter();
  const [d, setD] = useState<Agent>(agent);
  // 관리자가 끈 음성은 설정에서도 보이지 않는다 (plan/67).
  const voiceOn = useVoiceFeatures();
  const caps = CAPS.filter((c) => c !== "voice" || voiceOn.stt || voiceOn.tts);
  const [preview, setPreview] = useState<"owner" | "visitor" | null>(null);
  const [delOpen, setDelOpen] = useState(false); const [delName, setDelName] = useState("");
  // Studio (plan/37): the easy mode shows what shapes the character; the advanced mode shows everything.
  const [mode, setMode] = useState<"easy" | "advanced">("easy");
  useEffect(() => { if (storageGet("local", "blackmoa:studio:mode") === "advanced") setMode("advanced"); }, []);
  const pickMode = (m: "easy" | "advanced") => { setMode(m); storageSet("local", "blackmoa:studio:mode", m); };
  const adv = mode === "advanced";
  const [verifyOpen, setVerifyOpen] = useState(false);
  useEffect(() => { setD(agent); }, [agent]);
  const models = useQuery({ queryKey: ["models"], queryFn: Agents.models });
  const [promptAudience, setPromptAudience] = useState<"owner" | "visitor">("owner");
  const [baseOpen, setBaseOpen] = useState(false);
  const prompt = useQuery({ queryKey: ["agent-prompt", agent.id, promptAudience], queryFn: () => Agents.prompt(agent.id, promptAudience), staleTime: 30_000 });
  const dirty = useMemo(() => KEYS.filter((k) => JSON.stringify(d[k]) !== JSON.stringify(agent[k])), [d, agent]);
  const save = useMutation({
    mutationFn: () => { const body: Record<string, unknown> = {}; for (const k of dirty) body[k] = d[k]; return Agents.patch(agent.id, body); },
    onSuccess: (a) => { qc.setQueryData(["agents", agent.id], a); qc.invalidateQueries({ queryKey: ["agents"] }); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const act = useMutation({ mutationFn: (x: "pause" | "resume" | "archive" | "restore") => Agents.action(agent.id, x), onSuccess: (a) => { qc.setQueryData(["agents", agent.id], a); qc.invalidateQueries({ queryKey: ["agents"] }); toast.success(t("common.saved")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const del = useMutation({ mutationFn: () => Agents.remove(agent.id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["agents"] }); toast.success(t("agent.deleted")); router.replace("/app/agents"); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const set = <K extends keyof Agent>(k: K, v: Agent[K]) => setD((p) => ({ ...p, [k]: v }));
  // Framed before it is sent: a picture is cropped to the ring or the band it is going
  // into, so what the owner saw while choosing is what a visitor sees on the profile.
  const { crop, node: cropUI } = useImageCrop();
  //: 직접 올린 사진. 고른 줄에 같이 세워 두어야 프리셋을 눌러 봤다가 되돌아올 수 있다.
  //  이미 올려 둔 사진이 붙어 있으면 그것이 곧 내 사진이다(프리셋은 /presets/ 아래 산다).
  const [own, setOwn] = useState<string | null>(
    d.avatar_url && !d.avatar_url.startsWith("/presets/") ? d.avatar_url : null);
  //: 내 사진의 원본. 프로필은 동그라미로 잘라 흰 바탕을 깔지만, PC 앱의 아바타는 올린 그림을 그대로
  //  띄운다(투명한 PNG 면 투명한 채로, plan/63). 그래서 자르기 전의 파일도 같이 올려 둔다.
  const [ownCharacter, setOwnCharacter] = useState<string | null>(own ? d.character_url ?? null : null);
  const uploadPhoto = async (f: File, what: "avatar_url" | "cover_url") => {
    const framed = await crop(f, what === "avatar_url" ? "circle" : "cover");
    if (!framed) return;
    try {
      const [r, original] = await Promise.all([
        Chat.upload(framed, "avatar"),
        what === "avatar_url" ? Chat.upload(f, "avatar").catch(() => null) : Promise.resolve(null),
      ]);
      set(what, r.url);
      if (what === "avatar_url") { setOwn(r.url); setOwnCharacter(original?.url ?? null); set("character_url", original?.url ?? null); }
    } catch (e) { toast.error(friendlyError(e, locale)); }
  };
  // 프리셋을 고르면 원본 자리도 따라 비운다(앱은 그 프리셋을 쓴다). 내 사진으로 되돌아오면 내 원본도.
  const pickAvatar = (src: string | null) => { set("avatar_url", src); set("character_url", src && src === own ? ownCharacter : null); };
  const sq = d.suggested_questions ?? [];

  return (
    <Page className="pb-10">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-lg font-semibold">{t("studio.title")}</h1><p className="text-sm text-muted-fg">{t("studio.desc")}</p></div>
        <Segmented value={mode} onChange={pickMode} options={[{ value: "easy", label: t("studio.mode_easy") }, { value: "advanced", label: t("studio.mode_advanced") }]} ariaLabel={t("studio.mode")} />
      </div>
      <div className="space-y-4">
        <Section title={t("set.basic")}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("onb.name")}><Input value={d.name} maxLength={80} onChange={(e) => set("name", e.target.value)} /></Field>
            <Field label={t("onb.role")} hint={t("onb.role_hint")}><Input value={d.role_line ?? ""} maxLength={120} placeholder={agent.role_line_display ?? ""} onChange={(e) => set("role_line", e.target.value)} /></Field>
            <Field label={t("onb.language")}><Select value={d.language} onChange={(e) => set("language", e.target.value)}><option value="auto">{t("lang.auto")}</option><option value="ko">{t("lang.ko")}</option><option value="en">{t("lang.en")}</option></Select></Field>
            {/* Photo and cover together, over the band they will actually appear on — the
                two pictures are one decision, and an URL box beside a 44px thumbnail was
                no way to tell whether a face survived the crop. */}
            <div className="sm:col-span-2">
              <Field label={t("set.photos")} hint={t("set.photos_hint")}>
                {/* Width-capped, not height-capped: a cap on the height turns the preview
                    back into a wide strip on a desktop, which is exactly the shape the
                    profile does not have. */}
                <div className="max-w-[380px] overflow-hidden rounded-2xl border border-border">
                  {/* The profile's own shape, not a summary of it: the background across the
                      top with the photo in the middle of it. The photo used to sit in the row
                      underneath, where the band — a positioned element, unlike the row —
                      painted straight over the top half of it. */}
                  <div className="relative w-full aspect-[3/2]" style={d.cover_url ? undefined : { background: coverFallback(d.theme?.accent) }}>
                    {d.cover_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={d.cover_url} alt="" className="absolute inset-0 h-full w-full object-cover" />
                    ) : null}
                    <div className="absolute inset-0 flex items-center justify-center">
                      <div className={cn(d.avatar_url || d.cover_url ? "overflow-hidden rounded-full bg-card ring-4 ring-card" : "")}>
                        <Avatar mascot name={d.name} src={d.avatar_url} size={96} accent={d.theme?.accent} shape={d.theme?.avatar_shape} />
                      </div>
                    </div>
                    <div className="absolute right-2 top-2 flex gap-1.5">
                      <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full bg-black/45 px-3 text-xs font-medium text-white backdrop-blur hover:bg-black/60">
                        <Upload className="h-3.5 w-3.5" />{t("set.cover")}
                        <input type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void uploadPhoto(f, "cover_url"); }} />
                      </label>
                      {d.cover_url ? (
                        <button type="button" onClick={() => set("cover_url", null)}
                                className="inline-flex h-8 items-center rounded-full bg-black/45 px-3 text-xs font-medium text-white backdrop-blur hover:bg-black/60">{t("common.delete")}</button>
                      ) : null}
                    </div>
                  </div>
                  {d.avatar_url ? (
                    <div className="flex justify-center px-4 py-2">
                      <Button variant="ghost" size="sm" onClick={() => pickAvatar(null)}>{t("set.avatar_clear")}</Button>
                    </div>
                  ) : null}
                </div>
                {/* 얼굴은 만들 때 한 번 고르고 끝나는 것이 아니다. 만드는 화면에 있던
                    것과 같은 줄을 여기에도 둔다: 두 곳이 다르면 나중에 바꾸려는 사람은
                    자기 사진을 찾아오는 수밖에 없다. */}
                <div className="mt-3 max-w-[380px]">
                  <AvatarPicker value={d.avatar_url ?? null} onChange={pickAvatar}
                                mine={own} name={d.name} size={56}
                                onUpload={(f) => void uploadPhoto(f, "avatar_url")} />
                </div>
              </Field>
            </div>
          </div>
        </Section>

        {/* 성격 검증은 성격 옆에 있다 — 편집 중인 성격으로 세 장면에 답해 보는 일이다. */}
        <Section title={t("set.persona")} description={t("set.persona_desc")} action={<div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => setVerifyOpen(true)}><FlaskConical className="h-4 w-4" />{t("studio.verify")}</Button>
          <Button variant="outline" size="sm" onClick={() => setPreview("owner")}><Eye className="h-4 w-4" />{t("set.preview_prompt")}</Button>
        </div>}>
          <PersonaEditor value={d.persona} onChange={(p) => set("persona", p)} advanced={adv} />
          {/* 감정의 폭·호칭 변화는 말투의 결이라 성격에 둔다. 관계가 깊어지는 속도와 먼저 말 걸기는
              관리자가 정하므로(plan/45·54) 따로 된 [관계] 칸은 없다. */}
          {adv ? <div className="mt-4"><RelationshipSettings value={d.persona} onChange={(p) => set("persona", p)} advanced /></div> : null}
        </Section>

        <Section title={t("studio.first_meeting")} description={t("studio.first_meeting_desc")}>
          <FirstMeetingField value={d.persona} onChange={(p) => set("persona", p)} />
        </Section>

        <Section title={t("model.title")} description={t("set.model_desc")}>
          <ModelPicker value={{ provider: d.provider, model_id: d.model_id }} onChange={(m) => { set("provider", m.provider); set("model_id", m.model_id); }} models={models.data?.items ?? []} loading={models.isLoading} />
          <div className="mt-2"><SwitchRow title={t("set.thinking")} description={t("set.thinking_desc")} checked={!!d.thinking_enabled} onChange={(v) => set("thinking_enabled", v)} /></div>
        </Section>

        {adv ? <Section title={t("set.prompt")} description={t("set.prompt_desc")}>
          {/* Layer 1 — composed by the service, read-only. Shown so the owner can see what
              the secretary already knows before adding to it. */}
          <div className="rounded-xl border border-border bg-muted/30 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium">{t("set.base_prompt")}</span>
              <div className="flex items-center gap-2">
                <Segmented value={promptAudience} onChange={setPromptAudience} options={[{ value: "owner", label: t("set.aud_owner") }, { value: "visitor", label: t("set.aud_visitor") }]} />
                <Button variant="ghost" size="sm" onClick={() => setBaseOpen((v) => !v)}>{baseOpen ? t("adm.cc_log_hide") : t("set.base_show")}</Button>
              </div>
            </div>
            <p className="mt-1 text-xs text-muted-fg">{t("set.base_prompt_desc")}</p>
            {baseOpen ? (
              prompt.isLoading ? <Skeleton className="mt-3 h-40" /> :
              <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-bg/60 p-3 font-mono text-[11px] leading-relaxed text-muted-fg">{prompt.data?.base_prompt ?? ""}</pre>
            ) : null}
          </div>

          {/* Layer 2 — the owner's own words, in their language. */}
          <div className="mt-4">
            <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium">{t("set.custom")}</span>
              {!(d.custom_instructions ?? "").trim() && prompt.data?.custom_default
                ? <Button variant="outline" size="sm" onClick={() => set("custom_instructions", prompt.data!.custom_default)}>{t("set.custom_fill")}</Button>
                : null}
            </div>
            <p className="mb-2 text-xs text-muted-fg">{t("set.custom_desc")}</p>
            <Textarea value={d.custom_instructions ?? ""} maxLength={4000} placeholder={prompt.data?.custom_default ?? ""} onChange={(e) => set("custom_instructions", e.target.value)} className="min-h-[160px]" />
            <div className="mt-1 text-right text-xs text-muted-fg">{(d.custom_instructions ?? "").length}/4000</div>
          </div>
        </Section> : null}

        {adv ? <Section title={t("set.capabilities")} description={t("set.capabilities_desc")}>
          <p className="mb-3 rounded-xl border border-border px-3.5 py-3 text-sm text-muted-fg">
            {t("set.caps_where")} <Link href={`/app/agents/${agent.id}/knowledge`} className="font-medium text-accent hover:underline">{t("set.caps_where_go")}</Link>
          </p>
          <div className="divide-y divide-border">{caps.map((c) => <SwitchRow key={c} title={t(`cap.${c}`)} description={t(`cap.${c}_desc`)} checked={d.capabilities?.[c] ?? true} onChange={(v) => set("capabilities", { ...d.capabilities, [c]: v })} />)}</div>
        </Section> : null}

        {adv ? <Section title={t("set.disclosure")} description={t("set.disclosure_desc")} action={<Button variant="outline" size="sm" onClick={() => setPreview("visitor")}><Eye className="h-4 w-4" />{t("set.preview_visitor")}</Button>}>
          <DisclosureEditor agentId={agent.id} value={d.disclosure_policy} onChange={(p) => set("disclosure_policy", p)} />
        </Section> : null}

        <Section title={t("set.greeting")} description={t("set.greeting_desc")}>
          <Field label={t("set.greeting_label")} hint={t("set.greeting_hint")}><Textarea value={d.greeting ?? ""} maxLength={300} placeholder={agent.greeting_display ?? ""} onChange={(e) => set("greeting", e.target.value)} className="min-h-[80px]" /></Field>
          <div className="mt-4">
            <div className="mb-1.5 text-sm font-medium">{t("set.suggested")}</div>
            <div className="space-y-2">
              {[0, 1, 2, 3].map((i) => <Input key={i} value={sq[i] ?? ""} maxLength={120} placeholder={t("set.suggested_placeholder", { n: i + 1 })} onChange={(e) => { const n = [...sq]; n[i] = e.target.value; set("suggested_questions", n.filter((x, j) => x || j < n.length - 1).map((x) => x ?? "").filter((x, j) => j < 4 && (x !== "" || j < sq.length))); }} />)}
            </div>
          </div>
        </Section>

        {adv ? <Section title={voiceOn.stt || voiceOn.tts ? t("set.theme_voice") : t("set.theme")}>
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <div className="mb-1.5 text-sm font-medium">{t("set.accent")}</div>
              <div className="flex flex-wrap items-center gap-2">
                {ACCENTS.map((c) => <button key={c} type="button" aria-label={c} onClick={() => set("theme", { ...d.theme, accent: c })} className={cn("h-9 w-9 rounded-full border-2", d.theme?.accent === c ? "border-fg" : "border-transparent")} style={{ background: c }} />)}
                <input type="color" aria-label={t("set.accent")} value={d.theme?.accent ?? "#1a5fe0"} onChange={(e) => set("theme", { ...d.theme, accent: e.target.value })} className="h-9 w-12 rounded-lg border border-border bg-transparent" />
              </div>
            </div>
            <Field label={t("set.bubble_style")}><Segmented value={d.theme?.bubble_style ?? "soft"} onChange={(v) => set("theme", { ...d.theme, bubble_style: v })} options={[{ value: "soft", label: t("set.bubble_soft") }, { value: "square", label: t("set.bubble_square") }]} /></Field>
            <Field label={t("set.avatar_shape")}><Segmented value={d.theme?.avatar_shape ?? "circle"} onChange={(v) => set("theme", { ...d.theme, avatar_shape: v })} options={[{ value: "circle", label: t("set.shape_circle") }, { value: "rounded", label: t("set.shape_rounded") }]} /></Field>
            <Field label={t("set.background")}><Segmented value={d.theme?.background ?? "gradient"} onChange={(v) => set("theme", { ...d.theme, background: v })} options={[{ value: "gradient", label: t("set.bg_gradient") }, { value: "plain", label: t("set.bg_plain") }]} /></Field>
            {voiceOn.tts ? <Field label={t("set.tts_voice")} hint={t("set.tts_voice_hint")}><Input value={d.voice?.tts_voice ?? ""} onChange={(e) => set("voice", { ...d.voice, tts_voice: e.target.value })} placeholder="nova" /></Field> : null}
            {voiceOn.stt ? <Field label={t("set.stt_language")}><Select value={d.voice?.stt_language ?? ""} onChange={(e) => set("voice", { ...d.voice, stt_language: e.target.value })}><option value="">{t("lang.auto")}</option><option value="ko">{t("lang.ko")}</option><option value="en">{t("lang.en")}</option></Select></Field> : null}
            {voiceOn.tts ? <Slider label={t("set.tts_speed")} min={0.5} max={2} step={0.05} value={d.voice?.tts_speed ?? 1} onChange={(v) => set("voice", { ...d.voice, tts_speed: v })} /> : null}
          </div>
        </Section> : null}

        {adv ? <Section title={t("set.visitor")} description={t("set.visitor_desc")}>
          <SwitchRow title={t("set.turnstile")} description={t("set.turnstile_desc")} checked={!!d.visitor_settings?.require_turnstile} onChange={(v) => set("visitor_settings", { ...d.visitor_settings, require_turnstile: v })} />
          <div className="grid gap-4 sm:grid-cols-3 pt-2">
            <Field label={t("set.retention")}><Input type="number" min={1} max={3650} value={d.visitor_settings?.retention_days ?? 90} onChange={(e) => set("visitor_settings", { ...d.visitor_settings, retention_days: Number(e.target.value) })} /></Field>
            <Field label={t("set.collect_identity")}><Select value={d.visitor_settings?.collect_identity ?? "ask"} onChange={(e) => set("visitor_settings", { ...d.visitor_settings, collect_identity: e.target.value })}><option value="ask">{t("set.identity_ask")}</option><option value="never">{t("set.identity_never")}</option><option value="required">{t("set.identity_required")}</option></Select></Field>
          </div>
          {/* 공개 링크는 받는 쪽이 내는 구조다. 세 칸이 각각 다른 문을 지킨다:
              하루 전체, 한 곳에서 새로 여는 대화, 한 사람의 말 속도 (plan/53). */}
          <div className="grid gap-4 pt-2 sm:grid-cols-3">
            <Field label={t("set.visitor_turns")} hint={t("set.visitor_turns_hint")}>
              <Input type="number" min={0} max={100000} value={d.visitor_settings?.turns_per_day ?? 200} onChange={(e) => set("visitor_settings", { ...d.visitor_settings, turns_per_day: Math.max(0, Number(e.target.value)) })} />
            </Field>
            <Field label={t("set.visitor_sessions")} hint={t("set.visitor_sessions_hint")}>
              <Input type="number" min={0} max={10000} value={d.visitor_settings?.sessions_per_hour ?? 30} onChange={(e) => set("visitor_settings", { ...d.visitor_settings, sessions_per_hour: Math.max(0, Number(e.target.value)) })} />
            </Field>
            <Field label={t("set.rate")} hint={t("set.rate_hint")}>
              <Input type="number" min={0} max={120} value={d.visitor_settings?.rate_per_minute ?? 10} onChange={(e) => set("visitor_settings", { ...d.visitor_settings, rate_per_minute: Math.max(0, Number(e.target.value)) })} />
            </Field>
          </div>
          {/* 방문자가 건네는 파일 (plan/55 §6-3). 기본 켜짐. 받은 파일은 그 방문자와의 대화에서만
              비서가 읽고, 내 저장 공간을 쓴다 — 그래서 한 사람의 하루 개수와 한 개의 크기를 둔다. */}
          <div className="pt-2">
            <SwitchRow title={t("set.visitor_files")} description={t("set.visitor_files_desc")} checked={d.visitor_settings?.accept_files ?? true}
                       onChange={(v) => set("visitor_settings", { ...d.visitor_settings, accept_files: v })} />
            {(d.visitor_settings?.accept_files ?? true) ? (
              <div className="grid gap-4 pt-2 sm:grid-cols-3">
                <Field label={t("set.visitor_files_per_day")} hint={t("set.visitor_files_per_day_hint")}>
                  <Input type="number" min={1} max={200} value={d.visitor_settings?.files_per_day ?? 20} onChange={(e) => set("visitor_settings", { ...d.visitor_settings, files_per_day: Math.min(200, Math.max(1, Number(e.target.value))) })} />
                </Field>
                <Field label={t("set.visitor_file_max")} hint={t("set.visitor_file_max_hint")}>
                  <Input type="number" min={1} max={25} value={d.visitor_settings?.file_max_mb ?? 10} onChange={(e) => set("visitor_settings", { ...d.visitor_settings, file_max_mb: Math.min(25, Math.max(1, Number(e.target.value))) })} />
                </Field>
              </div>
            ) : null}
          </div>
        </Section> : null}

        {/* The owner's own guard rails (plan/34). A plan says what an account is given;
            what one secretary may spend of it is the owner's decision, and the balance is
            the limit that applies no matter what is typed here. */}
        {adv ? <Section title={t("set.budget")} description={t("set.budget_desc")}>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t("set.turn_cap")} hint={t("set.turn_cap_hint")}>
              <Input type="number" min={1} value={d.turn_cost_cap_credits ?? 50} onChange={(e) => set("turn_cost_cap_credits", Math.max(1, Number(e.target.value)))} />
            </Field>
            <Field label={t("set.daily_cap")} hint={t("set.unlimited_hint")}>
              <Input type="number" min={0} value={d.daily_credit_cap ?? 0} onChange={(e) => set("daily_credit_cap", Math.max(0, Number(e.target.value)))} />
            </Field>
            <Field label={t("set.monthly_cap")} hint={t("set.unlimited_hint")}>
              <Input type="number" min={0} value={d.monthly_credit_cap ?? 0} onChange={(e) => set("monthly_credit_cap", Math.max(0, Number(e.target.value)))} />
            </Field>
          </div>
        </Section> : null}

        <Section title={t("studio.versions")} description={t("studio.versions_desc")}>
          <VersionsSection agent={agent} />
        </Section>

        <Section title={t("set.danger")} className="border-danger/30">
          <div className="flex flex-wrap gap-2">
            {agent.status === "active" ? <Button variant="outline" loading={act.isPending} onClick={() => act.mutate("pause")}><Pause className="h-4 w-4" />{t("agent.pause")}</Button> : null}
            {agent.status === "paused" ? <Button variant="outline" loading={act.isPending} onClick={() => act.mutate("resume")}><Play className="h-4 w-4" />{t("agent.resume")}</Button> : null}
            {agent.status !== "archived" ? <Button variant="outline" loading={act.isPending} onClick={() => act.mutate("archive")}><Archive className="h-4 w-4" />{t("agent.archive")}</Button>
              : <Button variant="outline" loading={act.isPending} onClick={() => act.mutate("restore")}><ArchiveRestore className="h-4 w-4" />{t("agent.restore")}</Button>}
            <Button variant="danger" onClick={() => setDelOpen(true)}><Trash2 className="h-4 w-4" />{t("agent.delete")}</Button>
          </div>
          <p className="mt-2 text-xs text-muted-fg">{t("set.danger_desc")}</p>
        </Section>
      </div>

      {/* 저장 바는 고친 것이 있을 때만 뜬다. 늘 서 있던 바(미리보기·성격 검증·"저장하면 버전이
          남아요")는 걷었다 — 미리보기는 [방문자 화면] 탭이, 성격 검증은 [성격] 칸이 맡는다. */}
      {dirty.length ? (
        <div /* sticky inside the content column: a viewport-fixed bar ran under the sidebar and centred on the window */
          className="bottom-bar sticky bottom-0 z-20 -mx-4 mt-4 mb-16 border-t border-border bg-card/95 px-4 backdrop-blur md:-mx-6 md:mb-0 md:px-6 pb-[var(--sab)]">
          <div className="flex flex-wrap items-center justify-end gap-3 py-3">
            <span className="text-sm text-muted-fg">{t("set.unsaved", { n: dirty.length })}</span>
            <Button variant="ghost" onClick={() => setD(agent)}>{t("common.discard")}</Button><Button loading={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button>
          </div>
        </div>
      ) : null}

      <VerifyDialog agent={agent} draft={draftOf(d)} open={verifyOpen} onClose={() => setVerifyOpen(false)} />
      <PromptPreviewDialog agentId={agent.id} audience={preview} onClose={() => setPreview(null)} onAudience={setPreview} dirty={dirty.length > 0} />
      <Dialog open={delOpen} onClose={() => setDelOpen(false)} title={t("agent.delete")} description={t("agent.delete_desc", { name: agent.name })} size="sm"
        footer={<><Button variant="outline" onClick={() => setDelOpen(false)}>{t("common.cancel")}</Button><Button variant="danger" disabled={delName !== agent.name} loading={del.isPending} onClick={() => del.mutate()}>{t("common.delete")}</Button></>}>
        <Input value={delName} onChange={(e) => setDelName(e.target.value)} placeholder={agent.name} />
      </Dialog>
      {cropUI}
    </Page>
  );
}

export function PromptPreviewDialog({ agentId, audience, onClose, onAudience, dirty }: { agentId: string; audience: "owner" | "visitor" | null; onClose: () => void; onAudience: (a: "owner" | "visitor") => void; dirty: boolean }) {
  const t = useT();
  const q = useQuery({ queryKey: ["prompt-preview", agentId, audience], queryFn: () => Agents.promptPreview(agentId, audience!), enabled: !!audience });
  return (
    <Dialog open={!!audience} onClose={onClose} title={t("set.preview_prompt")} description={dirty ? t("set.preview_unsaved") : undefined} size="xl">
      <div className="mb-3"><Segmented value={audience ?? "owner"} onChange={onAudience} options={[{ value: "owner", label: t("conv.audience_owner") }, { value: "visitor", label: t("conv.audience_visitor") }]} /></div>
      {q.isLoading ? <Skeleton className="h-60" /> : (
        <div className="space-y-3">
          {q.data?.sections.filter((s) => s.text.trim()).map((s) => (
            <details key={s.key} open className="rounded-xl border border-border">
              {/* the preview shows the composed layers, so name them the way the docs do
                  instead of leaking block keys like "base_mission" into the dialog */}
              <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{t(`set.sec_${s.key}`)} <span className="ml-1 text-xs font-normal text-muted-fg">{s.text.length.toLocaleString()}자</span></summary>
              <pre className="whitespace-pre-wrap px-3 pb-3 font-mono text-[12px] leading-relaxed text-muted-fg">{s.text}</pre>
            </details>
          ))}
          <div className="text-xs text-muted-fg">{t("set.tools_exposed")}: {q.data?.tools.join(", ")} · {t("set.prompt_total", { n: (q.data?.sections.reduce((n, s) => n + s.text.length, 0) ?? 0).toLocaleString() })}</div>
        </div>
      )}
    </Dialog>
  );
}
export { Switch };
