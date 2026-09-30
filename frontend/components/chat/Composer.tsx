"use client";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowUp, Mic, Paperclip, Square, X, Loader2, FileText, ImageIcon, RotateCw, AlertCircle } from "@/components/icons";
import { toast } from "sonner";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { pickRecorderMime } from "@/lib/audio";
import { Button } from "@/components/ui/button";
import { ACCEPT, MAX_FILES, canPreview, fmtBytes, kindOf, refuse } from "@/lib/upload";

/** 글칸에 붙은 파일 하나. 올라가는 중이면 `progress`, 실패했으면 `failed`. */
export interface Attachment {
  upload_id: string; filename: string; mime: string; url?: string; size?: number; uploading?: boolean; localId: string;
  progress?: number; failed?: string; preview?: string; file?: File;
}
export interface ComposerHandle {
  focus: () => void; setText: (t: string) => void; getText: () => string;
  /** 끌어다 놓은 파일을 받는다 (FileDrop). 받을 수 없는 글칸이면 false. */
  addFiles: (files: File[]) => boolean;
}

interface Props {
  onSend: (text: string, attachments: Attachment[]) => void | Promise<void>;
  onCancel?: () => void;
  busy?: boolean;                 // a turn is streaming
  /** 보내는 중(취소할 수 없는 보내기). 보내기 단추만 돌고 글칸은 그대로 쓸 수 있다. */
  sending?: boolean;
  disabled?: boolean;
  placeholder?: string;
  voice?: boolean;
  onTranscribe?: (blob: Blob) => Promise<string>;
  attachments?: boolean;
  onUpload?: (file: File, onProgress: (ratio: number) => void) => Promise<Attachment>;
  maxLen?: number;
  /** 이 자리에서 받는 한 파일의 최대(MB). 서버 한도보다 작을 때만 뜻이 있다(공개 비서의 방문자). */
  fileMaxMb?: number;
  accent?: boolean;
  className?: string;
  onFocusChange?: (focused: boolean) => void;
}

