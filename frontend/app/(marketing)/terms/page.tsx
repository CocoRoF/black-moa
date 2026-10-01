import type { Metadata } from "next";
import { LegalDoc, fetchLegal } from "@/components/marketing/Legal";

// 관리자가 운영자 정보나 본문을 바꾸면 바로 보여야 한다.
export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  const d = await fetchLegal();
  return { title: `이용약관 · ${d?.service ?? "black-moa"}`, description: `${d?.service ?? "black-moa"} 이용약관 (시행일 ${d?.effective_date ?? ""})` };
}

export default async function Page() {
  return <LegalDoc kind="terms" data={await fetchLegal()} />;
}
