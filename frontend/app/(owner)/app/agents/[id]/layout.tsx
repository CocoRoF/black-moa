import { AgentLayout } from "@/components/agent/AgentLayout";
export default async function Layout({ children, params }: { children: React.ReactNode; params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AgentLayout id={id}>{children}</AgentLayout>;
}
