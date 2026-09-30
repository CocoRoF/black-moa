"use client";
import { useSearchParams } from "next/navigation";
import { CompanyHome } from "./CompanyHome";
import { CompanySearch } from "./CompanySearch";

/** One route, two screens: the dashboard, or — once there is a query — the results. */
export function CompaniesEntry() {
  const params = useSearchParams();
  const q = params.get("q");
  if (q === null) return <CompanyHome />;
  return <CompanySearch q={q} initialTab={params.get("tab") ?? undefined} />;
}
