"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { ImagePlus, Plus, Send, X } from "@/components/icons";
import { Blog, Chat, type FeedItem, type Mentionable } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { useAuth } from "@/stores/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Avatar } from "@/components/ui/misc";
import { Dialog } from "@/components/ui/dialog";
import { Segmented } from "@/components/ui/tabs";
import { confirm } from "@/lib/confirm";
import { CaptionBox } from "./CaptionBox";
import { Photos, useFileDrop, usePaste } from "./parts";

export const MAX_IMAGES = 8;
//: 소식에 적는 글은 천 자까지다. 그 이상은 제목이 필요한 글이고 제 페이지를 갖는다
//: (plan/42 §14). 제목이 있는 글은 길게 쓰는 자리라 여기서 재지 않는다.
const MAX_NOTE = 1000;

interface Pic { id: string; url: string }

/** Writing starts with a picture (plan/42 §10).
 *
 *  One button opens it, and the first thing it asks for is a photo — that is what this feed
 *  is made of. Words without one are still a post, which is why [사진 없이 쓰기] is on the
 *  same screen rather than somewhere else.
 */
export function Composer({ onPosted }: { onPosted: () => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}
              className="flex w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-border bg-card py-3.5 text-sm font-medium text-muted-fg shadow-soft transition-colors hover:border-accent hover:text-accent">
        <Plus className="h-4 w-4" />{t("feed.write")}
      </button>
      <PostEditor open={open} onClose={() => setOpen(false)} onSaved={onPosted} />
    </>
  );
}

type Level = "public" | "friends" | "private";

/** Writing a post, and changing one already written.
 *
 *  The same screen for both: what a post is made of does not change because it exists
 *  already, and a second editor would drift from this one the first time either changed.
 */
