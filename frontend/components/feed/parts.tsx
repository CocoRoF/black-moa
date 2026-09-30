"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Heart, MessageCircle } from "@/components/icons";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Face } from "@/components/profile/Face";

/** A caption with the people it names turned back into the addresses they are (plan/42 §11).
 *
 *  Only the people the server resolved are linked, and each is painted as a chip: a name
 *  that looks like plain words is not a link, and nobody presses it. Every other @word is
 *  left as the plain text somebody typed, because guessing hands readers dead links. */
export interface Mention { id: string; label: string; handle: string; agent?: boolean; code?: string }

export function Caption({ text, mentions, className, onNavigate }: {
  text: string; mentions?: Mention[]; className?: string; onNavigate?: () => void;
}) {
  const named = mentions ?? [];
  if (!named.length) return <span className={className}>{text}</span>;
  // Longest first: "@장하" must not win over "@장하렴" when both were named.
  const order = [...named].sort((a, b) => b.label.length - a.label.length);
  const out: React.ReactNode[] = [];
  let rest = text;
  let key = 0;
  while (rest) {
    let best: { at: number; who: Mention } | null = null;
    for (const who of order) {
      const at = rest.indexOf(`@${who.label}`);
      if (at >= 0 && (best === null || at < best.at)) best = { at, who };
    }
    if (!best) { out.push(<span key={key++}>{rest}</span>); break; }
    if (best.at) out.push(<span key={key++}>{rest.slice(0, best.at)}</span>);
    const { who } = best;
    // A secretary whose door has since closed is left as the words somebody typed: a chip
    // that leads nowhere is worse than no chip.
    if (who.agent && !who.code) {
      out.push(<span key={key++}>@{who.label}</span>);
      rest = rest.slice(best.at + who.label.length + 1);
      continue;
    }
    out.push(
      who.agent
        // A secretary has no page of its own. Its name opens the card the public chat
        // shows for it, with [대화하기] on it (plan/44 §8).
        ? <Face key={key++} agentId={who.id} stop={false} className="rounded bg-accent/10 px-0.5 font-medium text-accent hover:bg-accent/20">@{who.label}</Face>
        : <Link key={key++} onClick={onNavigate} href={who.handle ? `/@${who.handle}` : `/app/u/${who.id}`}
                className="rounded bg-accent/10 font-medium text-accent hover:bg-accent/20">@{who.label}</Link>,
    );
    rest = rest.slice(best.at + who.label.length + 1);
  }
  return <span className={className}>{out}</span>;
}

/** The frame takes the shape of the first picture rather than cropping everything to one
 *  ratio — a landscape photo squeezed into a portrait box loses its sides, which is the
 *  author's picture being edited by us. Clamped at both ends so a very tall one cannot push
 *  the rest of the card off the screen. */
const TALLEST = 5 / 4;
const WIDEST = 1 / 1.91;

export function Photos({ urls, fit = "ratio", className, at: told, onAt }: {
  urls: string[]; fit?: "ratio" | "fill"; className?: string;
  /** Whoever needs to know which one is on screen says so and hears it back. */
  at?: number; onAt?: (n: number) => void;
}) {
  const [mine, setMine] = useState(0);
  const at = told ?? mine;
  const setAt = (n: number) => { setMine(n); onAt?.(n); };
  const [ratio, setRatio] = useState<number | null>(null);
  const strip = useRef<HTMLDivElement | null>(null);
  const go = (n: number) => {
    const el = strip.current;
    if (el) el.scrollTo({ left: n * el.clientWidth, behavior: "smooth" });
    setAt(n);
  };
  // Somebody removed the one on screen: follow the strip to where it landed.
  useEffect(() => {
    const el = strip.current;
    if (el && Math.round(el.scrollLeft / Math.max(1, el.clientWidth)) !== at) el.scrollTo({ left: at * el.clientWidth });
  }, [at, urls.length]);
  return (
    <div className={cn("relative bg-fg/90", className)}>
      <div ref={strip}
           onScroll={(e) => setAt(Math.round(e.currentTarget.scrollLeft / Math.max(1, e.currentTarget.clientWidth)))}
           className={cn("flex snap-x snap-mandatory overflow-x-auto scrollbar-none", fit === "fill" && "h-full")}
           style={fit === "ratio" ? { aspectRatio: ratio ? `1 / ${ratio}` : "1 / 1" } : undefined}>
        {urls.map((u, i) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={u} src={u} alt="" loading={i === 0 ? "eager" : "lazy"}
               onLoad={i === 0 ? (e) => {
                 const el = e.currentTarget;
                 if (el.naturalWidth) setRatio(Math.min(TALLEST, Math.max(WIDEST, el.naturalHeight / el.naturalWidth)));
               } : undefined}
               className="h-full w-full shrink-0 snap-center object-contain" />
        ))}
      </div>
      {urls.length > 1 ? (
        <>
          <Arrow side="left" show={at > 0} onClick={() => go(at - 1)} />
          <Arrow side="right" show={at < urls.length - 1} onClick={() => go(at + 1)} />
          <div className="pointer-events-none absolute inset-x-0 bottom-2 flex justify-center gap-1.5">
            {urls.map((u, i) => <span key={u} className={cn("h-1.5 w-1.5 rounded-full", i === at ? "bg-white" : "bg-white/50")} />)}
          </div>
        </>
      ) : null}
    </div>
  );
}

