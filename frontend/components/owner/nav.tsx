"use client";
import { usePathname } from "next/navigation";
import { useCallback, useMemo, type ReactNode } from "react";
import { Briefcase, Building2, Home, PenLine } from "@/components/icons";
import { useCompanyFeatures } from "@/lib/hooks";

/** 웹의 틀(Shell)과 PC 앱 안의 틀(AppFrame)이 함께 쓰는 자리 목록. */
export interface NavItem { href: string; key: string; icon: ReactNode; exact?: boolean }

export const COMMUNITY_NAV: NavItem[] = [
  { href: "/app/community", key: "cnav.home", icon: <Home />, exact: true },
  { href: "/app/community/jobs", key: "cnav.jobs", icon: <Briefcase /> },
  { href: "/app/community/companies", key: "cnav.companies", icon: <Building2 /> },
  { href: "/app/community/mine", key: "cnav.mine", icon: <PenLine /> },
];

/** 기업 기능에 딸린 탭 — 채용공고와 기업정보는 함께 켜지고 꺼진다 (plan/71). */
const COMPANY_TABS = new Set(["/app/community/jobs", "/app/community/companies"]);

/** 광장의 탭 — 관리자가 기업 기능을 끄면 [채용공고]·[기업정보] 가 없다 (plan/71). */
export function useCommunityNav(): NavItem[] {
  const { on } = useCompanyFeatures();
  return useMemo(() => (on ? COMMUNITY_NAV : COMMUNITY_NAV.filter((n) => !COMPANY_TABS.has(n.href))), [on]);
}

export function useIsActive() {
  const path = usePathname();
  return useCallback((href: string, exact?: boolean) => (exact ? path === href : path === href || path.startsWith(href + "/")), [path]);
}
