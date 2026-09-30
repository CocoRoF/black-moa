"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { MessageSquare, Trash2, UserRound } from "@/components/icons";
import { Network } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { confirm } from "@/lib/confirm";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ConnectionControl } from "@/components/network/Connection";
import { Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar } from "@/components/ui/misc";
import { ProfileModal } from "@/components/profile/ProfileModal";

/** What I wrote down about somebody, and the two ways to reach them (plan/44 §8).
 *
 *  Pressing anything in the graph opens this. A person used to open a panel and a secretary
 *  used to open a new tab, which made the same gesture mean two things depending on what it
 *  landed on. Here they are one panel: a memo, [프로필], and [메시지].
 *
 *  The subject is either a row in my graph (`id` is a uuid) or a published secretary
 *  (`agent:<uuid>`), and only this component has to know the difference.
 */
export function NodeMemo({ id, onClose, onChanged, onMessage }: {
  id: string | null; onClose: () => void; onChanged: () => void;
  /** Opens the room with them. Absent while the messenger is not built yet. */
  onMessage?: (to: { userId?: string; agentId?: string }) => void;
}) {
  const t = useT(); const locale = useLocale(); const router = useRouter();
  const agentId = id?.startsWith("agent:") ? id.slice(6) : null;
  const nodeId = id && !agentId ? id : null;
  const [profile, setProfile] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  useEffect(() => { setDraft(null); setProfile(false); }, [id]);

  const node = useQuery({ queryKey: ["network", "node", nodeId], queryFn: () => Network.node(nodeId!), enabled: !!nodeId });
  const bot = useQuery({ queryKey: ["network", "subject", "agent", agentId], queryFn: () => Network.agentSubject(agentId!), enabled: !!agentId });
  const loading = (nodeId && node.isLoading) || (agentId && bot.isLoading);

  const name = bot.data?.name ?? node.data?.name ?? "";
  const avatar = bot.data?.avatar_url ?? node.data?.avatar_url ?? null;
  const sub = agentId
    ? (bot.data?.owner ? t("prof.works_for", { name: bot.data.owner.name }) : t("net.kind_agent"))
    : [node.data?.attrs?.title, node.data?.attrs?.company].filter(Boolean).join(" · ")
      || (typeof node.data?.attrs?.email === "string" ? node.data.attrs.email : "");
  const saved = bot.data?.notes ?? node.data?.notes ?? "";
  const text = draft ?? saved;
  //: A guest card and an offline card are not accounts. There is nobody to write to.
  const userId = node.data?.user_id ?? null;
  const reachable = !!agentId || !!userId;
  const mine = !!node.data?.is_self;

  const save = useMutation({
    mutationFn: () => agentId ? Network.agentMemo(agentId, text) : Network.patchNode(nodeId!, { notes: text }),
    onSuccess: () => {
      void (agentId ? bot.refetch() : node.refetch());
      onChanged(); setDraft(null); toast.success(t("common.saved"));
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const del = useMutation({
    mutationFn: () => Network.deleteNode(nodeId!),
    onSuccess: () => { onChanged(); onClose(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  return (
    <>
      <Dialog open={!!id && !profile} onClose={onClose} title={t("net.memo_title")} size="sm"
        footer={<div className="flex w-full items-center justify-between gap-2">
          {/* Only a card I keep can be thrown away. A member and a secretary are not mine
              to delete; the memo about them is all I own here. */}
          {nodeId && !mine && node.data?.person === "offline" ? (
            <Button variant="ghost" className="text-danger" onClick={async () => {
              if (await confirm({ title: t("net.delete_confirm"), danger: true, confirmLabel: t("common.delete") })) del.mutate();
            }}><Trash2 className="h-4 w-4" />{t("common.delete")}</Button>
          ) : <span />}
          <Button loading={save.isPending} disabled={draft === null} onClick={() => save.mutate()}>{t("common.save")}</Button>
        </div>}>
        {loading ? <Skeleton className="h-44" /> : (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <Avatar name={name} src={avatar ?? undefined} size={48} mascot={!!agentId} />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{name}</div>
                {sub ? <div className="truncate text-xs text-muted-fg">{sub}</div> : null}
              </div>
            </div>
            {/* The two ways to reach whoever this is. A card nobody can write to says so by
                not offering it, rather than by offering it and refusing. */}
            {reachable ? (
              <div className="flex gap-2">
                {/* A person's profile is their page; a secretary's is the card the public
                    chat shows, because a secretary has no page of its own. */}
                <Button variant="outline" size="sm" className="flex-1"
                        onClick={() => { if (agentId) setProfile(true); else { onClose(); router.push(`/app/u/${userId}`); } }}>
                  <UserRound className="h-4 w-4" />{t("prof.profile")}
                </Button>
                <Button variant="outline" size="sm" className="flex-1" disabled={!onMessage}
                        onClick={() => onMessage?.(agentId ? { agentId } : { userId: userId! })}>
                  <MessageSquare className="h-4 w-4" />{t("msg.message")}
                </Button>
              </div>
            ) : null}
            {/* 회원이면 지금 사이와 그 단추 — 사이트 어디서나 같은 [인맥 맺기] · [인맥 지우기] (plan/69). */}
            {userId && !agentId && !node.data?.is_self ? (
              <ConnectionControl userId={userId} name={node.data?.name} className="w-full justify-between" />
            ) : null}
            <div>
              <div className="mb-1.5 text-sm font-medium">{t("net.notes")}</div>
              <Textarea value={text} onChange={(e) => setDraft(e.target.value)} placeholder={t("net.notes_ph")}
                        className="min-h-[130px]" />
            </div>
          </div>
        )}
      </Dialog>
      {profile ? (
        <ProfileModal userId={userId ?? undefined} agentId={agentId ?? undefined}
                      onClose={() => setProfile(false)}
                      onMessage={onMessage ? () => onMessage(agentId ? { agentId } : { userId: userId! }) : undefined} />
      ) : null}
    </>
  );
}
