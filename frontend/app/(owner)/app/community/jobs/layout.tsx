import type { ReactNode } from "react";
import { CompaniesGate } from "@/components/company/CompaniesGate";

/** 채용공고는 기업정보와 함께 켜지고 꺼진다 (plan/71). */
export default function Layout({ children }: { children: ReactNode }) {
  return <CompaniesGate>{children}</CompaniesGate>;
}
