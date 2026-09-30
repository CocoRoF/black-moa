"use client";
import { useEffect, type ReactNode } from "react";
import { Inbox, Languages, MessageSquareText, Mic, Share2, X } from "@/components/icons";
import { toast } from "sonner";
import { cn, copyText } from "@/lib/utils";
import { useLocale, useT } from "@/lib/i18n";
import { Avatar } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";
import { ProfileHeader } from "@/components/profile/ProfileHeader";
import type { PublicAgent } from "./PublicChat";

/** The secretary's profile, opened by tapping its name in the chat header.
 *
 *  Messenger apps put a person behind their name, and a secretary answering for someone is
 *  exactly the case where a visitor wants to know who they are talking to before they say
 *  anything. A cover panel carries the agent's accent so it reads as *this* secretary, and
 *  the suggested questions double as a way in for someone who does not know what to ask.
 */
export function AgentProfile({ agent, accent, online, onClose, onAsk, primary, share = true, zIndex }: {
  agent: PublicAgent; accent: string; online: boolean;
  onClose: () => void; onAsk?: (q: string) => void;
  /** The card's leading action. On the public page that is sharing the link; opened from
   *  inside the app it is talking to this secretary (plan/44 §8). */
  primary?: { label: string; icon: ReactNode; onClick: () => void };
  share?: boolean;
  /** Above whatever opened it. A card opened from a dialog has to clear that dialog. */
  zIndex?: number;
}) {
  const t = useT(); const locale = useLocale();
  // A card is a dialog, and Escape is how a dialog is left on a keyboard.
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const questions = (agent.suggested_questions ?? []).slice(0, 4);
  // A language code is not a fact about a secretary that anybody can read. "KO" becomes
  // the name of the language in the reader's own locale, and drops out when it cannot.
  const language = languageName(agent.language, locale);
  const body: { icon: ReactNode; label: string; hint?: string }[] = [
    ...(agent.leave_message_enabled
      ? [{ icon: <Inbox className="h-4 w-4" />, label: t("prof.can_message"), hint: t("prof.can_message_hint", { name: agent.owner_display_name }) }] : []),
    ...(agent.voice_enabled ? [{ icon: <Mic className="h-4 w-4" />, label: t("prof.can_voice") }] : []),
    ...(language ? [{ icon: <Languages className="h-4 w-4" />, label: language }] : []),
  ];
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" style={zIndex ? { zIndex } : undefined} role="dialog" aria-modal="true" aria-label={agent.name}>
      <button type="button" aria-label={t("common.close")} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-[2px]" />
      <div className="relative w-full max-w-[440px] overflow-hidden rounded-t-3xl border border-border bg-card shadow-2xl sm:rounded-3xl">
        <div className="relative">
          <button type="button" onClick={onClose} aria-label={t("common.close")}
                  className="absolute right-3 top-3 z-10 inline-flex h-9 w-9 items-center justify-center rounded-full bg-black/40 text-white backdrop-blur hover:bg-black/60">
            <X className="h-5 w-5" />
          </button>
          {/* The same header a person's profile uses (plan/32) — a secretary is a profile
              too, and only what hangs below it is different. */}
          <ProfileHeader
            compact accent={accent} coverUrl={agent.cover_url} avatarSrc={agent.avatar_url}
            avatar={
              /* A disc is what separates the face from the background. The bare mark reads
                 as a second shape over the product's own gradient, so it only gets the disc
                 when it is actually standing on a photo. */
              <div className={cn(agent.avatar_url || agent.cover_url ? "overflow-hidden rounded-full bg-card ring-4 ring-card" : "")}>
                <Avatar mascot name={agent.name} src={agent.avatar_url} size={112} accent={accent} shape={agent.theme?.avatar_shape} />
              </div>
            }
            name={agent.name}
            subtitle={agent.role_line || undefined}
            meta={
              <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-xs">
                <span className={`h-1.5 w-1.5 rounded-full ${agent.resting ? "bg-warning" : online ? "bg-success" : "bg-muted-fg"}`} />
                {agent.resting ? t("public.resting_short") : online ? t("public.online") : t("chat.offline")}
              </span>
            }
          />
        </div>

        {body.length || questions.length ? (
          <div className="border-t border-border px-5 py-4">
            {/* Who it answers for — only when the subtitle has not already said so. The
                greeting used to sit here too, which was the chat's own first line repeated
                underneath as though it were an attribute of the secretary. */}
            {!agent.role_line ? (
              <p className="mb-4 text-sm text-muted-fg">{t("prof.works_for", { name: agent.owner_display_name })}</p>
            ) : null}

            {questions.length ? (
              <div className="mb-4">
                <div className="text-xs font-medium text-muted-fg">{t("prof.ask_about")}</div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {questions.map((q) => (
                    <button key={q} type="button" onClick={() => { onAsk?.(q); onClose(); }}
                            className="rounded-xl border border-border px-3 py-2 text-left text-[13px] transition-colors hover:border-accent hover:bg-accent/5 hover:text-accent">
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {/* What it can do here, as a list a person reads — three grey pills in a bare
                band looked like something left behind rather than something written. */}
            {body.length ? (
              <>
                <div className="text-xs font-medium text-muted-fg">{t("prof.can_do")}</div>
                <ul className="mt-2 space-y-2">
                  {body.map((it) => (
                    <li key={it.label} className="flex items-center gap-2.5 text-sm">
                      <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent">{it.icon}</span>
                      <span className="min-w-0">
                        <span className="block truncate">{it.label}</span>
                        {it.hint ? <span className="block truncate text-xs text-muted-fg">{it.hint}</span> : null}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        ) : null}

        {/* Going back is what the X above already does, so it does not need the loudest
            button on the card. Sharing is the one thing this panel offers that the chat
            does not, so it leads. */}
        <div className="flex gap-2 border-t border-border px-5 pt-4 pb-[max(1rem,var(--sab))]">
          {primary ? (
            <Button variant="accent" className="flex-1" onClick={primary.onClick}>{primary.icon}{primary.label}</Button>
          ) : (
            <Button variant="outline" className="flex-1" onClick={onClose}>
              <MessageSquareText className="h-4 w-4" />{t("prof.back_to_chat")}
            </Button>
          )}
          {share ? (
            <Button variant={primary ? "outline" : "accent"} className="flex-1"
                    onClick={async () => { if (await copyText(window.location.href)) toast.success(t("common.copied")); }}>
              <Share2 className="h-4 w-4" />{t("public.share_link")}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** "ko" → "한국어". Returns "" when the runtime cannot name it, so a code never leaks. */
function languageName(code: string, locale: string): string {
  const tag = (code || "").trim();
  if (!tag) return "";
  try {
    const name = new Intl.DisplayNames([locale], { type: "language" }).of(tag);
    return name && name.toLowerCase() !== tag.toLowerCase() ? name : "";
  } catch {
    return "";
  }
}
