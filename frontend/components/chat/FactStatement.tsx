"use client";
import { useLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const KO: Record<string, string> = { owner: "오너", visitor: "방문자", user: "사용자", agent: "비서", name: "이름", nickname: "별명", email: "이메일", phone: "전화번호", company: "소속", title: "직함", role: "역할", location: "지역", birthday: "생일", likes: "좋아함", dislikes: "싫어함", prefers: "선호", hobby: "취미", language: "언어", timezone: "시간대", works_at: "근무처", lives_in: "거주지", knows: "아는 사람", has: "보유", is: "은/는", wants: "원함", schedule: "일정", availability: "가용 시간" };
const humanize = (s: string, locale: string) => (locale === "ko" && KO[s.toLowerCase()]) || s.replace(/_/g, " ");

/** subject · predicate · **object** — accepts structured fields or a space-joined `statement` ("owner name 테스트"). */
export function FactStatement({ subject, predicate, object, statement, className }: { subject?: string; predicate?: string; object?: string; statement?: string; className?: string }) {
  const locale = useLocale();
  let s = subject ?? "", p = predicate ?? "", o = object ?? "";
  if (!s && !p && !o && statement) {
    const parts = statement.trim().split(/\s+/);
    if (parts.length >= 3) { s = parts[0]; p = parts[1]; o = parts.slice(2).join(" "); } else o = statement;
  }
  if (!s && !p) return <span className={cn("font-semibold", className)}>{o}</span>;
  return (
    <span className={cn("inline-flex flex-wrap items-baseline gap-x-1.5", className)}>
      <span className="text-muted-fg">{humanize(s, locale)}</span>
      <span className="text-muted-fg/60">·</span>
      <span className="text-muted-fg">{humanize(p, locale)}</span>
      <span className="text-muted-fg/60">·</span>
      <span className="font-semibold text-fg">{o}</span>
    </span>
  );
}
