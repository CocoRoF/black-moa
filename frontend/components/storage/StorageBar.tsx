"use client";
import Link from "next/link";
import type { StorageSegment, StorageUsage } from "@/lib/api";
import { HoverCard } from "@/components/ui/hover-card";
import { fmtBytes } from "@/lib/upload";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";

/** 저장 공간 막대 (plan/55 §3-3). 구글 저장 공간과 같은 모양: 막대 하나를 칸 수만큼 나눠
 *  칠하고, 칸이나 범례에 올려 두면 정확한 용량이 뜬다.
 *
 *  색은 칸마다 고정이다. 비서는 만든 순서대로 판에서 고른다 — 비서의 테마 색을 쓰면
 *  지식 저장소와 거의 같은 파랑이 나와 두 칸이 한 칸처럼 보였다. 판에는 고정 색과 겹치는
 *  색이 없다.
 *
 *  **칸은 아무리 작아도 10px 이다.** 실제 비율대로만 그리면 3GB 중 몇 MB 는 실처럼 가늘어
 *  보이지 않는다. 그렇다고 칸마다 최소 너비를 따로 주면, 거의 가득 찼을 때 작은 칸들의
 *  덤이 쌓여 막대 밖으로 삐져나간다. 그래서 두 단계로 그린다:
 *   1. 쓴 양만큼의 구간 하나 — 너비는 실제 비율(최대 100%), 다만 칸 수 × 10px 보다 좁지 않게.
 *   2. 그 구간을 칸마다 용량에 비례해 나눈다(flex-grow). 10px 에 못 미치는 칸은 10px 에
 *      고정되고, 모자란 만큼은 브라우저가 나머지 칸에서 비율대로 덜어 낸다.
 *  칸들의 합은 늘 구간과 같고 구간은 막대를 넘지 않으니, 가득 차도 튀어나가지 않는다.
 */
export const MIN_SEGMENT_PX = 10;
const FIXED: Record<string, string> = { knowledge: "#6366f1", files: "#0f766e", messenger: "#14b8a6", other: "#94a3b8" };
const PALETTE = ["#f59e0b", "#ec4899", "#22c55e", "#0ea5e9", "#a855f7", "#ef4444", "#84cc16", "#f97316"];

export function segmentColor(s: StorageSegment, agentIndex: number): string {
  if (s.kind !== "agent") return FIXED[s.kind] ?? FIXED.other;
  return PALETTE[agentIndex % PALETTE.length];
}

export function segmentLabel(s: StorageSegment, t?: (k: string) => string): string {
  const tr = t ?? ((k: string) => k);
  if (s.kind === "knowledge") return tr("storage.seg_knowledge");
  if (s.kind === "files") return tr("storage.seg_files");
  if (s.kind === "messenger") return tr("storage.seg_messenger");
  if (s.kind === "other") return tr("storage.seg_other");
  return s.name || tr("storage.seg_agent");
}

function colored(u: StorageUsage) {
  let i = 0;
  return u.segments.map((s) => ({ s, color: segmentColor(s, s.kind === "agent" ? i++ : 0) }));
}

function SegmentCard({ s, color }: { s: StorageSegment; color: string }) {
  const t = useT();
  return (
    <div className="space-y-1 text-sm">
      <div className="flex items-center gap-2 font-medium"><span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />{segmentLabel(s, t)}</div>
      <div className="tabular-nums">{fmtBytes(s.bytes)} <span className="text-muted-fg">({t("files.bytes", { n: s.bytes.toLocaleString() })})</span></div>
      <div className="text-xs text-muted-fg">
        {t("storage.files_n", { n: s.files.toLocaleString() })}{s.kind === "agent" && s.visitor_files ? ` · ${t("storage.visitor_files_n", { n: s.visitor_files.toLocaleString() })}` : ""}
      </div>
    </div>
  );
}

