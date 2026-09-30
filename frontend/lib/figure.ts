/**
 * 무대(plan/71)에 비서를 세울 그림을 준비한다 — PC 앱의 아바타(plan/63)와 같은 방법.
 *
 * 올린 그림을 **그대로** 세운다. 투명한 PNG 면 받은 파일 그대로(프리셋은 원본 전신 PNG 가 온다), 흰(밝은 무채색)
 * 바탕의 그림이면 가장자리에서 이어진 바탕만 걷어 사람만 남긴다(예전에 올린 사진). 바탕을 걷을 수 없는 사진(배경이
 * 있는 사진)은 그대로 둥근 카드로 세운다.
 *
 * 바탕을 걷는 법: 위·왼쪽·오른쪽 가장자리의 밝은 무채색 칸에서 시작해 이어진 밝은 무채색만 따라간다. 아래 가장자리는
 * 시작점이 아니다 — 상반신 그림은 흰 셔츠가 아래에 닿아 있고, 거기서 시작하면 셔츠가 사라진다.
 *
 * 그리고 그 사람이 차지한 사각형(불투명한 곳)을 잰다. 무대는 그것으로 얼굴부터 상체까지를 맞춘다.
 */

export const bgLike = (r: number, g: number, b: number): boolean =>
  Math.max(r, g, b) - Math.min(r, g, b) < 24 && (r * 299 + g * 587 + b * 114) / 1000 > 200;

/** 이미 투명한 곳이 넉넉한가(2% 넘게). */
export function hasAlpha(d: Uint8ClampedArray): boolean {
  let n = 0;
  const total = d.length / 4;
  for (let i = 3; i < d.length; i += 4) if (d[i] < 250) n++;
  return n > total * 0.02;
}

/** 가장자리에서 이어진 밝은 무채색을 걷는다. 못 걷을 그림이면 false. */
export function cutout(d: Uint8ClampedArray, w: number, h: number): boolean {
  const idx = (x: number, y: number) => y * w + x;
  const bg = new Uint8Array(w * h);
  const queue = new Int32Array(w * h);
  let head = 0;
  let tail = 0;
  let edge = 0;
  let edgeBg = 0;
  const seed = (x: number, y: number) => {
    edge++;
    const i = idx(x, y);
    const p = i * 4;
    if (!bgLike(d[p], d[p + 1], d[p + 2])) return;
    edgeBg++;
    if (!bg[i]) {
      bg[i] = 1;
      queue[tail++] = i;
    }
  };
  for (let x = 0; x < w; x++) seed(x, 0);
  for (let y = 1; y < h; y++) {
    seed(0, y);
    seed(w - 1, y);
  }
  if (edgeBg < edge * 0.6) return false;

  while (head < tail) {
    const i = queue[head++];
    const x = i % w;
    const y = (i - x) / w;
    const p = i * 4;
    const r = d[p];
    const g = d[p + 1];
    const b = d[p + 2];
    const visit = (nx: number, ny: number) => {
      if (nx < 0 || ny < 0 || nx >= w || ny >= h) return;
      const j = idx(nx, ny);
      if (bg[j]) return;
      const q = j * 4;
      const nr = d[q];
      const ng = d[q + 1];
      const nb = d[q + 2];
      if (!bgLike(nr, ng, nb)) return;
      if (Math.abs(nr - r) + Math.abs(ng - g) + Math.abs(nb - b) >= 60) return;
      bg[j] = 1;
      queue[tail++] = j;
    };
    visit(x + 1, y);
    visit(x - 1, y);
    visit(x, y + 1);
    visit(x, y - 1);
  }

  // 사람 쪽 가장자리 한 칸을 깎는다(흰 테두리가 남지 않게), 그다음 3×3 로 부드럽게.
  const hard = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = idx(x, y);
      if (bg[i]) continue;
      let keep = 255;
      for (let dy = -1; dy <= 1 && keep; dy++)
        for (let dx = -1; dx <= 1; dx++) {
          const nx = x + dx;
          const ny = y + dy;
          if (nx >= 0 && ny >= 0 && nx < w && ny < h && bg[idx(nx, ny)]) {
            keep = 0;
            break;
          }
        }
      hard[i] = keep;
    }
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let sum = 0;
      let n = 0;
      for (let dy = -1; dy <= 1; dy++)
        for (let dx = -1; dx <= 1; dx++) {
          const nx = x + dx;
          const ny = y + dy;
          if (nx >= 0 && ny >= 0 && nx < w && ny < h) {
            sum += hard[idx(nx, ny)];
            n++;
          }
        }
      const a = Math.round(sum / n);
      const p = idx(x, y) * 4;
      if (a > 0 && a < 255) {
        // 반쯤 비치는 가장자리는 흰 바탕과 섞인 색이다. 흰색을 걷어 본래 색으로(테두리가 희게 뜨지 않게).
        const af = a / 255;
        for (let c = 0; c < 3; c++) d[p + c] = Math.max(0, Math.min(255, Math.round((d[p + c] - (1 - af) * 255) / af)));
      }
      d[p + 3] = Math.min(d[p + 3], a);
    }
  }
  return true;
}

export interface Box { x: number; y: number; w: number; h: number }

/** 불투명한 곳이 차지한 사각형. 없으면 그림 전체. */
export function opaqueBox(d: Uint8ClampedArray, w: number, h: number): Box {
  let x0 = w, y0 = h, x1 = -1, y1 = -1;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (d[(y * w + x) * 4 + 3] > 40) {
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        if (y < y0) y0 = y;
        if (y > y1) y1 = y;
      }
    }
  }
  return x1 < 0 ? { x: 0, y: 0, w, h } : { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };
}

