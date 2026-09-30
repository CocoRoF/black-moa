"use client";
import { memo, useRef } from "react";
import { AlertTriangle, Brain, ShieldAlert, Info, Sparkles } from "@/components/icons";
import type { ChatMessage } from "@/stores/chat";
import { useT } from "@/lib/i18n";
import { MessageAttachments } from "./MessageAttachments";
import { cn } from "@/lib/utils";
import { fmtTime, fmtCredits } from "@/lib/format";
import { Markdown } from "./Markdown";
import { StreamingCursor, TypingDots } from "./StreamingCursor";
import { ToolChip } from "./ToolChip";
import { ThinkingPill } from "./ThinkingPill";
import { CardRenderer, type CardActions } from "./CardRenderer";
import { Avatar } from "@/components/ui/misc";

export interface BubbleProps {
  m: ChatMessage;
  mode: "owner" | "visitor";
  cardActions: CardActions;
  agentName?: string;
  agentAvatar?: string | null;
  showAvatar?: boolean;
  /** Tapping the face is how every messenger opens a profile, so it has to work here too
   *  — the header is not the only thing a person aims at. */
  onAgentClick?: () => void;
  onLongPress?: (m: ChatMessage) => void;
  onRetry?: (m: ChatMessage) => void;
  onTurnInfo?: (turnId: string) => void;
  /** The owner saying this answer was wrong about them (plan/41 §8). */
  onWrong?: (turnId: string) => void;
  bubbleStyle?: string;
}

function useLongPress(cb?: () => void, ms = 450) {
  const timer = useRef<number | null>(null);
  const moved = useRef(false);
  if (!cb) return {};
  return {
    onTouchStart: () => { moved.current = false; timer.current = window.setTimeout(() => { if (!moved.current) cb(); }, ms); },
    onTouchMove: () => { moved.current = true; if (timer.current) window.clearTimeout(timer.current); },
    onTouchEnd: () => { if (timer.current) window.clearTimeout(timer.current); },
    onContextMenu: (e: React.MouseEvent) => { e.preventDefault(); cb(); },
  };
}

