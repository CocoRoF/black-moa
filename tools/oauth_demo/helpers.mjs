import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
/** 녹화본·자막·로그를 두는 곳 — OUT 이 없으면 이 폴더의 out/. */
export const S = process.env.OUT ?? path.join(path.dirname(fileURLToPath(import.meta.url)), 'out');
fs.mkdirSync(S, { recursive: true });
export const O = 'https://black.memo-ora.com';
const env = { ...process.env, DISPLAY: ':77' };
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const xdo = (...a) => execFileSync('xdotool', a.map(String), { env });
export const log = (...a) => { const line = `[${new Date().toISOString().slice(11, 19)}] ${a.join(' ')}`; console.log(line); fs.appendFileSync(`${S}/rec.log`, line + '\n'); };

let cur = { x: 960, y: 540 };
export async function moveTo(x, y, steps = 20) {
  for (let i = 1; i <= steps; i++) {
    const k = i / steps, e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    xdo('mousemove', Math.round(cur.x + (x - cur.x) * e), Math.round(cur.y + (y - cur.y) * e));
    await sleep(14);
  }
  cur = { x, y };
}
/** 화면 좌표 — 창 위치 + 브라우저 틀 높이 + 요소 위치. 창 관리자가 없어 창은 틀까지 창 안에 그린다. */
export async function screenPos(page, loc) {
  const box = await loc.boundingBox();
  if (!box) throw new Error('no box');
  const m = await page.evaluate(() => ({ x: window.screenX, y: window.screenY, top: window.outerHeight - window.innerHeight, left: (window.outerWidth - window.innerWidth) / 2 }));
  return { x: Math.round(m.x + m.left + box.x + box.width / 2), y: Math.round(m.y + m.top + box.y + box.height / 2) };
}
export async function point(page, loc) {
  await loc.waitFor({ state: 'visible', timeout: 30000 });
  await loc.scrollIntoViewIfNeeded().catch(() => {});
  const p = await screenPos(page, loc);
  await moveTo(p.x, p.y);
  return p;
}
export async function click(page, loc, pause = 500) {
  await point(page, loc);
  await sleep(250);
  xdo('click', 1);
  await sleep(pause);
}
export async function type(text, delay = 45) { xdo('type', '--delay', delay, text); }
export async function smoothScrollTo(page, sel, block = 'start') {
  await page.evaluate(([s, b]) => { const el = typeof s === 'string' ? document.querySelector(s) : null; el?.scrollIntoView({ behavior: 'smooth', block: b }); }, [sel, block]);
  await sleep(1500);
}

export class Recorder {
  constructor(file) { this.file = file; this.caps = []; }
  start() {
    this.ff = spawn('ffmpeg', ['-y', '-f', 'x11grab', '-video_size', '1920x1080', '-framerate', '30', '-draw_mouse', '1', '-i', ':77',
      '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', this.file], { stdio: ['pipe', 'ignore', 'ignore'] });
    this.t0 = Date.now();
  }
  /** 흐리게 가릴 화면 영역(화면 좌표). off 로 끝낸다. */
  blurOn(key, x, y, w, h) { this.blurs ??= []; const t = (Date.now() - this.t0) / 1000; this.blurs.push({ key, t0: t, t1: null, x: Math.max(0, Math.round(x)), y: Math.max(0, Math.round(y)), w: Math.round(w), h: Math.round(h) }); log('blur on', key, t.toFixed(1)); }
  blurOff(key) { const t = (Date.now() - this.t0) / 1000; for (const b of this.blurs ?? []) if (b.key === key && b.t1 == null) b.t1 = t; log('blur off', key, t.toFixed(1)); }
  caption(text) { const t = (Date.now() - this.t0) / 1000; this.caps.push({ t, text }); log('caption', t.toFixed(1), text ?? '(clear)'); }
  async stop() {
    this.caption(null);
    this.ff.stdin.write('q');
    await new Promise((r) => this.ff.on('close', r));
    fs.writeFileSync(`${S}/captions.json`, JSON.stringify(this.caps, null, 1));
    fs.writeFileSync(`${S}/blurs.json`, JSON.stringify(this.blurs ?? [], null, 1));
  }
}