export function StorageBar({ usage, highlight, highlightLabel, compact, className, segmentHref }: {
  usage: StorageUsage; highlight?: string; compact?: boolean; className?: string;
  /** 강조한 칸이 아직 비어 있을 때 쓸 이름(예: 파일이 없는 비서). */
  highlightLabel?: string;
  /** 범례를 누르면 갈 곳. 없으면 범례는 올려 두기만 한다. */
  segmentHref?: (s: StorageSegment) => string | null;
}) {
  const t = useT();
  const segs = colored(usage);
  const pct = Math.min(100, usage.ratio * 100);
  const tone = usage.ratio >= 1 ? "danger" : usage.ratio >= 0.9 ? "warning" : null;
  const filled = segs.filter(({ s }) => s.bytes > 0);
  // 강조할 칸이 막대에 있을 때만 나머지를 흐린다. 비어 있는 칸을 강조하면 전부 흐려져 아무것도 안 보인다.
  const dimOthers = !!highlight && filled.some(({ s }) => s.key === highlight);
  const usedSum = filled.reduce((n, { s }) => n + s.bytes, 0);
  // 한도를 넘겨 쓴 경우에도 구간은 막대 끝(100%)에서 멈춘다.
  const denom = Math.max(usage.limit_bytes, usedSum, 1);
  const bar = (
    <div className={cn("flex w-full overflow-hidden rounded-full bg-muted", compact ? "h-2" : "h-3",
      tone === "danger" && "ring-1 ring-danger/60", tone === "warning" && "ring-1 ring-warning/60")}
      role="img" aria-label={t("storage.used", { used: fmtBytes(usage.used_bytes), limit: fmtBytes(usage.limit_bytes), pct: Math.round(pct) })}>
      {filled.length ? (
        <div data-storage-used className="flex h-full shrink-0"
             style={{ width: `${(usedSum / denom) * 100}%`, minWidth: `min(100%, ${filled.length * MIN_SEGMENT_PX}px)` }}>
          {filled.map(({ s, color }) => (
            <HoverCard key={s.key} content={<SegmentCard s={s} color={color} />} side="top" as="span"
              className={cn("block h-full transition-opacity", dimOthers && highlight !== s.key && "opacity-35")}
              // 나눠 가질 몫은 용량 비율(합 1000), 바탕 너비 0, 최소 MIN_SEGMENT_PX. 칸이 아주 많아
              // 막대가 칸 수 × 10px 보다 좁으면 최소는 막대를 칸 수로 나눈 만큼 — 그래도 넘치지 않는다.
              style={{ flex: `${(s.bytes / usedSum) * 1000} 1 0px`, minWidth: `min(${MIN_SEGMENT_PX}px, ${100 / filled.length}%)`, background: color }}>
              <span className="sr-only">{segmentLabel(s, t)} {fmtBytes(s.bytes)}</span>
            </HoverCard>
          ))}
        </div>
      ) : null}
    </div>
  );
  const summary = (
    <span className={cn("tabular-nums", tone === "danger" ? "text-danger" : tone === "warning" ? "text-warning" : "")}>
      {t("storage.used", { used: fmtBytes(usage.used_bytes), limit: fmtBytes(usage.limit_bytes), pct: Math.round(pct) })}
    </span>
  );

  if (compact) {
    const mine = highlight ? usage.segments.find((s) => s.key === highlight) : undefined;
    return (
      <div className={cn("flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3", className)}>
        <div className="min-w-0 flex-1">{bar}</div>
        <div className="flex shrink-0 items-center gap-2 text-xs text-muted-fg">
          {/* 이 화면이 무엇의 칸인지 이름으로 말한다: "지식 1.2 MB", "제니 15.7 KB". */}
          {mine || highlightLabel ? <span><b className="font-medium text-fg">{mine ? segmentLabel(mine, t) : highlightLabel}</b> {fmtBytes(mine?.bytes ?? 0)} ·</span> : null}
          {summary}
          <Link href="/app/cloud" className="font-medium text-accent underline-offset-2 hover:underline">{t("storage.manage")}</Link>
        </div>
      </div>
    );
  }

  const shown = segs.filter(({ s }) => s.bytes > 0);
  return (
    <div className={cn("space-y-3", className)}>
      <div className="text-lg font-semibold">{summary}</div>
      {bar}
      {shown.length ? (
        <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-sm">
          {shown.map(({ s, color }) => {
            const href = segmentHref?.(s);
            const face = <><span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />{segmentLabel(s, t)}<span className="text-muted-fg tabular-nums">{fmtBytes(s.bytes)}</span></>;
            return (
              <li key={s.key}>
                <HoverCard content={<SegmentCard s={s} color={color} />} side="bottom" align="start" focusable={!href}
                  className="inline-flex rounded-md hover:bg-muted">
                  {href ? <Link href={href} className="inline-flex items-center gap-1.5 px-1 py-0.5">{face}</Link>
                    : <span className="inline-flex items-center gap-1.5 px-1 py-0.5">{face}</span>}
                </HoverCard>
              </li>
            );
          })}
        </ul>
      ) : <p className="text-sm text-muted-fg">{t("storage.none")}</p>}
    </div>
  );
}
