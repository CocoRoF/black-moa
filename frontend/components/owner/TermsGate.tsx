"use client";
import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ScrollText } from "@/components/icons";
import { Auth } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { useAuth } from "@/stores/auth";
import { Button } from "@/components/ui/button";
import { TermsAgree } from "@/components/auth/TermsAgree";

/** 앱에 들어올 때 한 번 받는 동의 (plan/73).
 *
 *  가입할 때 동의를 남기지 않은 계정(예전 계정, 로그인 화면에서 곧바로 만들어진 연결 계정)과, 이용약관·개인정보
 *  처리방침의 판(시행일)이 바뀐 뒤의 모든 계정. 닫을 수 없다 — 동의하지 않으려면 [설정]에서 탈퇴할 수 있다. */
export function TermsGate() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const user = useAuth((s) => s.user);
  const path = usePathname();
  const { data: st } = useQuery({ queryKey: ["auth-status"], queryFn: Auth.status, staleTime: 300_000 });
  const [agree, setAgree] = useState(false);
  const version = st?.legal_version;
  const agreeM = useMutation({
    mutationFn: () => Auth.agreeTerms(version!),
    onSuccess: (r) => { useAuth.getState().setUser(r.user); toast.success(t("legal.consent_done")); },
    onError: (e) => { toast.error(friendlyError(e, locale)); void qc.invalidateQueries({ queryKey: ["auth-status"] }); },
  });
  // [설정]은 가리지 않는다 — 동의하지 않는 사람이 탈퇴할 길이 막히면 안 된다.
  if (!user || !version || user.terms_version === version || path.startsWith("/app/settings")) return null;
  const updated = !!user.terms_version;
  return (
    <div className="fixed inset-0 z-[120] flex items-end justify-center bg-black/50 p-0 backdrop-blur-[2px] min-[480px]:items-center min-[480px]:p-4" role="presentation">
      <div role="dialog" aria-modal="true" aria-labelledby="terms-gate-title"
           className="sheet-up w-full max-w-md rounded-t-2xl border border-border bg-card p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-2xl min-[480px]:fade-up min-[480px]:rounded-2xl">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-accent/12 text-accent"><ScrollText className="h-[18px] w-[18px]" /></span>
          <h2 id="terms-gate-title" className="text-base font-semibold">{t(updated ? "legal.consent_title_updated" : "legal.consent_title")}</h2>
        </div>
        <p className="mt-3 text-sm leading-relaxed text-muted-fg">{t(updated ? "legal.consent_desc_updated" : "legal.consent_desc")}</p>
        <TermsAgree checked={agree} onChange={setAgree} id="gate-terms" className="mt-4" />
        <Button variant="accent" className="mt-4 w-full" disabled={!agree} loading={agreeM.isPending} onClick={() => agreeM.mutate()}>{t("legal.consent_agree")}</Button>
        <p className="mt-3 text-center text-xs text-muted-fg">
          {t("legal.consent_decline")} <Link href="/app/settings" className="underline underline-offset-2 hover:text-fg">{t("legal.consent_settings")}</Link>
        </p>
      </div>
    </div>
  );
}
