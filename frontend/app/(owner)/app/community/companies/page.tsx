import { Suspense } from "react";
import { CompaniesEntry } from "@/components/company/CompaniesEntry";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <CompaniesEntry />
    </Suspense>
  );
}
