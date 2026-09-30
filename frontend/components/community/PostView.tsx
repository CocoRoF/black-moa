"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Eye, Flag, MessageCircle, MoreHorizontal, ThumbsUp, Trash2 } from "@/components/icons";
import { Community, type CommunityComment } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { fmtNumber, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Avatar } from "@/components/ui/misc";
import { Face } from "@/components/profile/Face";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/empty";
import { DropdownMenu } from "@/components/ui/dropdown";
import { Segmented } from "@/components/ui/tabs";
import { BoardIcon } from "@/components/icons";
import { ConfirmDialog } from "@/components/ui/dialog";

/** One comment box, used both at the top of the thread and inline under a reply target. */
function Composer({ value, onChange, onSubmit, pending, placeholder, submitLabel, autoFocus, onCancel, cancelLabel }: {
  value: string; onChange: (v: string) => void; onSubmit: () => void; pending: boolean;
  placeholder: string; submitLabel: string; autoFocus?: boolean; onCancel?: () => void; cancelLabel?: string;
}) {
  return (
    <form className={cn("rounded-2xl border bg-card p-3", onCancel ? "border-accent/40" : "border-border")}
      onSubmit={(e) => { e.preventDefault(); if (value.trim()) onSubmit(); }}>
      <Textarea value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
                className="min-h-[76px]" maxLength={5000} autoFocus={autoFocus} />
      <div className="mt-2 flex justify-end gap-2">
        {onCancel ? <Button type="button" size="sm" variant="ghost" onClick={onCancel}>{cancelLabel}</Button> : null}
        <Button type="submit" size="sm" variant="accent" loading={pending} disabled={!value.trim()}>{submitLabel}</Button>
      </div>
    </form>
  );
}

