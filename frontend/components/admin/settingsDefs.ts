import type { TFn } from "@/lib/i18n";
import type { SettingField } from "./common";

// 음성 (plan/67): 끄면 웹과 PC 앱에서 관련 단추와 설정이 사라진다. 꺼 두면 세부 설정도 접는다.
const sttOn = (v: Record<string, any>) => !!v["stt.enabled"];
const ttsOn = (v: Record<string, any>) => !!v["tts.enabled"];
export const sttFields = (t: TFn): SettingField[] => [
  { key: "stt.enabled", label: t("adm.stt_enabled"), type: "bool", hint: t("adm.stt_enabled_hint") },
  { key: "stt.provider", showIf: sttOn, label: t("adm.stt_provider"), type: "select", options: [{ value: "openai", label: "OpenAI" }, { value: "google", label: "Google" }, { value: "elevenlabs", label: "ElevenLabs" }] },
  { key: "stt.model", showIf: sttOn, label: t("adm.stt_model"), type: "text", placeholder: "gpt-4o-mini-transcribe" },
  { key: "stt.credit_per_minute", showIf: sttOn, label: t("adm.stt_credit"), type: "number" },
];
export const ttsFields = (t: TFn): SettingField[] => [
  { key: "tts.enabled", label: t("adm.tts_enabled"), type: "bool", hint: t("adm.tts_enabled_hint") },
  { key: "tts.provider", showIf: ttsOn, label: t("adm.tts_provider"), type: "select", options: [{ value: "openai", label: "OpenAI" }, { value: "google", label: "Google" }, { value: "elevenlabs", label: "ElevenLabs" }] },
  { key: "tts.model", showIf: ttsOn, label: t("adm.tts_model"), type: "text", placeholder: "gpt-4o-mini-tts" },
  { key: "tts.default_voice", showIf: ttsOn, label: t("adm.tts_voice"), type: "text", placeholder: "nova" },
  { key: "tts.credit_per_1k_chars", showIf: ttsOn, label: t("adm.tts_credit"), type: "number" },
];
export const embeddingFields = (t: TFn): SettingField[] => [
  { key: "embedding.provider", label: t("adm.emb_provider"), type: "select", options: [{ value: "openai", label: "OpenAI" }, { value: "voyage", label: "Voyage" }, { value: "google", label: "Google" }] },
  { key: "embedding.model", label: t("adm.emb_model"), type: "text", placeholder: "text-embedding-3-small" },
  { key: "embedding.dim", label: t("adm.emb_dim"), type: "number", hint: t("adm.emb_dim_hint") },
  { key: "embedding.credit_per_1k", label: t("adm.emb_credit"), type: "number" },
];
export const brandingFields = (t: TFn): SettingField[] => [
  { key: "branding.service_name", label: t("adm.service_name"), type: "text" },
  { key: "branding.tagline", label: t("adm.tagline"), type: "text" },
  { key: "branding.logo_url", label: t("adm.logo_url"), type: "text", placeholder: "https://…" },
];
export const signupFields = (t: TFn): SettingField[] => [
  { key: "signup.mode", label: t("adm.signup_mode"), type: "select", options: [{ value: "open", label: t("adm.signup_open") }, { value: "invite", label: t("adm.signup_invite") }, { value: "closed", label: t("adm.signup_closed") }] },
  { key: "signup.require_email_verification", label: t("adm.signup_verify"), type: "bool" },
  { key: "signup.verify_before_agent", label: t("adm.verify_before_agent"), type: "bool", hint: t("adm.verify_before_agent_hint") },
];
export const smtpFields = (): SettingField[] => [
  { key: "smtp.host", label: "SMTP host", type: "text" }, { key: "smtp.port", label: "Port", type: "number" },
  { key: "smtp.user", label: "User", type: "text" }, { key: "smtp.password", label: "Password", type: "secret" },
  { key: "smtp.from", label: "From", type: "text", placeholder: "black-moa <no-reply@black.memo-ora.com>" },
  { key: "smtp.from_agent", label: "From (secretary)", type: "text", placeholder: "black-moa <blackmoa@black.memo-ora.com>" },
  { key: "smtp.use_tls", label: "STARTTLS", type: "bool" },
];
export const telegramFields = (): SettingField[] => [
  { key: "telegram.bot_token", label: "Bot token", type: "secret" }, { key: "telegram.bot_username", label: "Bot username", type: "text", placeholder: "my_blackmoa_bot" },
];
export const turnstileFields = (): SettingField[] => [
  { key: "public.turnstile_site_key", label: "Turnstile site key", type: "text" }, { key: "public.turnstile_secret", label: "Turnstile secret", type: "secret" },
];
export const publicDefaultFields = (t: TFn): SettingField[] => [
  { key: "public.default_rate_per_minute", label: t("adm.rate_per_minute"), type: "number" }, { key: "public.default_retention_days", label: t("adm.retention_days"), type: "number" },
];
export const memoryFields = (t: TFn): SettingField[] => [
  { key: "memory.distill_enabled", label: t("adm.distill_enabled"), type: "bool" },
  { key: "memory.distill_provider", label: t("adm.distill_provider"), type: "text" }, { key: "memory.distill_model", label: t("adm.distill_model"), type: "text" },
  { key: "memory.max_open_vaults", label: t("adm.max_open_vaults"), type: "number" }, { key: "memory.idle_evict_minutes", label: t("adm.idle_evict"), type: "number" },
];
export const creditFields = (t: TFn): SettingField[] => [
  { key: "credits.usd_per_credit", label: t("adm.usd_per_credit"), type: "number" }, { key: "credits.margin", label: t("adm.margin"), type: "number" },
  { key: "credits.signup_grant", label: t("adm.signup_grant"), type: "number" }, { key: "credits.low_watermark_ratio", label: t("adm.low_watermark"), type: "number" },
];
export const stripeFields = (): SettingField[] => [
  { key: "stripe.secret_key", label: "Stripe secret key", type: "secret" }, { key: "stripe.webhook_secret", label: "Webhook secret", type: "secret" }, { key: "stripe.price_ids", label: "Price IDs (JSON)", type: "json" },
];
/** 운영자 정보 (plan/73): 이용약관·개인정보 처리방침과 바닥글에 들어간다. 비어 있는 칸은 문서에서 줄째로 빠진다. */
export const legalOperatorFields = (t: TFn): SettingField[] => [
  { key: "legal.company_name", label: t("adm.legal_company"), type: "text", hint: t("adm.legal_company_hint") },
  { key: "legal.ceo_name", label: t("adm.legal_ceo"), type: "text" },
  { key: "legal.business_no", label: t("adm.legal_business_no"), type: "text", placeholder: "000-00-00000" },
  { key: "legal.mail_order_no", label: t("adm.legal_mail_order_no"), type: "text", hint: t("adm.legal_mail_order_hint") },
  { key: "legal.address", label: t("adm.legal_address"), type: "text" },
  { key: "legal.phone", label: t("adm.legal_phone"), type: "text" },
  { key: "legal.email", label: t("adm.legal_email"), type: "text", hint: t("adm.legal_email_hint") },
  { key: "legal.hosting", label: t("adm.legal_hosting"), type: "text" },
  { key: "legal.privacy_officer", label: t("adm.legal_privacy_officer"), type: "text", hint: t("adm.legal_privacy_officer_hint") },
  { key: "legal.privacy_officer_title", label: t("adm.legal_privacy_officer_title"), type: "text" },
  { key: "legal.privacy_email", label: t("adm.legal_privacy_email"), type: "text" },
  { key: "legal.privacy_phone", label: t("adm.legal_privacy_phone"), type: "text" },
  { key: "legal.effective_date", label: t("adm.legal_effective_date"), type: "text", placeholder: "2026-09-29", hint: t("adm.legal_effective_date_hint") },
];
/** 본문: 비워 두면 기본 문서(대한민국 법 기준)를 쓴다. */
export const legalFields = (t: TFn): SettingField[] => [
  { key: "legal.terms", label: t("legal.terms"), type: "textarea", hint: t("adm.legal_text_hint") },
  { key: "legal.privacy", label: t("legal.privacy"), type: "textarea", hint: t("adm.legal_text_hint") },
];
export const logFields = (): SettingField[] => [{ key: "log.level", label: "Log level", type: "select", options: ["DEBUG", "INFO", "WARNING", "ERROR"].map((x) => ({ value: x, label: x })) }];

/** 내 주변 맛집 (plan/34). The REST key and client secret stay on the server; the JavaScript
 *  key is sent to browsers by design and protected by the domain registered with Kakao. */
