"use client";
/**
 * 무대 (plan/71) — 비서의 공개 대화를 게임처럼.
 *
 * 배경 위에 비서가 올린 그림이 **그대로** 가운데에 서고(얼굴부터 상체까지), 아래의 대화창으로 말한다. 비주얼 노벨·
 * 게임의 대화창처럼 지금 하는 말 한 마디가 한 글자씩 나오고, 그 창에서 바로 말을 건다. 지난 말은 [대화 기록]에 모두
 * 있다. 채팅 화면(기본)과 같은 대화를 보여 주는 다른 모양일 뿐이라, 말·카드·멈춤·음성 입력은 채팅과 같은 길로 간다.
 *
 * 크기는 창 크기가 아니라 **이 무대의 크기**로 정한다(ResizeObserver) — 미리보기처럼 작은 틀 안에서도 휴대폰 모양이
 * 휴대폰 모양으로 보이게. [대화 기록]은 무대를 어둡게 하고 오른쪽에서 밀려 나오는 옆 창이다(휴대폰은 화면 가득).
 * 무대의 자리는 그대로 두어 비서와 대화창이 움직이지 않는다.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { EllipsisVertical, Loader2, Mic, ScrollText, Square, X } from "@/components/icons";
import type { ChatMessage } from "@/stores/chat";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { pickRecorderMime } from "@/lib/audio";
import { placeFigure, prepareFigure, type Figure } from "@/lib/figure";
import { Markdown } from "@/components/chat/Markdown";
import { CardRenderer, type CardActions } from "@/components/chat/CardRenderer";
import { MessageList } from "@/components/chat/MessageList";
import { Avatar } from "@/components/ui/misc";
import { DropdownMenu, type MenuItem } from "@/components/ui/dropdown";
import type { PublicAgent } from "./PublicChat";
import { AiNotice } from "./AiNotice";

/** 무대의 기본 배경(사무실). 작은 무대는 가벼운 것을 쓴다. */
const BACKGROUND = { large: "/stage/office.webp", small: "/stage/office-960.webp", fallback: "/stage/office.jpg" };
/** 위의 단추들: 같은 높이, 같은 유리 모양. */
const TOP_BTN = "h-10 rounded-full bg-black/40 text-white ring-1 ring-white/15 backdrop-blur-md transition-colors hover:bg-black/55";
/** 한 글자씩 나오는 빠르기(ms/글자). 밀린 글이 많으면 따라잡도록 빨라진다. */
const CHAR_MS = 28;
/** 이보다 좁으면 휴대폰 모양. */
const COMPACT_BELOW = 640;

export interface StageProps {
  agent: PublicAgent;
  accent: string;
  accentFg: string;
  messages: ChatMessage[];
  busy: boolean;
  online: boolean;
  resting: boolean;
  /** 말을 걸 수 없다(아직 준비 중, 쉬는 중, 오프라인, 미리보기). */
  disabled: boolean;
  placeholder: string;
  /** 처음에 눌러 볼 물음들. */
  suggestions: string[];
  onSend: (text: string) => void;
  onStop: () => void;
  voice: boolean;
  onTranscribe?: (b: Blob) => Promise<string>;
  onProfile: () => void;
  /** 오른쪽 위 [더 보기] 의 항목(부르는 쪽이 만든다). 단추는 무대가 그린다 — 옆 단추와 같은 크기로. */
  menuItems?: MenuItem[];
  cardActions: CardActions;
  bubbleStyle?: string;
  /** 쉬는 중·미리보기 같은 짧은 표시. 대화창의 이름표 줄 오른쪽에 붙는다(비서의 얼굴을 가리지 않게). */
  banner?: ReactNode;
}

