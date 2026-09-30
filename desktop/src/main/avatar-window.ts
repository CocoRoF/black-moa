/**
 * 아바타 (plan/66) — XGen Dex 의 아바타 공간을 사진으로.
 *
 * 창이 둘이다.
 *
 *   아바타 창   테두리 없는 투명 창. 비서가 올린 사진이 그대로 서고, 말은 그 위의 말풍선으로 나온다.
 *   컨트롤 창   잠겼을 때 사진 아래에 붙어 다니는 작은 단추 줄(말하기·소리·글로·대화·잠금 풀기).
 *               마우스가 아바타(사진·말풍선) 위에 있을 때만 나온다. 숨어 있는 동안은 클릭도 뒤로 흐른다.
 *
 * 왜 둘인가. 잠긴 아바타는 클릭을 뒤의 데스크톱으로 흘려보내야 한다(곁에 떠 있되 일을 막지 않는다). 그런데
 * 입력이 통과하는 창은 **자기 잠금 해제 단추를 담을 수 없다.** 마우스가 단추 위에 오면 입력을 되살리는 식은
 * 리눅스에서 아예 안 되고(통과 창에는 이동 이벤트도 안 온다), 윈도·맥에서도 되살리는 사이에 누른 클릭이
 * 사라진다. 그래서 단추는 늘 눌리는 작은 창에 따로 산다(Dex·geny-connector 가 겪고 고친 그대로).
 *
 * 잠금을 풀면 아바타 창이 입력을 잡는다: 점선 틀의 여덟 손잡이로 크기를, 아래 막대의 손잡이로 자리를,
 * 사진 위에서 휠로 확대·축소, 끌어서 사진을 옮긴다. 잠금은 여기 한 곳이 가진다 — 두 창이 서로 다르게
 * 알고 있으면 "잠겼다는데 안 잠긴" 상태가 보인다.
 *
 * 자리와 크기는 화면마다 기억한다. 사진의 모양(확대·위치)은 사진마다 기억한다.
 */
import { BrowserWindow, screen, type Display, type Rectangle } from 'electron';
import { join } from 'node:path';
import { CH, IDLE_STATUS, type AvatarActivity, type AvatarCommand, type AvatarStatus, type AvatarSubject, type HitArea, type ResizeEdge, type SayState } from '@shared/contract';
import * as settings from './settings';
import * as voice from './voice';

let win: BrowserWindow | null = null;
let chip: BrowserWindow | null = null;
let subject: AvatarSubject = { agentId: null, name: '', avatarUrl: null, imageUrl: null };
let locked = true;
let activity: AvatarActivity = IDLE_STATUS;
let pages: { preload: string; rendererRoot: string; devUrl?: string } | null = null;
let watchingScreens = false;

/** 창이 이보다 작아지면 단추 줄이 사진을 다 가린다. */
export const MIN = { width: 240, height: 240 };
/** 컨트롤 창과 아바타 창 바닥 사이. */
const CHIP_MARGIN = 6;
/** 첫 보고 전의 컨트롤 크기는 작게 — 크게 잡으면 남는 투명한 자리가 잠깐 데스크톱 클릭을 먹는다. */
let chipSize = { w: 46, h: 38 };

const IS_LINUX = process.platform === 'linux';

export const current = (): BrowserWindow | null => (win && !win.isDestroyed() ? win : null);
const chipWin = (): BrowserWindow | null => (chip && !chip.isDestroyed() ? chip : null);
export const describe = (): AvatarSubject => ({ ...subject });
export const isLocked = (): boolean => locked;

// ───────────────────────── 항상 위 ─────────────────────────

/**
 * 한 번 "항상 위" 로 올려 두면 시간이 지나며 풀린다: 전체 화면·배율 전환이 그 표시를 벗기고, 나중에 뜬
 * 다른 "항상 위" 창이 위로 올라선다. 내려갈 수 있는 바로 그 순간들에 다시 올리고, 늦게 오는 전환(전체 화면
 * 진입)을 위해 조금 뒤에 한 번 더 본다. 쉬지 않고 도는 타이머는 두지 않는다.
 */
