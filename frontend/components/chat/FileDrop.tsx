"use client";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { toast } from "sonner";
import { Upload } from "@/components/icons";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { MAX_FILES } from "@/lib/upload";

/** 대화 화면 전체가 파일을 받는 자리다 (plan/55 §6-1).
 *
 *  글칸 하나만 받는 자리면 사람은 작은 칸을 겨냥해야 하고, 조금만 빗나가도 브라우저가
 *  그 파일을 열어 버려 쓰던 대화가 사라진다. 그래서:
 *
 *  - 대화 영역 어디에 놓아도 받는다. 파일을 끌고 들어오면 영역 전체에 "여기에 놓기"가 뜬다.
 *  - 끌고 온 것이 파일일 때만 뜬다. 글이나 링크를 끌 때 뜨면 방해다.
 *  - 자식 요소를 지날 때마다 enter/leave 가 번갈아 오므로 횟수를 세어 깜박이지 않게 한다.
 *  - 이 화면이 떠 있는 동안에는 영역 밖에 떨어뜨려도 브라우저가 파일을 열지 않는다.
 *  - 폴더는 받지 않는다. 브라우저는 폴더를 빈 파일 하나로 넘긴다.
 */
export function FileDrop({ onFiles, disabled, children, className, style }: {
  onFiles: (files: File[]) => void; disabled?: boolean; children: ReactNode; className?: string; style?: CSSProperties;
}) {
  const t = useT();
  const depth = useRef(0);
  const [over, setOver] = useState(false);

  useEffect(() => {
    const guard = (e: DragEvent) => { if (hasFiles(e.dataTransfer)) e.preventDefault(); };
    const reset = () => { depth.current = 0; setOver(false); };
    window.addEventListener("dragover", guard);
    window.addEventListener("drop", guard);
    window.addEventListener("dragend", reset);
    // 창 밖으로 끌고 나가면 leave 가 짝을 못 맞출 때가 있다.
    const leaveWindow = (e: DragEvent) => { if (!e.relatedTarget) reset(); };
    window.addEventListener("dragleave", leaveWindow);
    return () => {
      window.removeEventListener("dragover", guard);
      window.removeEventListener("drop", guard);
      window.removeEventListener("dragend", reset);
      window.removeEventListener("dragleave", leaveWindow);
    };
  }, []);

  return (
    <div className={cn("relative", className)} style={style}
      onDragEnter={(e) => { if (!hasFiles(e.dataTransfer)) return; e.preventDefault(); depth.current += 1; setOver(true); }}
      onDragOver={(e) => { if (!hasFiles(e.dataTransfer)) return; e.preventDefault(); e.dataTransfer.dropEffect = disabled ? "none" : "copy"; }}
      onDragLeave={(e) => { if (!hasFiles(e.dataTransfer)) return; depth.current = Math.max(0, depth.current - 1); if (!depth.current) setOver(false); }}
      onDrop={(e) => {
        if (!hasFiles(e.dataTransfer)) return;
        e.preventDefault();
        depth.current = 0; setOver(false);
        if (disabled) return;
        type Entry = DataTransferItem & { webkitGetAsEntry?: () => { isDirectory: boolean } | null };
        const items = Array.from(e.dataTransfer.items ?? []).filter((it) => it.kind === "file") as Entry[];
        let files: File[];
        if (items.length) {
          const folders = items.filter((it) => it.webkitGetAsEntry?.()?.isDirectory);
          if (folders.length) toast.error(t("chat.no_folders"));
          files = items.filter((it) => !it.webkitGetAsEntry?.()?.isDirectory).map((it) => it.getAsFile()).filter((f): f is File => !!f);
        } else files = Array.from(e.dataTransfer.files);
        if (files.length) onFiles(files);
      }}>
      {children}
      {over ? (
        <div className="pointer-events-none absolute inset-2 z-30 flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-accent/70 bg-bg/85 backdrop-blur-sm"
             role="status" aria-live="polite">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-accent/10 text-accent"><Upload className="h-6 w-6" /></span>
          <div className="text-base font-semibold">{disabled ? t("chat.drop_disabled") : t("chat.drop_here")}</div>
          {!disabled ? <div className="text-sm text-muted-fg">{t("chat.drop_hint", { n: MAX_FILES })}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function hasFiles(dt: DataTransfer | null): boolean {
  return !!dt && Array.from(dt.types ?? []).includes("Files");
}
