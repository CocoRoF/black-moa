/**
 * 아바타가 세울 그림을 준비한다 (plan/63).
 *
 * 올린 그림을 **그대로** 세운다 — 동그라미로 자르지 않는다. 투명한 PNG 면 **받은 파일 그대로**(다시 그려 저장하지
 * 않는다 — 프리셋은 서버가 원본 전신 PNG 를 준다), 흰(혹은 밝은 무채색) 바탕의 그림이면 가장자리에서 이어진 바탕만
 * 걷어 내 사람만 남긴다. 예전에 올린 사진은 흰 바탕의 JPEG 라서 이것이 없으면 네모 판이 데스크톱 위에 뜬다.
 *
 * 바탕을 걷는 법: 위·왼쪽·오른쪽 가장자리의 밝은 무채색 칸에서 시작해 이어진 밝은 무채색만 따라간다.
 * 아래 가장자리에서는 시작하지 않는다 — 상반신 그림은 흰 셔츠가 아래 가장자리에 닿아 있고, 거기서 시작하면
 * 셔츠가 사라진다. 안쪽의 흰 것(셔츠·눈)은 바탕과 이어지지 않으므로 남는다. 가장자리가 대부분 바탕이
 * 아니면(사진 배경) 오리지 않고 그대로 둥근 모서리의 카드로 세운다.
 */

import { cutout, hasAlpha } from '@shared/cutout';

export interface Prepared {
  url: string;
  /** 바탕 없이 서는가(투명했거나 오려 냈다). 아니면 카드로 세운다. */
  standing: boolean;
  width: number;
  height: number;
}

const MAX_EDGE = 900;
/** 투명한지 재는 데만 쓰는 크기. */
const MEASURE_EDGE = 480;

/** 바이트 → 세울 그림. 실패하면 null(창은 블랙모아 표식을 세운다). */
export async function prepare(bytes: ArrayBuffer): Promise<Prepared | null> {
  try {
    const file = new Blob([bytes]);
    const bmp = await createImageBitmap(file);
    // 이미 투명하면 받은 파일 그대로 — 캔버스는 재는 데만 쓴다.
    const km = Math.min(1, MEASURE_EDGE / Math.max(bmp.width, bmp.height));
    const probe = document.createElement('canvas');
    probe.width = Math.max(1, Math.round(bmp.width * km));
    probe.height = Math.max(1, Math.round(bmp.height * km));
    const pctx = probe.getContext('2d', { willReadFrequently: true });
    if (pctx) {
      pctx.drawImage(bmp, 0, 0, probe.width, probe.height);
      if (hasAlpha(pctx.getImageData(0, 0, probe.width, probe.height).data)) {
        const out = { url: URL.createObjectURL(file), standing: true, width: bmp.width, height: bmp.height };
        bmp.close();
        return out;
      }
    }
    const k = Math.min(1, MAX_EDGE / Math.max(bmp.width, bmp.height));
    const w = Math.max(1, Math.round(bmp.width * k));
    const h = Math.max(1, Math.round(bmp.height * k));
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return null;
    ctx.drawImage(bmp, 0, 0, w, h);
    bmp.close();
    const img = ctx.getImageData(0, 0, w, h);
    let standing = hasAlpha(img.data);
    if (!standing && cutout(img.data, w, h)) {
      ctx.putImageData(img, 0, 0);
      standing = true;
    }
    const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, 'image/png'));
    if (!blob) return null;
    return { url: URL.createObjectURL(blob), standing, width: w, height: h };
  } catch {
    return null;
  }
}
