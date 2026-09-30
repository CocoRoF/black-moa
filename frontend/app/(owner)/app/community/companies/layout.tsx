import type { ReactNode } from "react";
import { CompaniesGate } from "@/components/company/CompaniesGate";

export default function Layout({ children }: { children: ReactNode }) {
  return <CompaniesGate>{children}</CompaniesGate>;
}
