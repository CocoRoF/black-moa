"use client";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

export interface View { s: number; x: number; y: number }

/** Drag, pinch, wheel and double-tap over a picture.
 *
 *  Shared by the cropper and the photo viewer, because a picture behaves the same way in
 *  both hands: the only difference is where it starts. `cover` fills the window, so a crop
 *  frame can never show through; `contain` fits the whole picture inside it, which is how a
 *  viewer should open.
 *
 *  `box` is the window the picture is seen through — the crop frame, or the whole stage.
 *  Everything is measured from its centre, so the same clamp works for both modes: at the
 *  contain fit the picture is smaller than the box and cannot move at all.
 */
export function usePanZoom({ elRef, nat, box, mode, maxZoom = 8, resetKey, doubleTap = true }: {
  elRef: RefObject<HTMLElement | null>;
  nat: { w: number; h: number } | null;
  box: { w: number; h: number };
  mode: "cover" | "contain";
  maxZoom?: number;
  /** Change this (a new file, a new photo) to refit; a resize keeps the framing instead. */
  resetKey?: unknown;
  doubleTap?: boolean;
}) {
  const ready = !!nat && box.w > 0 && box.h > 0;
  const nw = nat?.w ?? 1, nh = nat?.h ?? 1;
  const base = ready ? (mode === "cover" ? Math.max(box.w / nw, box.h / nh) : Math.min(box.w / nw, box.h / nh)) : 1;
  // One object, not three: a zoom has to re-clamp the pan in the same commit, and two
  // states meant a frame where the picture had left the frame.
  const [view, setView] = useState<View>({ s: 1, x: 0, y: 0 });

  const clamp = useCallback((v: View): View => {
    if (!ready) return v;
    const s = Math.min(Math.max(v.s, base), base * maxZoom);
    const mx = Math.max(0, (nw * s - box.w) / 2);
    const my = Math.max(0, (nh * s - box.h) / 2);
    return { s, x: Math.min(Math.max(v.x, -mx), mx), y: Math.min(Math.max(v.y, -my), my) };
  }, [ready, base, maxZoom, nw, nh, box.w, box.h]);

  const fitted = useRef(false);
  useEffect(() => { fitted.current = false; }, [resetKey]);
  useEffect(() => {
    if (!ready) return;
    if (fitted.current) { setView((v) => clamp(v)); return; }   // the box resized: keep the framing, re-clamp it
    fitted.current = true;
    setView({ s: base, x: 0, y: 0 });
  }, [ready, base, clamp]);

  /** Zoom about a point given relative to the box centre, so what is under the fingers
   *  stays under them — everything sliding out from under a pinch is what makes a picture
   *  feel broken. */
  const zoomBy = useCallback((factor: number, at?: { dx: number; dy: number }) => {
    setView((v) => {
      const s = Math.min(Math.max(v.s * factor, base), base * maxZoom);
      const k = s / v.s;
      const px = at?.dx ?? 0, py = at?.dy ?? 0;
      return clamp({ s, x: px + (v.x - px) * k, y: py + (v.y - py) * k });
    });
  }, [base, maxZoom, clamp]);

  const centreOf = useCallback((clientX: number, clientY: number) => {
    const r = elRef.current?.getBoundingClientRect();
    return r ? { dx: clientX - (r.left + r.width / 2), dy: clientY - (r.top + r.height / 2) } : { dx: 0, dy: 0 };
  }, [elRef]);

  // Pointers by id: one is a pan, two are a pinch. A pointer that vanishes (a cancel, a
  // palm) just leaves the map, so the gesture degrades instead of freezing mid-drag.
  const pts = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ dist: number; cx: number; cy: number } | null>(null);
  const tap = useRef<{ at: number; x: number; y: number } | null>(null);
  /** Whether the gesture that just ended actually moved — a tap is not a drag. */
  const moved = useRef(false);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    pts.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    try { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
    if (pts.current.size === 1) moved.current = false;
    if (pts.current.size === 2) pinch.current = pinchOf(pts.current);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const prev = pts.current.get(e.pointerId);
    if (!prev) return;
    pts.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (Math.abs(e.clientX - prev.x) + Math.abs(e.clientY - prev.y) > 2) moved.current = true;
    if (pts.current.size >= 2) {
      const g = pinchOf(pts.current);
      const was = pinch.current;
      pinch.current = g;
      if (was && was.dist > 0) {
        setView((v) => clamp({ ...v, x: v.x + (g.cx - was.cx), y: v.y + (g.cy - was.cy) }));
        zoomBy(g.dist / was.dist, centreOf(g.cx, g.cy));
      }
      return;
    }
    setView((v) => clamp({ ...v, x: v.x + (e.clientX - prev.x), y: v.y + (e.clientY - prev.y) }));
  }, [clamp, zoomBy, centreOf]);

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    pts.current.delete(e.pointerId);
    if (pts.current.size < 2) pinch.current = null;
    if (!doubleTap || moved.current || pts.current.size) return;
    const now = Date.now(); const last = tap.current;
    tap.current = { at: now, x: e.clientX, y: e.clientY };
    if (last && now - last.at < 320 && Math.hypot(e.clientX - last.x, e.clientY - last.y) < 32) {
      tap.current = null;
      // Second tap on an already-zoomed picture means "put it back", not "closer still".
      if (view.s > base * 1.05) setView({ s: base, x: 0, y: 0 });
      else zoomBy(2.5, centreOf(e.clientX, e.clientY));
    }
  }, [doubleTap, base, view.s, zoomBy, centreOf]);

  // React attaches wheel passively, and a page that scrolls behind a picture while you are
  // zooming it is worse than no wheel zoom at all.
  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    const h = (e: WheelEvent) => { e.preventDefault(); zoomBy(Math.exp(-e.deltaY / 400), centreOf(e.clientX, e.clientY)); };
    el.addEventListener("wheel", h, { passive: false });
    return () => el.removeEventListener("wheel", h);
  }, [elRef, zoomBy, centreOf]);

  return { view, setView, base, ready, clamp, zoomBy, moved,
           handlers: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: onPointerUp } };
}

function pinchOf(pts: Map<number, { x: number; y: number }>) {
  const [a, b] = Array.from(pts.values());
  return { dist: Math.hypot(a.x - b.x, a.y - b.y), cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 };
}

/** The element's live size. Both surfaces need it, and both need it to survive a rotation. */
export function useMeasure(ref: RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}
