"use client";
import { Auth } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { GoogleIcon, KakaoIcon } from "@/components/integrations/ProviderIcon";

/** 연결로 로그인하는 버튼들 (plan/59). 관리자가 [연결]에서 로그인에 쓰기로 켠 공급자만 온다.
 *  모양은 각 공급자의 버튼 규칙을 따른다 — 카카오는 노란 바탕(#FEE500)에 검은 말풍선, Google 은 흰 바탕에 G. */
export function SsoButtons({ providers, next, invite, className, agree, requireAgree }: {
  providers: { id: string; label: string }[] | undefined; next: string; invite?: string | null; className?: string;
  /** 가입 화면에서 약관에 동의했는가 (plan/73). 동의를 싣고 가서 새 계정이 만들어지면 서버가 남긴다. */
  agree?: boolean;
  /** 가입 화면: 동의하기 전에는 누를 수 없다. */
  requireAgree?: boolean;
}) {
  const t = useT();
  if (!providers?.length) return null;
  const blocked = !!requireAgree && !agree;
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center gap-3 text-xs text-muted-fg" aria-hidden>
        <span className="h-px flex-1 bg-border" />{t("auth.or")}<span className="h-px flex-1 bg-border" />
      </div>
      {providers.map((p) => (
        <a key={p.id} href={blocked ? undefined : Auth.ssoStartUrl(p.id, { next, invite, agree })}
           aria-disabled={blocked || undefined} role={blocked ? "link" : undefined}
           className={cn("flex h-10 w-full items-center justify-center gap-2 rounded-xl text-sm font-medium transition-[filter]",
             blocked && "pointer-events-none opacity-45",
             p.id === "kakao" ? "bg-[#FEE500] text-black/85 hover:brightness-95"
               : "border border-border bg-card hover:bg-muted")}>
          {p.id === "kakao" ? <KakaoIcon bare size={18} /> : p.id === "google" ? <GoogleIcon size={18} /> : null}
          {p.id === "kakao" ? t("auth.kakao_continue") : p.id === "google" ? t("auth.google_continue") : t("auth.sso_continue", { name: p.label })}
        </a>
      ))}
      {blocked ? <p className="text-center text-xs text-muted-fg">{t("legal.agree_first")}</p> : null}
    </div>
  );
}