export function PostEditor({ open, post, kind = "note", onClose, onSaved }: {
  open: boolean; post?: FeedItem | null;
  /** What a new post is. A note starts with a photo; an article starts with a heading. */
  kind?: "note" | "article";
  onClose: () => void; onSaved: () => void;
}) {
  const t = useT(); const locale = useLocale();
  const user = useAuth((s) => s.user);
  const editing = !!post;
  const [pics, setPics] = useState<Pic[]>([]);
  const [words, setWords] = useState(false);   // chose to write without a picture
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [vis, setVis] = useState<Level>("public");
  const [busy, setBusy] = useState(false);
  //: Whether the last press was [임시저장]. Only something with a heading can wait.
  const [draft, setDraft] = useState(false);
  //: Which photo is on screen, so the X takes that one.
  const [at, setAt] = useState(0);
  const file = useRef<HTMLInputElement | null>(null);
  //: What is actually in the tray, read synchronously while uploads are in flight.
  const held = useRef<Pic[]>([]);
  //: Who was chosen from the `@` list, so a person with no address can still be named.
  const named = useRef<string[]>([]);

  // What is already there, once, when the window opens on an existing post.
  useEffect(() => {
    if (!open) return;
    if (!post) { held.current = []; named.current = []; setPics([]); setAt(0); setWords(kind === "article"); setTitle(""); setBody(""); setVis("public"); setDraft(false); return; }
    const ids = post.image_ids ?? [];
    held.current = ids.map((id, i) => ({ id, url: post.images[i] ?? "" }));
    named.current = post.mentions.map((m) => m.id);
    setPics(held.current);
    setAt(0);
    setWords(!ids.length);
    setTitle(post.title);
    setBody(post.body ?? "");
    setVis(post.visibility);
    setDraft(post.status === "draft");
    // Only when the window opens: re-running this while somebody types would undo them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, post?.id]);

  const add = useCallback(async (list: FileList | File[] | null) => {
    const chosen = Array.from(list ?? []).filter((f) => f.type.startsWith("image/"));
    if (!chosen.length) return;
    // Counted here rather than inside a state updater: React may run an updater twice, and
    // reading the count out of one made a single picture look like a full tray.
    const room = MAX_IMAGES - held.current.length;
    if (room <= 0) { toast.message(t("feed.photos_full", { n: MAX_IMAGES })); return; }
    if (chosen.length > room) toast.message(t("feed.photos_full", { n: MAX_IMAGES }));
    setBusy(true);
    try {
      for (const f of chosen.slice(0, room)) {
        // The community lane resizes pictures; knowledge indexing must not queue behind them.
        const up = await Chat.upload(f, "attachment", "community");
        const next = { id: up.upload_id, url: URL.createObjectURL(f) };
        held.current = [...held.current, next];
        setPics(held.current);
      }
    } catch (e) { toast.error(friendlyError(e, locale)); }
    finally { setBusy(false); }
  }, [locale, t]);

  // A picture in the clipboard is how one most often arrives, and dropping it anywhere on
  // this window should work the same as picking it.
  const over = useFileDrop((f) => void add(f), open);
  usePaste((f) => void add(f), open);

  const reset = () => { held.current = []; named.current = []; setPics([]); setAt(0); setWords(false); setTitle(""); setBody(""); setVis("public"); setDraft(false); onClose(); };
  // Anything typed or picked is work somebody did. A stray click outside must not take it,
  // and the way out asks first. An edit counts from the moment it differs from what is
  // already saved, so opening a post and closing it again asks nothing.
  const dirty = editing
    ? body !== (post?.body ?? "") || vis !== post?.visibility || title !== (post?.title ?? "")
      || pics.map((p) => p.id).join() !== (post?.image_ids ?? []).join()
    : pics.length > 0 || !!body.trim() || !!title.trim();
  const leave = async () => {
    if (!dirty) { reset(); return; }
    if (await confirm({ title: t("feed.leave_title"), description: t("feed.leave_desc"),
                        danger: true, confirmLabel: t("feed.leave_yes") })) reset();
  };
  const save = useMutation({
    mutationFn: (keep?: boolean) => editing
      // No `images` key when the post arrived without its upload ids: saying nothing about
      // the photos keeps them, and sending an empty list would take them off the post.
      ? Blog.update(post!.id, { body: body.trim(), visibility: vis, mentions: named.current,
                                ...(Array.isArray(post!.image_ids) ? { images: pics.map((p) => p.id) } : {}),
                                ...(titled ? { title: title.trim() } : {}),
                                ...(canDraft ? { status: keep ? "draft" : "published" } : {}) })
      : Blog.create({ title: titled ? title.trim() : "", body: body.trim(), visibility: vis, kind,
                      publish: !keep, images: pics.map((p) => p.id), mentions: named.current }),
    onSuccess: (_r, keep) => { toast.success(t(keep ? "blog.saved_draft" : editing ? "feed.saved" : "feed.posted")); reset(); onSaved(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  const picking = !editing && !pics.length && !words;
  //: An article carries a heading of its own; a note takes one from its first line.
  const titled = editing ? post!.kind === "article" : kind === "article";
  //: Only something with a heading can wait unpublished. A note goes up or it is not one.
  const canDraft = titled && (!editing || draft || post!.status === "draft");
  const ready = (pics.length > 0 || !!body.trim()) && (!titled || !!title.trim());

  return (
    <Dialog open={open} onClose={leave} size={picking ? "md" : "xl"} bare guard={dirty}>
      <input ref={file} type="file" accept="image/*" multiple hidden
             onChange={(e) => { void add(e.target.files); e.target.value = ""; }} />
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">{t(editing ? "feed.edit_post" : titled ? "blog.new" : "feed.new_post")}</h2>
        {picking ? null : (
          <div className="flex items-center gap-2">
            {canDraft ? (
              <Button variant="outline" size="sm" loading={save.isPending} disabled={!ready} onClick={() => save.mutate(true)}>
                {t("blog.save_draft")}
              </Button>
            ) : null}
            <Button variant="accent" size="sm" loading={save.isPending} disabled={!ready} onClick={() => save.mutate(false)}>
              <Send className="h-4 w-4" />{t(canDraft ? "blog.publish" : editing ? "feed.save" : "feed.post")}
            </Button>
          </div>
        )}
      </div>

      {picking ? (
        <div className={cn("flex flex-col items-center justify-center gap-4 px-6 py-14 text-center",
                           over && "bg-accent/5")}>
          <ImagePlus className="h-12 w-12 text-muted-fg" />
          <div>
            <p className="text-[15px] font-medium">{t("feed.drop_title")}</p>
            <p className="mt-1 text-xs text-muted-fg">{t("feed.drop_hint")}</p>
          </div>
          <Button variant="accent" loading={busy} onClick={() => file.current?.click()}>{t("feed.pick_photos")}</Button>
          <button type="button" onClick={() => setWords(true)} className="text-xs text-muted-fg underline-offset-2 hover:underline">
            {t("feed.no_photo")}
          </button>
        </div>
      ) : (
        <div className={cn("grid", pics.length ? "sm:grid-cols-[minmax(0,1fr)_320px]" : "")}>
          {pics.length ? (
            <div className="relative">
              <Photos urls={pics.map((p) => p.url)} fit="ratio" className="max-h-[34vh] overflow-hidden sm:max-h-[62vh]"
                      at={at} onAt={setAt} />
              {/* The one being looked at is the one that goes. Taking the last off the pile
                  instead meant the only way to drop the second of four was to drop three. */}
              <button type="button" aria-label={t("common.delete")}
                      onClick={() => { held.current = held.current.filter((_, i) => i !== at); setPics(held.current); setAt((n) => Math.max(0, Math.min(n, held.current.length - 1))); }}
                      className="absolute right-2 top-2 rounded-full bg-bg/85 p-1.5 text-danger shadow">
                <X className="h-4 w-4" />
              </button>
            </div>
          ) : null}

          <div className="flex flex-col gap-3 p-4 sm:border-l sm:border-border">
            <div className="flex items-center gap-2">
              <Avatar name={user?.display_name} src={user?.avatar_url} size={28} />
              <span className="text-sm font-medium">{user?.display_name}</span>
            </div>
            {titled ? (
              <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("blog.title_ph")}
                     className="text-base font-medium" />
            ) : null}
            <CaptionBox value={body} onChange={setBody} autoFocus={!titled} limit={titled ? undefined : MAX_NOTE}
                        onPick={(who: Mentionable) => { if (!named.current.includes(who.id)) named.current = [...named.current, who.id]; }}
                        placeholder={titled ? t("blog.body_ph") : pics.length ? t("feed.caption_ph") : t("feed.compose_ph")}
                        className={cn("flex-1", titled ? "min-h-[200px] sm:min-h-[340px]" : "min-h-[96px] sm:min-h-[160px]")} />
            <div className="space-y-2 border-t border-border pt-3">
              <div className="flex items-center justify-between gap-2 text-xs text-muted-fg">
                {/* 고른 것이 무슨 뜻인지 그 자리에서 말한다. [비서에게만] 은 처음 보는
                    낱말이라 이름만으로는 아무도 모른다. */}
                <span className="min-w-0 flex-1 truncate">{t(`blog.vis_${vis}_hint`)}</span>
                {/* 나만 보기 is only offered on something already written: nobody opens a
                    composer to publish to an audience of one. */}
                {/* [비서에게만] 은 짧은 글에도 있어야 한다. 아무에게도 안 보이는 글을
                    적는 자리가 곧 일기이고, 일기는 제목이 있는 글이 아니다 (plan/45 §6). */}
                <Segmented<Level> size="sm" value={vis} onChange={setVis} ariaLabel={t("blog.who")}
                  options={[{ value: "public", label: t("blog.vis_public") },
                            { value: "friends", label: t("blog.vis_friends") },
                            { value: "private", label: t("blog.vis_private") }]} />
              </div>
              <div className="flex items-center justify-between text-xs text-muted-fg">
                <span>{pics.length ? t("feed.photos_n", { n: pics.length }) : t("feed.no_photos_yet")}</span>
                <Button variant="ghost" size="sm" loading={busy} disabled={pics.length >= MAX_IMAGES}
                        onClick={() => file.current?.click()}><ImagePlus className="h-4 w-4" />{t("feed.add_photo")}</Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </Dialog>
  );
}
