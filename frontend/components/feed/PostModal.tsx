"use client";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { MoreHorizontal, PenLine, Send, Trash2, X } from "@/components/icons";
import { Blog, Feed, type FeedItem, type PostComment } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { confirm } from "@/lib/confirm";
import { fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar } from "@/components/ui/misc";
import { Dialog } from "@/components/ui/dialog";
import { DropdownMenu } from "@/components/ui/dropdown";
import { PostEditor } from "./Composer";
//: 댓글은 오백 자. 피드는 [사진 + 짧은 글]이고 그 아래 달리는 말도 같은 크기다 (plan/42 §4).
const MAX_COMMENT = 500;
import { Actions, Caption, Counts, Photos, Rule } from "./parts";
import { Face } from "@/components/profile/Face";

/** One post, opened where you were (plan/42 §12).
 *
 *  Reading a post used to mean a link out to another tab, which is leaving the feed to see
 *  something that was already on it. The photo takes the room it needs and the conversation
 *  runs beside it, in the order the card already reads in: what you can do, what everyone
 *  did, then what it says and everything said back.
 *
 *  It opens either from a card that already has the post, or from an id alone: a tile in
 *  somebody's grid, a row in my own blog. Both end up here, so a post is read the same way
 *  wherever it was pressed.
 *
 *  Either way the whole post is fetched. A card carries only what a card draws, and this
 *  window draws everything: a long article's body, the upload ids editing it takes. The
 *  card it was opened from stands in until that arrives, so nothing blinks.
 */