export const Composer = forwardRef<ComposerHandle, Props>(function Composer({ onSend, onCancel, busy, sending, disabled, placeholder, voice, onTranscribe, attachments, onUpload, fileMaxMb, maxLen = 4000, accent = true, className, onFocusChange }, ref) {
  const t = useT();
  const ta = useRef<HTMLTextAreaElement>(null);
  const [text, setTextState] = useState("");
  const [atts, setAtts] = useState<Attachment[]>([]);
  const [rec, setRec] = useState<"idle" | "recording" | "transcribing">("idle");
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const isComposing = useRef(false);

  const resize = useCallback(() => {
    const el = ta.current; if (!el) return;
    el.style.height = "0px";
    // 여덟 줄까지는 칸이 자란다. 그 뒤로는 칸 안에서 스크롤한다.
    const max = 22 * 8;
    el.style.height = Math.min(el.scrollHeight, max) + "px";
    el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
  }, []);
  // ── 한 줄이면 한 줄, 넘치면 두 층 ─────────────────────────────────────────
  //
  // 한 줄일 때는 [첨부] [글] [마이크] [보내기] 가 한 줄에 선 알약이고, 글이 한 줄을
  // 넘기면(줄바꿈이 있거나 옆으로 넘치면) 글이 위에서 폭을 다 쓰고 버튼이 아래 한
  // 줄로 내려간다. 예전에는 한 줄일 때도 늘 두 층이라 빈 칸이 두 배로 두꺼웠다.
  //
  // 넘치는지는 **한 줄 배치일 때 글이 쓸 수 있는 폭**으로 잰다. 지금 보이는 칸으로
  // 재면 두 층으로 넘어가는 순간 칸이 넓어져 다시 한 줄로 돌아가고, 그렇게 두 배치를
  // 오가며 깜박인다. 그 폭은 상자 폭에서 양옆 버튼 묶음을 뺀 값이라 어느 배치에서나
  // 같게 나온다.
  const box = useRef<HTMLDivElement>(null);
  const left = useRef<HTMLDivElement>(null);
  const right = useRef<HTMLDivElement>(null);
  const measureCtx = useRef<CanvasRenderingContext2D | null>(null);
  const [multi, setMulti] = useState(false);
  const [boxW, setBoxW] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setBoxW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useLayoutEffect(() => {
    const el = ta.current; const b = box.current;
    if (!el || !b) return;
    let next = false;
    if (text.includes("\n")) next = true;
    else if (text) {
      const cs = getComputedStyle(el);
      const bs = getComputedStyle(b);
      const gap = parseFloat(bs.columnGap || "0") || 0;
      const room = b.clientWidth - parseFloat(bs.paddingLeft) - parseFloat(bs.paddingRight)
        - (left.current?.offsetWidth ?? 0) - (right.current?.offsetWidth ?? 0)
        - gap * ((left.current?.offsetWidth ? 1 : 0) + 1)
        - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      const ctx = measureCtx.current ?? (measureCtx.current = document.createElement("canvas").getContext("2d"));
      if (ctx) {
        ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
        next = ctx.measureText(text).width > room - 2;
      }
    }
    if (next !== multi) setMulti(next);
    resize();
  }, [text, multi, boxW, resize]);

  const send = async () => {
    const v = text.trim();
    const ready = atts.filter((a) => a.upload_id && !a.failed);
    if ((!v && !ready.length) || busy || sending || disabled || atts.some((a) => a.uploading)) return;
    const before = atts;
    setTextState(""); setAtts([]); setPasteOffer(null);
    try {
      await onSend(v, ready.map(({ file: _f, preview: _p, ...rest }) => rest));
      before.forEach((a) => a.preview && URL.revokeObjectURL(a.preview));
    } catch (e) {
      // 못 보냈으면 쓴 글과 붙인 파일을 그대로 돌려놓는다 — 다시 쓰게 하지 않는다.
      setTextState(v); setAtts(before);
      toast.error((e as Error).message);
    }
    ta.current?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !isComposing.current && !(e.nativeEvent as unknown as { isComposing?: boolean }).isComposing) {
      // On touch devices Enter inserts newline? No — keep Enter=send for parity, but allow Shift+Enter newline.
      e.preventDefault(); void send();
    }
  };

  const startRec = async () => {
    if (!onTranscribe) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = pickRecorderMime();
      const mr = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunks.current = [];
      mr.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((tr) => tr.stop());
        const blob = new Blob(chunks.current, { type: mr.mimeType || mime || "audio/webm" });
        if (blob.size < 800) { setRec("idle"); return; }
        setRec("transcribing");
        try { const txt = await onTranscribe(blob); if (txt) setTextState((p) => (p ? p + " " + txt : txt)); ta.current?.focus(); }
        catch (e) { toast.error((e as Error).message); }
        finally { setRec("idle"); }
      };
      mr.start(); recorder.current = mr; setRec("recording");
    } catch { toast.error(t("chat.mic_denied")); }
  };
  const stopRec = () => { recorder.current?.stop(); recorder.current = null; };

  // ── 파일 ────────────────────────────────────────────────────────────
  //
  // [첨부] 단추·붙여넣기·끌어다 놓기가 모두 여기(addFiles)로 들어온다. 길이 셋이면 규칙도
  // 셋이 되기 쉽다 — 몇 개까지, 무엇을, 얼마나 큰 것을 받는지는 한 곳에서 정한다.
  const canAttach = !!(attachments && onUpload);
  const aborts = useRef(new Map<string, () => void>());
  const attsRef = useRef<Attachment[]>([]);
  attsRef.current = atts;
  useEffect(() => () => {
    aborts.current.forEach((abort) => abort());
    attsRef.current.forEach((a) => a.preview && URL.revokeObjectURL(a.preview));
  }, []);

  const startUpload = useCallback((localId: string, f: File) => {
    if (!onUpload) return;
    let cancelled = false;
    aborts.current.set(localId, () => { cancelled = true; });
    const patch = (p: Partial<Attachment>) => setAtts((prev) => prev.map((a) => (a.localId === localId ? { ...a, ...p } : a)));
    patch({ uploading: true, failed: undefined, progress: 0 });
    onUpload(f, (r) => { if (!cancelled) patch({ progress: r }); })
      .then((up) => { if (!cancelled) patch({ upload_id: up.upload_id, url: up.url, mime: up.mime, size: up.size, filename: up.filename, uploading: false, progress: 1 }); })
      .catch((e: Error) => { if (!cancelled) patch({ uploading: false, failed: e.message || t("chat.upload_failed") }); })
      .finally(() => { aborts.current.delete(localId); });
  }, [onUpload, t]);

  const addFiles = useCallback((files: File[]): boolean => {
    if (!canAttach || disabled) return false;
    const room = MAX_FILES - attsRef.current.length;
    if (room <= 0) { toast.error(t("chat.too_many_files", { n: MAX_FILES })); return true; }
    if (files.length > room) toast.error(t("chat.too_many_files", { n: MAX_FILES }));
    const next: Attachment[] = [];
    for (const f of files.slice(0, room)) {
      const why = refuse(f);
      if (why) { toast.error(t(why, { name: f.name || t("chat.pasted_image") })); continue; }
      if (fileMaxMb && f.size > fileMaxMb * 1024 * 1024) { toast.error(t("chat.file_too_big_here", { name: f.name, n: fileMaxMb })); continue; }
      // 붙여넣은 화면 캡처는 이름이 모두 "image.png" 다. 여러 장이면 구별이 안 되니 시각을 붙인다.
      const name = f.name && f.name !== "image.png" ? f.name : `${t("chat.pasted_image")} ${new Date().toTimeString().slice(0, 8).replace(/:/g, "")}.png`;
      const file = f.name === name ? f : new File([f], name, { type: f.type });
      next.push({ localId: `${Date.now()}-${Math.random()}`, upload_id: "", filename: name, mime: kindOf(file), size: file.size,
                  uploading: true, progress: 0, file, preview: canPreview(file) ? URL.createObjectURL(file) : undefined });
    }
    if (!next.length) return true;
    setAtts((p) => [...p, ...next]);
    next.forEach((a) => startUpload(a.localId, a.file!));
    return true;
  }, [canAttach, disabled, startUpload, t, fileMaxMb]);

  const removeAtt = (localId: string) => {
    aborts.current.get(localId)?.();
    setAtts((p) => {
      const gone = p.find((a) => a.localId === localId);
      if (gone?.preview) URL.revokeObjectURL(gone.preview);
      return p.filter((a) => a.localId !== localId);
    });
  };

  // 워드·엑셀에서 복사하면 클립보드에 글과 그 그림이 함께 온다. 그때 사람이 원한 건 거의
  // 언제나 글이다 — 글을 붙이고, 그림으로도 붙일 수 있게 잠깐 단추를 띄운다.
  const [pasteOffer, setPasteOffer] = useState<File[] | null>(null);
  useEffect(() => {
    if (!pasteOffer) return;
    const tm = setTimeout(() => setPasteOffer(null), 8000);
    return () => clearTimeout(tm);
  }, [pasteOffer]);
  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (!canAttach) return;
    const files = Array.from(e.clipboardData?.files ?? []);
    if (!files.length) return;
    const hasText = !!e.clipboardData.getData("text/plain").trim();
    if (hasText) { setPasteOffer(files.filter((f) => f.type.startsWith("image/"))); return; }
    e.preventDefault();
    addFiles(files);
  };

  const pickFiles = (files: FileList | null) => { if (files) addFiles(Array.from(files)); };
  useImperativeHandle(ref, () => ({ focus: () => ta.current?.focus(), setText: (v) => setTextState(v), getText: () => text, addFiles }), [text, addFiles]);

  const canSend = (text.trim().length > 0 || atts.some((a) => a.upload_id && !a.failed)) && !atts.some((a) => a.uploading);
  return (
    <div className={cn("w-full", className)}>
      {/* 화면 낭독기에 "첨부 2개" — 붙여 넣거나 끌어다 놓은 것이 들어갔는지 눈 없이도 안다. */}
      <span className="sr-only" aria-live="polite">{atts.length ? t("chat.attached_n", { n: atts.length }) : ""}</span>
      {atts.length ? (
        <ul className="mb-2 flex gap-2 overflow-x-auto px-1 pb-0.5 pt-1.5 scrollbar-thin" aria-label={t("chat.attached_files")}>
          {atts.map((a) => <AttachmentChip key={a.localId} a={a} onRemove={() => removeAtt(a.localId)}
            onRetry={a.file ? () => startUpload(a.localId, a.file!) : undefined} />)}
        </ul>
      ) : null}
      {pasteOffer?.length ? (
        <div className="mb-1.5 flex items-center gap-2 px-1 text-xs text-muted-fg" role="status">
          <span>{t("chat.pasted_as_text")}</span>
          <button type="button" className="font-medium text-accent underline-offset-2 hover:underline"
                  onClick={() => { addFiles(pasteOffer); setPasteOffer(null); }}>{t("chat.paste_as_image")}</button>
        </div>
      ) : null}
      {/* 글칸은 한 자리에 그대로 두고 CSS 의 순서만 바꾼다. 배치를 바꿀 때 글칸을 다른
          자리에 새로 그리면 초점·커서·한글 조합이 끊긴다 — 쓰던 글자가 사라지는 일이다. */}
      <div ref={box} data-multi={multi || undefined}
        className={cn("flex flex-wrap gap-1 border border-border bg-card shadow-soft transition-colors focus-within:border-accent/60",
          multi ? "items-center rounded-[26px] p-2" : "items-center rounded-[26px] p-1.5",
          disabled && "opacity-60")}>
        <div ref={left} className={cn("flex shrink-0 items-center", multi ? "order-2" : "order-1", !(attachments && onUpload) && "hidden")}>
          {attachments && onUpload ? (
            <>
              <input ref={fileInput} type="file" multiple hidden accept={ACCEPT} onChange={(e) => { pickFiles(e.target.files); e.target.value = ""; }} />
              <Button variant="ghost" size="icon" className="h-9 w-9 rounded-full shrink-0" aria-label={t("chat.attach")} disabled={disabled} onClick={() => fileInput.current?.click()}><Paperclip className="h-5 w-5" /></Button>
            </>
          ) : null}
        </div>
        <textarea ref={ta} rows={1} value={text} maxLength={maxLen} disabled={disabled} placeholder={rec === "recording" ? t("chat.recording") : placeholder ?? t("chat.placeholder")}
          onChange={(e) => setTextState(e.target.value)} onKeyDown={onKey} onPaste={onPaste} onCompositionStart={() => { isComposing.current = true; }} onCompositionEnd={() => { isComposing.current = false; }}
          onFocus={() => onFocusChange?.(true)} onBlur={() => onFocusChange?.(false)}
          aria-label={t("chat.placeholder")} enterKeyHint="send" autoCapitalize="sentences"
          className={cn("block min-w-0 resize-none bg-transparent px-2 text-[16px] leading-[22px] outline-none placeholder:text-muted-fg/70",
            multi ? "order-1 basis-full pb-1 pt-1.5" : "order-2 flex-1 py-[7px]",
            !(attachments && onUpload) && !multi && "pl-3")} />
        <div ref={right} className={cn("order-3 flex shrink-0 items-center gap-1", multi && "ml-auto")}>
          {voice && onTranscribe ? (
            <Button variant={rec === "recording" ? "danger" : "ghost"} size="icon" className={cn("h-9 w-9 rounded-full shrink-0", rec === "recording" && "animate-pulse")} aria-label={rec === "recording" ? t("chat.stop_recording") : t("chat.record")} aria-pressed={rec === "recording"} disabled={disabled || rec === "transcribing"} onClick={() => (rec === "recording" ? stopRec() : void startRec())}>
              {rec === "transcribing" ? <Loader2 className="h-5 w-5 animate-spin" /> : rec === "recording" ? <Square className="h-4 w-4" /> : <Mic className="h-5 w-5" />}
            </Button>
          ) : null}
          {busy ? (
            <Button variant="secondary" size="icon" className="h-9 w-9 rounded-full shrink-0" aria-label={t("chat.stop")} onClick={onCancel}><Square className="h-4 w-4" /></Button>
          ) : (
            <Button variant={accent ? "accent" : "primary"} size="icon" className="h-9 w-9 rounded-full shrink-0" aria-label={t("chat.send")} loading={sending} disabled={!canSend || disabled || sending} onClick={() => void send()}><ArrowUp className="h-5 w-5" /></Button>
          )}
        </div>
      </div>
    </div>
  );
});

