"use client";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { MoreHorizontal } from "@/components/icons";
import { Blog, type FeedItem } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtRelative } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/misc";
import { DropdownMenu, type MenuItem } from "@/components/ui/dropdown";
import { Actions, Caption, Clamped, Counts, Photos, Rule } from "./parts";
import { Face } from "@/components/profile/Face";

/** One post, always in the same order (plan/42 §12): the subject, what you can do to it,
 *  what everyone already did, a faint line, then what it says.
 *
 *  A post with no picture has its words as the subject, so they sit where the picture would
 *  be and nothing repeats them underneath.
 *
 *  Every screen that draws a post draws this: 소식, my own blog, somebody's page. A post
 *  that looks different depending on where it was found is two posts to the person reading
 *  it, and pressing one has to open the same window as pressing the other.
 */
export function PostCard({ item, onOpen, onChanged, tags, menu }: {
  item: FeedItem; onOpen: () => void; onChanged: (p: Partial<FeedItem>) => void;
  /** What this particular shelf needs said about the post, beside the author's name. */
  tags?: React.ReactNode;
  /** What I can do to this post, if it is mine. Nothing is drawn when there is nothing. */
  menu?: MenuItem[];
}) {
  const t = useT(); const locale = useLocale();
  const like = useMutation({
    mutationFn: (on: boolean) => Blog.like(item.id, on),
    onSuccess: (r) => onChanged({ liked: r.liked, like_count: r.like_count }),
    onError: (e) => { onChanged({ liked: item.liked, like_count: item.like_count }); toast.error(friendlyError(e, locale)); },
  });
  const caption = item.kind === "note" ? (item.body ?? "") : "";
  const words = (
    <>
      {item.kind === "article" ? (
        // Spans, not a heading and a paragraph: a button may only contain phrasing
        // content, and a browser that re-shapes invalid markup hands React a tree it did
        // not render.
        <button type="button" onClick={onOpen} className="block w-full text-left">
          <span className="block text-[15px] font-semibold hover:text-accent">{item.title}</span>
          <span className="mt-1 line-clamp-3 text-sm text-muted-fg">{item.excerpt}</span>
        </button>
      ) : caption ? (
        // The name is in the header of this very card. Repeating it in front of the words
        // is the same fact twice on one screen.
        <Clamped onMore={onOpen} watch={caption}>
          <p className="whitespace-pre-wrap break-words text-[15px] leading-relaxed">
            <Caption text={caption} mentions={item.mentions} />
          </p>
        </Clamped>
      ) : null}
    </>
  );

  return (
    <article className="overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
      <header className="flex items-center gap-2.5 px-4 py-3">
        {/* A face opens the person, here and everywhere else (plan/44 §8). */}
        <Face id={item.author.id}><Avatar name={item.author.name} src={item.author.avatar_url} size={34} /></Face>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5 text-sm">
            <Face id={item.author.id} className="font-medium hover:underline">{item.author.name}</Face>
            {tags ?? <Badge tone="outline">{t(`feed.why_${item.why}`)}</Badge>}
            {item.visibility !== "public" ? <Badge tone="neutral">{t(`blog.vis_${item.visibility}`)}</Badge> : null}
          </div>
          <div className="text-[11px] text-muted-fg">{item.at ? fmtRelative(item.at, locale) : t("blog.not_published")}</div>
        </div>
        {/* My own post, so the two things I might do to it are on the card rather than one
            window further in. */}
        {menu?.length ? (
          <DropdownMenu align="end" items={menu} trigger={
            <button type="button" aria-label={t("common.more")}
                    className="-mr-1 rounded-lg p-2 text-muted-fg hover:bg-muted hover:text-fg">
              <MoreHorizontal className="h-5 w-5" />
            </button>} />
        ) : null}
      </header>

      {/* The subject of the card: the photo, or the words when there is no photo. Then what
          you can do to it, then what everyone already did, then what it says. */}
      {item.images.length ? (
        // Not a <button>: the strip carries its own arrows, and a button inside a button is
        // markup no browser keeps. Opening the post is still one tab away on the comment
        // icon and on the tally beneath it.
        <div onClick={onOpen} className="w-full cursor-zoom-in">
          <Photos urls={item.images} />
        </div>
      ) : (
        <div className="px-4 pb-1 pt-0.5">{words}</div>
      )}

      <Actions liked={item.liked} onLike={() => like.mutate(!item.liked)} onComment={onOpen} />
      <Counts likes={item.like_count} comments={item.comment_count} onComments={onOpen} />

      {item.images.length ? (
        <>
          <Rule />
          <div className="px-4 py-3">{words}</div>
        </>
      ) : null}
    </article>
  );
}
