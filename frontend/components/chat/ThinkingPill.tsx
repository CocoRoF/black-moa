"use client";
import { useState } from "react";
import { Brain, ChevronDown } from "@/components/icons";
import { useT } from "@/lib/i18n";
import { TypingDots } from "./StreamingCursor";
import { cn } from "@/lib/utils";

export function ThinkingPill({ active, text, label }: { active: boolean; text?: string; label?: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  if (!active && !text) return null;
  return (
    <div>
      <button type="button" onClick={() => text && setOpen((v) => !v)} className={cn("inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-xs text-muted-fg", text && "hover:bg-border/60")}>
        <Brain className="h-3 w-3" />
        <span>{label ?? (active ? t("chat.thinking") : t("chat.thought"))}</span>
        {active ? <TypingDots className="ml-0.5" /> : null}
        {text ? <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} /> : null}
      </button>
      {open && text ? <div className="mt-1 max-h-48 overflow-y-auto rounded-lg border border-border bg-muted/40 p-2 text-[12px] text-muted-fg whitespace-pre-wrap">{text}</div> : null}
    </div>
  );
}
