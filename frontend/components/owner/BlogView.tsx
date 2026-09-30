"use client";
import { useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { PenLine, Plus } from "@/components/icons";
import { Blog, type FeedItem } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Page } from "./Shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { PageHeader } from "@/components/ui/misc";
import { PostCard } from "@/components/feed/PostCard";
import { PostEditor } from "@/components/feed/Composer";
import { usePostActions } from "@/components/feed/PostActions";
import { PostModal } from "@/components/feed/PostModal";
import { Pages } from "@/components/ui/pages";


/** My blog (plan/41 §4).
 *
 *  Writing here does two things: the post goes up at my own address, and a public post
 *  becomes material my secretary can answer visitors from. The screen says so, because a
 *  person deciding between "누구나" and "친구에게만" is also deciding what their secretary
 *  is allowed to repeat.
 */
export function BlogPage() {
  const t = useT(); const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ["blog", page], queryFn: () => Blog.list(page), placeholderData: keepPreviousData });
  const [writing, setWriting] = useState(false);
  const [read, setRead] = useState<string | null>(null);
  const [patch, setPatch] = useState<Record<string, Partial<FeedItem>>>({});
  const posts = (q.data?.items ?? []).map((p) => ({ ...p, ...(patch[p.id] ?? {}) }));
  const change = (id: string, p: Partial<FeedItem>) => setPatch((s) => ({ ...s, [id]: { ...(s[id] ?? {}), ...p } }));
  const again = () => { setRead(null); setPatch({}); void qc.invalidateQueries({ queryKey: ["blog"] }); };
  const acts = usePostActions(again);

  return (
    <Page>
      <div className="mx-auto w-full max-w-[560px]">
        <PageHeader title={t("nav.blog")} description={t("blog.desc")}
                    action={<Button variant="accent" onClick={() => setWriting(true)}><Plus className="h-4 w-4" />{t("blog.new")}</Button>} />
        {q.isLoading ? <Skeleton className="h-48" /> : !posts.length ? (
          <EmptyState icon={<PenLine />} title={t("blog.empty")} description={t("blog.empty_desc")}
                      action={<Button variant="accent" onClick={() => setWriting(true)}>{t("blog.new")}</Button>} />
        ) : (
          /* My own writing is the same thing 소식 shows, so it is the same card. What this
             shelf says that 소식 does not is whether a post is up yet. */
          <ul className="space-y-4">
            {posts.map((p) => (
              <li key={p.id}>
                <PostCard item={p} onOpen={() => setRead(p.id)} onChanged={(x) => change(p.id, x)} menu={acts.menuFor(p)}
                          tags={p.status === "published" ? <span /> : <Badge tone="neutral">{t("blog.status_draft")}</Badge>} />
              </li>
            ))}
          </ul>
        )}
        <Pages page={q.data?.page ?? 1} pages={q.data?.pages ?? 1} onGo={setPage} />
      </div>
      {read ? (
        <PostModal postId={read} onClose={() => setRead(null)} onChanged={(x) => change(read, x)} onGone={again} />
      ) : null}
      {acts.dialogs}
      {/* One writing surface. The blog used to have a second one that could not hold a
          photo or name anybody, and two of anything drift apart. */}
      <PostEditor open={writing} kind="article" onClose={() => setWriting(false)}
                  onSaved={() => { setWriting(false); again(); }} />
    </Page>
  );
}
