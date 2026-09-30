import { Suspense } from "react";
import { CompanyPage } from "@/components/company/CompanyPage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense fallback={null}>
      <CompanyPage id={id} />
    </Suspense>
  );
}
