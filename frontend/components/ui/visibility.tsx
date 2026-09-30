"use client";
import { Segmented } from "@/components/ui/tabs";
import { useLocale, useT } from "@/lib/i18n";
import { levelHint, levelOptions, normalize, type Level } from "@/lib/visibility";

/**
 * 무엇이 어디까지 나가는지 고르는 자리 (plan/48 §2).
 *
 * 내 정보·지식·인맥·글·기억이 **전부 이 한 부품**을 쓴다. 원천마다 다르게 생긴
 * 고르개를 두면 같은 세 단계인데도 다른 것처럼 보이고, 실제로 어휘가 갈라진다.
 */
export function VisibilityPicker({
  value,
  onChange,
  size = "sm",
  hint = false,
}: {
  value: unknown;
  onChange: (v: Level) => void;
  size?: "sm" | "md";
  /** 고른 것이 무슨 뜻인지 한 줄로 덧붙인다. 좁은 칸에서는 끈다. */
  hint?: boolean;
}) {
  const t = useT();
  const locale = useLocale();
  const level = normalize(value);
  return (
    <div className={hint ? "" : "contents"}>
      <Segmented<Level> size={size} value={level} onChange={onChange} ariaLabel={t("vis.label")}
                        options={levelOptions(locale)} />
      {hint ? <p className="mt-1.5 text-[12px] text-muted-fg">{levelHint(level, locale)}</p> : null}
    </div>
  );
}
