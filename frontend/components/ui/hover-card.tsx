"use client";
/** 올려 두면 보이는 것 — 화면 어디서나 같은 부품 하나.
 *
 *  예전 Tooltip 은 트리거 옆에 `absolute` 로 붙어 있었다. 그러면 스크롤되는 상자나
 *  `overflow:hidden` 인 카드 안에서는 잘리고, 화면 가장자리에서는 반쯤 밖으로 나가고,
 *  한 줄짜리라 긴 내용은 담지 못했다. 여기서는 그 셋을 한 번에 해결한다.
 *
 *  - **body 로 띄운다(portal).** 어떤 부모의 overflow·transform 에도 잘리지 않는다.
 *  - **자리를 스스로 고른다.** 원하는 쪽에 자리가 없으면 반대쪽으로 뒤집고, 화면 안으로
 *    밀어 넣고, 화살표는 트리거의 가운데를 계속 가리킨다. 스크롤·창 크기·내용 크기가
 *    바뀌면 다시 잰다.
 *  - **옮겨 갈 수 있다(interactive).** 트리거에서 카드로 손을 옮기는 동안 닫히지 않아서
 *    카드 안의 글을 고르거나 링크를 누를 수 있다.
 *  - **손·키보드·손가락 모두.** 키보드로 초점이 가면 열리고, Esc 로 닫히고, 터치에서는
 *    눌러서 열고 바깥을 눌러 닫는다.
 *  - **한 번에 하나.** 달력 칸을 훑고 지나갈 때 카드가 겹겹이 쌓이지 않는다.
 *
 *  잘렸을 때만 보여 주고 싶으면 `useOverflow` 로 잰 값을 `disabled` 에 넘긴다. */
