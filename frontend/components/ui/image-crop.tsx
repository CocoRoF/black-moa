"use client";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Check, Minus, Plus, X } from "@/components/icons";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { usePanZoom, useMeasure } from "./pan-zoom";

/** Which hole the picture is being fitted into. `circle` is an avatar, `cover` the
 *  background behind one. Both crop the same way; only the frame differs. */
export type CropShape = "circle" | "cover";

/** A cover is the whole top of a profile with the face in the middle of it, so it is
 *  framed at the same 3:2 the profile header shows — what you frame is what appears. */
const COVER_RATIO = 2 / 3;
const OUT_MAX = { circle: 640, cover: 1600 };
const MAX_ZOOM = 8;

/** Pick a photo, then choose what part of it is the photo.
 *
 *  Uploading used to mean handing over a file and finding out afterwards which square of it
 *  survived — a portrait taken in portrait lost its face to a centre crop. Here the crop is
 *  the thing being chosen: drag to move, pinch or scroll or drag the slider to zoom, and
 *  what is inside the ring is exactly what is saved.
 */
export function CropDialog({ file, shape, onCancel, onDone }: {
  file: File; shape: CropShape; onCancel: () => void; onDone: (f: File) => void;
}) {
  const t = useT();
  const [url, setUrl] = useState<string>("");
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const stageRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const stage = useMeasure(stageRef);
  const box = frameOf(shape, stage);
  const { view, setView, base, ready, clamp, zoomBy, handlers } =
    usePanZoom({ elRef: stageRef, nat, box, mode: "cover", maxZoom: MAX_ZOOM, resetKey: `${file.name}:${shape}` });

  useEffect(() => {
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", h);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", h); document.body.style.overflow = prev; };
  }, [onCancel]);

  const save = useCallback(async () => {
    const img = imgRef.current;
    if (!img || !nat || !box.w) return;
    setBusy(true);
    try {
      onDone(await render(img, nat, box, view, shape, file.name));
    } catch {
      setFailed(true);
    } finally { setBusy(false); }
  }, [nat, box, view, shape, file.name, onDone]);

  if (typeof document === "undefined") return null;
  const zoomPct = ready ? Math.round((view.s / base) * 100) : 100;
  return createPortal(
    // Above the toasts, deliberately: a "saved" toast lands top-centre, which on a phone is
    // exactly where this dialog's title and buttons are — tapping X did nothing until the
    // toast expired.
    <div role="dialog" aria-modal="true" aria-label={t("crop.title")} style={{ zIndex: 1_000_000_001 }}
         className="fixed inset-0 flex flex-col bg-black/95 text-white">
      <div className="flex items-center justify-between gap-2 px-2 pt-[max(0.5rem,var(--sat))]">
        <button type="button" onClick={onCancel} aria-label={t("common.cancel")}
                className="inline-flex h-10 w-10 items-center justify-center rounded-full hover:bg-white/10"><X className="h-5 w-5" /></button>
        <span className="text-sm font-medium">{t(shape === "circle" ? "crop.title" : "crop.title_cover")}</span>
        <button type="button" onClick={() => void save()} disabled={!ready || busy} aria-label={t("common.done")}
                className="inline-flex h-10 items-center gap-1.5 rounded-full px-4 text-sm font-medium text-accent-fg bg-accent disabled:opacity-50">
          <Check className="h-4 w-4" />{t("common.done")}
        </button>
      </div>

      <div ref={stageRef} {...handlers} className="relative min-h-0 flex-1 touch-none overflow-hidden select-none">
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img ref={imgRef} src={url} alt="" draggable={false}
               onLoad={(e) => setNat({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
               onError={() => setFailed(true)}
               style={ready ? { position: "absolute", left: "50%", top: "50%", width: nat!.w * view.s, height: nat!.h * view.s,
                                transform: `translate(-50%, -50%) translate(${view.x}px, ${view.y}px)`, maxWidth: "none" }
                            : { position: "absolute", opacity: 0, pointerEvents: "none" }} />
        ) : null}
        {ready ? (
          <div aria-hidden className={cn("pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 border border-white/70",
                                          shape === "circle" ? "rounded-full" : "rounded-xl")}
               style={{ width: box.w, height: box.h, boxShadow: "0 0 0 9999px rgba(0,0,0,0.6)" }} />
        ) : null}
        {failed ? <p className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm">{t("crop.failed")}</p> : null}
      </div>

      <div className="flex items-center gap-3 px-5 pb-[max(1rem,var(--sab))] pt-4">
        <button type="button" aria-label={t("crop.zoom_out")} onClick={() => zoomBy(1 / 1.2)}
                className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 hover:bg-white/20"><Minus className="h-4 w-4" /></button>
        <input type="range" min={100} max={MAX_ZOOM * 100} value={zoomPct} aria-label={t("crop.zoom")}
               onChange={(e) => setView((v) => clamp({ ...v, s: base * (Number(e.target.value) / 100) }))}
               className="h-1.5 min-w-0 flex-1 cursor-pointer appearance-none rounded-full bg-white/25 accent-white" />
        <button type="button" aria-label={t("crop.zoom_in")} onClick={() => zoomBy(1.2)}
                className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 hover:bg-white/20"><Plus className="h-4 w-4" /></button>
      </div>
      <p className="pb-[max(0.75rem,var(--sab))] text-center text-xs text-white/60">{t("crop.hint")}</p>
    </div>,
    document.body,
  );
}

/** The hole, sized to the room it has. Kept off the very edge so a finger can still grab
 *  the picture outside the frame instead of only inside it. */
function frameOf(shape: CropShape, stage: { w: number; h: number }) {
  if (!stage.w || !stage.h) return { w: 0, h: 0 };
  if (shape === "circle") {
    const side = Math.max(120, Math.min(stage.w - 48, stage.h - 48, 420));
    return { w: side, h: side };
  }
  let w = Math.max(160, Math.min(stage.w - 32, 560));
  let h = w * COVER_RATIO;
  if (h > stage.h - 48) { h = Math.max(80, stage.h - 48); w = h / COVER_RATIO; }
  return { w, h };
}

async function render(img: HTMLImageElement, nat: { w: number; h: number }, box: { w: number; h: number },
                      view: { s: number; x: number; y: number }, shape: CropShape, name: string): Promise<File> {
  // Where the frame sits on the picture, in the picture's own pixels.
  const dw = nat.w * view.s, dh = nat.h * view.s;
  const sx = (dw - box.w) / 2 / view.s - view.x / view.s;
  const sy = (dh - box.h) / 2 / view.s - view.y / view.s;
  const sw = box.w / view.s, sh = box.h / view.s;
  const outW = Math.max(1, Math.round(Math.min(sw, OUT_MAX[shape])));
  const outH = Math.max(1, Math.round(outW * (box.h / box.w)));
  const canvas = document.createElement("canvas");
  canvas.width = outW; canvas.height = outH;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2d context");
  // JPEG has no transparency: without this a PNG with an alpha edge arrives black.
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, outW, outH);
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, sx, sy, sw, sh, 0, 0, outW, outH);
  const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, "image/jpeg", 0.9));
  if (!blob) throw new Error("encode failed");
  const base = (name.replace(/\.[^.]+$/, "") || "photo").slice(0, 60);
  return new File([blob], `${base}.jpg`, { type: "image/jpeg" });
}

/** Crop-then-upload, as one call.
 *
 *  `crop(file)` resolves with the cropped file, or null if the person backed out — so an
 *  upload site keeps reading top to bottom instead of splitting in half around a dialog.
 *  Render `node` anywhere inside the component that owns it.
 */
export function useImageCrop(): { crop: (file: File, shape?: CropShape) => Promise<File | null>; node: ReactNode } {
  const [job, setJob] = useState<{ file: File; shape: CropShape; resolve: (f: File | null) => void } | null>(null);
  const crop = useCallback((file: File, shape: CropShape = "circle") =>
    new Promise<File | null>((resolve) => setJob({ file, shape, resolve })), []);
  const node = job ? (
    <CropDialog file={job.file} shape={job.shape}
                onCancel={() => { job.resolve(null); setJob(null); }}
                onDone={(f) => { job.resolve(f); setJob(null); }} />
  ) : null;
  return { crop, node };
}
