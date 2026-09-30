"use client";
import Link from "next/link";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/** 가입할 때 받는 하나의 동의 (plan/73): 만 14세 이상 + 이용약관 동의 + 개인정보 처리방침 확인.
 *
 *  14세 미만은 법정대리인 동의를 받아야 하는데 그 절차를 두지 않으므로 가입을 받지 않는다. 서버도 이 동의 없이는
 *  가입시키지 않는다(`agree_terms`). 문서는 새 창에서 열어 입력한 것이 사라지지 않게 한다. */
export function TermsAgree({ checked, onChange, className, id = "agree-terms" }: {
  checked: boolean; onChange: (v: boolean) => void; className?: string; id?: string;
}) {
  const t = useT();
  const [before, rest] = t("legal.agree_line").split("{terms}");
  const [middle, after] = (rest ?? "").split("{privacy}");
  const link = "font-medium text-fg underline underline-offset-2 hover:text-accent";
  return (
    <label htmlFor={id} className={cn("flex cursor-pointer items-start gap-2.5 rounded-xl border border-border bg-muted/40 px-3 py-2.5 text-[13px] leading-relaxed text-muted-fg", checked && "border-accent/50 bg-accent/5", className)}>
      <input id={id} type="checkbox" required checked={checked} onChange={(e) => onChange(e.target.checked)}
             className="mt-[3px] h-[18px] w-[18px] shrink-0 rounded accent-[var(--accent)]" />
      <span>
        <span className="font-semibold text-fg">{t("legal.agree_required")}</span>{" "}
        {before}<Link href="/terms" target="_blank" rel="noopener" className={link}>{t("legal.terms")}</Link>{middle}
        <Link href="/privacy" target="_blank" rel="noopener" className={link}>{t("legal.privacy")}</Link>{after}
      </span>
    </label>
  );
}
