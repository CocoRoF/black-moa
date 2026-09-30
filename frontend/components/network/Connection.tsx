"use client";
/**
 * 인맥의 상태와 그 단추, 사이트 전체에 하나 (plan/69).
 *
 * 두 사람 사이는 넷 중 하나다: 인맥(서로 연결) · 내가 연결 · 상대가 나를 연결 · 아무것도 아님. 예전에는 화면마다
 * 따로 알아서 — 인박스의 [인맥 맺기] 는 상태를 몰라 누른 뒤에도 그대로였고, 프로필은 두 열쇠로 따로 들고 있었다.
 * 이제 모두 `["network","link",id]` 한 곳을 읽고, 바꾸는 곳도 여기 하나다. 다른 탭이나 상대가 바꾸면 서버가
 * `link` 소식을 보내 같은 자리를 고친다(useShellLive).
 *
 * 규칙은 하나: 내가 연결하지 않았으면 [인맥 맺기], 연결했으면 [인맥 지우기]. 옆에는 지금 상태를 적는다.
 */
import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { UserMinus, UserPlus } from "@/components/icons";
import { Network, type Account } from "@/lib/api";
import { confirm } from "@/lib/confirm";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Button, type ButtonSize } from "@/components/ui/button";

export type LinkStatus = "mutual" | "outgoing" | "incoming" | "none";
export const linkKey = (userId: string) => ["network", "link", userId] as const;
export const statusOf = (link: Account["link"] | undefined): LinkStatus => link?.status ?? "none";
const DIRECTION = { mutual: "both", outgoing: "outgoing", incoming: "incoming" } as const;

/** 한 사람과의 상태가 바뀌었다 — 그 자리를 고치고, 그 사람을 담은 목록은 다시 받는다. */
export function applyLink(qc: QueryClient, userId: string, status: LinkStatus): void {
  qc.setQueryData(linkKey(userId), status);
  const patch = (p: unknown) =>
    p && typeof p === "object" ? { ...(p as object), link: status === "none" ? null : { status, direction: DIRECTION[status] } } : p;
  qc.setQueryData(["network", "profile", userId], patch);
  qc.setQueryData(["people", userId], patch);
  qc.invalidateQueries({
    predicate: (q) => {
      const k = q.queryKey as unknown[];
      return (k[0] === "network" && k[1] !== "link") || k[0] === "people" || k[0] === "feed";
    },
  });
}

/**
 * 이 사람과 지금 어떤 사이인가. 목록이 이미 알려 준 값(`known`)이 있으면 묻지 않는다 — 수백 줄의 목록이
 * 한 줄씩 묻지 않게. 그래도 누군가 바꾸면(여기서든 다른 탭·상대든) 바뀐 값이 이긴다.
 */
export function useLink(userId: string | null | undefined, known?: LinkStatus): LinkStatus | "self" | null {
  const q = useQuery({
    queryKey: linkKey(userId ?? ""),
    queryFn: async () => (await Network.link(userId!)).status,
    enabled: !!userId && known === undefined,
    staleTime: 30_000,
  });
  return q.data ?? known ?? null;
}

export function useLinkActions() {
  const t = useT();
  const locale = useLocale();
  const qc = useQueryClient();
  const connect = useMutation({
    mutationFn: (userId: string) => Network.follow(userId),
    onSuccess: (r, userId) => {
      applyLink(qc, userId, r.status);
      toast.success(r.status === "mutual" ? t("net.became_friends") : t("net.linked_one_way"));
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const disconnect = useMutation({
    mutationFn: (userId: string) => Network.unfollow(userId),
    onSuccess: (r, userId) => {
      applyLink(qc, userId, r.status);
      toast.success(t("net.unlinked"));
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  /** 지우기 전에 한 번 묻는다. 인맥이었다면 상대의 연결은 남아 "나를 연결" 이 된다는 것도. */
  const remove = useCallback(
    async (userId: string, status: LinkStatus, name?: string) => {
      const ok = await confirm({
        title: name ? t("net.unlink_q_name", { name }) : t("net.unlink_q"),
        description: status === "mutual" ? t("net.unlink_mutual_desc") : t("net.unlink_desc"),
        confirmLabel: t("net.unlink"),
        danger: true,
      });
      if (ok) disconnect.mutate(userId);
    },
    [disconnect, t],
  );
  return { connect, disconnect, remove, busy: connect.isPending || disconnect.isPending };
}

/** 지금 상태 한 마디. 아무 사이도 아니면 없다. */
export function LinkBadge({ status, className }: { status: LinkStatus | "self" | null; className?: string }) {
  const t = useT();
  if (!status || status === "none" || status === "self") return null;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
        status === "mutual" ? "bg-accent-soft text-accent" : "bg-muted text-muted-fg",
        className,
      )}
    >
      {t(status === "mutual" ? "net.link_mutual" : status === "outgoing" ? "net.link_outgoing" : "net.link_incoming")}
    </span>
  );
}

/**
 * [인맥 맺기] 또는 [인맥 지우기], 그리고 지금 상태.
 *  - `look="button"`: 프로필·목록의 단추.
 *  - `look="link"`: 카드·인박스처럼 글 사이에 놓이는 가벼운 모양.
 */
export function ConnectionControl({
  userId,
  name,
  known,
  look = "button",
  size = "sm",
  showState = true,
  className,
}: {
  userId: string | null | undefined;
  name?: string;
  known?: LinkStatus;
  look?: "button" | "link";
  size?: ButtonSize;
  showState?: boolean;
  className?: string;
}) {
  const t = useT();
  const status = useLink(userId, known);
  const { connect, remove, busy } = useLinkActions();
  if (!userId || !status || status === "self") return null;
  const mine = status === "mutual" || status === "outgoing";
  const act = () => (mine ? void remove(userId, status, name) : connect.mutate(userId));
  const label = mine ? t("net.unlink") : t("net.link_action");
  const Icon = mine ? UserMinus : UserPlus;
  return (
    <span className={cn("inline-flex items-center gap-2", className)} data-link-status={status}>
      {showState ? <LinkBadge status={status} /> : null}
      {look === "link" ? (
        <button
          type="button"
          disabled={busy}
          onClick={act}
          className={cn(
            "inline-flex items-center gap-1 underline-offset-2 hover:underline disabled:opacity-60",
            mine ? "text-muted-fg hover:text-danger" : "text-accent",
          )}
        >
          <Icon className="h-3.5 w-3.5" />
          {label}
        </button>
      ) : (
        <Button size={size} variant={mine ? "outline" : "accent"} loading={busy} onClick={act}>
          <Icon className="h-4 w-4" />
          {label}
        </Button>
      )}
    </span>
  );
}