function armAlwaysOnTop(w: BrowserWindow): void {
  let settle: NodeJS.Timeout | null = null;
  const now = (): void => {
    if (w.isDestroyed() || !w.isVisible() || w.isMinimized()) return;
    try {
      w.setAlwaysOnTop(true, 'screen-saver');
      if (process.platform === 'darwin') w.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
      w.moveTop();
      raiseChip();
    } catch {
      /* 닫히는 중 */
    }
  };
  const assert = (): void => {
    now();
    if (settle) clearTimeout(settle);
    settle = setTimeout(() => {
      settle = null;
      now();
    }, 900);
  };
  now();
  w.on('show', assert);
  w.on('restore', assert);
  w.on('blur', assert);
  w.on('always-on-top-changed', (_e, on) => {
    if (!on) assert();
  });
  const onMetrics = (): void => assert();
  screen.on('display-metrics-changed', onMetrics);
  w.on('closed', () => {
    if (settle) clearTimeout(settle);
    screen.removeListener('display-metrics-changed', onMetrics);
  });
}

// ───────────────────────── 자리 ─────────────────────────

const displayKey = (d: Display): string => `${d.bounds.x},${d.bounds.y}:${d.size.width}x${d.size.height}@${d.scaleFactor}`;
let lastDisplay = '';

/** 작업 영역 안으로(작업 표시줄을 덮지 않게). 크기는 그 화면보다 크지 않게. */
function clampTo(b: Rectangle): Rectangle {
  const wa = screen.getDisplayMatching(b).workArea;
  const width = Math.max(MIN.width, Math.min(Math.round(b.width), wa.width));
  const height = Math.max(MIN.height, Math.min(Math.round(b.height), wa.height));
  const x = Math.round(Math.min(Math.max(b.x, wa.x), wa.x + wa.width - width));
  const y = Math.round(Math.min(Math.max(b.y, wa.y), wa.y + wa.height - height));
  return { x, y, width, height };
}

function visibleSomewhere(b: Rectangle): boolean {
  return screen.getAllDisplays().some((d) => {
    const wa = d.workArea;
    const ix = Math.min(b.x + b.width, wa.x + wa.width) - Math.max(b.x, wa.x);
    const iy = Math.min(b.y + b.height, wa.y + wa.height) - Math.max(b.y, wa.y);
    return ix > 40 && iy > 40;
  });
}

/** 마지막 자리가 지금 어느 화면 위면 그 화면에서 쓰던 크기로, 아니면(화면을 뗐다) 주 화면 오른쪽 아래. */
function initialBounds(): Rectangle {
  const last = settings.avatarBounds();
  if (last && visibleSomewhere(last)) {
    const d = screen.getDisplayMatching(last);
    return clampTo(settings.avatarBoundsOn(displayKey(d)) ?? last);
  }
  const wa = screen.getPrimaryDisplay().workArea;
  const { width, height } = settings.AVATAR_DEFAULT;
  return clampTo({ x: wa.x + wa.width - width - 28, y: wa.y + wa.height - height - 28, width, height });
}

/** 지금 자리를 적는다. 다른 화면으로 옮겨 갔으면 그 화면에서 쓰던 크기로 맞춘 뒤에. */
function persist(now = false): void {
  const w = current();
  if (!w || w.isMinimized()) return;
  const d = screen.getDisplayMatching(w.getBounds());
  const key = displayKey(d);
  if (lastDisplay && key !== lastDisplay) {
    const there = settings.avatarBoundsOn(key);
    if (there) {
      const b = w.getBounds();
      w.setBounds(clampTo({ x: b.x, y: b.y, width: there.width, height: there.height }));
      syncChip();
    }
  }
  lastDisplay = key;
  settings.setAvatarBounds(key, w.getBounds(), now);
}

// ── 끌어 옮기기 ──
//
// setPosition(getPosition()+이동)은 배율 150% 윈도에서 창을 키운다: 안에서 지금 크기를 읽어 다시 쓰는데
// 읽을 때마다 반올림된 조금 큰 크기가 나와, 한 번 끄는 동안 수백 번 쌓인다(setBounds 도 같다). 그래서 끌기가
// 시작될 때 한 번 읽은 사각형을 여기서 들고, 매번 **같은 크기**로 자리만 바꿔 쓴다.
let moveRect: { x: number; y: number; w: number; h: number } | null = null;
let moveIdle: NodeJS.Timeout | null = null;

