"use client";
import type { ReactNode } from "react";
import { Camera, Trash2, Upload } from "@/components/icons";
import { DropdownMenu } from "@/components/ui/dropdown";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { usePhotoViewer } from "@/components/ui/photo-view";

/** The top of a profile — cover, photo, name — for a person and for a secretary alike.
 *
 *  A profile is one thing in this product: a background with a face in the middle of it and
 *  a name underneath. Only what hangs below differs (a secretary lists what it can do; a
 *  person lists what they published), so only that part lives in the callers.
 *
 *  Both pictures are openable. A profile photo is small on purpose and a cover is cropped
 *  to the header's shape, so the one thing a visitor wants from either is the picture
 *  itself — tapping it opens the viewer.
 */
export function ProfileHeader({ name, subtitle, badges, meta, actions, avatar, avatarSrc, coverUrl, accent, compact,
                                onPickCover, onPickAvatar, onRemoveCover, onRemoveAvatar, coverBusy, className }: {
  name: ReactNode; subtitle?: ReactNode; badges?: ReactNode; meta?: ReactNode; actions?: ReactNode;
  avatar: ReactNode; avatarSrc?: string | null; coverUrl?: string | null; accent?: string; compact?: boolean;
  onPickCover?: () => void; onPickAvatar?: () => void; onRemoveCover?: () => void; onRemoveAvatar?: () => void;
  coverBusy?: boolean; className?: string;
}) {
  const t = useT();
  const photo = usePhotoViewer();
  return (
    <div className={cn("overflow-hidden", className)}>
      {/* The background owns the whole top: 3:2, the ratio the cropper frames, with the
          face in the middle of it. It used to be a short band with the photo hanging off
          the bottom edge, which read as a letterhead rather than as someone's profile. */}
      <div className={cn("relative w-full aspect-[3/2]", compact ? "max-h-[300px]" : "max-h-[380px]")}
           style={coverUrl ? undefined : { background: coverFallback(accent) }}>
        {coverUrl ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={coverUrl} alt="" className="absolute inset-0 h-full w-full object-cover" draggable={false} />
            <button type="button" onClick={() => photo.view(coverUrl, t("prof.cover"))} aria-label={t("prof.cover_view")}
                    className="absolute inset-0 cursor-zoom-in" />
          </>
        ) : null}

        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="pointer-events-auto relative">
            {avatarSrc ? (
              <button type="button" onClick={() => photo.view(avatarSrc, typeof name === "string" ? name : undefined)}
                      aria-label={t("prof.avatar_view")} className="block cursor-zoom-in rounded-full">{avatar}</button>
            ) : avatar}
            {onPickAvatar ? (
              <PhotoMenu onPick={onPickAvatar} onRemove={avatarSrc ? onRemoveAvatar : undefined}
                         className="absolute bottom-0 right-0"
                         trigger={<span className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-border bg-card text-fg shadow hover:bg-muted"><Camera className="h-4 w-4" /></span>}
                         label={t("settings.avatar_upload")} />
            ) : null}
          </div>
        </div>

        {onPickCover ? (
          <PhotoMenu onPick={onPickCover} onRemove={coverUrl ? onRemoveCover : undefined} className="absolute right-3 top-3"
                     label={t("prof.cover_edit")}
                     trigger={<span className={cn("inline-flex h-9 items-center gap-1.5 rounded-full bg-black/45 px-3 text-xs font-medium text-white backdrop-blur transition-colors hover:bg-black/60", coverBusy && "opacity-60")}>
                                <Camera className="h-3.5 w-3.5" />{t("prof.cover_edit")}
                              </span>} />
        ) : null}
      </div>

      <div className={cn("text-center", compact ? "px-5 pb-5 pt-4" : "px-4 pb-5 pt-4 sm:px-6")}>
        <h1 className="flex flex-wrap items-center justify-center gap-2 text-xl font-semibold tracking-tight">{name}{badges}</h1>
        {subtitle ? <p className="mt-0.5 text-sm text-muted-fg">{subtitle}</p> : null}
        {meta ? <div className="mt-1.5 flex flex-wrap items-center justify-center gap-x-3 gap-y-0.5 text-sm text-muted-fg">{meta}</div> : null}
        {actions ? <div className="mt-3 flex flex-wrap justify-center gap-2">{actions}</div> : null}
      </div>
      {photo.node}
    </div>
  );
}

/** No cover uploaded: the subject's own accent, not a grey band. A secretary passes its
 *  theme colour, a person gets the product's. */
export function coverFallback(accent?: string): string {
  const a = accent || "var(--brand-violet)";
  return `radial-gradient(120% 160% at 85% 0%, color-mix(in oklab, ${a} 70%, transparent) 0%, transparent 55%),`
       + ` radial-gradient(120% 140% at 5% 100%, var(--brand-sky) 0%, transparent 60%), #0a1020`;
}


/** Change or remove — one button, because a profile has two things you can do to a picture
 *  and a page cluttered with a second icon for "delete" is a page nobody reads. With no
 *  picture yet there is nothing to remove, so it just picks one. */
function PhotoMenu({ trigger, label, onPick, onRemove, className }: {
  trigger: ReactNode; label: string; onPick: () => void; onRemove?: () => void; className?: string;
}) {
  const t = useT();
  if (!onRemove) {
    return <button type="button" onClick={onPick} aria-label={label} className={className}>{trigger}</button>;
  }
  return (
    <DropdownMenu className={className} trigger={<button type="button" aria-label={label}>{trigger}</button>}
      items={[
        { key: "pick", label: t("prof.photo_change"), icon: <Upload />, onSelect: onPick },
        { key: "remove", label: t("prof.photo_remove"), icon: <Trash2 />, danger: true, onSelect: onRemove },
      ]} />
  );
}
