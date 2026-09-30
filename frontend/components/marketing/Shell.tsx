"use client";
import Link from "next/link";
import { useEffect } from "react";
import { currentDoor, inAppShell, interceptLinks } from "@/lib/desktop";
import { useQuery } from "@tanstack/react-query";
import { Moon, Sun } from "@/components/icons";
import { LocaleProvider, useT } from "@/lib/i18n";
import { useBrowserLocale, useSession } from "@/lib/hooks";
import { Public } from "@/lib/api";
import { useTheme } from "@/lib/theme";
import { BRAND } from "@/lib/brand";
import { Button, buttonLook } from "@/components/ui/button";
import { Logo, Wordmark } from "@/components/brand/Logo";
import { useLocale } from "@/lib/i18n";

function Header() {
  const t = useT();
  const { user, ready } = useSession(true);
  const { resolved, setPref } = useTheme();
  const { data } = useQuery({ queryKey: ["branding"], queryFn: Public.branding, staleTime: 300_000 });
  return (
    <header className="app-hide sticky top-0 z-40 border-b border-border/70 bg-bg/80 backdrop-blur safe-pt">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
        <Logo href="/" size={34} label={data?.service_name && data.service_name !== "MFSG" ? data.service_name : BRAND.name} />
        <nav className="flex items-center gap-1.5">
          <Button variant="ghost" size="icon-sm" aria-label={t("common.toggle_theme")} onClick={() => setPref(resolved === "dark" ? "light" : "dark")}>{resolved === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</Button>
          {ready && user ? (
            <Link href="/app" className={buttonLook("accent", "sm")}>{t("mkt.go_console")}</Link>
          ) : (
            <>
              <Link href="/login" className={buttonLook("ghost", "sm")}>{t("auth.login")}</Link>
              <Link href="/signup" className={buttonLook("accent", "sm")}>{t("auth.signup")}</Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}

function Footer() {
  const t = useT(); const locale = useLocale();
  return (
    <footer className="app-hide border-t border-border/70 pt-8 pb-[max(2rem,var(--sab))] text-center text-xs text-muted-fg">
      <Link href="/" aria-label={BRAND.name} className="inline-flex justify-center rounded-lg"><Wordmark size={22} /></Link>
      <p className="mt-2 text-[13px] text-muted-fg">{locale === "ko" ? BRAND.tagline_ko : BRAND.tagline_en}</p>
      <div className="mt-3 flex justify-center gap-4"><Link href="/terms" className="hover:text-fg">{t("legal.terms")}</Link><Link href="/privacy" className="font-semibold hover:text-fg">{t("legal.privacy")}</Link></div>
      <OperatorInfo />
      <div className="mt-2">© {new Date().getFullYear()} {BRAND.name}</div>
    </footer>
  );
}

/** 사업자 정보 (plan/73, 전자상거래법 제10조): 관리자가 [설정 → 운영자 정보]에 채운 것만 보인다. */
function OperatorInfo() {
  const { data } = useQuery({ queryKey: ["legal"], queryFn: Public.legal, staleTime: 600_000 });
  const o = data?.operator ?? {};
  const parts = [o.company_name ?? o.company, o.ceo && `대표 ${o.ceo}`, o.business_no && `사업자등록번호 ${o.business_no}`,
    o.mail_order_no && `통신판매업 신고 ${o.mail_order_no}`, o.address, o.phone && `전화 ${o.phone}`, o.email && `이메일 ${o.email}`,
    o.hosting && `호스팅 ${o.hosting}`].filter(Boolean);
  if (parts.length < 2) return null;
  return <p className="mx-auto mt-3 max-w-2xl px-4 leading-relaxed">{parts.join(" · ")}</p>;
}

/** PC 앱 안(plan/62)의 로그인·가입 화면에서도 문 밖의 링크(약관 등)는 브라우저가 연다. */
function AppLinks() {
  useEffect(() => (inAppShell() ? interceptLinks(currentDoor()) : undefined), []);
  return null;
}

export function MarketingShell({ children }: { children: React.ReactNode }) {
  const locale = useBrowserLocale();
  return (
    <LocaleProvider locale={locale}>
      <div className="min-h-dvh flex flex-col">
        <AppLinks />
        <Header />
        <main className="flex-1">{children}</main>
        <Footer />
      </div>
    </LocaleProvider>
  );
}