function Arrow({ side, show, onClick }: { side: "left" | "right"; show: boolean; onClick: () => void }) {
  if (!show) return null;
  return (
    // Stopped here: the frame around the strip opens the post, and turning to the next
    // photo is not asking for that.
    <button type="button" aria-label={side} onClick={(e) => { e.stopPropagation(); onClick(); }}
            className={cn("absolute top-1/2 -translate-y-1/2 rounded-full bg-bg/85 p-1.5 shadow", side === "left" ? "left-2" : "right-2")}>
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
        <path d={side === "left" ? "M15 18l-6-6 6-6" : "M9 18l6-6-6-6"} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );
}

/** Pictures arrive by drop anywhere on the window, not only onto a marked rectangle. */
export function useFileDrop(onFiles: (f: File[]) => void, active: boolean) {
  const [over, setOver] = useState(false);
  const latest = useRef(onFiles);
  latest.current = onFiles;
  useEffect(() => {
    if (!active) { setOver(false); return; }
    const stop = (e: DragEvent) => e.preventDefault();
    const enter = (e: DragEvent) => { e.preventDefault(); setOver(true); };
    const leave = (e: DragEvent) => { e.preventDefault(); if (!e.relatedTarget) setOver(false); };
    const drop = (e: DragEvent) => {
      e.preventDefault(); setOver(false);
      const files = Array.from(e.dataTransfer?.files ?? []).filter((f) => f.type.startsWith("image/"));
      if (files.length) latest.current(files);
    };
    window.addEventListener("dragover", stop);
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", stop);
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [active]);
  return over;
}

/** Anything pasted while this is on, wherever the caret is. A picture in the clipboard is
 *  the most common way one arrives, and it must land in the window you are writing in. */
export function usePaste(onFiles: (f: File[]) => void, active: boolean) {
  const latest = useRef(onFiles);
  latest.current = onFiles;
  useEffect(() => {
    if (!active) return;
    const paste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.files ?? []).filter((f) => f.type.startsWith("image/"));
      if (files.length) { e.preventDefault(); latest.current(files); }
    };
    window.addEventListener("paste", paste);
    return () => window.removeEventListener("paste", paste);
  }, [active]);
}

/** What you can do to a post (plan/42 §5).
 *
 *  The same row on the card and in the modal, in the same place, so pressing 좋아요 is one
 *  gesture wherever the post is being read. */
export function Actions({ liked, onLike, onComment }: {
  liked: boolean; onLike: () => void; onComment: () => void;
}) {
  const t = useT();
  return (
    <div className="flex items-center gap-1 px-2.5 pt-2 text-muted-fg">
      <button type="button" aria-pressed={liked} aria-label={t("feed.like")} onClick={onLike}
              className={cn("rounded-lg p-2 hover:bg-muted", liked && "text-accent")}>
        <Heart className={cn("h-[22px] w-[22px]", liked && "fill-current")} />
      </button>
      <button type="button" aria-label={t("feed.comments")} onClick={onComment}
              className="rounded-lg p-2 hover:bg-muted">
        <MessageCircle className="h-[22px] w-[22px]" />
      </button>
    </div>
  );
}

/** What everyone already did, at zero too.
 *
 *  A tally that appears only once somebody presses something makes the card jump under the
 *  reader's thumb and leaves an empty gap where a number belongs. It is always two numbers,
 *  always in the same place. */
export function Counts({ likes, comments, onComments }: {
  likes: number; comments: number; onComments?: () => void;
}) {
  const t = useT();
  const n = <span className="font-medium text-fg">{t("feed.likes_n", { n: likes })}</span>;
  const c = t("feed.comments_n", { n: comments });
  return (
    <div className="flex items-center gap-3 px-4 pb-2.5 pt-1 text-sm text-muted-fg">
      {n}
      {onComments ? <button type="button" onClick={onComments} className="tap-area hover:underline">{c}</button> : <span>{c}</span>}
    </div>
  );
}

/** The line between what was done to a post and what the post says. Barely there: it is a
 *  change of subject, not a border. */
export function Rule() {
  return <div className="mx-4 border-t border-border/50" />;
}

/** Words on a card, cut at four lines with a way into the rest (plan/42 §14).
 *
 *  A card is a glance. A note runs to a thousand characters, and a card that draws all of
 *  it pushes the next post off the screen — so the card shows the top and the window shows
 *  the whole thing. Measured rather than counted: whether it overflows depends on the
 *  screen, and a character count guesses wrong on both.
 */
export function Clamped({ children, onMore, watch }: {
  children: React.ReactNode; onMore: () => void;
  /** The text inside, so a post that was edited is measured again. */
  watch?: string;
}) {
  const t = useT();
  const box = useRef<HTMLDivElement | null>(null);
  const [over, setOver] = useState(false);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const look = () => setOver(el.scrollHeight - el.clientHeight > 2);
    look();
    const ro = new ResizeObserver(look);
    ro.observe(el);
    return () => ro.disconnect();
  }, [watch]);
  return (
    <>
      <div ref={box} className="line-clamp-4">{children}</div>
      {over ? (
        <button type="button" onClick={onMore} className="mt-0.5 text-sm text-muted-fg hover:underline">
          {t("feed.more")}
        </button>
      ) : null}
    </>
  );
}
