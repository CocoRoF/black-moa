"use client";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X, ZoomIn } from "@/components/icons";
import { useT } from "@/lib/i18n";
import { usePanZoom, useMeasure } from "./pan-zoom";

/** A picture, full size, the way every phone shows one.
 *
 *  A profile photo is small on purpose, and the cover is cropped to a band — so the one
 *  thing a person wants from either is to see the actual picture. Drag it, pinch or scroll
 *  or double-tap to zoom, tap the backdrop to leave.
 */
export function PhotoViewer({ src, alt, onClose }: { src: string; alt?: string; onClose: () => void }) {
  const t = useT();
  const stageRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const stage = useMeasure(stageRef);
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const { view, ready, handlers, moved } = usePanZoom({ elRef: stageRef, nat, box: stage, mode: "contain", maxZoom: 6, resetKey: src });

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", h); document.body.style.overflow = prev; };
  }, [onClose]);

  // Tap beside the picture to leave. Tapping the picture itself must not close — a tap
  // there is the first half of the double-tap that zooms, and while zoomed it is the end
  // of a pan. It has to be decided by where the finger landed, not by e.target: the stage
  // captures the pointer, so every pointerup is reported against the stage.
  const up = useCallback((e: React.PointerEvent) => {
    handlers.onPointerUp(e);
    const r = imgRef.current?.getBoundingClientRect();
    const onPicture = !!r && e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
    if (!moved.current && !onPicture) onClose();
  }, [handlers, moved, onClose]);

  if (typeof document === "undefined") return null;
  return createPortal(
    // Above the toasts: this is the only thing on screen while it is open.
    // Labelled "사진", not with the subject's name: a profile card is already a dialog
    // named after its subject, and two dialogs with one name is ambiguous to anything
    // reading the page aloud. The name is shown in the bar instead.
    <div role="dialog" aria-modal="true" aria-label={t("photo.view")} style={{ zIndex: 1_000_000_002 }}
         className="fixed inset-0 flex flex-col bg-black/95 text-white">
      <div className="flex items-center justify-between px-2 pt-[max(0.5rem,var(--sat))]">
        <span className="min-w-0 truncate pl-2 text-sm text-white/70">{alt}</span>
        <button type="button" onClick={onClose} aria-label={t("common.close")}
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full hover:bg-white/10">
          <X className="h-5 w-5" />
        </button>
      </div>
      <div ref={stageRef} {...handlers} onPointerUp={up} className="relative min-h-0 flex-1 touch-none overflow-hidden select-none">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img ref={imgRef} src={src} alt={alt ?? ""} draggable={false}
             onLoad={(e) => setNat({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
             onError={() => setFailed(true)}
             style={ready ? { position: "absolute", left: "50%", top: "50%", width: nat!.w * view.s, height: nat!.h * view.s,
                              transform: `translate(-50%, -50%) translate(${view.x}px, ${view.y}px)`, maxWidth: "none" }
                          : { position: "absolute", opacity: 0, pointerEvents: "none" }} />
        {failed ? <p className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm">{t("photo.failed")}</p> : null}
      </div>
      <p className="flex items-center justify-center gap-1.5 pb-[max(0.75rem,var(--sab))] pt-2 text-center text-xs text-white/55">
        <ZoomIn className="h-3.5 w-3.5" />{t("photo.hint")}
      </p>
    </div>,
    document.body,
  );
}

/** `view(src)` from anywhere in a component; render `node` once inside it. */
export function usePhotoViewer(): { view: (src: string, alt?: string) => void; node: ReactNode } {
  const [shown, setShown] = useState<{ src: string; alt?: string } | null>(null);
  const view = useCallback((src: string, alt?: string) => { if (src) setShown({ src, alt }); }, []);
  return { view, node: shown ? <PhotoViewer src={shown.src} alt={shown.alt} onClose={() => setShown(null)} /> : null };
}
