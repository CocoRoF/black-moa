"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BadgeCheck, Download, LogOut, Monitor, Trash2, Upload } from "@/components/icons";
import { Auth, Chat, Users, fetchBlobUrl } from "@/lib/api";
import { useLocale, useSetLocale, useT, type Locale } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtDateTime } from "@/lib/format";
import { useAuth } from "@/stores/auth";
import { useTheme, type ThemePref } from "@/lib/theme";
import { CODE_LENGTH, normalizeCode } from "@/lib/otp";
import { checkPassword } from "@/lib/password";
import { PasswordRules } from "@/components/ui/password-rules";
import { Page } from "./Shell";
import { Section } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/tabs";
import { Dialog } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar, PageHeader } from "@/components/ui/misc";
import { useImageCrop } from "@/components/ui/image-crop";
import { Badge } from "@/components/ui/badge";
import { LoginMethods } from "./LoginMethods";

const TZS = ["Asia/Seoul", "Asia/Tokyo", "Asia/Singapore", "Asia/Shanghai", "Asia/Kolkata", "Europe/London", "Europe/Berlin", "Europe/Paris", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "Australia/Sydney", "UTC"];

export function SettingsPage() {
  const t = useT(); const locale = useLocale(); const setLocaleCtx = useSetLocale(); const qc = useQueryClient(); const router = useRouter();
  const user = useAuth((s) => s.user)!;
  const { pref, setPref } = useTheme();
  const [name, setName] = useState(user.display_name); const [tz, setTz] = useState(user.timezone || "Asia/Seoul"); const [loc, setLoc] = useState<Locale>(user.locale);
  const [cur, setCur] = useState(""); const [pw, setPw] = useState(""); const [pw2, setPw2] = useState("");
  const [delOpen, setDelOpen] = useState(false); const [delText, setDelText] = useState("");
  const [code, setCode] = useState(""); const [avatarBusy, setAvatarBusy] = useState(false);
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: Users.sessions });
  // 연결로만 들어온 사람은 비밀번호가 없다 — 그러면 "바꾸기" 가 아니라 "만들기" 다 (plan/59).
  const ids = useQuery({ queryKey: ["identities"], queryFn: Auth.identities });
  const hasPw = ids.data?.has_password !== false;
  const { crop, node: cropUI } = useImageCrop();
  const saveMe = useMutation({ mutationFn: () => Users.patchMe({ display_name: name, timezone: tz, locale: loc }), onSuccess: (u) => { useAuth.getState().setUser(u); setLocaleCtx?.(u.locale); toast.success(t("common.saved")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const changePw = useMutation({
    mutationFn: () => Users.password({ current_password: cur, new_password: pw }),
    // The server hands back a new session for this device; adopt it so the person
    // who just changed their password is not the one who gets signed out.
    onSuccess: (r) => { useAuth.getState().setAuth(r.access_token, r.user); setCur(""); setPw(""); setPw2(""); qc.invalidateQueries({ queryKey: ["sessions"] }); qc.invalidateQueries({ queryKey: ["identities"] }); toast.success(hasPw ? t("settings.pw_changed") : t("settings.pw_created")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const setAvatar = async (url: string | null) => {
    const u = await Users.patchMe({ avatar_url: url ?? "" });
    useAuth.getState().setUser(u);
  };
  const uploadAvatar = async (f: File) => {
    // Frame it first (plan/32). A wide photo used to arrive centre-cropped, which for a
    // portrait taken sideways meant a shoulder.
    const framed = await crop(f, "circle");
    if (!framed) return;
    setAvatarBusy(true);
    try { const r = await Chat.upload(framed, "avatar"); await setAvatar(r.url); toast.success(t("common.saved")); }
    catch (e) { toast.error(friendlyError(e, locale)); } finally { setAvatarBusy(false); }
  };
  const sendCode = useMutation({ mutationFn: Auth.sendVerification, onSuccess: () => toast.success(t("settings.verify_sent")), onError: (e) => toast.error(friendlyError(e, locale)) });
  const verify = useMutation({ mutationFn: () => Auth.verifyEmail(code), onSuccess: async () => { setCode(""); const u = await Auth.me(); useAuth.getState().setUser(u); toast.success(t("settings.verified")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const logoutAll = useMutation({ mutationFn: Auth.logoutAll, onSuccess: () => { useAuth.getState().clear(); qc.clear(); router.replace("/login"); } });
  const exportZip = useMutation({ mutationFn: () => fetchBlobUrl("/api/users/me/export"), onSuccess: (url) => { const a = document.createElement("a"); a.href = url; a.download = `memora-export-${new Date().toISOString().slice(0, 10)}.zip`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 5000); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const delMe = useMutation({ mutationFn: Users.deleteMe, onSuccess: () => { useAuth.getState().clear(); qc.clear(); router.replace("/"); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  return (
    <Page>
      <PageHeader title={t("nav.settings")} description={user.email} />
      <div className="space-y-4">
        <Section title={t("settings.account")}>
          <Field label={t("settings.avatar")} hint={t("settings.avatar_hint")}>
            <div className="flex items-center gap-3">
              <Avatar name={user.display_name} src={user.avatar_url} size={56} />
              <label className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-xl border border-border px-3 text-sm font-medium hover:bg-muted">
                <Upload className="h-4 w-4" />{t("settings.avatar_upload")}
                <input type="file" accept="image/*" className="hidden" disabled={avatarBusy}
                  onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void uploadAvatar(f); }} />
              </label>
              {user.avatar_url ? <Button variant="ghost" size="sm" onClick={() => void setAvatar(null)}>{t("common.delete")}</Button> : null}
            </div>
          </Field>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field label={t("auth.display_name")}><Input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
            <Field label={t("settings.locale")}><Segmented value={loc} onChange={setLoc} options={[{ value: "ko", label: "한국어" }, { value: "en", label: "English" }]} /></Field>
            <Field label={t("settings.timezone")}><Select value={tz} onChange={(e) => setTz(e.target.value)}>{[...new Set([tz, ...TZS])].map((z) => <option key={z} value={z}>{z}</option>)}</Select></Field>
            <Field label={t("settings.theme")}><Segmented<ThemePref> value={pref} onChange={setPref} options={[{ value: "light", label: t("common.light_mode") }, { value: "dark", label: t("common.dark_mode") }, { value: "system", label: t("settings.theme_system") }]} /></Field>
          </div>
          <div className="mt-4"><Button loading={saveMe.isPending} onClick={() => saveMe.mutate()}>{t("common.save")}</Button></div>
        </Section>
        <Section title={t("settings.email")} description={user.email}>
          {user.email_verified ? (
            <Badge tone="success"><BadgeCheck className="h-3.5 w-3.5" />{t("settings.email_verified")}</Badge>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2"><Badge tone="warning">{t("settings.email_unverified")}</Badge>
                <Button variant="outline" size="sm" loading={sendCode.isPending} onClick={() => sendCode.mutate()}>{t("settings.send_code")}</Button></div>
              <div className="flex items-end gap-2">
                <Field label={t("settings.verify_code")} className="w-40"><Input value={code} inputMode="numeric" autoComplete="one-time-code" onChange={(e) => setCode(normalizeCode(e.target.value))} /></Field>
                <Button variant="outline" disabled={code.length < CODE_LENGTH} loading={verify.isPending} onClick={() => verify.mutate()}>{t("settings.verify")}</Button>
              </div>
            </div>
          )}
        </Section>
        <LoginMethods />
        <Section title={hasPw ? t("settings.password") : t("settings.password_create")} description={hasPw ? undefined : t("settings.password_create_desc")}>
          <div className="grid gap-4 sm:grid-cols-3">
            {hasPw ? <Field label={t("settings.current_password")}><Input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></Field> : null}
            <Field label={t("auth.new_password")}><Input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} aria-describedby="settings-pw-rules" /></Field>
            <Field label={t("auth.confirm_password")} error={pw2 && pw !== pw2 ? t("auth.password_mismatch") : undefined}><Input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} /></Field>
          </div>
          {/* The same checklist as signup, from the same rule the server enforces. */}
          <div className="mt-3 max-w-sm"><PasswordRules verdict={checkPassword(pw)} show={pw.length > 0} id="settings-pw-rules" /></div>
          <div className="mt-4"><Button variant="outline" loading={changePw.isPending} disabled={!checkPassword(pw).ok || pw !== pw2} onClick={() => changePw.mutate()}>{hasPw ? t("settings.change_password") : t("settings.create_password")}</Button></div>
        </Section>
        <Section title={t("settings.sessions")} action={<Button variant="outline" size="sm" loading={logoutAll.isPending} onClick={() => logoutAll.mutate()}><LogOut className="h-4 w-4" />{t("settings.logout_all")}</Button>}>
          {sessions.isLoading ? <Skeleton className="h-20" /> : <ul className="divide-y divide-border">{sessions.data?.items.map((s) => <li key={s.id} className="flex items-center gap-3 py-2 text-sm"><Monitor className="h-4 w-4 text-muted-fg shrink-0" /><div className="min-w-0 flex-1"><div className="truncate">{s.ua || "–"}</div><div className="text-xs text-muted-fg">{s.ip} · {fmtDateTime(s.created_at)}</div></div></li>)}</ul>}
        </Section>
        <Section title={t("settings.data")} description={t("settings.data_desc")}>
          <Button variant="outline" loading={exportZip.isPending} onClick={() => exportZip.mutate()}><Download className="h-4 w-4" />{t("settings.export")}</Button>
        </Section>
        <Section title={t("set.danger")} className="border-danger/30">
          <p className="mb-3 text-sm text-muted-fg">{t("settings.delete_desc")}</p>
          <Button variant="danger" onClick={() => setDelOpen(true)}><Trash2 className="h-4 w-4" />{t("settings.delete_account")}</Button>
        </Section>
      </div>
      <Dialog open={delOpen} onClose={() => setDelOpen(false)} title={t("settings.delete_account")} description={t("settings.delete_confirm", { email: user.email })} size="sm" footer={<><Button variant="outline" onClick={() => setDelOpen(false)}>{t("common.cancel")}</Button><Button variant="danger" disabled={delText !== user.email} loading={delMe.isPending} onClick={() => delMe.mutate()}>{t("common.delete")}</Button></>}>
        <Input value={delText} onChange={(e) => setDelText(e.target.value)} placeholder={user.email} />
      </Dialog>
      {cropUI}
    </Page>
  );
}