export function PostModal({ item, postId, onClose, onChanged, onGone, focusCommentId, notice, onSent }: {
  item?: FeedItem | null;
  /** Open by id when the screen that opened it has only that. */
  postId?: string | null;
  onClose: () => void;
  onChanged: (patch: Partial<FeedItem>) => void;
  /** The post was changed or taken down: whoever listed it has to look again. */
  onGone?: () => void;
  /** 인박스의 댓글 소식에서 열었다(plan/70): 그 댓글을 짚어 보이고, 입력칸은 그 댓글에 다는 답글이 된다. */
  focusCommentId?: string | null;
  /** 머리 아래에 붙는 한 줄(무슨 소식으로 열었는지, 보관). */
  notice?: ReactNode;
  /** 댓글·답글을 달았다. */
  onSent?: () => void;
}) {
  const t = useT(); const locale = useLocale();
  const want = item?.id ?? postId ?? "";
  const fetched = useQuery({ queryKey: ["feed", "post", want], queryFn: () => Feed.one(want), enabled: !!want });
  //: The fetched post wins; the card stands in while it is on its way.
  const post = fetched.data ?? item ?? null;
  const whole = !!fetched.data;

  const [rows, setRows] = useState<PostComment[]>([]);
  const [loading, setLoading] = useState(false);
  //: Whether the conversation has arrived at all, as opposed to being empty.
  const [ready, setReady] = useState(false);
  const [text, setText] = useState("");
  //: Which comment the box is answering, if any.
  const [to, setTo] = useState<PostComment | null>(null);
  const [editing, setEditing] = useState(false);
  const box = useRef<HTMLTextAreaElement | null>(null);

  const load = useCallback(async (id: string) => {
    setLoading(true);
    try { setRows((await Blog.comments(id)).items); setReady(true); }
    catch (e) { toast.error(friendlyError(e, locale)); }
    finally { setLoading(false); }
  }, [locale]);

  const id = post?.id ?? "";
  useEffect(() => {
    if (!id) { setRows([]); setText(""); setTo(null); setReady(false); return; }
    setText(""); setTo(null); setReady(false);
    void load(id);
  }, [id, load]);

  // Roots in the order they were written, each carrying whatever answered it. A reply
  // whose root fell outside the window stands on its own rather than vanishing: a long
  // thread loses its beginning, and what is left has to still be all there.
  const threads = useMemo(() => {
    const here = new Set(rows.map((c) => c.id));
    const kids = new Map<string, PostComment[]>();
    for (const c of rows) {
      if (!c.parent_id || !here.has(c.parent_id)) continue;
      kids.set(c.parent_id, [...(kids.get(c.parent_id) ?? []), c]);
    }
    return rows.filter((c) => !c.parent_id || !here.has(c.parent_id))
               .map((c) => ({ root: c, replies: kids.get(c.id) ?? [] }));
  }, [rows]);

  const like = useMutation({
    mutationFn: (on: boolean) => Blog.like(id, on),
    onSuccess: (r) => onChanged({ liked: r.liked, like_count: r.like_count }),
    onError: (e) => { if (post) onChanged({ liked: post.liked, like_count: post.like_count }); toast.error(friendlyError(e, locale)); },
  });
  // 소식에서 짚은 댓글: 불러오면 그 자리로 옮겨 보이고, 입력칸이 그 댓글의 답글이 된다.
  const focused = useRef<string | null>(null);
  useEffect(() => {
    if (!ready || !focusCommentId || focused.current === focusCommentId) return;
    const c = rows.find((x) => x.id === focusCommentId);
    if (!c) return;
    focused.current = focusCommentId;
    setTo(c);
    requestAnimationFrame(() => document.querySelector(`[data-comment-id="${focusCommentId}"]`)?.scrollIntoView({ block: "center" }));
  }, [ready, rows, focusCommentId]);
  const send = useMutation({
    mutationFn: () => Blog.comment(id, text.trim(), to?.id ?? null),
    onSuccess: (c) => { setRows((p) => [...p, c]); setText(""); setTo(null); onChanged({ comment_count: rows.length + 1 }); onSent?.(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const drop = useMutation({
    mutationFn: (cid: string) => Blog.removeComment(id, cid),
    onSuccess: (r, cid) => {
      const gone = new Set([cid, ...rows.filter((x) => x.parent_id === cid).map((x) => x.id)]);
      setRows((p) => p.filter((x) => !gone.has(x.id)));
      onChanged({ comment_count: Math.max(0, rows.length - (r.removed ?? gone.size)) });
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const remove = useMutation({
    mutationFn: () => Blog.remove(id),
    onSuccess: () => { toast.success(t("blog.removed")); onGone?.(); onClose(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  const answer = (c: PostComment) => { setTo(c); box.current?.focus(); };

  // Nothing was asked for: the feed keeps this mounted with no post open.
  if (!want) return null;
  if (!post && fetched.isLoading) {
    return <Dialog open onClose={onClose} size="md" bare><Skeleton className="h-64" /></Dialog>;
  }
  // Taken down, or never mine to read. A notice about it stays in the inbox after the post
  // is gone, and pressing it has to say so rather than do nothing.
  if (!post) {
    return (
      <Dialog open onClose={onClose} size="md" title={t("feed.post_title")}>
        {notice ? <div className="-mx-1 mb-2 rounded-lg bg-muted/40 px-3 py-2 text-xs">{notice}</div> : null}
        <p className="py-6 text-center text-sm text-muted-fg">{t("feed.post_gone")}</p>
      </Dialog>
    );
  }
  const caption = post.kind === "note" ? (post.body ?? "") : "";
  const wide = post.images.length > 0;
  return (
    <>
    {/* While the editor is up the post steps aside: two windows stacked gave two close
        buttons, and the lower one shut the thing behind. */}
    <Dialog open={!editing} onClose={onClose} size={wide ? "xl" : "md"} bare>
      <div className={cn("grid h-full min-h-0", wide ? "sm:grid-cols-[minmax(0,1fr)_360px]" : "")}>
        {wide ? (
          <div className="flex min-h-0 items-center justify-center bg-fg/90">
            <Photos urls={post.images} fit="ratio" className="max-h-[38vh] w-full overflow-hidden sm:max-h-[86dvh]" />
          </div>
        ) : null}

        <div className="flex min-h-0 flex-col sm:border-l sm:border-border">
          <header className="flex shrink-0 items-center gap-2.5 border-b border-border px-4 py-3">
            <Face id={post.author.id}><Avatar name={post.author.name} src={post.author.avatar_url} size={34} /></Face>
            <div className="min-w-0 flex-1 text-sm">
              <div className="truncate"><Face id={post.author.id} className="font-medium hover:underline">{post.author.name}</Face></div>
              <div className="truncate text-[11px] text-muted-fg">
                {post.at ? fmtRelative(post.at, locale) : t("blog.not_published")}{post.author.handle ? ` · @${post.author.handle}` : ""}
              </div>
            </div>
            {post.visibility !== "public" ? <Badge tone="neutral">{t(`blog.vis_${post.visibility}`)}</Badge> : null}
            {/* My own post: the same menu the card carries, in the same corner, so the two
                are one gesture and not two things to learn. */}
            {post.can_edit && whole ? (
              <DropdownMenu align="end" items={[
                { key: "edit", label: t("common.edit"), icon: <PenLine />, onSelect: () => setEditing(true) },
                { key: "remove", label: t("common.delete"), icon: <Trash2 />, danger: true,
                  onSelect: async () => { if (await confirm({ title: t("blog.remove_q"), danger: true })) remove.mutate(); } },
              ]} trigger={
                <button type="button" aria-label={t("common.more")}
                        className="-mr-1 rounded-lg p-2 text-muted-fg hover:bg-muted hover:text-fg">
                  <MoreHorizontal className="h-5 w-5" />
                </button>} />
            ) : null}
          </header>

          {notice ? <div className="shrink-0 border-b border-border bg-muted/40 px-4 py-2 text-xs">{notice}</div> : null}
          {/* Pinned, so the two numbers and the two buttons stay put however long the
              conversation under them gets. */}
          <div className="shrink-0">
            <Actions liked={post.liked} onLike={() => like.mutate(!post.liked)}
                     onComment={() => box.current?.focus()} />
            {/* The post's own count until the conversation is here: a tally that starts at
                zero and jumps says the post had no replies, which is not what happened. */}
            <Counts likes={post.like_count} comments={ready ? rows.length : post.comment_count} />
            <Rule />
          </div>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3.5 scrollbar-thin">
            {post.kind === "article" ? (
              <div>
                <h2 className="text-[15px] font-semibold">{post.title}</h2>
                {/* The excerpt is a card's line. Showing it here would be opening a post
                    and being handed its first hundred words. */}
                {whole ? <p className="mt-1 whitespace-pre-wrap text-sm text-muted-fg">{post.body}</p>
                       : <Skeleton className="mt-2 h-20" />}
              </div>
            ) : caption ? (
              // Who wrote it is in the header, one line above. Saying it again with a
              // second copy of their face is the same fact three times.
              <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
                <Caption text={caption} mentions={post.mentions} />
              </p>
            ) : null}

            {loading ? <Skeleton className="h-16" /> : threads.map(({ root, replies }) => (
              <div key={root.id} className="space-y-3">
                <Line c={root} focus={root.id === focusCommentId} onReply={() => answer(root)} onDrop={() => drop.mutate(root.id)} />
                {replies.length ? (
                  // Indented once and never again: an answer to an answer joins this same
                  // column, so a long argument still fits on a phone.
                  <div className="space-y-3 border-l border-border/60 pl-3.5 ml-3.5">
                    {replies.map((r) => (
                      // 답글에 답하면 화면에는 그 사람 이름이 뜨고, 들어가는 자리는 이
                      // 실타래다. 이름만 원댓글 사람으로 바꿔 두면 화면이 거짓말을 한다.
                      <Line key={r.id} c={r} small focus={r.id === focusCommentId} onReply={() => answer(r)} onDrop={() => drop.mutate(r.id)} />
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
            {!loading && !rows.length && !caption && post.kind !== "article"
              ? <p className="py-6 text-center text-sm text-muted-fg">{t("feed.no_comments")}</p> : null}
          </div>

          <footer className="shrink-0 border-t border-border">
            {to ? (
              <div className="flex items-center gap-2 border-b border-border/60 px-4 py-1.5 text-[11px] text-muted-fg">
                <span className="truncate">{t("feed.reply_to", { name: to.author.name })}</span>
                <button type="button" aria-label={t("common.cancel")} onClick={() => setTo(null)}
                        className="ml-auto rounded p-1 hover:bg-muted hover:text-fg"><X className="h-3.5 w-3.5" /></button>
              </div>
            ) : null}
            <div className="flex items-end gap-2 px-4 py-2.5">
              <textarea ref={box} value={text} onChange={(e) => setText(e.target.value)}
                        placeholder={t(to ? "feed.reply_ph" : "feed.comment_ph")}
                        rows={1} maxLength={MAX_COMMENT}
                        // 한글을 치는 중의 Enter 는 글자를 확정하는 Enter 다. 그걸 전송으로
                        // 받으면 쓰다 만 댓글이 올라간다. 그리고 보내는 중에는 다시 보내지
                        // 않는다: Enter 를 두 번 누른 사람은 댓글을 두 개 쓴 것이 아니다.
                        onKeyDown={(e) => {
                          if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
                          e.preventDefault();
                          if (text.trim() && !send.isPending) send.mutate();
                        }}
                        className="max-h-24 min-h-[36px] flex-1 resize-none bg-transparent py-1.5 text-sm leading-relaxed text-fg outline-none placeholder:text-muted-fg/70" />
              {/* 끝이 가까워졌을 때만 센다. 한 줄 적는 자리가 글자 수를 재는 자리가 되면 안 된다. */}
              {text.length > MAX_COMMENT - 60 ? (
                <span className={cn("shrink-0 self-center text-[11px] tabular-nums",
                                    text.length >= MAX_COMMENT ? "font-medium text-danger" : "text-muted-fg")}>
                  {text.length}/{MAX_COMMENT}
                </span>
              ) : null}
              <Button variant="accent" size="sm" loading={send.isPending} disabled={!text.trim() || send.isPending} onClick={() => send.mutate()}>
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </footer>
        </div>
      </div>
    </Dialog>
    <PostEditor open={editing} post={fetched.data ?? null} onClose={() => setEditing(false)}
                onSaved={() => { setEditing(false); onGone?.(); onClose(); }} />
    </>
  );
}

/** One thing somebody said, and the two things you can do about it. */
function Line({ c, small, focus, onReply, onDrop }: {
  c: PostComment; small?: boolean; focus?: boolean; onReply: () => void; onDrop: () => void;
}) {
  const t = useT(); const locale = useLocale();
  return (
    <div data-comment-id={c.id} className={cn("flex gap-2.5", focus && "-mx-2 rounded-xl bg-muted/60 px-2 py-1.5")}>
      {/* A secretary's face opens the secretary's card, a person's the person's: the same
          press wherever it lands (plan/44 §8). */}
      <Face id={c.author.agent ? undefined : c.author.id} agentId={c.author.agent ? c.author.id : undefined} className="shrink-0">
        <Avatar name={c.author.name} src={c.author.avatar_url} size={small ? 24 : 28} mascot={!!c.author.agent} />
      </Face>
      <div className="min-w-0 flex-1">
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
          {c.author.agent
            ? <Face agentId={c.author.id} className="mr-1.5 inline-flex items-center gap-1 font-medium">{c.author.name}
                <span className="rounded bg-accent/10 px-1 text-[10px] text-accent">{t("feed.by_agent")}</span>
              </Face>
            : <Face id={c.author.id} className="mr-1.5 font-medium hover:underline">{c.author.name}</Face>}
          {c.body}
        </p>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-fg">
          <span>{fmtRelative(c.created_at, locale)}</span>
          <button type="button" className="font-medium hover:underline" onClick={onReply}>{t("feed.reply")}</button>
          {c.can_delete ? <button type="button" className="hover:underline" onClick={onDrop}>{t("common.delete")}</button> : null}
        </div>
      </div>
    </div>
  );
}
