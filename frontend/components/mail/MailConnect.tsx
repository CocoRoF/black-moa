"use client";
import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ExternalLink, Lock } from "@/components/icons";
import { Mail } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";

/* 메일함 연결 (plan/74).

   메일 서비스가 주는 IMAP 과 앱 비밀번호로 잇는다 — Gmail 도 이 길이다. 서비스마다 앱 비밀번호를 만드는 곳이
   달라서 고른 서비스의 안내와 바로 가는 링크를 보여 준다. 비밀번호는 서버가 먼저 로그인해 보고 되면 암호화해서
   보관하며, 다시 보여 주지 않는다. */

export type MailPreset = "gmail" | "naver" | "daum" | "kakao" | "custom";

const SERVICES: { id: MailPreset; label: string; link?: string }[] = [
  { id: "gmail", label: "Gmail", link: "https://myaccount.google.com/apppasswords" },
  { id: "naver", label: "네이버", link: "https://mail.naver.com" },
  { id: "daum", label: "다음", link: "https://mail.daum.net" },
  { id: "kakao", label: "카카오", link: "https://mail.kakao.com" },
  { id: "custom", label: "기타" },
];

export function MailConnect({ open, onClose, initial }: {
  open: boolean; onClose: () => void;
  /** 다시 연결할 때 — 고른 서비스와 주소를 채워 둔다. */
  initial?: { preset?: string; email?: string };
}) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [preset, setPreset] = useState<MailPreset>("gmail");
  const [email, setEmail] = useState(""); const [password, setPassword] = useState(""); const [host, setHost] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    setPreset((initial?.preset as MailPreset) || "gmail");
    setEmail(initial?.email ?? ""); setPassword(""); setHost(""); setErr(null);
  }, [open, initial?.preset, initial?.email]);
  const add = useMutation({
    mutationFn: () => Mail.addAccount({ preset, email: email.trim(), password, host: preset === "custom" ? host.trim() : null }),
    onSuccess: () => {
      toast.success(t("mail.connected"));
      qc.invalidateQueries({ queryKey: ["mail"] });
      onClose();
    },
    onError: (e) => setErr(friendlyError(e, locale)),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); setErr(null); add.mutate(); };
  const svc = SERVICES.find((s) => s.id === preset)!;
  const ready = !!email.trim() && !!password.trim() && (preset !== "custom" || !!host.trim());
  return (
    <Dialog open={open} onClose={onClose} title={t("mail.connect_dialog")} description={t("mail.connect_dialog_desc")}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div role="radiogroup" aria-label={t("mail.service")} className="grid grid-cols-5 gap-1.5">
          {SERVICES.map((s) => (
            <button key={s.id} type="button" role="radio" aria-checked={preset === s.id} onClick={() => { setPreset(s.id); setErr(null); }}
                    className={cn("rounded-xl border px-2 py-2 text-[13px] font-medium transition-colors",
                      preset === s.id ? "border-accent bg-accent/8 text-fg ring-1 ring-accent" : "border-border text-muted-fg hover:bg-muted/60")}>
              {s.label}
            </button>
          ))}
        </div>
        <div className="rounded-xl bg-muted/50 px-3 py-2.5 text-[13px] leading-relaxed text-muted-fg">
          <p>{t(`mail.guide_${preset}`)}</p>
          {svc.link ? (
            <a href={svc.link} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 font-medium text-accent hover:underline">
              {t(preset === "gmail" ? "mail.guide_gmail_link" : "mail.guide_open", { name: svc.label })}<ExternalLink className="h-3.5 w-3.5" />
            </a>
          ) : null}
        </div>
        {preset === "custom" ? (
          <Field label={t("mail.host")} htmlFor="mail-host" hint={t("mail.host_hint")}>
            <Input id="mail-host" value={host} onChange={(e) => setHost(e.target.value)} placeholder="imap.example.com" autoComplete="off" spellCheck={false} />
          </Field>
        ) : null}
        <Field label={t("mail.address")} htmlFor="mail-email">
          <Input id="mail-email" type="email" inputMode="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="me@example.com" />
        </Field>
        <Field label={t("mail.app_password")} htmlFor="mail-pw" hint={t("mail.app_password_hint")}>
          <Input id="mail-pw" type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="abcd efgh ijkl mnop" />
        </Field>
        {err ? <p role="alert" className="text-sm text-danger">{err}</p> : null}
        <p className="flex items-start gap-1.5 text-xs text-muted-fg"><Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" />{t("mail.connect_privacy")}</p>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="submit" variant="accent" loading={add.isPending} disabled={!ready}>{t("mail.connect_do")}</Button>
        </div>
      </form>
    </Dialog>
  );
}
