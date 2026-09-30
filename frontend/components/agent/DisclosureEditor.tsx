"use client";
import Link from "next/link";
import type { DisclosurePolicy } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Field, Select } from "@/components/ui/input";
import { TagInput } from "@/components/ui/misc";

/** 비서가 외부인에게 **어떻게 말하는가** — 말해도 되는 주제, 피할 주제, 모를 때 (plan/57).
 *  무엇을 쓰는지는 비서의 [지식] 탭, 프로필 칸이 누구에게 보이는지는 [내 정보 → 정보] 에서 정한다. */
export function DisclosureEditor({ agentId, value, onChange }: { agentId: string; value: DisclosurePolicy; onChange: (p: DisclosurePolicy) => void }) {
  const t = useT();
  const set = (patch: Partial<DisclosurePolicy>) => onChange({ ...value, ...patch });
  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-border px-3.5 py-3">
        <p className="text-sm">{t("disc.where")}</p>
        <Link href={`/app/agents/${agentId}/knowledge`} className="mt-1 inline-block text-sm text-accent hover:underline">
          {t("disc.where_go")}
        </Link>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("disc.topics_public")} hint={t("disc.topics_public_hint")}><TagInput value={value.topics_public ?? []} onChange={(v) => set({ topics_public: v })} placeholder={t("disc.topic_placeholder")} /></Field>
        <Field label={t("disc.topics_private")} hint={t("disc.topics_private_hint")}><TagInput value={value.topics_private ?? []} onChange={(v) => set({ topics_private: v })} placeholder={t("disc.topic_placeholder")} /></Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("disc.unknown_policy")}><Select value={value.unknown_policy ?? "offer_message"} onChange={(e) => set({ unknown_policy: e.target.value as "offer_message" | "say_unknown" })}><option value="offer_message">{t("disc.unk_offer")}</option><option value="say_unknown">{t("disc.unk_say")}</option></Select></Field>
      </div>
    </div>
  );
}
