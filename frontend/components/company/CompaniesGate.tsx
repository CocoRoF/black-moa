"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import { Building2 } from "@/components/icons";
import { EmptyState } from "@/components/ui/empty";
import { buttonLook } from "@/components/ui/button";
import { useCompanyFeatures } from "@/lib/hooks";
import { useT } from "@/lib/i18n";

/** 기업 페이지와 채용공고의 문 (plan/71). 관리자가 기업 기능을 끄면 주소로 들어와도 닫혀 있다 — 서버도 요청을 받지 않는다. */
export function CompaniesGate({ children }: { children: ReactNode }) {
  const t = useT();
  const { on, ready } = useCompanyFeatures();
  if (!ready) return null;
  if (!on) {
    return (
      <div className="mx-auto w-full max-w-xl px-4 py-16">
        <EmptyState icon={<Building2 />} title={t("co.off_title")} description={t("co.off_desc")}
                    action={<Link href="/app/community" className={buttonLook("outline", "sm")}>{t("co.off_back")}</Link>} />
      </div>
    );
  }
  return <>{children}</>;
}
