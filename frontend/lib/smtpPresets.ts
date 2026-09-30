/** SMTP relays we know how to fill in.
 *
 *  Every one of these authenticates with a token, and the trap is the same each time: the
 *  username is a fixed literal, not your email address. Cloudflare wants `api_token`,
 *  SendGrid wants `apikey`, Resend wants `resend` — typing the account address there fails
 *  with a generic auth error that tells you nothing. So a preset pins the literal and the
 *  form explains it instead of leaving a blank box.
 *
 *  Verified against each provider's own documentation on 2026-09-08.
 */
export interface SmtpPreset {
  id: string;
  label: string;
  host: string;
  port: number;
  /** Fixed username, or null when the provider expects the account's own login. */
  user: string | null;
  userHintKey: string;
  secretLabelKey: string;
  docs: string;
}

export const SMTP_PRESETS: SmtpPreset[] = [
  { id: "cloudflare", label: "Cloudflare Email Sending", host: "smtp.mx.cloudflare.net", port: 465,
    user: "api_token", userHintKey: "email.hint_literal", secretLabelKey: "email.secret_cf",
    docs: "https://developers.cloudflare.com/email-service/api/send-emails/smtp/" },
  { id: "resend", label: "Resend", host: "smtp.resend.com", port: 465,
    user: "resend", userHintKey: "email.hint_literal", secretLabelKey: "email.secret_api_key",
    docs: "https://resend.com/docs/send-with-smtp" },
  { id: "sendgrid", label: "SendGrid", host: "smtp.sendgrid.net", port: 587,
    user: "apikey", userHintKey: "email.hint_literal", secretLabelKey: "email.secret_api_key",
    docs: "https://www.twilio.com/docs/sendgrid/for-developers/sending-email/integrating-with-the-smtp-api" },
  { id: "brevo", label: "Brevo", host: "smtp-relay.brevo.com", port: 587,
    user: null, userHintKey: "email.hint_login", secretLabelKey: "email.secret_smtp_key",
    docs: "https://developers.brevo.com/docs/smtp-integration" },
  { id: "custom", label: "", host: "", port: 587, user: null, userHintKey: "email.hint_free",
    secretLabelKey: "email.secret_password", docs: "" },
];

export const presetById = (id: string) => SMTP_PRESETS.find((p) => p.id === id) ?? SMTP_PRESETS[SMTP_PRESETS.length - 1];

/** Port decides the encryption; 465 is implicit TLS and never negotiates STARTTLS. */
export const encryptionFor = (port: number) => (port === 465 || port === 2465 ? "ssl" : "starttls");
