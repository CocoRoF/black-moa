"use client";
import { createContext, useContext, useState } from "react";
import Link from "next/link";
import { FileText, ImageOff } from "@/components/icons";
import { usePhotoViewer } from "@/components/ui/photo-view";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { fmtBytes } from "@/lib/upload";

export interface MessageFile { upload_id?: string; file_id?: string; filename?: string; mime?: string; url?: string; size?: number }

/** 문서 카드를 누르면 [파일] 의 그 파일로 (plan/55 §6-1). 주인 화면만 이 길을 준다 —
 *  방문자에게는 [파일] 이 없다. 없으면 문서는 새 탭에서 열린다. */
export const FileLinks = createContext<((fileId: string) => string) | null>(null);

/** 서명한 주소는 반나절이면 끝난다. 하루 종일 열어 둔 대화에서 그림이 깨지면 화면이 말들을
 *  다시 받아 새 주소를 얻는다 — 이 함수를 주는 화면만. 한 번 시도한 주소는 다시 시도하지 않고,
 *  여러 그림이 한꺼번에 깨져도 1분에 한 번만 받는다. */
export const AttachmentRefresh = createContext<(() => unknown) | null>(null);
let lastRefresh = 0;
const tried = new Set<string>();

/** 말풍선에 붙은 파일들 (plan/55 §6-1). 비서 대화·메신저·공개 비서가 모두 이것을 쓴다.
 *
 *  사진은 사진답게 크게 — 한 장이면 폭을 다 쓰고, 여러 장이면 네모 칸으로 모아 둔다.
 *  누르면 전체 화면으로 확대해 본다. 문서는 이름과 크기가 적힌 카드이고, 누르면 새 탭에서
 *  열린다(그림·PDF) 또는 내려받는다(나머지). 주소가 없거나 그림이 깨지면 이름 카드로
 *  물러선다 — 빈 네모를 남기지 않는다.
 */
export function MessageAttachments({ items, align = "start" }: { items: MessageFile[]; align?: "start" | "end" }) {
  const t = useT();
  const photo = usePhotoViewer();
  const fileHref = useContext(FileLinks);
  const refresh = useContext(AttachmentRefresh);
  // 깨진 것은 주소로 기억한다 — 새 주소가 오면 다시 그려 본다.
  const [broken, setBroken] = useState<Set<string>>(new Set());
  const key = (a: MessageFile, i: number) => a.upload_id || `${a.filename}-${i}`;
  const isBroken = (a: MessageFile) => !!a.url && broken.has(a.url);
  const onBroken = (url: string) => {
    if (refresh && !tried.has(url)) {
      tried.add(url);
      if (Date.now() - lastRefresh > 60_000) { lastRefresh = Date.now(); void refresh(); }
      return;
    }
    setBroken((p) => new Set(p).add(url));
  };
  const imgs = items.filter((a) => a.mime?.startsWith("image/") && a.url && !isBroken(a));
  const files = items.filter((a) => !(a.mime?.startsWith("image/") && a.url && !isBroken(a)));
  if (!items.length) return null;
  return (
    <div className={cn("flex flex-col gap-1.5", align === "end" ? "items-end" : "items-start")}>
      {imgs.length ? (
        <div className={cn("grid gap-1 overflow-hidden rounded-2xl", imgs.length === 1 ? "grid-cols-1" : imgs.length === 2 || imgs.length === 4 ? "grid-cols-2" : "grid-cols-3")}>
          {imgs.map((a) => {
            const k = key(a, items.indexOf(a));
            return (
              <button key={k} type="button" onClick={() => photo.view(a.url!, a.filename)} aria-label={t("chat.open_photo", { name: a.filename ?? "" })}
                      className={cn("block overflow-hidden bg-muted focus-visible:outline-2 focus-visible:outline-ring", imgs.length === 1 ? "max-w-[min(20rem,70vw)]" : "h-28 w-28 sm:h-32 sm:w-32")}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={a.url} alt={a.filename ?? ""} loading="lazy" decoding="async"
                     onError={() => onBroken(a.url!)}
                     className={cn("block", imgs.length === 1 ? "max-h-80 w-auto max-w-full object-contain" : "h-full w-full object-cover")} />
              </button>
            );
          })}
        </div>
      ) : null}
      {files.map((a, i) => {
        const img = a.mime?.startsWith("image/");
        const body = (
          <>
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">
              {img ? <ImageOff className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
            </span>
            <span className="min-w-0 flex-1 text-left">
              <span className="block truncate text-[13px] font-medium">{a.filename || t("chat.file")}</span>
              {a.size ? <span className="block text-[11px] text-muted-fg">{fmtBytes(a.size)}</span> : null}
            </span>
          </>
        );
        const cls = "flex w-60 max-w-full items-center gap-2.5 rounded-xl border border-border bg-card px-2.5 py-2 text-fg";
        if (a.file_id && fileHref && !img) {
          return <Link key={`${key(a, i)}-f`} href={fileHref(a.file_id)} className={cn(cls, "hover:bg-muted")}>{body}</Link>;
        }
        return a.url && !img ? (
          <a key={`${key(a, i)}-f`} href={a.url} target="_blank" rel="noopener noreferrer" className={cn(cls, "hover:bg-muted")}>{body}</a>
        ) : <div key={`${key(a, i)}-f`} className={cls}>{body}</div>;
      })}
      {photo.node}
    </div>
  );
}