export function moveBy(dx: number, dy: number): void {
  const w = current();
  if (!w || !Number.isFinite(dx) || !Number.isFinite(dy)) return;
  if (!moveRect) {
    const b = w.getBounds();
    moveRect = { x: b.x, y: b.y, w: b.width, h: b.height };
  }
  moveRect.x += dx;
  moveRect.y += dy;
  w.setBounds({ x: Math.round(moveRect.x), y: Math.round(moveRect.y), width: moveRect.w, height: moveRect.h });
  // 리눅스는 코드로 옮긴 창에 'moved' 를 주지 않는다. 컨트롤은 여기서 직접 따라오게 한다.
  syncChip();
  if (moveIdle) clearTimeout(moveIdle);
  moveIdle = setTimeout(commitBounds, 300); // 손을 뗀 소식이 오지 않아도 끝난 것으로
}

export function resizeBy(edge: ResizeEdge, dx: number, dy: number): void {
  const w = current();
  if (!w || !Number.isFinite(dx) || !Number.isFinite(dy)) return;
  let { x, y, width, height } = w.getBounds();
  if (edge.includes('e')) width = Math.max(MIN.width, width + Math.round(dx));
  if (edge.includes('s')) height = Math.max(MIN.height, height + Math.round(dy));
  if (edge.includes('w')) {
    const nw = Math.max(MIN.width, width - Math.round(dx));
    x += width - nw;
    width = nw;
  }
  if (edge.includes('n')) {
    const nh = Math.max(MIN.height, height - Math.round(dy));
    y += height - nh;
    height = nh;
  }
  w.setBounds({ x, y, width, height });
  syncChip();
}

/** 끌기가 끝났다 — 곧 꺼져도 잃지 않게 바로 적는다. */
export function commitBounds(): void {
  if (moveIdle) clearTimeout(moveIdle);
  moveIdle = null;
  moveRect = null;
  persist(true);
}

// ───────────────────────── 컨트롤 창 ─────────────────────────

function chipBounds(b: Rectangle): Rectangle {
  return {
    x: Math.round(b.x + (b.width - chipSize.w) / 2),
    y: Math.round(b.y + b.height - chipSize.h - CHIP_MARGIN),
    width: chipSize.w,
    height: chipSize.h,
  };
}

/** 컨트롤이 아바타 창 바닥을 덮는 높이. 아바타 창은 그 존재를 모르니, 두 사각형을 다 아는 여기서 알린다. */
function chipInset(): number {
  // 컨트롤은 마우스를 올렸을 때만 보이지만, 그 자리는 잠겨 있는 동안 늘 비워 둔다 — 나오고 숨을 때마다 말풍선이
  // 오르내리지 않게(plan/70).
  return chipWin() && locked ? chipSize.h + CHIP_MARGIN * 2 : 0;
}

function publishInset(): void {
  current()?.webContents.send(CH.chipInset, chipInset());
}

function raiseChip(): void {
  const c = chipWin();
  if (!c || !c.isVisible()) return;
  try {
    c.setAlwaysOnTop(true, 'screen-saver');
    c.moveTop();
  } catch {
    /* 닫히는 중 */
  }
}

function syncChip(): void {
  const c = chipWin();
  const w = current();
  if (!c || !w) return;
  try {
    c.setBounds(chipBounds(w.getBounds()));
    raiseChip();
  } catch {
    /* 닫히는 중 */
  }
}

/** 잠겨 있고 아바타가 보일 때만. 숨은 아바타 위에 단추만 떠 있으면 무엇의 단추인지 알 수 없다. */
/** 잠겨 있고, 아바타가 보이고, 마우스가 아바타 위에 있을 때만 컨트롤 창이 뜬다(plan/70). */
function applyChipVisibility(): void {
  const c = chipWin();
  if (!c) return;
  const w = current();
  if (locked && w && w.isVisible() && revealed) {
    syncChip();
    // 포커스를 가져가지 않는다 — 마우스를 올릴 때마다 하던 일에서 끌려 나오면 곁에 있는 것이 아니다.
    if (!c.isVisible()) c.showInactive();
    raiseChip();
  } else if (c.isVisible()) {
    c.hide();
  }
  publishInset();
}

function load(w: BrowserWindow, page: string): void {
  if (!pages) return;
  if (pages.devUrl) void w.loadURL(`${pages.devUrl}/${page}`);
  else void w.loadFile(join(pages.rendererRoot, page));
}