import {
  useCallback, useEffect, useId, useLayoutEffect, useRef, useState,
  type CSSProperties, type ReactNode, type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

export type HoverSide = "top" | "bottom" | "left" | "right";
export type HoverAlign = "start" | "center" | "end";

export interface HoverCardProps {
  /** 올려 두면 보일 내용. 글 한 줄이어도, 목록이어도, 링크가 든 카드여도 된다. */
  content: ReactNode;
  children: ReactNode;
  side?: HoverSide;
  align?: HoverAlign;
  /** 스쳐 지나갈 때마다 열리면 시끄럽다. 잠깐 머물러야 연다. */
  openDelay?: number;
  /** 카드로 손을 옮기는 사이에 닫히지 않을 만큼. */
  closeDelay?: number;
  /** 카드 안으로 들어갈 수 있는가. 끄면 손이 트리거를 떠나는 즉시 닫힌다. */
  interactive?: boolean;
  disabled?: boolean;
  /** 카드 모양: 밝은 면의 카드(`card`) 또는 짧은 검은 말풍선(`tip`). */
  tone?: "card" | "tip";
  maxWidth?: number;
  offset?: number;
  arrow?: boolean;
  /** 트리거를 감쌀 태그. 칸 하나를 통째로 트리거로 쓰려면 `div`. */
  as?: "span" | "div" | "li";
  className?: string;
  style?: CSSProperties;
  contentClassName?: string;
  /** 키보드로 이 트리거에 올 수 있는가. 본래 초점을 받지 못하는 칸도 열 수 있게. */
  focusable?: boolean;
}

const PAD = 8;
const OPPOSITE: Record<HoverSide, HoverSide> = { top: "bottom", bottom: "top", left: "right", right: "left" };

interface Placement { x: number; y: number; side: HoverSide; arrow: number }

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** 카드가 설 자리. 좌표는 화면 기준(`position: fixed`)이라 스크롤을 더하지 않는다. */
export function placeCard(tr: DOMRect, cw: number, ch: number, want: HoverSide, align: HoverAlign, offset: number,
                          vw = window.innerWidth, vh = window.innerHeight): Placement {
  const room: Record<HoverSide, number> = { top: tr.top, bottom: vh - tr.bottom, left: tr.left, right: vw - tr.right };
  const vertical = (s: HoverSide) => s === "top" || s === "bottom";
  const need = (s: HoverSide) => (vertical(s) ? ch : cw) + offset + PAD;
  // 원하는 쪽에 자리가 없고 반대쪽이 더 넓으면 뒤집는다. 둘 다 좁으면 넓은 쪽.
  let side = want;
  if (room[want] < need(want) && room[OPPOSITE[want]] > room[want]) side = OPPOSITE[want];

  let x: number; let y: number; let arrow: number;
  if (vertical(side)) {
    y = side === "top" ? tr.top - ch - offset : tr.bottom + offset;
    x = align === "start" ? tr.left : align === "end" ? tr.right - cw : tr.left + tr.width / 2 - cw / 2;
    x = clamp(x, PAD, Math.max(PAD, vw - cw - PAD));
    y = clamp(y, PAD, Math.max(PAD, vh - ch - PAD));
    arrow = clamp(tr.left + tr.width / 2 - x, 14, cw - 14);
  } else {
    x = side === "left" ? tr.left - cw - offset : tr.right + offset;
    y = align === "start" ? tr.top : align === "end" ? tr.bottom - ch : tr.top + tr.height / 2 - ch / 2;
    x = clamp(x, PAD, Math.max(PAD, vw - cw - PAD));
    y = clamp(y, PAD, Math.max(PAD, vh - ch - PAD));
    arrow = clamp(tr.top + tr.height / 2 - y, 14, ch - 14);
  }
  return { x, y, side, arrow };
}

/** 지금 열려 있는 카드를 닫는 손잡이. 한 번에 하나만 연다. */
let closeOpen: (() => void) | null = null;

export function HoverCard({
  content, children, side = "top", align = "center", openDelay = 220, closeDelay = 140,
  interactive = true, disabled = false, tone = "card", maxWidth = 360, offset = 8, arrow = true,
  as: Tag = "span", className, style, contentClassName, focusable = false,
}: HoverCardProps) {
  const id = useId();
  const triggerRef = useRef<HTMLElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<Placement | null>(null);
  const openTimer = useRef<number | null>(null);
  const closeTimer = useRef<number | null>(null);

  const clearTimers = () => {
    if (openTimer.current) { window.clearTimeout(openTimer.current); openTimer.current = null; }
    if (closeTimer.current) { window.clearTimeout(closeTimer.current); closeTimer.current = null; }
  };
  const hide = useCallback(() => {
    clearTimers();
    setOpen(false);
    setPlace(null);
    if (closeOpen === hideRef.current) closeOpen = null;
  }, []);
  const hideRef = useRef(hide);
  hideRef.current = hide;

  const show = useCallback(() => {
    if (disabled) return;
    clearTimers();
    if (closeOpen && closeOpen !== hideRef.current) closeOpen();
    closeOpen = hideRef.current;
    setOpen(true);
  }, [disabled]);

  const scheduleOpen = () => {
    if (disabled) return;
    if (closeTimer.current) { window.clearTimeout(closeTimer.current); closeTimer.current = null; }
    if (open || openTimer.current) return;
    openTimer.current = window.setTimeout(() => { openTimer.current = null; show(); }, openDelay);
  };
  const scheduleClose = (delay = closeDelay) => {
    if (openTimer.current) { window.clearTimeout(openTimer.current); openTimer.current = null; }
    if (!open) return;
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => { closeTimer.current = null; hide(); }, delay);
  };

  // 끄면 즉시 닫는다 (잘렸던 것이 풀린 경우 등).
  useEffect(() => { if (disabled && open) hide(); }, [disabled, open, hide]);
  useEffect(() => () => { clearTimers(); if (closeOpen === hideRef.current) closeOpen = null; }, []);

  // 자리 재기: 먼저 보이지 않게 그려 크기를 재고, 그 크기로 자리를 정한다.
  const measure = useCallback(() => {
    const t = triggerRef.current; const c = cardRef.current;
    if (!t || !c) return;
    const tr = t.getBoundingClientRect();
    // 트리거가 화면 밖으로 스크롤돼 나갔으면 카드만 떠 있지 않게 닫는다.
    if (tr.bottom < 0 || tr.top > window.innerHeight || tr.right < 0 || tr.left > window.innerWidth) { hide(); return; }
    setPlace(placeCard(tr, c.offsetWidth, c.offsetHeight, side, align, offset));
  }, [side, align, offset, hide]);

  useLayoutEffect(() => {
    if (!open) return;
    measure();
    const onMove = () => measure();
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(onMove) : null;
    if (ro && cardRef.current) ro.observe(cardRef.current);
    if (ro && triggerRef.current) ro.observe(triggerRef.current);
    return () => {
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
      ro?.disconnect();
    };
  }, [open, measure]);

  // Esc 로 닫고, 터치로 연 것은 바깥을 누르면 닫는다.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { hide(); triggerRef.current?.focus?.(); } };
    const onDown = (e: PointerEvent) => {
      const n = e.target as Node;
      if (triggerRef.current?.contains(n) || cardRef.current?.contains(n)) return;
      hide();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown, true);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("pointerdown", onDown, true); };
  }, [open, hide]);

  const triggerProps = {
    ref: (el: HTMLElement | null) => { triggerRef.current = el; },
    className,
    style,
    tabIndex: focusable && !disabled ? 0 : undefined,
    "aria-describedby": open ? id : undefined,
    onPointerEnter: (e: React.PointerEvent) => { if (e.pointerType !== "touch") scheduleOpen(); },
    onPointerLeave: (e: React.PointerEvent) => { if (e.pointerType !== "touch") scheduleClose(interactive ? closeDelay : 0); },
    // 터치에는 "올려 두기" 가 없다. 눌러서 열고 닫는다.
    onPointerUp: (e: React.PointerEvent) => { if (e.pointerType === "touch" && !disabled) { if (open) hide(); else show(); } },
    onFocus: (e: React.FocusEvent) => {
      // 마우스로 눌러서 생긴 초점에는 열지 않는다 — 누르면 그 칸의 일을 하려는 것이다.
      const el = e.currentTarget as HTMLElement;
      if (el.matches?.(":focus-visible")) show();
    },
    onBlur: (e: React.FocusEvent) => {
      if (cardRef.current?.contains(e.relatedTarget as Node)) return;
      scheduleClose(0);
    },
  };

  const card = open && typeof document !== "undefined" ? createPortal(
    <div
      ref={cardRef}
      id={id}
      role="tooltip"
      onPointerEnter={() => { if (interactive && closeTimer.current) { window.clearTimeout(closeTimer.current); closeTimer.current = null; } }}
      onPointerLeave={(e) => { if (e.pointerType !== "touch") scheduleClose(); }}
      onBlur={(e) => { if (!triggerRef.current?.contains(e.relatedTarget as Node) && !cardRef.current?.contains(e.relatedTarget as Node)) scheduleClose(0); }}
      data-side={place?.side ?? side}
      className={cn(
        "hover-card fixed left-0 top-0 z-[120]",
        tone === "tip"
          ? "rounded-lg bg-fg px-2.5 py-1.5 text-xs text-bg shadow-lg"
          : "rounded-xl border border-border bg-card p-3 text-sm text-fg shadow-xl",
        interactive ? "pointer-events-auto" : "pointer-events-none",
        contentClassName,
      )}
      style={{
        maxWidth: `min(${maxWidth}px, calc(100vw - ${PAD * 2}px))`,
        transform: place ? `translate3d(${Math.round(place.x)}px, ${Math.round(place.y)}px, 0)` : "translate3d(-9999px, -9999px, 0)",
        visibility: place ? "visible" : "hidden",
      }}
    >
      {content}
      {arrow && place ? (
        <span aria-hidden className={cn("hover-card-arrow absolute h-2.5 w-2.5 rotate-45",
          tone === "tip" ? "bg-fg" : "border-border bg-card",
          place.side === "top" && "-bottom-[5px] border-b border-r",
          place.side === "bottom" && "-top-[5px] border-l border-t",
          place.side === "left" && "-right-[5px] border-r border-t",
          place.side === "right" && "-left-[5px] border-b border-l")}
          style={place.side === "top" || place.side === "bottom"
            ? { left: place.arrow - 5 } : { top: place.arrow - 5 }} />
      ) : null}
    </div>,
    document.body,
  ) : null;

  return (
    <>
      <Tag {...(triggerProps as Record<string, unknown>)}>{children}</Tag>
      {card}
    </>
  );
}

