"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, ImagePlus, X } from "@/components/icons";
import { Chat, Community, Users } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { Page } from "@/components/owner/Shell";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { Section } from "@/components/ui/card";
import { Skeleton, Spinner } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/misc";

const MAX_IMAGES = 6;

export function PostEditor() {
  const t = useT(); const locale = useLocale(); const router = useRouter(); const sp = useSearchParams();
  const editId = sp.get("edit");
  const qc = useQueryClient();
  // Every board people write on: discussion boards and 맛집 (plan/34). Jobs has its own form.
  const boards = useQuery({ queryKey: ["c", "boards", "writable"],
    queryFn: async () => { const r = await Community.boards(); return { items: r.items.filter((b) => b.kind === "discussion") }; } });
  const existing = useQuery({ queryKey: ["c", "post", editId], queryFn: () => Community.post(editId!), enabled: !!editId });

  const [board, setBoard] = useState(sp.get("board") ?? "");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [images, setImages] = useState<{ id: string; url: string }[]>([]);
  const imagesRef = useRef(images);
  imagesRef.current = images;
  const [uploading, setUploading] = useState(false);
  const [drop, setDrop] = useState(false);
  // Object URLs are revoked by hand; a composer that is opened and abandoned a hundred
  // times should not leave a hundred decoded bitmaps behind.
  const blobs = useRef<string[]>([]);
  useEffect(() => () => { blobs.current.forEach(URL.revokeObjectURL); blobs.current = []; }, []);
  // One token per composed post: a double-tap on a slow network must not post twice.
  const token = useMemo(() => (typeof crypto !== "undefined" ? crypto.randomUUID().slice(0, 32) : String(Date.now())), []);

  useEffect(() => {
    if (existing.data) {
      setTitle(existing.data.title); setBody(existing.data.body ?? ""); setBoard(existing.data.board?.slug ?? "");
      // The server hands back view URLs; the ids they end with are what an edit sends back.
      setImages((existing.data.images ?? []).map((u) => ({ id: (u.split("?")[0] ?? "").split("/").pop() ?? "", url: u })));
    }
  }, [existing.data]);
  useEffect(() => {
    if (!board && boards.data?.items.length) setBoard(sp.get("board") || boards.data.items[0].slug);
  }, [boards.data, board, sp]);

  /** The one way images enter this post — picker, paste, or drop all land here. */
  const addFiles = useCallback(async (files: File[]) => {
    const pics = files.filter((f) => f.type.startsWith("image/"));
    if (!pics.length) return;
    const room = MAX_IMAGES - imagesRef.current.length;
    if (room <= 0) { toast.error(t("com.images_full", { n: MAX_IMAGES })); return; }
    if (pics.length > room) toast.message(t("com.images_full", { n: MAX_IMAGES }));
    setUploading(true);
    try {
      for (const f of pics.slice(0, room)) {
        const r = await Chat.upload(f, "attachment", "community");
        // The upload endpoint needs a bearer token, which an <img> cannot send, so the
        // thumbnail comes from the file that is already in the browser.
        const url = URL.createObjectURL(f);
        blobs.current.push(url);
        setImages((prev) => [...prev, { id: r.upload_id, url }]);
      }
    } catch (x) { toast.error(friendlyError(x, locale)); } finally { setUploading(false); }
  }, [locale, t]);

  const save = useMutation({
    mutationFn: async () => {
      if (editId) {
        await Community.editPost(editId, { title: title.trim(), body: body.trim(), version: existing.data?.version,
                                           images: images.map((i) => i.id) });
        return editId;
      }
      return (await Community.createPost({ board, title: title.trim(), body: body.trim(), client_token: token,
                                           images: images.map((i) => i.id) })).id;
    },
    onSuccess: async (id) => {
      toast.success(editId ? t("common.saved") : t("com.posted"));
      // The post page reads from the same cache this write just invalidated, so drop the
      // old copy before navigating — otherwise an edit only appears after a reload.
      await qc.invalidateQueries({ queryKey: ["c", "post", id] });
      qc.invalidateQueries({ queryKey: ["c", "posts"] });
      qc.invalidateQueries({ queryKey: ["c", "boards"] });
      router.replace(`/app/community/p/${id}`);
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  // 이름은 계정에 하나뿐이다 (plan/52). 글마다 적는 자리가 없고, 정하지 않았으면
  // 쓰기 전에 정하는 자리로 보낸다.
  const square = useQuery({ queryKey: ["me", "community-name"], queryFn: () => Users.communityName() });
  const penName = square.data?.name ?? "";
  const named = !!penName;
  const ready = !!board && title.trim().length > 0 && body.trim().length > 0 && named;
  return (
    <Page>
      <PageHeader title={editId ? t("com.edit_title") : t("com.write")} description={t("com.write_desc")}
        back={<button type="button" onClick={() => router.back()} className="mb-2 inline-flex items-center gap-1 text-sm text-muted-fg hover:text-fg"><ArrowLeft className="h-4 w-4" />{t("common.back")}</button>} />
      {editId && existing.isLoading ? <Skeleton className="h-64" /> : (
        <Section title={t("com.compose")}>
          {/* A screenshot in the clipboard is the most common way an image reaches a post,
              so paste and drop take the same path the picker does. */}
          <form className={cn("space-y-4 rounded-xl transition-colors", drop && "outline-2 outline-dashed outline-accent outline-offset-4")}
            onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate(); }}
            onPaste={(e) => {
              const files = Array.from(e.clipboardData?.files ?? []).filter((f) => f.type.startsWith("image/"));
              if (!files.length) return;
              e.preventDefault();            // otherwise the file name lands in the textarea
              void addFiles(files);
            }}
            onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDrop(true); } }}
            onDragLeave={(e) => { if (e.currentTarget === e.target) setDrop(false); }}
            onDrop={(e) => {
              const files = Array.from(e.dataTransfer.files ?? []).filter((f) => f.type.startsWith("image/"));
              setDrop(false);
              if (!files.length) return;
              e.preventDefault();
              void addFiles(files);
            }}>
            <Field label={t("com.board")}>
              <Select value={board} onChange={(e) => setBoard(e.target.value)} disabled={!!editId}>
                {(boards.data?.items ?? []).map((b) => <option key={b.slug} value={b.slug}>{b.name}</option>)}
              </Select>
            </Field>
            <Field label={t("com.post_title")}>
              <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} placeholder={t("com.title_ph")} />
            </Field>
            <Field label={t("com.post_body")} hint={t("com.body_hint")}>
              <Textarea value={body} onChange={(e) => setBody(e.target.value)} maxLength={20000} className="min-h-[280px]" placeholder={t("com.body_ph")} />
            </Field>
            <Field label={t("com.images")} hint={t("com.images_hint")}>
              <div className="flex flex-wrap gap-2">
                {images.map((im) => (
                  <div key={im.id} className="relative">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={im.url} alt="" className="h-24 w-24 rounded-xl border border-border object-cover" />
                    <button type="button" aria-label={t("common.delete")} onClick={() => setImages(images.filter((x) => x.id !== im.id))}
                            className="absolute -right-2 -top-2 inline-flex h-6 w-6 items-center justify-center rounded-full bg-card text-muted-fg shadow ring-1 ring-border hover:text-danger">
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
                {images.length < MAX_IMAGES ? (
                  <label className="flex h-24 w-24 cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-border text-xs text-muted-fg hover:border-accent hover:text-accent">
                    {uploading ? <Spinner className="h-4 w-4" /> : <ImagePlus className="h-5 w-5" />}
                    <span>{uploading ? t("com.uploading") : t("com.add_image")}</span>
                    <input type="file" accept="image/*" multiple className="hidden" onChange={(e) => {
                      const files = Array.from(e.target.files ?? []); e.target.value = "";
                      void addFiles(files);
                    }} />
                  </label>
                ) : null}
              </div>
            </Field>

            {/* 커뮤니티는 익명이다 (plan/51). 실명으로 쓰는 선택지는 없고, 이름은 계정에
                정해 둔 하나다 (plan/52). 늘 같은 이름이라 대화가 이어진다. */}
            <div className="-mx-5 -mb-5 mt-1 flex flex-wrap items-center gap-3 border-t border-border bg-muted/30 px-5 py-3.5">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{t("com.byline_label")}</p>
                {named ? (
                  <p className="mt-0.5 text-xs text-muted-fg">{t("com.byline_is", { name: penName })}</p>
                ) : (
                  <p className="mt-0.5 text-xs text-muted-fg">
                    {t("com.byline_unset")}{" "}
                    <Link href="/app/profile" className="text-accent underline-offset-2 hover:underline">{t("com.byline_go_set")}</Link>
                  </p>
                )}
              </div>
              <div className="flex gap-2">
                <Button type="button" variant="ghost" onClick={() => router.back()}>{t("common.cancel")}</Button>
                <Button type="submit" variant="accent" loading={save.isPending} disabled={!ready}>{editId ? t("common.save") : t("com.publish")}</Button>
              </div>
            </div>
          </form>
        </Section>
      )}
    </Page>
  );
}
