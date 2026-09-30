import { Suspense } from "react";
import { CompanyCompare } from "@/components/company/CompanyCompare";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <CompanyCompare />
    </Suspense>
  );
}
