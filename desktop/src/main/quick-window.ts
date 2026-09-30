/**
 * 빠른 대화 창.
 *
 * 어디서든 단축키 하나(기본 Ctrl/⌘+Shift+Space)로 뜨는 입력칸. 본창을 열지 않고 비서에게 한 마디 묻고, 답을
 * 그 자리에서 읽는다. 말은 그 비서의 가장 최근 대화에 쌓이므로 [대화에서 이어 보기] 로 본창에서 이어 간다.
 *
 * 모양은 Geny·Dex 의 것을 따른다: 커서가 있는 화면의 가운데, 위에서 22% 높이. 처음에는 입력칸만큼 작고,
 * 답이 길어지면 520 까지 자란다. 다른 곳을 누르면 숨는다 — 다만 뜬 직후의 잠깐(창 관리자가 초점을 옮기는
 * 사이)은 봐준다. 숨겨도 답은 메인에서 계속 흐르고, 다시 열면 그대로 있다.
 */
import { BrowserWindow, screen } from 'electron';
import { join } from 'node:path';
import { CH } from '@shared/contract';
import { openOutside } from './outside';
import { isDark, palette } from './window';

export const WIDTH = 640;
export const MIN_H = 48;
export const MAX_H = 520;
const BLUR_GRACE_MS = 450;

let win: BrowserWindow | null = null;
let shownAt = 0;
let paths: { preload: string; renderer: string; devUrl?: string };

export const current = (): BrowserWindow | null => (win && !win.isDestroyed() ? win : null);

export function init(p: typeof paths): void {
  paths = p;
}

function build(): BrowserWindow {
  const w = new BrowserWindow({
    width: WIDTH,
    height: MIN_H,
    frame: false,
    resizable: false,
    movable: true,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    show: false,
    // 투명 창은 플랫폼마다 그림자·모서리가 제각각이라 불투명한 카드로 간다(Geny 와 같음).
    backgroundColor: palette().card,
    roundedCorners: true,
    webPreferences: { preload: paths.preload, contextIsolation: true, nodeIntegration: false, sandbox: false },
  });
  w.setAlwaysOnTop(true, 'pop-up-menu');
  w.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  w.on('blur', () => {
    if (Date.now() - shownAt < BLUR_GRACE_MS) return;
    w.hide();
  });
  w.on('closed', () => {
    win = null;
  });
  // 답 속의 링크는 브라우저로. 이 창은 앱의 화면 말고는 아무것도 싣지 않는다.
  w.webContents.setWindowOpenHandler(({ url }) => {
    void openOutside(url);
    return { action: 'deny' };
  });
  w.webContents.on('will-navigate', (e, url) => {
    e.preventDefault();
    void openOutside(url);
  });
  if (paths.devUrl) void w.loadURL(`${paths.devUrl}/quick.html`);
  else void w.loadFile(join(paths.renderer, 'quick.html'));
  return w;
}

/** 커서가 있는 화면의 가운데 위쪽. 여러 화면이면 지금 보고 있는 화면에 뜬다. */
function place(w: BrowserWindow): void {
  const d = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const a = d.workArea;
  const [, h] = w.getSize();
  w.setBounds({ x: Math.round(a.x + (a.width - WIDTH) / 2), y: Math.round(a.y + a.height * 0.22), width: WIDTH, height: h });
}

export function show(): void {
  const w = current() ?? (win = build());
  place(w);
  shownAt = Date.now();
  const reveal = () => {
    w.show();
    w.focus();
    w.webContents.send(CH.qShown);
  };
  if (w.webContents.isLoading()) w.webContents.once('did-finish-load', reveal);
  else reveal();
}

export function hide(): void {
  current()?.hide();
}

let wasVisible = false;
/** 화면을 찍는 동안 비킨다(plan/70). 떠 있었으면 찍은 뒤에 다시 띄운다. */
export function stepAside(on: boolean): void {
  const w = current();
  if (!w) return;
  if (on) {
    wasVisible = w.isVisible();
    if (wasVisible) {
      shownAt = Date.now(); // 숨겼다 다시 띄우는 사이의 blur 로 닫히지 않게
      w.hide();
    }
  } else if (wasVisible) {
    wasVisible = false;
    show();
  }
}

export function toggle(): void {
  const w = current();
  if (w?.isVisible() && w.isFocused()) hide();
  else show();
}

/** 내용이 자란 만큼. 위쪽 모서리는 그대로 두고 아래로만 자란다. */
export function resize(height: number): void {
  const w = current();
  if (!w || !Number.isFinite(height)) return;
  const h = Math.round(Math.max(MIN_H, Math.min(MAX_H, height)));
  const b = w.getBounds();
  if (b.height === h) return;
  w.setBounds({ x: b.x, y: b.y, width: WIDTH, height: h });
}

export function send(channel: string, payload: unknown): void {
  current()?.webContents.send(channel, payload);
}

export function repaint(): void {
  current()?.setBackgroundColor(palette().card);
  current()?.webContents.send(CH.theme, isDark() ? 'dark' : 'light');
}