export const MessageBubble = memo(function MessageBubble({ m, mode, cardActions, agentName, agentAvatar, showAvatar = true, onAgentClick, onLongPress, onRetry, onTurnInfo, onWrong, bubbleStyle = "soft" }: BubbleProps) {
  const t = useT();
  const lp = useLongPress(onLongPress ? () => onLongPress(m) : undefined);
  const isUser = m.role === "user";
  const radius = bubbleStyle === "square" ? "rounded-lg" : "rounded-2xl";
  // plan/37: a message the secretary sent first, unprompted, is marked as such.
  const proactive = !isUser ? m.cards.find((c) => c.card_type === "proactive") : undefined;

  if (m.role === "card" || (m.role !== "user" && !m.content && !m.streaming && m.cards.length && !m.tools?.length && !m.error)) {
    return (
      <div className="flex justify-start px-3 py-1.5 fade-up">
        <div className="space-y-2">{m.cards.map((c, i) => <CardRenderer key={i} card={c} actions={cardActions} messageId={m.id} />)}</div>
      </div>
    );
  }
  if (m.role === "system") {
    return <div className="px-3 py-1.5 text-center text-xs text-muted-fg">{m.content}</div>;
  }

  return (
    <div className={cn("flex gap-2 px-3 py-1.5", isUser ? "justify-end" : "justify-start")} {...lp}>
      {!isUser && showAvatar ? (
        onAgentClick ? (
          <button type="button" onClick={onAgentClick} aria-label={agentName}
                  className="mt-1 shrink-0 self-start rounded-full transition-opacity hover:opacity-80 focus-visible:outline-2 focus-visible:outline-ring">
            <Avatar mascot name={agentName} src={agentAvatar} size={30} accent="var(--accent)" />
          </button>
        ) : <Avatar mascot name={agentName} src={agentAvatar} size={30} className="mt-1" accent="var(--accent)" />
      ) : null}
      <div className={cn("min-w-0 max-w-[85%] md:max-w-[75%] space-y-1.5", isUser ? "items-end" : "items-start")}>
        {proactive ? <div className="inline-flex items-center gap-1 rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent"><Sparkles className="h-3 w-3" />{t(`chat.proactive_${proactive.payload?.kind ?? "checkin"}`)}</div> : null}
        {!isUser && (m.tools?.length || m.thinking || m.thinkingText) ? (
          <div className="flex flex-wrap gap-1.5">
            <ThinkingPill active={!!m.thinking} text={mode === "owner" ? m.thinkingText : undefined} />
            {m.tools?.map((tool) => <ToolChip key={tool.call_id} tool={tool} showDetail={mode === "owner"} />)}
          </div>
        ) : null}
        {m.attachments?.length ? <MessageAttachments items={m.attachments} align={isUser ? "end" : "start"} /> : null}
        {(m.content || (m.streaming && !m.tools?.length && !m.thinking)) ? (
          <div className={cn("relative px-3.5 py-2.5 text-[15px] leading-relaxed", radius,
            isUser ? "bg-accent text-accent-fg rounded-br-md" : "bg-card border border-border rounded-bl-md",
            m.pending && "opacity-70")}>
            {isUser ? <p className="whitespace-pre-wrap break-words">{m.content}</p> : m.content ? <Markdown text={m.content} /> : null}
            {m.streaming && !isUser && !m.content ? <TypingDots className="text-muted-fg" /> : null}
            {m.streaming && !isUser && m.content ? <StreamingCursor /> : null}
          </div>
        ) : null}
        {m.cards.length ? <div className="space-y-2">{m.cards.map((c, i) => <CardRenderer key={i} card={c} actions={cardActions} messageId={m.id} />)}</div> : null}
        {m.notices?.map((n, i) => <div key={i} className="flex items-center gap-1 text-[11px] text-muted-fg"><Info className="h-3 w-3" />{n}</div>)}
        {m.redacted ? <div className="flex items-center gap-1 text-[11px] text-warning"><ShieldAlert className="h-3 w-3" />{t("chat.redacted", { n: m.redacted })}</div> : null}
        {m.error ? (
          <div role="alert" className="flex flex-wrap items-center gap-2 rounded-xl border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">
            <AlertTriangle className="h-3.5 w-3.5" /><span>{m.error.message || m.error.code}</span>
            {m.error.retryable && onRetry ? <button type="button" className="underline" onClick={() => onRetry(m)}>{t("common.retry")}</button> : null}
          </div>
        ) : null}
        {m.cancelled ? <div className={cn("text-[11px] text-muted-fg", isUser && "text-right")}>{t(m.stopReason === "superseded" ? "chat.superseded" : "chat.cancelled")}</div> : null}
        {m.failedTurn ? <div className={cn("flex items-center gap-1 text-[11px] text-danger", isUser && "justify-end")}><AlertTriangle className="h-3 w-3" />{t("chat.no_answer")}</div> : null}
        {m.created_at || m.usage || m.memory?.count || (m.turn_id && onTurnInfo) ? <div className={cn("flex items-center gap-2 text-[11px] text-muted-fg", isUser ? "justify-end" : "")}>
          {m.created_at ? <span>{fmtTime(m.created_at)}</span> : null}
          {mode === "owner" && !isUser && m.usage ? <span title={`${m.usage.input_tokens}/${m.usage.output_tokens} tok`}>· {fmtCredits(m.usage.credits)} cr</span> : null}
          {mode === "owner" && !isUser && m.memory?.count ? <span className="inline-flex items-center gap-0.5"><Brain className="h-3 w-3" />{m.memory.count}</span> : null}
          {mode === "owner" && !isUser && m.turn_id && onTurnInfo && !m.streaming ? <button type="button" className="underline-offset-2 hover:underline" onClick={() => onTurnInfo(m.turn_id!)}>{t("chat.turn_info")}</button> : null}
          {/* Nobody but the owner can say the secretary got them wrong, so only they see it. */}
          {mode === "owner" && !isUser && m.turn_id && onWrong && !m.streaming ? (
            m.feedback?.verdict === "wrong"
              ? <span className="text-accent">{t(m.feedback.note ? "chat.wrong_fixed" : "chat.wrong_marked")}</span>
              : <button type="button" className="underline-offset-2 hover:underline" onClick={() => onWrong(m.turn_id!)}>{t("chat.mark_wrong")}</button>
          ) : null}
        </div> : null}
      </div>
    </div>
  );
});
