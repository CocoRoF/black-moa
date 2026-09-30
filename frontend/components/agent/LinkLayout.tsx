"use client";
/**
 * 공개 대화의 모양을 고르고 미리 본다 (plan/71).
 *
 * 채팅(기본)은 지금의 메신저 모양, 무대는 배경 위에 비서가 서고 게임처럼 대화창으로 말하는 모양이다. 미리보기는 그
 * 링크의 실제 공개 화면을 **예시 대화로** PC 와 휴대폰 크기의 틀에 띄운다(`?preview=`). 틀 안의 화면은 그 틀의 크기로
 * 그려지므로 휴대폰 모양이 정말 휴대폰 모양으로 보인다. 미리보기는 방문자 세션을 만들지 않는다.
 */
import { useLayoutEffect, useRef, useState } from "react";
import { MessageSquareText, MonitorSmartphone } from "@/components/icons";
import type { LinkLayout } from "@/components/public/PublicChat";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Dialog } from "@/components/ui/dialog";
import { Segmented } from "@/components/ui/tabs";

export function LayoutPicker({ value, onChange, disabled }: { value: LinkLayout; onChange: (v: LinkLayout) => void; disabled?: boolean }) {
  const t = useT();
  const opts: { v: LinkLayout; title: string; desc: string; art: React.ReactNode }[] = [
    { v: "chat", title: t("links.layout_chat"), desc: t("links.layout_chat_desc"), art: <ChatArt /> },
    { v: "stage", title: t("links.layout_stage"), desc: t("links.layout_stage_desc"), art: <StageArt /> },
  ];
  return (
    <div role="radiogroup" aria-label={t("links.layout")} className="grid grid-cols-2 gap-2">
      {opts.map((o) => (
        <button key={o.v} type="button" role="radio" aria-checked={value === o.v} disabled={disabled} onClick={() => onChange(o.v)}
                className={cn("flex flex-col gap-2 rounded-xl border p-2 text-left transition-colors disabled:opacity-60",
                  value === o.v ? "border-accent bg-accent/8 ring-1 ring-accent" : "border-border hover:bg-muted/60")}>
          <div className="aspect-[16/10] w-full overflow-hidden rounded-lg">{o.art}</div>
          <div className="px-0.5">
            <div className="text-[13px] font-semibold">{o.title}</div>
            <div className="text-[11.5px] leading-snug text-muted-fg">{o.desc}</div>
          </div>
        </button>
      ))}
    </div>
  );
}

/** 채팅 모양의 작은 그림: 주고받는 말풍선. */
function ChatArt() {
  return (
    <div className="flex h-full w-full flex-col justify-end gap-1.5 bg-muted p-2.5">
      <span className="h-2.5 w-3/5 rounded-full bg-card" />
      <span className="ml-auto h-2.5 w-2/5 rounded-full bg-accent/70" />
      <span className="h-2.5 w-1/2 rounded-full bg-card" />
      <span className="mt-1 h-3 w-full rounded-full border border-border bg-card" />
    </div>
  );
}

/** 무대 모양의 작은 그림: 배경, 가운데 선 사람, 아래 대화창. */
function StageArt() {
  return (
    <div className="relative h-full w-full bg-cover bg-center" style={{ backgroundImage: "url(/stage/office-960.webp)" }}>
      <div className="absolute left-1/2 top-[18%] h-[26%] w-[16%] -translate-x-1/2 rounded-full bg-[#f1d4c0] ring-2 ring-[#3b2a22]" />
      <div className="absolute left-1/2 top-[40%] h-[40%] w-[34%] -translate-x-1/2 rounded-t-[40%] bg-[#20263a]" />
      <div className="absolute inset-x-[6%] bottom-[7%] h-[28%] rounded-md border border-white/20 bg-[rgba(10,12,20,0.85)] p-1">
        <span className="block h-1.5 w-1/4 rounded-sm bg-accent" />
        <span className="mt-1 block h-1 w-3/4 rounded-sm bg-white/60" />
        <span className="mt-0.5 block h-1 w-1/2 rounded-sm bg-white/40" />
      </div>
    </div>
  );
}

const PC = { w: 1280, h: 800 };
const PHONE = { w: 390, h: 844 };

/** 그 링크의 공개 화면을 PC·휴대폰 틀에 예시 대화로. 모양을 바꿔 가며 볼 수 있다. */
export function LayoutPreviewDialog({ code, layout: initial, open, onClose }: { code: string | null; layout: LinkLayout; open: boolean; onClose: () => void }) {
  const t = useT();
  const [layout, setLayout] = useState<LinkLayout>(initial);
  const [shown, setShown] = useState({ code, initial });
  if (shown.code !== code || shown.initial !== initial) { setShown({ code, initial }); setLayout(initial); }
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, [open]);
  const src = code ? `/secretary/${encodeURIComponent(code)}?preview=${layout}` : "";
  // 넓으면 나란히(두 틀의 높이를 맞춘다), 좁으면 위아래로.
  const wide = width >= 720;
  const gap = 24;
  const pcScale = wide ? (width - gap) / (PC.w + (PHONE.w * PC.h) / PHONE.h) : width / PC.w;
  const phoneScale = wide ? (PC.h * pcScale) / PHONE.h : Math.min(0.62, (width * 0.7) / PHONE.w);
  return (
    <Dialog open={open} onClose={onClose} size="xl" className="min-[480px]:max-w-[min(1240px,96vw)]"
            title={<span className="flex items-center gap-2"><MonitorSmartphone className="h-5 w-5" />{t("links.preview_title")}</span>}
            description={t("links.preview_hint")}>
      <div className="mb-3 flex justify-center">
        <Segmented value={layout} onChange={(v) => setLayout(v as LinkLayout)}
                   options={[{ value: "chat", label: t("links.layout_chat") }, { value: "stage", label: t("links.layout_stage") }]} />
      </div>
      <div ref={box} className={cn("flex w-full gap-6", wide ? "items-start justify-center" : "flex-col items-center")}>
        {width > 0 && src ? (
          <>
            <Frame key={`pc-${layout}`} src={src} size={PC} scale={pcScale} label={t("links.preview_pc")} />
            <Frame key={`phone-${layout}`} src={src} size={PHONE} scale={phoneScale} label={t("links.preview_mobile")} phone />
          </>
        ) : null}
      </div>
    </Dialog>
  );
}

function Frame({ src, size, scale, label, phone }: { src: string; size: { w: number; h: number }; scale: number; label: string; phone?: boolean }) {
  return (
    <figure className="flex shrink-0 flex-col items-center gap-2">
      <div className={cn("overflow-hidden border border-border bg-black shadow-lg", phone ? "rounded-[22px]" : "rounded-xl")}
           style={{ width: Math.round(size.w * scale), height: Math.round(size.h * scale) }}>
        <iframe src={src} title={label} loading="lazy"
                style={{ width: size.w, height: size.h, border: 0, transform: `scale(${scale})`, transformOrigin: "top left" }} />
      </div>
      <figcaption className="flex items-center gap-1 text-xs text-muted-fg"><MessageSquareText className="h-3.5 w-3.5" />{label}</figcaption>
    </figure>
  );
}
