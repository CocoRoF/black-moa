/**
 * 아바타 창에서 사진을 어디에 얼마나 크게 놓나 (plan/66). 순수한 계산이라 여기 두고 따로 검사한다.
 *
 * 창에 맞춘 크기(바닥에 붙어 선다)가 1배다. 확대는 그 배수, 위치는 창 크기에 대한 비율로 적는다 — 창을
 * 키우면 사진도 같이 커지고 같은 자리에 머문다. 휠은 커서가 가리키는 곳을 붙잡은 채 키우고 줄인다.
 */
import type { PictureView } from './contract';

/** 바닥에 비워 두는 자리: 잠겼을 때는 컨트롤이, 풀었을 때는 막대가 선다. 사진의 발이 거기에 가리지 않게. */
export const RESERVE = 52;
const TOP = 10;
export const DEFAULT_VIEW: PictureView = { scale: 1, x: 0, y: 0 };
export const ZOOM_MIN = 0.2;
export const ZOOM_MAX = 5;
/** 휠 한 칸. */
export const ZOOM_STEP = 1.08;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
export const isDefault = (v: PictureView): boolean => Math.abs(v.scale - 1) < 1e-3 && Math.abs(v.x) < 1e-3 && Math.abs(v.y) < 1e-3;

export interface Figure {
  width: number;
  height: number;
  /** 바탕 없이 서는가. 아니면(사진 배경) 조금 작게, 둥근 카드로. */
  standing: boolean;
}

export interface Layout {
  left: number;
  top: number;
  width: number;
  height: number;
  cx: number;
  cy: number;
  /** 1배일 때 사진 가운데의 높이(바닥에 붙어 선 자리). */
  baseCy: number;
}

export function layout(W: number, H: number, fig: Figure, v: PictureView): Layout {
  const areaW = Math.max(40, W - 16);
  const areaH = Math.max(40, H - RESERVE - TOP);
  const fit = Math.min(areaW / fig.width, areaH / fig.height) * (fig.standing ? 1 : 0.92);
  const baseCy = H - RESERVE - (fig.height * fit) / 2;
  const width = fig.width * fit * v.scale;
  const height = fig.height * fit * v.scale;
  const cx = W / 2 + v.x * W;
  const cy = baseCy + v.y * H;
  return { left: cx - width / 2, top: cy - height / 2, width, height, cx, cy, baseCy };
}

/** 사진의 가운데는 창 안에 둔다 — 아무리 옮기고 줄여도 사진을 잃어버리지 않는다. */
export function clampView(v: PictureView, W: number, H: number, baseCy: number): PictureView {
  return {
    scale: clamp(v.scale, ZOOM_MIN, ZOOM_MAX),
    x: clamp(v.x, -0.5, 0.5),
    y: clamp(v.y, -baseCy / H, (H - baseCy) / H),
  };
}

/**
 * 휠의 움직임 → 몇 칸. 마우스 휠 한 칸(윈도 100, 리눅스 53·120 등)은 한 칸으로, 터치패드처럼 잘게 오는 것은
 * 그만큼 잘게. 위로 굴리면 +.
 */
export function wheelNotches(deltaY: number): number {
  if (!Number.isFinite(deltaY) || deltaY === 0) return 0;
  return Math.abs(deltaY) >= 40 ? -Math.sign(deltaY) : -deltaY / 40;
}

/** (px, py) 를 붙잡은 채 notches 칸만큼 확대·축소. */
export function zoomAt(v: PictureView, W: number, H: number, fig: Figure, px: number, py: number, notches: number): PictureView {
  const L = layout(W, H, fig, v);
  const scale = clamp(v.scale * ZOOM_STEP ** notches, ZOOM_MIN, ZOOM_MAX);
  const r = scale / v.scale;
  const cx = px + (L.cx - px) * r;
  const cy = py + (L.cy - py) * r;
  return clampView({ scale, x: (cx - W / 2) / W, y: (cy - L.baseCy) / H }, W, H, L.baseCy);
}

/** 끌어서 옮기기(화면 픽셀). */
export function panBy(v: PictureView, W: number, H: number, fig: Figure, dx: number, dy: number): PictureView {
  return clampView({ ...v, x: v.x + dx / W, y: v.y + dy / H }, W, H, layout(W, H, fig, v).baseCy);
}
