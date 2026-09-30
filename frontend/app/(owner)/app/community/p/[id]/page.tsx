import { PostView } from "@/components/community/PostView";
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PostView id={id} />;
}
