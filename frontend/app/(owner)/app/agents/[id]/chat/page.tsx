import { redirect } from "next/navigation";

/** The chat moved out of the agent tabs into /app/chat. Old links, bookmarks and the
 *  conversation deep-links keep working by redirecting with the agent preselected. */
export default async function AgentChatRedirect({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const c = typeof sp.c === "string" ? sp.c : undefined;
  redirect(`/app/chat?a=${id}${c ? `&c=${c}` : ""}`);
}
