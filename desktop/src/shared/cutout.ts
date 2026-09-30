/**
 * 흰(밝은 무채색) 바탕을 걷어 사람만 남긴다 (plan/63). 픽셀 배열만 다루는 순수한 셈이라 창과 시험이 함께 쓴다.
 * 걷는 법은 renderer/src/character.ts 의 머리말에 있다.
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
        // 반쯤 비치는 가장자리는 흰 바탕과 섞인 색이다. 흰색을 걷어 내 본래 색으로(테두리가 희게 뜨지 않게).
        const af = a / 255;
        for (let c = 0; c < 3; c++) d[p + c] = Math.max(0, Math.min(255, Math.round((d[p + c] - (1 - af) * 255) / af)));
      }
      d[p + 3] = Math.min(d[p + 3], a);
    }
  }
  return true;
}

