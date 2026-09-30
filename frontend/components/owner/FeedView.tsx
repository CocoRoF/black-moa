"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Newspaper, UserPlus } from "@/components/icons";
import { Feed, type FeedItem, type Suggestion } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Page } from "./Shell";
import { buttonLook } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Avatar, PageHeader } from "@/components/ui/misc";
import { Composer } from "@/components/feed/Composer";
import { PostModal } from "@/components/feed/PostModal";
import { PostCard } from "@/components/feed/PostCard";
import { Face } from "@/components/profile/Face";
import { ConnectionControl, statusOf } from "@/components/network/Connection";
import { usePostActions } from "@/components/feed/PostActions";

/** 소식 (plan/42).
 *
 *  Everything here comes from somebody this person chose. The community is a different
 *  room and never appears: it is where you go for an answer, this is where you come to see
 *  people you know. A quiet page is answered with people to follow, not with writing from
 *  strangers.
 */
export function FeedPage() {
  const t = useT();
  const q = useInfiniteQuery({
    queryKey: ["feed"],
    queryFn: ({ pageParam }) => Feed.list(pageParam as string | undefined),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.cursor ?? undefined,
  });
  const pages = q.data?.pages ?? [];
  const server = pages.flatMap((p) => p.items);
  const suggestions = pages[0]?.suggestions ?? [];
  // What a like or a reply did, kept over the server's copy so opening a post and closing
  // it again does not roll the count back.
  const [patch, setPatch] = useState<Record<string, Partial<FeedItem>>>({});
  const items = server.map((i) => ({ ...i, ...(patch[i.id] ?? {}) }) as FeedItem);
  const [openId, setOpenId] = useState<string | null>(null);
  const open = items.find((i) => i.id === openId) ?? null;
  const change = (id: string, p: Partial<FeedItem>) => setPatch((x) => ({ ...x, [id]: { ...(x[id] ?? {}), ...p } }));
  const again = () => { setOpenId(null); setPatch({}); void q.refetch(); };
  const acts = usePostActions(again);

  const foot = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = foot.current;
    if (!el || !q.hasNextPage) return;
    const io = new IntersectionObserver((es) => {
      if (es[0]?.isIntersecting && !q.isFetchingNextPage) void q.fetchNextPage();
    }, { rootMargin: "400px" });
    io.observe(el);
    return () => io.disconnect();
  }, [q.hasNextPage, q.isFetchingNextPage, q, items.length]);

  return (
    <Page>
      <div className="mx-auto w-full max-w-[560px]">
        <PageHeader title={t("nav.feed")} description={t("feed.desc")} />
        <Composer onPosted={() => { setPatch({}); void q.refetch(); }} />
        {q.isLoading ? (
          <div className="mt-4 space-y-4"><Skeleton className="h-80" /><Skeleton className="h-80" /></div>
        ) : items.length ? (
          <ul className="mt-4 space-y-4">
            {items.map((i) => (
              <li key={i.id}>
                <PostCard item={i} onOpen={() => setOpenId(i.id)} onChanged={(p) => change(i.id, p)} menu={acts.menuFor(i)} />
              </li>
            ))}
          </ul>
        ) : suggestions.length ? (
          <Suggestions people={suggestions} />
        ) : (
          <EmptyState icon={<Newspaper />} title={t("feed.empty")} description={t("feed.empty_desc")}
                      action={<Link href="/app/network" className={buttonLook("accent", "md")}><UserPlus className="h-4 w-4" />{t("feed.find_people")}</Link>} />
        )}
        <div ref={foot} className="h-10" />
        {q.isFetchingNextPage ? <Skeleton className="h-40" /> : null}
      </div>
      <PostModal item={open} onClose={() => setOpenId(null)} onChanged={(p) => open && change(open.id, p)} onGone={again} />
      {acts.dialogs}
    </Page>
  );
}

/** A quiet page means nobody chosen yet, so it offers people rather than filling itself
 *  with writing from strangers (plan/42 §2). */
function Suggestions({ people }: { people: Suggestion[] }) {
  const t = useT();
  // 연결하면 Connection.applyLink 가 피드를 다시 받는다 — 연결한 사람은 제안에서 빠진다.
  return (
    <section className="mt-4 rounded-2xl border border-border bg-card p-4 shadow-soft">
      <h2 className="text-sm font-semibold">{t("net.suggest_title")}</h2>
      <p className="mt-0.5 text-xs text-muted-fg">{t("feed.suggest_desc")}</p>
      <ul className="mt-3 divide-y divide-border">
        {people.map((p) => (
          <li key={p.id} className="flex items-center gap-3 py-2.5">
            <Face id={p.id}><Avatar name={p.display_name} src={p.avatar_url} size={40} /></Face>
            <div className="min-w-0 flex-1">
              <Face id={p.id} className="block truncate text-sm font-medium hover:underline">{p.display_name}</Face>
              <span className="block truncate text-xs text-muted-fg">
                {p.reason === "connected_me" ? t("net.why_connected_me") : t("net.why_guest")}
              </span>
            </div>
            <ConnectionControl userId={p.id} name={p.display_name} known={statusOf(p.link)} showState={false} />
          </li>
        ))}
      </ul>
      <Link href="/app/network" className="mt-3 block text-center text-xs text-accent hover:underline">{t("feed.find_people")}</Link>
    </section>
  );
}
