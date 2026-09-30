"use client";
import Link from "next/link";
import { Sparkles } from "@/components/icons";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/** 방문자에게 미리 알리는 한 줄 (plan/73): 상대는 AI 비서이고, 나눈 대화는 그 비서의 주인에게 전달된다.
 *  인공지능 기본법 제31조의 사전 고지이자, 대화가 주인에게 간다는 개인정보 안내. 약관·처리방침을 새 창으로 연다. */
export function AiNotice({ ownerName, className, tone = "muted" }: { ownerName: string; className?: string; tone?: "muted" | "onDark" }) {
  const t = useT();
  const link = tone === "onDark" ? "underline underline-offset-2 hover:text-white" : "underline underline-offset-2 hover:text-fg";
  return (
    <p className={cn("flex flex-wrap items-center justify-center gap-x-1.5 gap-y-0.5 text-center text-[11.5px] leading-snug",
      tone === "onDark" ? "text-white/55" : "text-muted-fg", className)}>
      <Sparkles aria-hidden className="h-3 w-3 shrink-0" />
      <span>{t("public.ai_notice", { owner: ownerName })}</span>
      <span aria-hidden>·</span>
      <Link href="/terms" target="_blank" rel="noopener" className={link}>{t("legal.terms")}</Link>
      <span aria-hidden>·</span>
      <Link href="/privacy" target="_blank" rel="noopener" className={link}>{t("legal.privacy")}</Link>
    </p>
  );
}
