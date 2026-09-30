"use client";
import { useEffect } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, Bot, Briefcase, MapPin, MessageSquare, UserRound, X } from "@/components/icons";
import { Network, Public, type MemberProfile } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Avatar } from "@/components/ui/misc";
import { Button, buttonLook } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ProfileHeader } from "@/components/profile/ProfileHeader";
import { AgentProfile } from "@/components/public/AgentProfile";
import type { PublicAgent } from "@/components/public/PublicChat";
import { ConnectionControl, LinkBadge, statusOf, useLink } from "@/components/network/Connection";
import { useMessenger } from "@/stores/messenger";

/** Who somebody is, in a card, without leaving where you were (plan/44 §8).
 *
 *  Every face in the app opens this: a name in 소식, a comment under a post, a row in 인맥, a
 *  node in the graph. A secretary gets the same card the public chat shows for it, with
 *  [대화하기] where the public page has [링크 공유]. A person gets their header, the two or
 *  three facts that decide whether this is who you meant, and every secretary they left a
 *  door open to — because talking to somebody's secretary is often the point of finding
 *  them.
 */
export function ProfileModal({ userId, agentId, onClose, onMessage }: {
  /** A member, by account id. */
  userId?: string | null;
  /** A published secretary, by agent id. */
  agentId?: string | null;
  onClose: () => void;
  /** Opens the room with them. Left out, the card opens it itself. */
  onMessage?: () => void;
}) {
  const t = useT();
  const openWith = useMessenger((s) => s.openWith);
  const person = useQuery({ queryKey: ["people", userId], queryFn: () => Network.profile(userId!), enabled: !!userId });
  // 이 사람과의 지금 사이 — 사이트의 다른 모든 인맥 단추와 같은 자리를 읽는다(plan/69).
  const linkStatus = useLink(person.data && !person.data.is_me ? userId : null, person.data ? statusOf(person.data.link) : undefined);
  const linked = !!linkStatus && linkStatus !== "none" && linkStatus !== "self";
  const bot = useQuery({ queryKey: ["network", "subject", "agent", agentId], queryFn: () => Network.agentSubject(agentId!), enabled: !!agentId });
  const code = bot.data?.link_code;
  const pub = useQuery({ queryKey: ["public", "link", code], queryFn: () => Public.link(code!), enabled: !!code });

  if (agentId) {
    const a = pub.data?.agent as unknown as PublicAgent | undefined;
    if (!a) {
      return (
        <Shell onClose={onClose} label="">
          {bot.isError || pub.isError ? <p className="p-8 text-center text-sm text-muted-fg">{t("prof.agent_gone")}</p> : <Skeleton className="h-72" />}
        </Shell>
      );
    }
    return (
      <AgentProfile agent={a} accent={a.theme?.accent || "#1a5fe0"} online={a.status === "active" && !a.resting}
                    onClose={onClose} share={false} zIndex={105}
                    primary={{ label: t("msg.talk"), icon: <MessageSquare className="h-4 w-4" />,
                               onClick: () => { (onMessage ?? (() => openWith({ agentId })))(); onClose(); } }} />
    );
  }

  const p = person.data;
  return (
    <Shell onClose={onClose} label={p?.display_name ?? ""}>
      {person.isLoading ? <Skeleton className="h-72" /> : person.isError || !p ? (
        <p className="p-8 text-center text-sm text-muted-fg">{t("prof.person_gone")}</p>
      ) : (
        <>
          <ProfileHeader
            compact coverUrl={p.fields?.cover} avatarSrc={p.avatar_url}
            avatar={
              <div className={cn(p.avatar_url ? "overflow-hidden rounded-full bg-card ring-4 ring-card" : "")}>
                <Avatar name={p.display_name} src={p.avatar_url ?? undefined} size={112} />
              </div>
            }
            name={p.display_name}
            subtitle={p.fields?.title || (p.handle ? `@${p.handle}` : undefined)}
            meta={p.is_me ? <Badge tone="outline">{t("feed.why_mine")}</Badge> : <LinkBadge status={linkStatus} />}
          />
          <PersonFacts p={p} />
          {/* The doors they left open. A secretary anybody can talk to is one press from
              the face of the person it works for. */}
          {p.secretaries?.length ? (
            <div className="border-t border-border px-5 py-3">
              <div className="mb-2 text-xs font-medium text-muted-fg">{t("prof.their_secretaries")}</div>
              <ul className="space-y-1.5">
                {p.secretaries.map((s) => (
                  <li key={s.id} className="flex items-center gap-2.5">
                    <Avatar mascot name={s.name} src={s.avatar_url ?? undefined} size={32} />
                    <span className="block min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{s.name}</span>
                      {s.role_line ? <span className="block truncate text-xs text-muted-fg">{s.role_line}</span> : null}
                    </span>
                    <Button size="sm" variant="outline" onClick={() => { openWith({ agentId: s.id }); onClose(); }}>
                      <Bot className="h-4 w-4" />{t("prof.talk_to_secretary")}
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {/* 말을 걸려면 먼저 연결한다 (plan/44 §4). 아직 아무 쪽으로도 닿지 않은 사이에
              [메시지]를 내밀면, 누른 사람은 거절당하려고 누른 셈이 된다. 연결 단추는 어디서나
              같다: [인맥 맺기] · [인맥 지우기] (plan/69). */}
          <div className="flex flex-wrap gap-2 border-t border-border px-5 pt-4 pb-[max(1rem,var(--sab))]">
            <Link href={`/app/u/${p.id}`} onClick={onClose}
                  className={buttonLook(p.is_me ? "accent" : "outline", "md", "flex-1")}>
              <UserRound className="h-4 w-4" />{t("prof.full_profile")}
            </Link>
            {p.is_me ? null : <ConnectionControl userId={p.id} name={p.display_name} known={statusOf(p.link)} size="md" showState={false} />}
            {!p.is_me && linked ? (
              <Button variant="accent" className="flex-1"
                      onClick={() => { (onMessage ?? (() => openWith({ userId: p.id })))(); onClose(); }}>
                <MessageSquare className="h-4 w-4" />{t("msg.message")}
              </Button>
            ) : null}
          </div>
        </>
      )}
    </Shell>
  );
}

function Shell({ label, onClose, children }: { label: string; onClose: () => void; children: React.ReactNode }) {
  const t = useT();
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[105] flex items-end justify-center sm:items-center" role="dialog" aria-modal="true" aria-label={label || undefined}>
      <button type="button" aria-label={t("common.close")} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-[2px]" />
      <div className="relative w-full max-w-[440px] overflow-hidden rounded-t-3xl border border-border bg-card shadow-2xl sm:rounded-3xl">
        <button type="button" onClick={onClose} aria-label={t("common.close")}
                className="absolute right-3 top-3 z-10 inline-flex h-9 w-9 items-center justify-center rounded-full bg-black/40 text-white backdrop-blur hover:bg-black/60">
          <X className="h-5 w-5" />
        </button>
        {children}
      </div>
    </div>
  );
}

/** The two or three things about a member that decide whether this is who you meant. */
function PersonFacts({ p }: { p: MemberProfile }) {
  const t = useT();
  const rows = [
    p.fields?.company ? { icon: <Briefcase className="h-4 w-4" />, label: p.fields.company,
                          badge: p.fields.company_verified_at ? <BadgeCheck className="h-3.5 w-3.5 text-success" /> : null } : null,
    p.fields?.location ? { icon: <MapPin className="h-4 w-4" />, label: p.fields.location, badge: null } : null,
  ].filter(Boolean) as { icon: React.ReactNode; label: string; badge: React.ReactNode }[];
  return (
    <div className="border-t border-border px-5 py-4">
      {p.fields?.bio ? <p className="mb-3 whitespace-pre-wrap text-sm text-muted-fg">{p.fields.bio}</p> : null}
      {rows.length ? (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li key={r.label} className="flex items-center gap-2.5 text-sm">
              <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent">{r.icon}</span>
              <span className="inline-flex min-w-0 items-center gap-1"><span className="truncate">{r.label}</span>{r.badge}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <div className={cn("flex gap-4 text-xs text-muted-fg", rows.length || p.fields?.bio ? "mt-3" : "")}>
        <span>{t("net.followers_n", { n: p.follow?.followers ?? 0 })}</span>
        <span>{t("net.following_n", { n: p.follow?.following ?? 0 })}</span>
      </div>
    </div>
  );
}