function createChip(preload: string): void {
  if (chipWin()) return;
  chip = new BrowserWindow({
    width: chipSize.w,
    height: chipSize.h,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    movable: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    hasShadow: false,
    backgroundColor: '#00000000',
    // 가려졌다고 여겨져도 그리기를 멈추지 않는다(plan/70) — 나올 때 그림이 준비돼 있어야 한다.
    webPreferences: { preload, contextIsolation: true, nodeIntegration: false, sandbox: false, backgroundThrottling: false },
  });
  const c = chip;
  c.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  // 마우스가 오기 전에는 숨어 있다 — 클릭도 뒤로.
  revealed = false;
  chipHovered = false;
  c.on('closed', () => {
    if (chip === c) chip = null;
  });
  // 그려진 뒤에 띄운다 — 먼저 띄우면 빈 투명 사각형이 잠깐 데스크톱 클릭을 먹는다.
  c.once('ready-to-show', () => applyChipVisibility());
  load(c, 'chip.html');
}

export function setChipSize(w: number, h: number): void {
  const nw = Math.max(48, Math.min(640, Math.round(Number(w) || 0)));
  const nh = Math.max(28, Math.min(120, Math.round(Number(h) || 0)));
  if (nw === chipSize.w && nh === chipSize.h) return;
  chipSize = { w: nw, h: nh };
  syncChip();
  publishInset();
}

// ───────────────────────── 마우스를 올렸을 때만 ─────────────────────────
//
// 잠긴 컨트롤은 늘 떠 있지 않다. 마우스가 아바타(사진·말풍선)나 컨트롤 자리에 오면 나오고, 떠나면 조금 뒤에
// 숨는다. 숨는 동안 창은 그대로 두되 클릭을 뒤로 흘려보낸다(창을 닫았다 열면 깜빡이고, 나오는 데 한 박자 늦다).
//
// **알아차리는 길은 셋, 하나만 맞아도 나온다(plan/70).**
//   1. 운영체제의 커서 자리(메인이 90ms 마다 본다) — 리눅스의 통과 창은 마우스가 지나가도 소식이 없어서.
//   2. 아바타 창이 받은 마우스 움직임(윈도·맥은 통과 창에도 움직임을 넘겨준다) — 배율이 다른 둘째 화면에서
//      커서 자리가 어긋나는 일이 있어서.
//   3. 컨트롤 창 자체에 마우스가 들어와 있음 — 나온 뒤에는 그 위에 있는 동안 숨지 않게.
//
// **나오고 숨는 것은 컨트롤 창 자체를 띄우고 내리는 것으로 한다.** 예전에는 창은 띄워 둔 채 페이지 안의 CSS 로
// 흐리게 했다. 그런데 크로미움은 가려졌다고 여기는 창의 그리기를 멈추고(다른 창이 겹치거나 본창이 떠 있지 않을 때),
// 그러면 "나왔다" 는 그림이 그려지지 않아 마우스를 올려도 아무것도 보이지 않았다. 새로 뜨는 창은 반드시 그려진다.
// (창의 불투명도는 윈도의 투명 창과 함께 쓰면 그리는 방식이 부딪힐 수 있어 쓰지 않는다.)

let revealed = false;
let hit: HitArea | null = null;
let hoverTimer: NodeJS.Timeout | null = null;
let leftAt = 0;
/** 아바타 창이 마지막으로 "마우스가 사진 위에 있다" 고 알린 때. */
let hoverPingAt = 0;
/** 마우스가 컨트롤 창 안에 있다. */
let chipHovered = false;
/** 떠나고 이만큼은 기다린다 — 사진에서 컨트롤로 내려가는 사이에 사라지지 않게. */
const HIDE_AFTER_MS = 450;
/** 아바타 창의 알림은 움직이는 동안만 온다 — 이만큼 지나면 떠난 것으로 본다. */
const PING_FRESH_MS = 400;

export const isRevealed = (): boolean => revealed;

export function setHitArea(a: HitArea | null): void {
  const ok = a && [a.x, a.y, a.width, a.height].every(Number.isFinite) && a.width > 0 && a.height > 0;
  hit = ok ? a : null;
}

/** 아바타 창: 마우스가 사진·말풍선 위에서 움직였다. */
export function hoverPing(): void {
  hoverPingAt = Date.now();
  tick();
}

/** 컨트롤 창: 마우스가 들어왔다·나갔다. */
export function setChipHovered(on: boolean): void {
  chipHovered = on;
  tick();
}

const inside = (p: { x: number; y: number }, r: Rectangle, pad = 0): boolean =>
  p.x >= r.x - pad && p.x < r.x + r.width + pad && p.y >= r.y - pad && p.y < r.y + r.height + pad;

