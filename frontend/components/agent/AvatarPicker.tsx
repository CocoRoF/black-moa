"use client";
import { useRef } from "react";
import { Plus } from "@/components/icons";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { AVATAR_GROUPS } from "@/lib/presets";

/** 비서에게 얼굴을 주는 자리 (plan/36).
 *
 *  사진을 찾아오라고 먼저 시키면 거기서 그만두는 사람이 생긴다. 그래서 고를 수 있는
 *  얼굴을 먼저 세워 두고, 직접 올리는 것은 그 옆에 둔다.
 *
 *  줄은 **남자 / 여자** 로 나눈다. 여섯 장을 한 줄에 섞어 두면 고르기 전에 먼저
 *  분류부터 해야 하고, 그건 고르는 사람이 할 일이 아니다. 한 무리 안에서도 그림체가
 *  다르면(사진 / 도트 그림) 줄을 나눈다. 줄마다 다섯 칸이고, 좁은 화면에서는 줄이 넘어가지
 *  않고 동그라미가 작아진다(넓으면 `size`).
 */
export function AvatarPicker({ value, onChange, onUpload, mine, name, size = 64 }: {
  /** 지금 고른 사진의 주소. */
  value: string | null;
  onChange: (src: string) => void;
  /** 파일 하나를 받아 올리고, 올라간 주소를 돌려준다. */
  onUpload: (file: File) => void;
  /** 직접 올린 사진이 이미 있으면 그것도 고를 수 있어야 한다. */
  mine?: string | null;
  name?: string;
  size?: number;
}) {
  const t = useT();
  const file = useRef<HTMLInputElement>(null);
  // 고른 것을 알아볼 때는 `?v=` 를 떼고 본다. 사진을 다시 자르면 그 숫자가 올라가는데,
  // 이미 골라 둔 사람의 주소에는 예전 숫자가 박혀 있다. 그것 때문에 자기가 고른 얼굴에
  // 표시가 사라지면 고른 적이 없는 것처럼 보인다.
  const same = (a: string | null, b: string) => !!a && a.split("?")[0] === b.split("?")[0];
  const dot = (src: string, label: string) => (
    <button key={src} type="button" onClick={() => onChange(src)} aria-pressed={same(value, src)} aria-label={label}
            className={cn("aspect-square w-full rounded-full ring-offset-2 ring-offset-card transition-shadow",
                          same(value, src) ? "ring-2 ring-accent" : "ring-1 ring-border hover:ring-accent/50")}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={name ?? ""} draggable={false} className="h-full w-full rounded-full bg-muted object-cover" />
    </button>
  );
  const row = (key: string | number, children: React.ReactNode) => (
    <div key={key} className="grid grid-cols-5 gap-2.5" style={{ maxWidth: size * 5 + 40 }}>{children}</div>
  );
  return (
    <div className="space-y-3">
      {AVATAR_GROUPS.map((g) => (
        <div key={g.key}>
          <div className="mb-1.5 text-xs font-medium text-muted-fg">{t(`onb.photo_${g.key}`)}</div>
          <div className="space-y-2.5">
            {g.rows.map((r, i) => row(i, r.map((p) => dot(p.src, t(`onb.photo_${g.key}`)))))}
          </div>
        </div>
      ))}
      <div>
        <div className="mb-1.5 text-xs font-medium text-muted-fg">{t("onb.photo_mine")}</div>
        {row("mine", <>
          {mine ? dot(mine, t("onb.photo_custom")) : null}
          <button type="button" onClick={() => file.current?.click()} aria-label={t("onb.photo_custom")}
                  className="flex aspect-square w-full flex-col items-center justify-center gap-0.5 rounded-full border border-dashed border-border text-[10px] text-muted-fg hover:border-accent hover:text-accent">
            <Plus className="h-4 w-4" />{t("onb.photo_add")}
          </button>
        </>)}
      </div>
      <input ref={file} type="file" accept="image/*" hidden
             onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onUpload(f); }} />
    </div>
  );
}