export function PostView({ id }: { id: string }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient(); const router = useRouter();
  const [sort, setSort] = useState<"new" | "top">("new");
  const [body, setBody] = useState("");
  const [replyTo, setReplyTo] = useState<CommunityComment | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const post = useQuery({ queryKey: ["c", "post", id], queryFn: () => Community.post(id) });
  const comments = useQuery({ queryKey: ["c", "comments", id, sort], queryFn: () => Community.comments(id, sort) });
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["c", "post", id] }); qc.invalidateQueries({ queryKey: ["c", "comments", id] }); qc.invalidateQueries({ queryKey: ["c", "posts"] }); };

  const like = useMutation({ mutationFn: () => Community.like("posts", id), onSuccess: () => invalidate(), onError: (e) => toast.error(friendlyError(e, locale)) });
  const likeComment = useMutation({ mutationFn: (cid: string) => Community.like("comments", cid), onSuccess: () => invalidate() });
  const addComment = useMutation({
    mutationFn: () => Community.addComment(id, { body: body.trim(), parent_id: replyTo?.id ?? null }),
    onSuccess: () => { setBody(""); setReplyTo(null); invalidate(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const removeComment = useMutation({ mutationFn: (cid: string) => Community.removeComment(cid), onSuccess: () => invalidate() });
  const removePost = useMutation({
    mutationFn: () => Community.removePost(id),
    onSuccess: () => { toast.success(t("com.deleted")); qc.invalidateQueries({ queryKey: ["c", "posts"] }); router.replace("/app/community"); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const report = useMutation({
    mutationFn: (target: { kind: "posts" | "comments"; tid: string }) => Community.report(target.kind, target.tid, "abuse"),
    onSuccess: () => toast.success(t("com.reported")),
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  if (post.isLoading) return <Page><Skeleton className="h-64" /></Page>;
  if (post.error || !post.data) return <Page><ErrorState message={friendlyError(post.error, locale)} onRetry={() => post.refetch()} retryLabel={t("common.retry")} /></Page>;
  const p = post.data;
  const mine = !!p.author?.is_me;

  return (
    <Page>
      <Link href={p.board ? `/app/community/b/${p.board.slug}` : "/app/community"} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-fg hover:text-fg">
        <ArrowLeft className="h-4 w-4" />{p.board ? <span className="inline-flex items-center gap-1.5"><BoardIcon name={p.board.icon} className="h-4 w-4" />{p.board.name}</span> : t("com.title")}
      </Link>

      <article className="rounded-2xl border border-border bg-card p-5">
        <h1 className="text-xl font-semibold tracking-tight">{p.title}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-fg">
          {p.author ? (
            // A byline stands alone: a face beside a chosen name reads as a person.
            <Face id={p.author.pen_name ? "" : p.author.id} className="inline-flex items-center gap-2">
              {p.author.pen_name ? null : <Avatar name={p.author.name} src={p.author.avatar_url} size={26} />}
              <span><span className="font-medium text-fg">{p.author.name}</span>{p.author.job ? <span className="text-muted-fg"> | {p.author.job}</span> : null}</span>
            </Face>
          ) : null}
          <span>{fmtRelative(p.created_at, locale)}</span>
          {p.edited_at ? <span>· {t("com.edited")}</span> : null}
          <span className="inline-flex items-center gap-1"><Eye className="h-3.5 w-3.5" />{fmtNumber(p.view_count)}</span>
          <span className="ml-auto">
            <DropdownMenu trigger={<Button variant="ghost" size="icon-sm" aria-label={t("common.more")}><MoreHorizontal className="h-4 w-4" /></Button>}
              items={[
                ...(mine ? [{ key: "edit", label: t("common.edit"), onSelect: () => router.push(`/app/community/write?edit=${p.id}`) },
                            { key: "del", label: t("common.delete"), icon: <Trash2 />, danger: true, onSelect: () => setConfirmDelete(true) }]
                        : [{ key: "report", label: t("com.report"), icon: <Flag />, onSelect: () => report.mutate({ kind: "posts", tid: p.id }) }]),
              ]} />
          </span>
        </div>

        <div className="mt-4 whitespace-pre-wrap break-words text-[15px] leading-relaxed">{p.body}</div>
        {p.images?.length ? (
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            {p.images.map((src) => (
              // eslint-disable-next-line @next/next/no-img-element
              <a key={src} href={src} target="_blank" rel="noopener noreferrer">
                <img src={src} alt="" className="w-full rounded-xl border border-border object-cover" loading="lazy" />
              </a>
            ))}
          </div>
        ) : null}

        <div className="mt-5 flex items-center gap-2">
          {/* Liked is a state, not a call to action: a saturated fill shouts louder than
              the post it sits under, so the mark is a tint and a filled glyph. */}
          <Button variant="outline" size="sm" loading={like.isPending} onClick={() => like.mutate()}
            aria-pressed={p.liked}
            className={cn(p.liked && "border-accent/35 bg-accent/10 text-accent hover:bg-accent/15")}>
            <ThumbsUp className={cn("h-4 w-4", p.liked && "fill-current")} />{fmtNumber(p.like_count)}
          </Button>
          <span className="inline-flex items-center gap-1 text-sm text-muted-fg"><MessageCircle className="h-4 w-4" />{fmtNumber(p.comment_count)}</span>
        </div>
      </article>

      <section className="mt-5">
        <div className="mb-2 flex items-center gap-2">
          <h2 className="text-sm font-semibold">{t("com.comments")} {fmtNumber(p.comment_count)}</h2>
          <Segmented className="ml-auto" size="sm" value={sort} onChange={setSort} ariaLabel={t("com.sort")}
            options={[{ value: "new", label: t("com.oldest") }, { value: "top", label: t("com.best") }]} />
        </div>

        {/* The box for a new top-level comment. A reply gets its own box under the comment
            it answers — see below — because a composer at the top of the page cannot show
            where the reply is about to land. */}
        {!replyTo ? (
          <Composer value={body} onChange={setBody} onSubmit={() => addComment.mutate()} pending={addComment.isPending}
                    placeholder={t("com.comment_ph")} submitLabel={t("com.comment_submit")} />
        ) : null}

        <div className="mt-3 space-y-2">
          {comments.isLoading ? <Skeleton className="h-20" /> : (comments.data?.items ?? []).map((c) => (
            <div key={c.id} className={cn(c.depth > 0 && "ml-6 sm:ml-10")}>
            <div className="rounded-2xl border border-border bg-card p-3">
              <div className="flex items-center gap-2 text-xs text-muted-fg">
                {c.author ? (
                  <Face id={c.author.pen_name ? "" : c.author.id} className="inline-flex items-center gap-1.5">
                    {c.author.pen_name ? null : <Avatar name={c.author.name} src={c.author.avatar_url} size={20} />}
                    <span className="font-medium text-fg/90">{c.author.name}</span>
                    {c.author.job ? <span>| {c.author.job}</span> : null}
                  </Face>
                ) : null}
                <span>{fmtRelative(c.created_at, locale)}</span>
                {!c.deleted ? (
                  <span className="ml-auto flex items-center gap-1">
                    <button type="button" onClick={() => likeComment.mutate(c.id)} className={cn("inline-flex items-center gap-1 rounded-full px-2 py-1 hover:bg-muted", c.liked && "text-accent")}>
                      <ThumbsUp className={cn("h-3.5 w-3.5", c.liked && "fill-current")} />{c.like_count || ""}
                    </button>
                    {c.depth < 2 ? <button type="button" aria-expanded={replyTo?.id === c.id}
                      className={cn("rounded-full px-2 py-1 hover:bg-muted", replyTo?.id === c.id && "bg-muted text-fg")}
                      onClick={() => { setReplyTo(replyTo?.id === c.id ? null : c); setBody(""); }}>{t("com.reply")}</button> : null}
                    {c.author?.is_me
                      ? <button type="button" className="rounded-full px-2 py-1 text-danger hover:bg-muted" onClick={() => removeComment.mutate(c.id)}>{t("common.delete")}</button>
                      : <button type="button" className="rounded-full px-2 py-1 hover:bg-muted" onClick={() => report.mutate({ kind: "comments", tid: c.id })}>{t("com.report")}</button>}
                  </span>
                ) : null}
              </div>
              {/* A removed comment keeps its place so the replies under it still make sense. */}
              <p className={cn("mt-1.5 whitespace-pre-wrap break-words text-sm", c.deleted && "italic text-muted-fg")}>
                {c.deleted ? t("com.comment_deleted") : c.body}
              </p>
            </div>
            {replyTo?.id === c.id ? (
              <div className="ml-6 mt-1.5 sm:ml-10">
                <Composer value={body} onChange={setBody} onSubmit={() => addComment.mutate()} pending={addComment.isPending}
                          placeholder={t("com.reply_ph", { name: c.author?.name ?? "" })} submitLabel={t("com.reply")}
                          autoFocus onCancel={() => { setReplyTo(null); setBody(""); }} cancelLabel={t("common.cancel")} />
              </div>
            ) : null}
            </div>
          ))}
        </div>
      </section>

      <ConfirmDialog open={confirmDelete} onClose={() => setConfirmDelete(false)} onConfirm={() => removePost.mutate()}
        title={t("com.delete_title")} description={t("com.delete_desc")} confirmLabel={t("common.delete")}
        cancelLabel={t("common.cancel")} danger loading={removePost.isPending} />
    </Page>
  );
}