function pointerOver(): boolean {
  const w = current();
  if (!w || !w.isVisible()) return false;
  const p = screen.getCursorScreenPoint();
  const b = w.getBounds();
  // 컨트롤 자리(사진 바닥 가운데)도 아바타의 일부로 본다.
  if (inside(p, chipBounds(b), 6)) return true;
  if (!hit) return inside(p, b);
  const area = { x: b.x + hit.x, y: b.y + hit.y, width: hit.width, height: hit.height };
  // 창 밖으로 삐져나간 사진의 부분은 보이지 않으니 창 안쪽만.
  return inside(p, area, 4) && inside(p, b);
}

function setRevealed(on: boolean): void {
  if (on === revealed) return;
  revealed = on;
  const c = chipWin();
  if (!c) return;
  c.webContents.send(CH.chipReveal, on);
  applyChipVisibility();
}

function tick(): void {
  // 듣는 중에는 늘 보인다 — 마이크를 끌 단추가 숨어 있으면 안 된다.
  const pinged = Date.now() - hoverPingAt < PING_FRESH_MS;
  const want = locked && !!current()?.isVisible() && (activity.recording || chipHovered || pinged || pointerOver());
  if (want) {
    leftAt = 0;
    setRevealed(true);
  } else if (revealed) {
    if (!leftAt) leftAt = Date.now();
    else if (Date.now() - leftAt >= HIDE_AFTER_MS) setRevealed(false);
  }
}

function watchPointer(on: boolean): void {
  if (on && !hoverTimer) hoverTimer = setInterval(tick, 90);
  if (!on && hoverTimer) {
    clearInterval(hoverTimer);
    hoverTimer = null;
  }
  if (!on) {
    leftAt = 0;
    hoverPingAt = 0;
    chipHovered = false;
    setRevealed(false);
  }
}

// ───────────────────────── 잠금 ─────────────────────────

/** 잠김 = 클릭이 뒤로 흐른다. 규칙은 이것 하나다. forward 를 모르는 리눅스는 그냥 통과. */
function applyInput(): void {
  const w = current();
  if (!w) return;
  w.setIgnoreMouseEvents(locked, locked && !IS_LINUX ? { forward: true } : undefined);
}

export function setLocked(next: boolean): void {
  locked = next;
  if (!locked) setRevealed(false);
  applyInput();
  applyChipVisibility();
  current()?.webContents.send(CH.lockedChanged, locked);
  chipWin()?.webContents.send(CH.lockedChanged, locked);
  onLockedFns.forEach((fn) => fn(locked));
  // 풀면 창이 앞으로 나와야 손잡이를 바로 잡을 수 있다(포커스는 가져가지 않는다).
  if (!locked) current()?.moveTop();
}

const onLockedFns = new Set<(locked: boolean) => void>();
export function onLocked(fn: (locked: boolean) => void): () => void {
  onLockedFns.add(fn);
  return () => onLockedFns.delete(fn);
}

// ───────────────────────── 상태 ─────────────────────────

export function status(): AvatarStatus {
  const v = voice.get();
  return { ...activity, speak: settings.get().speak, hidden: settings.avatarHidden(), stt: v.stt, tts: v.tts, capture: settings.get().capture };
}

/**
 * 화면을 찍는 동안 비킨다(plan/70). 윈도·맥은 창의 불투명도로(자리·순서가 그대로라 돌아올 때 흔들리지 않는다),
 * 리눅스는 숨겼다 다시 띄운다.
 */
export function stepAside(on: boolean): void {
  const w = current();
  if (!w) return;
  // 숨기면 컨트롤도 따라 숨고(hide 소식), 다시 띄우면 마우스가 위에 있을 때만 다시 나온다.
  if (on) w.hide();
  else w.showInactive();
}

voice.onChange(() => broadcastStatus());

/** 두 창에 지금 상태를. 설정(소리·숨김)이 바뀌었을 때도 부른다. */
export function broadcastStatus(): void {
  const s = status();
  current()?.webContents.send(CH.avatarStatus, s);
  chipWin()?.webContents.send(CH.avatarStatus, s);
}

export function reportActivity(a: AvatarActivity): void {
  activity = { recording: !!a.recording, busy: !!a.busy, speaking: !!a.speaking, proactive: !!a.proactive };
  broadcastStatus();
}

/** 컨트롤 창의 단추를 아바타 창으로. 녹음과 재생은 아바타 창에 산다. */
export function relay(c: AvatarCommand): void {
  current()?.webContents.send(CH.avatarCommand, c);
}