export interface Figure {
  url: string;
  width: number;
  height: number;
  /** 바탕 없이 서는가(투명했거나 걷어 냈다). 아니면 둥근 카드로 세운다. */
  standing: boolean;
  /** 사람이 차지한 곳(그림 좌표). */
  box: Box;
}

const MAX_EDGE = 1400;
/** 사람이 선 자리를 재는 데만 쓰는 크기(그리는 그림이 아니다). */
const MEASURE_EDGE = 640;

/**
 * 주소 → 세울 그림. 실패하면 null(무대는 비서의 첫 글자로 대신한다).
 *
 * 이미 투명한 그림(프리셋의 원본, 투명하게 올린 PNG)은 **받은 파일 그대로** 세운다 — 캔버스에 다시 그려 저장하지
 * 않는다. 캔버스는 사람이 선 자리를 재는 데만 쓴다. 바탕을 걷어야 하는 그림(흰 바탕)만 걷은 결과를 새로 만든다.
 */
export async function prepareFigure(src: string): Promise<Figure | null> {
  try {
    const res = await fetch(src, { credentials: "omit" });
    if (!res.ok) return null;
    const file = await res.blob();
    const bmp = await createImageBitmap(file);
    const W = bmp.width;
    const H = bmp.height;
    // 재기: 작게 그려서 투명한지, 사람이 어디 섰는지.
    const km = Math.min(1, MEASURE_EDGE / Math.max(W, H));
    const mw = Math.max(1, Math.round(W * km));
    const mh = Math.max(1, Math.round(H * km));
    const probe = document.createElement("canvas");
    probe.width = mw;
    probe.height = mh;
    const pctx = probe.getContext("2d", { willReadFrequently: true });
    if (!pctx) { bmp.close(); return null; }
    pctx.drawImage(bmp, 0, 0, mw, mh);
    const small = pctx.getImageData(0, 0, mw, mh);
    if (hasAlpha(small.data)) {
      bmp.close();
      const b = opaqueBox(small.data, mw, mh);
      const box = { x: b.x / km, y: b.y / km, w: b.w / km, h: b.h / km };
      return { url: URL.createObjectURL(file), width: W, height: H, standing: true, box };
    }
    // 흰 바탕의 그림: 가장자리에서 이어진 바탕만 걷는다(걷을 수 없으면 둥근 카드로).
    const k = Math.min(1, MAX_EDGE / Math.max(W, H));
    const w = Math.max(1, Math.round(W * k));
    const h = Math.max(1, Math.round(H * k));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) { bmp.close(); return null; }
    ctx.drawImage(bmp, 0, 0, w, h);
    bmp.close();
    const img = ctx.getImageData(0, 0, w, h);
    if (!cutout(img.data, w, h)) return { url: URL.createObjectURL(file), width: W, height: H, standing: false, box: { x: 0, y: 0, w: W, h: H } };
    ctx.putImageData(img, 0, 0);
    const box = opaqueBox(img.data, w, h);
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/png"));
    if (!blob) return null;
    return { url: URL.createObjectURL(blob), width: w, height: h, standing: true, box };
  } catch {
    return null;
  }
}

/**
 * 무대에 서는 자리(무대 좌표, px). 무대 높이에 대해 사람이 **작게**, 대신 몸이 더 많이 보이게 선다.
 *
 * - 얼마나 보일지는 그림의 모양으로 정한다(사람이 차지한 사각형의 세로/가로): 전신이면 위 55%(머리~엉덩이),
 *   무릎 위까지인 그림이면 75%, 상반신이면 전부. 보이는 부분이 위 여백부터 대화창 조금 아래까지 찬다.
 * - 머리가 무대 높이의 15%(휴대폰 14%)를 넘지 않는다 — 상반신 사진을 그대로 키우면 얼굴만 부풀었다.
 * - 가로로는 PC 에서 무대 폭의 60%, 휴대폰에서는 115%까지(팔 끝은 잘려도 된다).
 * - 그림의 아래 끝(잘린 선)은 대화창 뒤로 숨는다 — 드러나면 필요한 만큼 아래로 내린다.
 */
export function placeFigure(f: Figure, stageW: number, stageH: number, dialogTop: number, compact: boolean): { left: number; top: number; width: number; height: number } {
  const b = f.box;
  const topPad = stageH * (compact ? 0.1 : 0.11);
  if (!f.standing) {
    // 바탕을 걷지 못한 사진: 대화창 위에 둥근 카드로, 작게.
    const s = Math.min((dialogTop - topPad - 24) / f.height, (stageW * (compact ? 0.62 : 0.34)) / f.width, (stageH * 0.42) / f.height);
    return { left: stageW / 2 - (f.width * s) / 2, top: topPad, width: f.width * s, height: f.height * s };
  }
  const aspect = b.h / Math.max(1, b.w);
  const shape = aspect >= 2.2 ? { vis: 0.55, head: 1 / 8 } : aspect >= 1.35 ? { vis: 0.75, head: 1 / 6.5 } : { vis: 1, head: 0.4 };
  const hidden = stageH * 0.06;
  let s = (dialogTop + hidden - topPad) / (b.h * shape.vis);
  s = Math.min(s, (stageH * (compact ? 0.14 : 0.15)) / (b.h * shape.head));
  s = Math.min(s, (stageW * (compact ? 1.15 : 0.6)) / b.w);
  let top = topPad - b.y * s;
  const bottom = top + (b.y + b.h) * s;
  if (bottom < dialogTop + hidden) top += dialogTop + hidden - bottom;
  const width = f.width * s;
  const height = f.height * s;
  const left = stageW / 2 - (b.x + b.w / 2) * s;
  return { left, top, width, height };
}
