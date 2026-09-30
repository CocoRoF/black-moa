import { ReviewForm } from "@/components/company/ReviewForm";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReviewForm id={id} />;
}