/** 보내기 전 글칸 위에 놓인 파일 한 장. 사진은 작은 그림으로, 문서는 이름과 크기로.
 *  올라가는 동안은 실제로 간 만큼 차오르고, 실패하면 그 자리에서 다시 보낼 수 있다. */
function AttachmentChip({ a, onRemove, onRetry }: { a: Attachment; onRemove: () => void; onRetry?: () => void }) {
  const t = useT();
  const pct = Math.round((a.progress ?? 0) * 100);
  const img = a.mime.startsWith("image/");
  return (
    <li tabIndex={0} aria-label={a.filename}
      onKeyDown={(e) => { if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); onRemove(); } }}
      className={cn("group relative flex shrink-0 items-center overflow-hidden rounded-xl border bg-card outline-none focus-visible:ring-2 focus-visible:ring-ring",
      a.failed ? "border-danger/50" : "border-border", img && a.preview ? "h-16 w-16" : "h-16 w-52 gap-2.5 pl-2.5 pr-7")}
      title={a.failed ? a.failed : a.filename}>
      {img && a.preview ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={a.preview} alt={a.filename} className={cn("h-full w-full object-cover", (a.uploading || a.failed) && "opacity-60")} />
      ) : (
        <>
          <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", a.failed ? "bg-danger/10 text-danger" : "bg-accent/10 text-accent")}>
            {a.failed ? <AlertCircle className="h-5 w-5" /> : img ? <ImageIcon className="h-5 w-5" /> : <FileText className="h-5 w-5" />}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium">{a.filename}</span>
            <span className={cn("block truncate text-[11px]", a.failed ? "text-danger" : "text-muted-fg")}>
              {a.failed ? t("chat.upload_failed") : a.uploading ? `${pct}%` : a.size ? fmtBytes(a.size) : ""}
            </span>
          </span>
        </>
      )}
      {a.uploading ? (
        <span className="absolute inset-x-0 bottom-0 h-1 bg-black/10" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={a.filename}>
          <span className="block h-full bg-accent transition-[width] duration-150" style={{ width: `${Math.max(4, pct)}%` }} />
        </span>
      ) : null}
      {img && a.preview && a.uploading ? <Loader2 className="absolute left-1/2 top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 animate-spin text-white drop-shadow" /> : null}
      {a.failed && onRetry ? (
        <button type="button" onClick={onRetry} aria-label={t("chat.retry_upload")}
                className={cn("absolute flex items-center justify-center rounded-full bg-card text-danger shadow-soft hover:bg-muted",
                  img && a.preview ? "left-1/2 top-1/2 h-8 w-8 -translate-x-1/2 -translate-y-1/2" : "bottom-1.5 right-1.5 h-6 w-6")}>
          <RotateCw className="h-3.5 w-3.5" />
        </button>
      ) : null}
      <button type="button" onClick={onRemove} aria-label={t("chat.remove_file", { name: a.filename })}
              className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-black/55 text-white hover:bg-black/75">
        <X className="h-3 w-3" />
      </button>
    </li>
  );
}
