import type { Metadata } from "next";
import { LegalDoc, fetchLegal } from "@/components/marketing/Legal";

// 관리자가 운영자 정보나 본문을 바꾸면 바로 보여야 한다.
export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  const d = await fetchLegal();
  return { title: `개인정보 처리방침 · ${d?.service ?? "black-moa"}`, description: `${d?.service ?? "black-moa"} 개인정보 처리방침 (시행일 ${d?.effective_date ?? ""})` };
}

export default async function Page() {
  return <LegalDoc kind="privacy" data={await fetchLegal()} />;
}