export function StageView(p: StageProps) {
  const t = useT();
  const root = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ rootW: 0, w: 0, h: 0, dialogTop: 0 });
  const [figure, setFigure] = useState<Figure | null>(null);
  const [figureTried, setFigureTried] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const compact = size.rootW > 0 && size.rootW < COMPACT_BELOW;

  // 기록 창은 Esc 로 닫는다.
  useEffect(() => {
    if (!logOpen) return;
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") setLogOpen(false); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [logOpen]);

  // 무대와 대화창의 크기 — 그림을 그 사이에 맞춘다.
  useLayoutEffect(() => {
    const rt = root.current;
    const el = stage.current;
    const dl = dialog.current;
    if (!rt || !el || !dl) return;
    const measure = () => {
      const rw = rt.getBoundingClientRect().width;
      const r = el.getBoundingClientRect();
      const d = dl.getBoundingClientRect();
      const next = { rootW: rw, w: r.width, h: r.height, dialogTop: d.top - r.top };
      setSize((s) => (s.rootW === next.rootW && s.w === next.w && s.h === next.h && s.dialogTop === next.dialogTop ? s : next));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(rt);
    ro.observe(el);
    ro.observe(dl);
    return () => ro.disconnect();
  }, []);

  // 세울 그림: 올린 원본이 있으면 원본, 없으면 프로필 사진. 흰 바탕이면 걷는다.
  const src = p.agent.character_url || p.agent.avatar_url || null;
  useEffect(() => {
    let alive = true;
    let made: string | null = null;
    setFigureTried(false);
    if (!src) { setFigure(null); setFigureTried(true); return; }
    void prepareFigure(src).then((f) => {
      if (!alive) { if (f) URL.revokeObjectURL(f.url); return; }
      made = f?.url ?? null;
      setFigure(f);
      setFigureTried(true);
    });
    return () => { alive = false; if (made) URL.revokeObjectURL(made); };
  }, [src]);

  const place = figure && size.w ? placeFigure(figure, size.w, size.h, size.dialogTop, compact) : null;

  // 지금 대화창에 나올 말: 가장 최근의 비서 말, 그리고 그 앞에 사람이 한 말(작게).
  const scene = useMemo(() => {
    const ms = p.messages;
    let ai = -1;
    for (let i = ms.length - 1; i >= 0; i--) if (ms[i].role === "assistant") { ai = i; break; }
    const last = ms[ms.length - 1];
    // 사람이 막 말했고 아직 답의 자리가 없으면: 그 말과 "생각하는 중".
    if (last && last.role === "user" && (ai < 0 || ai < ms.length - 1)) return { said: last, line: null as ChatMessage | null, thinking: true };
    const line = ai >= 0 ? ms[ai] : null;
    let said: ChatMessage | null = null;
    for (let i = ai - 1; i >= 0; i--) if (ms[i].role === "user") { said = ms[i]; break; }
    return { said, line, thinking: !!line?.streaming && !line.content };
  }, [p.messages]);

  const speaking = !!scene.line?.streaming;

  const log = (
    <>
      <div className="safe-pt flex h-12 shrink-0 items-center justify-between border-b border-border px-3">
        <span className="flex items-center gap-2 text-[14px] font-semibold"><ScrollText className="h-4 w-4" />{t("stage.log")}</span>
        <button type="button" onClick={() => setLogOpen(false)} aria-label={t("common.close")} className="inline-flex h-9 w-9 items-center justify-center rounded-full hover:bg-muted"><X className="h-5 w-5" /></button>
      </div>
      <MessageList messages={p.messages} mode="visitor" agentName={p.agent.name} agentAvatar={p.agent.avatar_url}
                   onAgentClick={p.onProfile} bubbleStyle={p.bubbleStyle} cardActions={p.cardActions} className="min-h-0 flex-1" />
    </>
  );

  return (
    <div ref={root} className="dark flex h-full w-full overflow-hidden bg-[#0b0d12] text-fg" style={{ ["--accent" as string]: p.accent, ["--accent-fg" as string]: p.accentFg, ["--ring" as string]: p.accent }}>
      <div ref={stage} className="relative h-full min-w-0 flex-1 overflow-hidden">
        {/* 배경 */}
        <picture>
          <source media="(max-width: 700px)" srcSet={BACKGROUND.small} type="image/webp" />
          <source srcSet={BACKGROUND.large} type="image/webp" />
          <img src={BACKGROUND.fallback} alt="" draggable={false} className="pointer-events-none absolute inset-0 h-full w-full select-none object-cover" />
        </picture>
        {/* 사람이 배경에서 떠 보이도록 아래를 살짝 어둡게 */}
        <div aria-hidden className="pointer-events-none absolute inset-0" style={{ background: "linear-gradient(to top, rgba(6,8,14,0.78) 0%, rgba(6,8,14,0.28) 38%, rgba(6,8,14,0) 60%)" }} />

        {/* 비서 */}
        {place && figure ? (
          <div aria-hidden className="pointer-events-none absolute" style={{ left: place.left, top: place.top, width: place.width, height: place.height }}>
            <div className="stage-breathe h-full w-full">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={figure.url} alt="" draggable={false}
                   className={cn("h-full w-full select-none", !figure.standing && "rounded-3xl object-cover shadow-2xl ring-1 ring-white/15")}
                   style={figure.standing ? { filter: `drop-shadow(0 12px 28px rgba(0,0,0,0.45))${speaking ? ` drop-shadow(0 0 18px color-mix(in oklab, ${p.accent} 55%, transparent))` : ""}` } : undefined} />
            </div>
          </div>
        ) : figureTried && !figure && size.w ? (
          <div aria-hidden className="absolute left-1/2 -translate-x-1/2" style={{ top: size.h * 0.16 }}>
            <Avatar mascot name={p.agent.name} src={p.agent.avatar_url} size={Math.round(Math.min(size.w * 0.42, size.h * 0.34))} shape="circle" accent={p.accent} />
          </div>
        ) : null}

        {/* 위: 누구인지와 차림표. 배경 위에 옅은 그늘을 깔아 글이 읽히게 하고, 가장자리와 서로 사이를 띄운다.
            셋 다 같은 높이(44px)의 둥근 모양. */}
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 z-10 h-24" style={{ background: "linear-gradient(to bottom, rgba(6,8,14,0.45), rgba(6,8,14,0))" }} />
        <div className={cn("absolute inset-x-0 top-0 z-20 flex items-center justify-between gap-3", compact ? "px-3" : "px-6")}
             style={{ paddingTop: `calc(var(--sat, 0px) + ${compact ? 12 : 18}px)` }}>
          <button type="button" onClick={p.onProfile} aria-label={t("prof.open", { name: p.agent.name })}
                  className={cn(TOP_BTN, "flex min-w-0 items-center gap-2.5 pl-1 pr-4 text-left")}>
            <Avatar mascot name={p.agent.name} src={p.agent.avatar_url} size={36} shape="circle" accent={p.accent} />
            <span className="min-w-0">
              <span className="block truncate text-[14px] font-semibold leading-tight">{p.agent.name}</span>
              <span className="mt-0.5 flex items-center gap-1.5 text-[11px] leading-none text-white/70">
                <span className={cn("h-1.5 w-1.5 rounded-full", p.resting ? "bg-warning" : p.online ? "bg-success" : "bg-white/40")} />
                {p.resting ? t("public.resting_short") : p.online ? t("public.online") : t("chat.offline")}
              </span>
            </span>
          </button>
          <div className="flex shrink-0 items-center gap-2.5">
            <button type="button" onClick={() => setLogOpen(true)} aria-label={t("stage.log")} title={t("stage.log")} aria-expanded={logOpen}
                    className={cn(TOP_BTN, "inline-flex items-center justify-center gap-2 text-[13px] font-medium", compact ? "w-10" : "px-4")}>
              <ScrollText className="h-[18px] w-[18px]" />{compact ? null : t("stage.log")}
            </button>
            {p.menuItems?.length ? (
              <DropdownMenu items={p.menuItems} menuClassName="dark"
                trigger={<button type="button" aria-label={t("common.more")} title={t("common.more")} className={cn(TOP_BTN, "inline-flex w-10 items-center justify-center")}><EllipsisVertical className="h-5 w-5" /></button>} />
            ) : null}
          </div>
        </div>

        {/* 대화창 */}
        <div ref={dialog} className="absolute left-1/2 z-10 w-[min(920px,calc(100%-16px))] -translate-x-1/2"
             style={{ bottom: `calc(var(--sab, 0px) + var(--kb-offset, 0px) + ${compact ? 8 : 20}px)` }}>
          <Dialog {...p} scene={scene} compact={compact} onOpenLog={() => setLogOpen(true)} />
        </div>

        {/* 대화 기록 — 무대를 어둡게 하고 오른쪽에서 밀려 나오는 옆 창. 어두운 곳을 누르거나 Esc 로 닫는다. */}
        {logOpen ? (
          <div className="stage-dim absolute inset-0 z-30 flex justify-end bg-black/60" onClick={() => setLogOpen(false)}>
            <aside role="dialog" aria-modal="true" aria-label={t("stage.log")} onClick={(e) => e.stopPropagation()}
                   className={cn("stage-log-in flex h-full flex-col bg-bg shadow-[-24px_0_60px_rgba(0,0,0,0.45)]",
                     compact ? "w-full" : "w-[min(420px,92%)] border-l border-white/10")}>
              {log}
            </aside>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Dialog(p: StageProps & { scene: { said: ChatMessage | null; line: ChatMessage | null; thinking: boolean }; compact: boolean; onOpenLog: () => void }) {
  const t = useT();
  const { scene } = p;
  const [text, setText] = useState("");
  const [rec, setRec] = useState<"idle" | "recording" | "transcribing">("idle");
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const box = useRef<HTMLTextAreaElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const line = scene.line;
  const full = line?.content ?? "";
  // 흐르던 말은 끝나면 서버 번호로 이름이 바뀐다 — 턴 번호로 알아봐야 끝나는 순간 처음부터 다시 쓰지 않는다.
  const shown = useTypewriter(full, line?.turn_id || line?.id || "");
  const typing = shown < full.length;

  useEffect(() => { body.current?.scrollTo({ top: body.current.scrollHeight }); }, [shown, scene.thinking]);

  const send = () => {
    const v = text.trim();
    if (!v || p.disabled || p.busy) return;
    p.onSend(v);
    setText("");
  };
  const startRec = async () => {
    if (!p.onTranscribe) return;
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
        try { const txt = await p.onTranscribe!(blob); if (txt) setText((prev) => (prev ? prev + " " + txt : txt)); box.current?.focus(); }
        catch (e) { toast.error((e as Error).message); }
        finally { setRec("idle"); }
      };
      mr.start(); recorder.current = mr; setRec("recording");
    } catch { toast.error(t("chat.mic_denied")); }
  };

  return (
    <div className="rounded-2xl border border-white/12 bg-[rgba(10,12,20,0.84)] text-white shadow-[0_18px_60px_rgba(0,0,0,0.55)] backdrop-blur-xl">
      {/* 이름표 */}
      <div className={cn("flex items-center gap-2 px-4", p.compact ? "pt-3" : "pt-4")}>
        <span className="shrink-0 rounded-md px-2 py-0.5 text-[13px] font-bold" style={{ background: p.accent, color: p.accentFg }}>{p.agent.name}</span>
        {p.agent.role_line ? <span className="min-w-0 truncate text-[12px] text-white/60">{p.agent.role_line}</span> : null}
        {p.banner ? <span className="ml-auto shrink-0">{p.banner}</span> : null}
      </div>

      {/* 지금 하는 말 — 누르면 끝까지 한 번에 */}
      <div ref={body} onClick={() => shown < full.length && skipRef.current?.()}
           className={cn("overflow-y-auto px-4 pb-2 pt-2", p.compact ? "max-h-[26vh] min-h-[64px]" : "max-h-[172px] min-h-[76px]")}>
        {scene.said ? <p className="mb-1.5 line-clamp-2 text-[12.5px] text-white/55">{t("stage.you")} · {scene.said.content}</p> : null}
        {scene.thinking ? (
          <span className="inline-flex items-center gap-1 py-1.5" aria-label={t("stage.thinking")}>
            {[0, 1, 2].map((i) => <span key={i} className="h-1.5 w-1.5 rounded-full bg-white/80" style={{ animation: `pulse-dot 1.2s ${i * 0.16}s infinite ease-in-out` }} />)}
          </span>
        ) : line ? (
          <div className={cn("text-[15.5px] leading-[1.7] [&_p]:my-0", p.compact && "text-[15px]")}>
            <Markdown text={full.slice(0, shown)} />
            {typing || line.streaming ? <span className="ml-0.5 inline-block h-[15px] w-[2px] translate-y-[2px] animate-pulse bg-white/80" /> : null}
            {line.error ? <p className="mt-1 text-[13px] text-red-300">{line.error.message}</p> : null}
            {line.cancelled ? <p className="mt-1 text-[12px] text-white/50">{t(line.stopReason === "superseded" ? "chat.superseded" : "chat.cancelled")}</p> : null}
            {!typing && line.cards.length ? <div className="mt-2 space-y-2">{line.cards.map((c, i) => <CardRenderer key={i} card={c} actions={p.cardActions} messageId={line.id} />)}</div> : null}
          </div>
        ) : null}
      </div>

      {/* 처음 물어볼 것 */}
      {p.suggestions.length ? (
        <div className="flex flex-wrap gap-1.5 px-4 pb-2">
          {p.suggestions.slice(0, 4).map((q) => (
            <button key={q} type="button" disabled={p.disabled} onClick={() => p.onSend(q)}
                    className="rounded-full border border-white/20 bg-white/8 px-3 py-1.5 text-left text-[12.5px] text-white/90 hover:bg-white/15 disabled:opacity-50">{q}</button>
          ))}
        </div>
      ) : null}

      {/* 말 걸기 */}
      <div className="flex items-end gap-2 border-t border-white/10 px-3 py-2.5">
        <textarea ref={box} rows={1} value={text} disabled={p.disabled}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}
                  placeholder={p.placeholder} aria-label={p.placeholder}
                  className="max-h-28 min-h-[40px] flex-1 resize-none rounded-xl border border-white/12 bg-white/8 px-3 py-2.5 text-[15px] text-white outline-none placeholder:text-white/45 focus:border-white/30 disabled:opacity-60" />
        {p.voice && p.onTranscribe ? (
          <button type="button" disabled={p.disabled || rec === "transcribing"} onClick={() => (rec === "recording" ? (recorder.current?.stop(), (recorder.current = null)) : void startRec())}
                  aria-label={rec === "recording" ? t("chat.stop_recording") : t("chat.record")} title={rec === "recording" ? t("chat.stop_recording") : t("chat.record")}
                  className={cn("inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl disabled:opacity-50", rec === "recording" ? "bg-red-500 text-white" : "text-white/75 hover:bg-white/10")}>
            {rec === "transcribing" ? <Loader2 className="h-5 w-5 animate-spin" /> : <Mic className="h-5 w-5" />}
          </button>
        ) : null}
        {p.busy ? (
          <button type="button" onClick={p.onStop} aria-label={t("chat.stop")}
                  className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl bg-white/12 px-3.5 text-[14px] font-medium text-white hover:bg-white/20">
            <Square className="h-3.5 w-3.5" fill="currentColor" />{t("chat.stop")}
          </button>
        ) : (
          <button type="button" onClick={send} disabled={!text.trim() || p.disabled}
                  className="inline-flex h-10 shrink-0 items-center rounded-xl px-4 text-[14px] font-semibold disabled:opacity-45"
                  style={{ background: p.accent, color: p.accentFg }}>
            {t("stage.talk")}
          </button>
        )}
      </div>
      {/* 상대가 AI 이고 대화가 주인에게 간다는 것을 늘 보이게 (plan/73). 휴대폰은 이 한 줄만. */}
      {p.compact ? (
        <AiNotice ownerName={p.agent.owner_display_name} tone="onDark" className="px-3 pb-2.5" />
      ) : (
        <div className="flex items-center justify-between gap-3 px-4 pb-2.5 text-[11px] text-white/45">
          <AiNotice ownerName={p.agent.owner_display_name} tone="onDark" className="justify-start text-left" />
          <button type="button" onClick={p.onOpenLog} className="shrink-0 underline-offset-2 hover:text-white/80 hover:underline">{t("stage.log_open")}</button>
        </div>
      )}
    </div>
  );
}

/** 한 글자씩. 새 말이면(앞의 말을 이어 쓴 것이 아니면) 처음부터. 밀린 글이 많으면 빨라진다. */
const skipRef: { current: (() => void) | null } = { current: null };
function useTypewriter(text: string, key: string): number {
  const [shown, setShown] = useState(0);
  const pos = useRef(0);
  const prevKey = useRef(key);
  const target = useRef(text);
  target.current = text;
  // 다른 말로 바뀌었으면 처음부터.
  if (prevKey.current !== key) {
    prevKey.current = key;
    pos.current = 0;
  }
  const skip = useCallback(() => { pos.current = target.current.length; setShown(pos.current); }, []);
  skipRef.current = skip;
  useEffect(() => {
    let raf = 0;
    let last = 0;
    const tick = (ts: number) => {
      const dt = last ? Math.min(0.1, (ts - last) / 1000) : 0;
      last = ts;
      const goal = target.current.length;
      if (pos.current < goal) {
        const backlog = goal - pos.current;
        const cps = (1000 / CHAR_MS) * (backlog > 200 ? 5 : backlog > 80 ? 2.5 : 1);
        pos.current = Math.min(goal, pos.current + cps * dt);
        setShown(Math.floor(pos.current));
        raf = requestAnimationFrame(tick);
      } else {
        pos.current = goal;
        setShown(goal);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [text, key]);
  return Math.min(shown, text.length);
}
