"use client";
import { useState } from "react";
import { AlertCircle, Check, ChevronDown, Loader2 } from "@/components/icons";
import type { ToolChipState } from "@/stores/chat";
import { cn } from "@/lib/utils";
import { fmtMs } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n";

export function ToolChip({ tool, showDetail }: { tool: ToolChipState; showDetail?: boolean }) {
  const [open, setOpen] = useState(false);
  const t = useT(); const locale = useLocale();
  // 서버가 붙인 이름표는 한국어다. 다른 말로 쓰는 사람에게는 그 말의 도구 이름을 보인다.
  const key = `tool.${(tool.name ?? "").replace(/^mcp__blackmoa__/, "")}`;
  // 방문자 화면은 도구 이름 대신 "activity" 를 받는다 — 그때는 서버가 함께 보낸 영어 이름표를 쓴다.
  const label = locale === "ko" ? tool.label || tool.name
    : tool.name !== "activity" && t(key) !== key ? t(key) : tool.label_en || tool.label || tool.name;
  return (
    <div className="max-w-full">
      <button type="button" onClick={() => showDetail && setOpen((v) => !v)} aria-expanded={showDetail ? open : undefined}
        className={cn("inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs text-muted-fg", showDetail && "hover:bg-muted", tool.is_error && "border-danger/40 text-danger")}>
        {!tool.done ? <Loader2 className="h-3 w-3 animate-spin shrink-0" /> : tool.is_error ? <AlertCircle className="h-3 w-3 shrink-0" /> : <Check className="h-3 w-3 shrink-0 text-success" />}
        <span className="truncate">{label}</span>
        {tool.done && tool.duration_ms ? <span className="opacity-60 shrink-0">{fmtMs(tool.duration_ms)}</span> : null}
        {showDetail ? <ChevronDown className={cn("h-3 w-3 shrink-0 transition-transform", open && "rotate-180")} /> : null}
      </button>
      {open && showDetail ? (
        <div className="mt-1 rounded-lg border border-border bg-muted/50 p-2 text-[11px] font-mono whitespace-pre-wrap break-all text-muted-fg">
          <div className="font-sans font-medium text-fg mb-1">{tool.name}</div>
          {tool.input_preview ? <div>→ {tool.input_preview}</div> : null}
          {tool.output_preview ? <div className="mt-1">← {tool.output_preview}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