/** 짧은 설명 한 줄. 같은 부품의 검은 말풍선 모양이다. */
export function Tooltip({ content, children, side = "top", className }: { content: ReactNode; children: ReactNode; side?: HoverSide; className?: string }) {
  return (
    <HoverCard content={content} side={side} tone="tip" interactive={false} openDelay={120} closeDelay={0}
               maxWidth={280} className={cn("inline-flex", className)}>
      {children}
    </HoverCard>
  );
}

/** 이 상자의 내용이 잘렸는가. 잘렸을 때만 호버로 전체를 보여 주려고 쓴다.
 *
 *  상자 자체가 넘치거나(세로·가로), 안에서 `data-truncate` 를 단 줄 하나라도 말줄임이
 *  됐으면 잘린 것이다. 글이 바뀌어도 크기는 그대로인 칸이 많아서, 그리기마다 다시 잰다. */
export function useOverflow<T extends HTMLElement>(): [RefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null);
  const [over, setOver] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => {
      const lines = Array.from(el.querySelectorAll<HTMLElement>("[data-truncate]"));
      const cut = el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1
        || lines.some((l) => l.scrollWidth > l.clientWidth + 1);
      setOver((prev) => (prev === cut ? prev : cut));
    };
    check();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(check) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  });
  return [ref, over];
}
