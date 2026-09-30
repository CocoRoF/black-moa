"use client";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PenLine, Trash2 } from "@/components/icons";
import { Blog, Feed, type FeedItem } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { confirm } from "@/lib/confirm";
import type { MenuItem } from "@/components/ui/dropdown";
import { PostEditor } from "./Composer";

/** The two things I can do to my own post, wherever it is drawn.
 *
 *  One editor and one question for a whole page of cards rather than a pair per card: a
 *  screen of twenty posts should not be carrying twenty dialogs nobody opened. The card
 *  asks for the menu it should show and knows nothing about what pressing it does.
 */
export function usePostActions(onGone: () => void) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [editing, setEditing] = useState<FeedItem | null>(null);
  // A card carries what a card draws. Editing works from the whole post, so it is fetched
  // before the window opens: saving a long article from a card's excerpt would have
  // written the excerpt back over the article.
  const open = async (item: FeedItem) => {
    try {
      setEditing(await qc.fetchQuery({ queryKey: ["feed", "post", item.id], queryFn: () => Feed.one(item.id) }));
    } catch (e) { toast.error(friendlyError(e, locale)); }
  };
  const remove = useMutation({
    mutationFn: (id: string) => Blog.remove(id),
    onSuccess: () => { toast.success(t("blog.removed")); onGone(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  const menuFor = (item: FeedItem): MenuItem[] | undefined => item.can_edit ? [
    { key: "edit", label: t("common.edit"), icon: <PenLine />, onSelect: () => void open(item) },
    { key: "remove", label: t("common.delete"), icon: <Trash2 />, danger: true,
      onSelect: async () => { if (await confirm({ title: t("blog.remove_q"), danger: true })) remove.mutate(item.id); } },
  ] : undefined;

  const dialogs = (
    <PostEditor open={!!editing} post={editing} onClose={() => setEditing(null)}
                onSaved={() => { setEditing(null); onGone(); }} />
  );
  return { menuFor, dialogs };
}
