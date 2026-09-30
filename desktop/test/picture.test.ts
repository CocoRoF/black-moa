/**
 * 아바타 사진의 배치·확대·옮기기 계산 (plan/66).
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DEFAULT_VIEW, RESERVE, ZOOM_MAX, ZOOM_MIN, clampView, layout, panBy, wheelNotches, zoomAt } from '../src/shared/picture';

const W = 340;
const H = 460;
const tall = { width: 600, height: 900, standing: true };

test('1배면 창에 맞춰 바닥(컨트롤 자리 위)에 붙어 선다', () => {
  const L = layout(W, H, tall, DEFAULT_VIEW);
  assert.ok(Math.abs(L.top + L.height - (H - RESERVE)) < 1e-6);
  assert.ok(Math.abs(L.left + L.width / 2 - W / 2) < 1e-6);
  assert.ok(L.width <= W && L.height <= H - RESERVE);
});

test('휠은 커서가 가리키는 곳을 붙잡은 채 키운다', () => {
  const before = layout(W, H, tall, DEFAULT_VIEW);
  const px = before.left + before.width * 0.3;
  const py = before.top + before.height * 0.25;
  const v = zoomAt(DEFAULT_VIEW, W, H, tall, px, py, 3);
  const after = layout(W, H, tall, v);
  assert.ok(Math.abs(v.scale - 1.08 ** 3) < 1e-9);
  assert.ok(Math.abs((px - after.left) / after.width - 0.3) < 1e-9);
  assert.ok(Math.abs((py - after.top) / after.height - 0.25) < 1e-9);
});

test('확대는 한계 안에서만', () => {
  let v = DEFAULT_VIEW;
  for (let i = 0; i < 200; i++) v = zoomAt(v, W, H, tall, W / 2, H / 2, 1);
  assert.equal(v.scale, ZOOM_MAX);
  for (let i = 0; i < 400; i++) v = zoomAt(v, W, H, tall, W / 2, H / 2, -1);
  assert.equal(v.scale, ZOOM_MIN);
});

test('아무리 끌어도 사진의 가운데는 창 안에 있다', () => {
  let v = DEFAULT_VIEW;
  for (let i = 0; i < 50; i++) v = panBy(v, W, H, tall, 500, -500);
  const L = layout(W, H, tall, v);
  assert.ok(L.cx >= 0 && L.cx <= W && L.cy >= 0 && L.cy <= H);
  const c = clampView({ scale: 99, x: -9, y: 9 }, W, H, L.baseCy);
  assert.equal(c.scale, ZOOM_MAX);
  assert.equal(c.x, -0.5);
});

test('창을 키우면 사진도 따라 커지고 같은 자리에 있다', () => {
  const v = { scale: 1.3, x: 0.1, y: -0.05 };
  const a = layout(W, H, tall, v);
  const b = layout(W * 1.5, H * 1.5, tall, v);
  // 바닥의 컨트롤 자리는 픽셀로 고정이라 정확히 1.5배는 아니다(조금 더 커진다).
  assert.ok(b.width / a.width > 1.45 && b.width / a.width < 1.65);
  assert.ok(Math.abs(b.cx / (W * 1.5) - a.cx / W) < 1e-9);
});

test('휠 한 칸은 기기와 상관없이 한 칸', () => {
  assert.equal(wheelNotches(-100), 1);
  assert.equal(wheelNotches(53.33), -1);
  assert.equal(wheelNotches(120), -1);
  assert.equal(wheelNotches(-4), 0.1);
  assert.equal(wheelNotches(0), 0);
  assert.equal(wheelNotches(Number.NaN), 0);
});
