"use client";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ArrowDown } from "@/components/icons";
import type { ChatMessage } from "@/stores/chat";
import { useT } from "@/lib/i18n";
import { MessageBubble, type BubbleProps } from "./MessageBubble";
import { cn } from "@/lib/utils";

export interface MessageListHandle { scrollToBottom: (smooth?: boolean) => void }

interface Props extends Omit<BubbleProps, "m"> {
  messages: ChatMessage[];
  header?: ReactNode;
  footer?: ReactNode;
  className?: string;
  onStartReached?: () => void;
}

/** How close to the floor still counts as standing on it. */
const FLOOR = 48;

/** The transcript.
 *
 *  A plain scroller, deliberately. This was virtualised, and a virtualiser owns the scroll
 *  position: it placed the view against *estimated* heights, decided that was the end of
 *  the list, and parked 991px of conversation under the fold — where the newest message
 *  was. Asking it to scroll further did nothing, because by its own measurements it had
 *  already arrived. A conversation is a bounded thing (the API hands over a hundred
 *  messages) and bubbles are cheap; the browser's own scrolling is exactly right and has
 *  no second opinion about where the bottom is.
 */
export const MessageList = forwardRef<MessageListHandle, Props>(function MessageList({ messages, header, footer, className, onStartReached, ...bubble }, ref) {
  const t = useT();
  const box = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [unseen, setUnseen] = useState(0);
  const lastLen = useRef(messages.length);
  const lastContentLen = useRef(0);
  const content = useRef<HTMLDivElement>(null);
  // Whether the reader is standing on the floor. While they are, every growth of the
  // transcript — a token arriving, an image loading, markdown laying out — has to keep
  // them there. One jump at load time cannot: the page is still growing after it.
  const stick = useRef(true);
  // Set when older messages are being prepended, so the view can stay on the message the
  // reader was looking at instead of jumping to wherever that content now begins.
  const anchor = useRef<{ height: number; top: number } | null>(null);

  const scrollToBottom = useCallback((smooth = true) => {
    const el = box.current;
    if (!el) return;
    stick.current = true;
    if (smooth) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    else el.scrollTop = el.scrollHeight;
    setUnseen(0);
  }, []);
  useImperativeHandle(ref, () => ({ scrollToBottom }), [scrollToBottom]);

  /** Follow the content while the reader is on the floor.
   *
   *  Not a timer and not a one-shot jump: the transcript keeps growing after it is first
   *  rendered (markdown lays out, fonts swap, images arrive, tokens stream), and each of
   *  those pushes the newest message below the fold. Watching the content's own size is
   *  the only thing that catches all of them. */
  useEffect(() => {
    const el = box.current;
    const inner = content.current;
    if (!el || !inner) return;
    const ro = new ResizeObserver(() => { if (stick.current) el.scrollTop = el.scrollHeight; });
    ro.observe(inner);
    return () => ro.disconnect();
  }, []);

  // A different conversation is a fresh floor to stand on.
  const firstId = messages[0]?.id;
  useEffect(() => { stick.current = true; setUnseen(0); }, [firstId]);

  // Count what arrived while the reader was reading something else.
  useEffect(() => {
    const last = messages[messages.length - 1];
    const grew = messages.length > lastLen.current;
    const prepended = grew && anchor.current !== null;
    // A turn appends the reader's line and the answer's placeholder together, so "the last
    // message" is never the reader's: look at everything that arrived.
    const added = grew && !prepended ? messages.slice(lastLen.current) : [];
    if (added.some((m) => m.role === "user")) {
      // The reader just wrote: they mean to watch the answer arrive.
      stick.current = true;
      const el = box.current;
      if (el) el.scrollTop = el.scrollHeight;
      setUnseen(0);
    } else if (added.length && !stick.current) {
      setUnseen((n) => n + added.length);
    }
    lastLen.current = messages.length;
    lastContentLen.current = last?.content.length ?? 0;
  }, [messages]);

  // Older messages were just prepended: put the reader back where they were.
  useLayoutEffect(() => {
    const el = box.current;
    const a = anchor.current;
    if (!el || !a) return;
    anchor.current = null;
    el.scrollTop = a.top + (el.scrollHeight - a.height);
  }, [messages]);

  // A phone's keyboard opening, or any resize, moves the floor: stay on it.
  useEffect(() => {
    const onResize = () => { const el = box.current; if (el && stick.current) el.scrollTop = el.scrollHeight; };
    window.addEventListener("resize", onResize);
    window.visualViewport?.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); window.visualViewport?.removeEventListener("resize", onResize); };
  }, []);

  /** Only the reader lets go of the floor.
   *
   *  Scroll events do not say who caused them: a token arriving, a smooth scroll-to-bottom
   *  still in flight, and the browser correcting a height all fire the same event as a
   *  finger dragging the transcript up. The old rule — "not at the bottom ⇒ stop
   *  following" — read every one of those as the reader leaving, so following broke a few
   *  tokens into almost every answer. Now a *gesture* (wheel, touch, keyboard, scrollbar
   *  drag) arms a short window, and only a scroll inside that window can unstick; reaching
   *  the bottom, by any means, sticks again. */
  const gesture = useRef(0);
  const armGesture = useCallback(() => { gesture.current = Date.now(); }, []);
  const onScroll = useCallback(() => {
    const el = box.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.clientHeight - el.scrollTop <= FLOOR;
    const byReader = Date.now() - gesture.current < 400;
    if (bottom) stick.current = true;
    else if (byReader) stick.current = false;
    setAtBottom(bottom);
    if (bottom) setUnseen(0);
    if (el.scrollTop < 200 && byReader && onStartReached) {
      anchor.current = { height: el.scrollHeight, top: el.scrollTop };
      onStartReached();
    }
  }, [onStartReached]);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const up = (e: WheelEvent) => { if (e.deltaY < 0) armGesture(); };
    const key = (e: KeyboardEvent) => { if (["ArrowUp", "PageUp", "Home"].includes(e.key)) armGesture(); };
    el.addEventListener("wheel", up, { passive: true });
    el.addEventListener("touchmove", armGesture, { passive: true });
    el.addEventListener("pointerdown", armGesture, { passive: true });   // a scrollbar drag starts here
    el.addEventListener("keydown", key);
    return () => { el.removeEventListener("wheel", up); el.removeEventListener("touchmove", armGesture); el.removeEventListener("pointerdown", armGesture); el.removeEventListener("keydown", key); };
  }, [armGesture]);

  return (
    <div className={cn("relative flex-1 min-h-0", className)}>
      <div ref={box} onScroll={onScroll} className="h-full overflow-y-auto scrollbar-thin"
           style={{ overscrollBehavior: "contain" }}>
        {/* One element to measure: the observer watches this, not the scroller, because the
            scroller's own size never changes — only what is inside it does. */}
        <div ref={content}>
          {header}
          <div className="h-2" />
          {messages.map((m) => <MessageBubble key={m.id} m={m} {...bubble} />)}
          {footer}
          <div className="h-3" />
        </div>
      </div>
      {(!atBottom && (unseen > 0 || messages.length > 4)) ? (
        <button type="button" onClick={() => scrollToBottom(true)} aria-label={t("chat.new_messages")}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 inline-flex h-9 items-center gap-1.5 rounded-full border border-border bg-card px-3 text-xs font-medium shadow-lg fade-up">
          <ArrowDown className="h-3.5 w-3.5" />{unseen > 0 ? t("chat.new_messages_n", { n: unseen }) : t("chat.scroll_bottom")}
        </button>
      ) : null}
    </div>
  );
});