export function setHidden(on: boolean): void {
  settings.setAvatarHidden(on);
  broadcastStatus();
}

// ───────────────────────── 열고 닫기 ─────────────────────────

export function open(about: AvatarSubject, preload: string, rendererRoot: string, devUrl?: string): BrowserWindow {
  subject = about;
  pages = { preload, rendererRoot, devUrl };
  const existing = current();
  if (existing) {
    existing.webContents.send(CH.subject, describe());
    existing.showInactive();
    applyChipVisibility();
    return existing;
  }
  if (!watchingScreens) {
    watchingScreens = true;
    screen.on('display-removed', ensureOnScreen);
    screen.on('display-metrics-changed', () => setTimeout(ensureOnScreen, 1000));
  }
  // 켤 때는 언제나 잠긴 채로 — 떠 있는 비서가 클릭을 먹는 일로 하루를 시작하지 않게.
  locked = true;
  activity = IDLE_STATUS;
  const b = initialBounds();
  win = new BrowserWindow({
    ...b,
    minWidth: MIN.width,
    minHeight: MIN.height,
    frame: false,
    transparent: true,
    resizable: true,
    movable: true,
    skipTaskbar: true,
    alwaysOnTop: true,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    // 투명 창에 그림자를 켜 두면 플랫폼에 따라 네모난 회색 판이 같이 그려진다.
    hasShadow: false,
    backgroundColor: '#00000000',
    show: false,
    webPreferences: { preload, contextIsolation: true, nodeIntegration: false, sandbox: false, backgroundThrottling: false },
  });
  const w = win;
  lastDisplay = displayKey(screen.getDisplayMatching(b));
  // 전체 화면 위에도 떠야 한다. 발표 중에 비서가 사라지면 곁에 있는 것이 아니다.
  w.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  armAlwaysOnTop(w);
  applyInput();
  createChip(preload);
  watchPointer(true);
  w.once('ready-to-show', () => {
    w.showInactive();
    w.webContents.send(CH.subject, describe());
    applyChipVisibility();
  });
  // 윈도·맥은 사용자가 옮기고 키운 것에 이 소식을 준다(가장자리를 끄는 운영체제 손잡이 등).
  let settle: NodeJS.Timeout | null = null;
  const later = () => {
    syncChip();
    if (settle) clearTimeout(settle);
    settle = setTimeout(() => {
      if (!moveRect) persist();
    }, 450);
  };
  w.on('moved', later);
  w.on('resized', later);
  w.on('show', applyChipVisibility);
  w.on('hide', applyChipVisibility);
  w.on('closed', () => {
    if (settle) clearTimeout(settle);
    watchPointer(false);
    hit = null;
    if (win === w) win = null;
    chipWin()?.destroy();
    chip = null;
  });
  load(w, 'avatar.html');
  return w;
}

/** 비서가 바뀌었다(설정에서 다른 비서를 골랐다). 떠 있으면 얼굴만 바꾼다. */
export function setSubject(about: AvatarSubject): void {
  subject = about;
  current()?.webContents.send(CH.subject, describe());
}

export function close(): void {
  const w = current();
  if (w) {
    persist(true);
    w.close();
  }
  chipWin()?.destroy();
  win = null;
  chip = null;
}

let lastSay: { at: number; s: SayState } | null = null;

/** 지금 흐르는 답, 또는 비서가 먼저 건넨 말을 아바타에게 들려준다. */
export function say(payload: SayState): void {
  lastSay = { at: Date.now(), s: payload };
  current()?.webContents.send(CH.say, payload);
}

/** 창이 막 떴을 때 이어 보일 말: 아직 흐르는 답, 또는 방금 끝난 답. */
export function recentSay(): SayState | null {
  if (!lastSay) return null;
  return !lastSay.s.done || Date.now() - lastSay.at < 30_000 ? lastSay.s : null;
}

/** 테마가 바뀌었다. */
export function repaint(dark: boolean): void {
  current()?.webContents.send(CH.theme, dark ? 'dark' : 'light');
  chipWin()?.webContents.send(CH.theme, dark ? 'dark' : 'light');
}

/** 화면을 떼거나 배치를 바꿔 창이 화면 밖에 남았으면 가까운 화면으로. 보이는 창은 사용자가 둔 자리 그대로. */
export function ensureOnScreen(): void {
  const w = current();
  if (!w) return;
  const b = w.getBounds();
  if (visibleSomewhere(b)) return;
  w.setBounds(clampTo(b));
  syncChip();
}
