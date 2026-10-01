/**
 * 본창.
 *
 * 테두리 없는 창 하나에 앱이 틀을 그린다: 위의 제목 줄(36px), 왼쪽의 아이콘 막대(48px). 나머지 자리에는
 * 세 문 — 비서와 대화·소식·커뮤니티 — 이 **문마다 웹 뷰 하나씩** 들어간다. 뷰는 처음 열 때 만들고 살려 두어,
 * 문을 오가도 스크롤과 쓰던 글이 그대로다. 알림과 설정은 앱이 직접 그리므로 그때는 뷰를 모두 가린다.
 *
 * 뷰는 제 문 밖으로 나가지 않는다(plan/62 §4). 웹이 먼저 지키고(`lib/desktop.ts`), 여기서 한 번 더 지킨다:
 * 새 창과 전체 이동은 규칙대로 다른 문이나 브라우저로 보낸다.
 */
import { BrowserWindow, WebContentsView, nativeTheme, screen, type Rectangle } from 'electron';
import { join } from 'node:path';
import { CH, DOORS, ORIGIN, SHELL_GEN, doorHome, doorOf, routeFor, type Door, type Pane, type Route } from '@shared/contract';
import { PARTITION } from './api';
import { openOutside } from './outside';
import * as settings from './settings';
import * as state from './state';

export const BAR = 48;
export const TITLE = 36;

const LIGHT = { bg: '#f7f7f9', card: '#ffffff', fg: '#111318' };
const DARK = { bg: '#0d0f14', card: '#12151c', fg: '#eceef3' };
/** 어두운 화면인가: 설정이 정하고, "시스템" 이면 운영체제를 따른다. */
export function isDark(): boolean {
  const t = settings.get().theme;
  return t === 'dark' || (t === 'system' && nativeTheme.shouldUseDarkColors);
}
export const palette = () => (isDark() ? DARK : LIGHT);

let win: BrowserWindow | null = null;
const views = new Map<Door, WebContentsView>();
let paths: { appPreload: string; hostPreload: string; renderer: string; devUrl?: string };
let quitting = false;

export const current = (): BrowserWindow | null => (win && !win.isDestroyed() ? win : null);
export const setQuitting = (): void => {
  quitting = true;
};

const isDoor = (p: Pane): p is Door => p === 'chat' || p === 'feed' || p === 'community';

/** 저장해 둔 자리가 지금 연결된 화면 안에 있을 때만 쓴다. 떼어 낸 모니터 위로 창이 사라지지 않게. */
function restoredBounds(): Partial<Rectangle> {
  const b = settings.mainBounds();
  if (!b) return { width: 1180, height: 820 };
  const onScreen = screen.getAllDisplays().some((d) => {
    const a = d.workArea;
    return b.x + 80 < a.x + a.width && b.x + b.width - 80 > a.x && b.y >= a.y - 8 && b.y + 40 < a.y + a.height;
  });
  return onScreen ? { x: b.x, y: b.y, width: b.width, height: b.height } : { width: b.width, height: b.height };
}

function overlay() {
  const p = palette();
  // 틀의 제목 줄은 35px + 아래 선 1px. 창 단추가 그 선을 덮지 않게 한 줄 짧게.
  return { color: p.card, symbolColor: p.fg, height: TITLE - 1 };
}

export function create(p: typeof paths, show: boolean): BrowserWindow {
  paths = p;
  const mac = process.platform === 'darwin';
  const w = new BrowserWindow({
    ...restoredBounds(),
    minWidth: 480,
    minHeight: 520,
    show: false,
    title: 'black-moa',
    backgroundColor: palette().bg,
    // 제목 줄은 앱이 그린다. 창 단추는 운영체제의 것을 그 위에 겹친다(맥은 신호등, 윈도·리눅스는 오른쪽 셋).
    ...(mac
      ? { titleBarStyle: 'hiddenInset' as const, trafficLightPosition: { x: 13, y: 11 } }
      : { titleBarStyle: 'hidden' as const, titleBarOverlay: overlay() }),
    webPreferences: { preload: p.appPreload, contextIsolation: true, nodeIntegration: false, sandbox: false },
  });
  win = w;
  if (settings.mainBounds()?.maximized) w.maximize();

  w.once('ready-to-show', () => {
    if (show) w.show();
  });
  // 창을 닫는 것은 앱을 끄는 것이 아니다. 트레이에 남아 있어야 곁에 있는 것이다.
  w.on('close', (e) => {
    rememberBounds();
    settings.flush();
    if (quitting) return;
    e.preventDefault();
    w.hide();
  });
  w.on('closed', () => {
    win = null;
    views.clear();
  });
  w.on('move', () => rememberBounds());
  w.on('resize', () => {
    rememberBounds();
    layout();
  });
  w.on('maximize', () => layout());
  w.on('unmaximize', () => layout());
  // 윈도의 마우스 뒤로 단추.
  w.on('app-command', (_e, cmd) => {
    if (cmd === 'browser-backward') void back();
    if (cmd === 'browser-forward') forward();
  });
  w.on('focus', () => {
    const pane = state.get().pane;
    if (isDoor(pane)) views.get(pane)?.webContents.focus();
  });

  // 틀은 앱의 화면 하나만 싣는다. 무엇이 이 창을 다른 곳으로 옮기려 하면 브라우저로 보낸다.
  w.webContents.setWindowOpenHandler(({ url }) => {
    void openOutside(url);
    return { action: 'deny' };
  });
  w.webContents.on('will-navigate', (e, url) => {
    if (p.devUrl && url.startsWith(p.devUrl)) return;
    e.preventDefault();
    void openOutside(url);
  });
  if (p.devUrl) void w.loadURL(`${p.devUrl}/shell.html`);
  else void w.loadFile(join(p.renderer, 'shell.html'));

  // 첫 문은 대화다. 이 뷰가 웹의 세션을 되살리고 토큰을 앱에 건넨다.
  select('chat');
  return w;
}

let boundsTimer: NodeJS.Timeout | null = null;
function rememberBounds(): void {
  const w = current();
  if (!w) return;
  if (boundsTimer) clearTimeout(boundsTimer);
  boundsTimer = setTimeout(() => {
    if (!current() || w.isMinimized() || w.isFullScreen()) return;
    const maximized = w.isMaximized();
    // 최대화한 채로는 원래 크기를 기억한다. 풀었을 때 돌아갈 자리가 있어야 한다.
    const b = maximized ? (w.getNormalBounds?.() ?? w.getBounds()) : w.getBounds();
    settings.setMainBounds({ ...b, maximized });
  }, 300);
}

/** 테마가 바뀌면 운영체제가 그리는 창 단추의 색도 바꾼다. */
export function repaint(): void {
  const w = current();
  if (!w) return;
  const p = palette();
  w.setBackgroundColor(p.bg);
  if (process.platform !== 'darwin') {
    try {
      w.setTitleBarOverlay(overlay());
    } catch {
      /* 겹치기가 없는 창 관리자 */
    }
  }
  for (const v of views.values()) v.setBackgroundColor(p.bg);
  // 운영체제에 따라 Electron 의 테마가 웹의 prefers-color-scheme 에 닿지 않는다(리눅스에서 실제로 그랬다).
  // 그래서 앱이 직접 건넨다: 틀에는 클래스로, 문에는 명령으로.
  const t = isDark() ? 'dark' : 'light';
  w.webContents.send(CH.theme, t);
  for (const d of views.keys()) send(d, 'theme', t);
}

function contentRect(): Rectangle {
  const w = current();
  if (!w) return { x: 0, y: 0, width: 0, height: 0 };
  const [width, height] = w.getContentSize();
  const s = state.get();
  // 나간 뒤에는 막대가 없다. 로그인 화면이 창 전체를 쓴다.
  const bar = !s.signedIn && !s.restoring ? 0 : BAR;
  return { x: bar, y: TITLE, width: Math.max(0, width - bar), height: Math.max(0, height - TITLE) };
}

export function layout(): void {
  const r = contentRect();
  for (const v of views.values()) v.setBounds(r);
}

// ───────────────────────── 문 ─────────────────────────

function viewFor(door: Door, path?: string): WebContentsView {
  const have = views.get(door);
  if (have && !have.webContents.isDestroyed()) return have;
  const v = new WebContentsView({
    webPreferences: {
      // 웹에 얹는 다리는 이것 하나다(preload/host.ts). 문 이름은 여기서 건넨다.
      preload: paths.hostPreload,
      partition: PARTITION,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: true,
      additionalArguments: [`--blackmoa-door=${door}`, `--blackmoa-shell=${SHELL_GEN}`],
    },
  });
  v.setBackgroundColor(palette().bg);
  v.setVisible(false);
  views.set(door, v);
  current()?.contentView.addChildView(v);
  v.setBounds(contentRect());
  const wc = v.webContents;

  // 새 창(target=_blank, window.open)은 앱 안에 열지 않는다. 규칙대로 다른 문이나 브라우저로.
  wc.setWindowOpenHandler(({ url }) => {
    act(routeFor(url, door), door);
    return { action: 'deny' };
  });
  // 전체 이동(주소를 바꾸는 링크, 서버의 리디렉트가 아닌 것). 같은 문이면 그대로 둔다.
  wc.on('will-navigate', (e, url) => {
    const r = routeFor(url, door);
    if (r.kind === 'stay') return;
    e.preventDefault();
    act(r, door);
  });
  const sync = () => {
    if (state.get().pane === door) state.patch({ canBack: wc.navigationHistory.canGoBack() });
  };
  wc.on('did-navigate', (_e, url) => {
    sync();
    watchAuth(door, url);
  });
  wc.on('did-navigate-in-page', (_e, url, isMain) => {
    if (!isMain) return;
    sync();
    watchAuth(door, url);
  });
  wc.on('did-start-loading', () => {
    if (state.get().pane === door) state.patch({ loading: true });
  });
  wc.on('did-stop-loading', () => {
    if (state.get().pane === door) state.patch({ loading: false });
  });
  // 서버에 못 닿았을 때 빈 흰 창만 남으면 앱이 죽은 줄 안다. 틀이 대신 말하고, 다시 시도를 준다.
  wc.on('did-fail-load', (_e, code, _desc, url, isMain) => {
    if (!isMain || code === -3) return; // -3 은 이동을 취소한 것
    failed.set(door, url);
    if (state.get().pane === door) {
      v.setVisible(false);
      state.patch({ offline: true, loading: false });
    }
  });
  wc.on('did-finish-load', () => {
    failed.delete(door);
    if (state.get().pane === door) {
      state.patch({ offline: false });
      v.setVisible(true);
    }
  });
  wc.on('render-process-gone', () => {
    // 렌더러가 죽으면 그 문을 새로 만든다. 다음에 열 때 깨끗한 뷰가 뜬다.
    drop(door);
    if (state.get().pane === door) select(door);
  });
  void wc.loadURL(ORIGIN + (path ?? doorHome(door)));
  return v;
}

const failed = new Map<Door, string>();

function drop(door: Door): void {
  const v = views.get(door);
  views.delete(door);
  if (!v) return;
  try {
    current()?.contentView.removeChildView(v);
  } catch {
    /* 창이 먼저 닫혔다 */
  }
  if (!v.webContents.isDestroyed()) v.webContents.close();
}

/** 규칙이 정한 곳으로 보낸다. */
function act(r: Route, from: Door): void {
  if (r.kind === 'browser') void openOutside(r.url);
  else if (r.kind === 'door' && r.door !== from) go(r.door, r.path);
}

/** 문을 연다(없으면 만든다). 틀의 아이콘과 알림이 쓰는 길. */
export function select(pane: Pane): void {
  const w = current();
  if (!w) return;
  state.patch({ pane });
  if (!isDoor(pane)) {
    for (const v of views.values()) v.setVisible(false);
    state.patch({ offline: false, loading: false, canBack: false });
    return;
  }
  const v = viewFor(pane);
  for (const [d, other] of views) if (d !== pane) other.setVisible(false);
  const down = failed.has(pane);
  v.setVisible(!down);
  state.patch({ offline: down, loading: v.webContents.isLoading(), canBack: v.webContents.navigationHistory.canGoBack() });
  if (w.isFocused()) v.webContents.focus();
  // 다시 보였다고 웹에 알린다. 그사이 빠른 대화·아바타가 보탠 말을 채운다.
  send(pane, 'shown');
}

/** 그 문의 그 자리로. 이미 떠 있는 뷰면 웹이 제 안에서 옮기고(다시 싣지 않는다), 없으면 그 주소로 만든다. */
export function go(door: Door, path: string): void {
  const have = views.get(door);
  if (!have || have.webContents.isDestroyed()) {
    viewFor(door, path);
  } else {
    const at = pathOf(have.webContents.getURL());
    // 웹의 앱이 떠 있을 때만 제 안에서 옮길 수 있다. 로그인 화면이나 실패한 뷰는 새로 싣는다.
    if (at && doorOf(at) === door && !failed.has(door)) send(door, 'go', path);
    else void have.webContents.loadURL(ORIGIN + path);
  }
  select(door);
}

function pathOf(url: string): string | null {
  try {
    const u = new URL(url);
    return u.origin === ORIGIN ? u.pathname + u.search : null;
  } catch {
    return null;
  }
}

/** 웹에게 시킨다(preload/host.ts 의 onCommand). */
export function send(door: Door, cmd: string, arg?: string): void {
  const v = views.get(door);
  if (v && !v.webContents.isDestroyed()) v.webContents.send(CH.hostCommand, cmd, arg);
}

/** 그 문의 뷰에 웹의 앱이 떠 있나(로그인 화면도, 실패한 뷰도 아니다). */
export function hasApp(door: Door): boolean {
  const v = views.get(door);
  if (!v || v.webContents.isDestroyed() || failed.has(door)) return false;
  const at = pathOf(v.webContents.getURL());
  return !!at && doorOf(at) === door;
}

/** 지금 보이는 문의 뷰. */
export function activeView(): WebContentsView | null {
  const p = state.get().pane;
  return isDoor(p) ? (views.get(p) ?? null) : null;
}

export async function back(): Promise<void> {
  const v = activeView();
  if (v?.webContents.navigationHistory.canGoBack()) v.webContents.navigationHistory.goBack();
}

function forward(): void {
  const v = activeView();
  if (v?.webContents.navigationHistory.canGoForward()) v.webContents.navigationHistory.goForward();
}

export function reload(): void {
  const p = state.get().pane;
  if (!isDoor(p)) return;
  const v = views.get(p);
  if (!v) return;
  const url = failed.get(p);
  failed.delete(p);
  state.patch({ offline: false });
  if (url) void v.webContents.loadURL(url);
  else v.webContents.reload();
}

/** 지금 문의 그 자리를 브라우저로. */
export function openHereInBrowser(): void {
  const v = activeView();
  const url = v?.webContents.getURL();
  void openOutside(url && url.startsWith(ORIGIN) ? url : ORIGIN + '/app');
}

// ───────────────────────── 로그인 ─────────────────────────

let onAuthPage: (door: Door, url: string) => void = () => {};
export const onLandedOnAuth = (fn: typeof onAuthPage): void => {
  onAuthPage = fn;
};

function watchAuth(door: Door, url: string): void {
  const p = pathOf(url);
  if (p && doorOf(p) === 'auth') onAuthPage(door, url);
}

/** 나갔다. 다른 문의 뷰는 그 사람의 화면을 들고 있으므로 버리고, 대화의 뷰는 로그인으로. */
export function signedOut(): void {
  for (const d of [...views.keys()]) if (d !== 'chat') drop(d);
  const chat = views.get('chat');
  const at = chat ? pathOf(chat.webContents.getURL()) : null;
  if (chat && !(at && doorOf(at) === 'auth')) void chat.webContents.loadURL(ORIGIN + '/login');
  select('chat');
  layout();
}

export function signedIn(): void {
  layout();
}

export function focus(): void {
  const w = current();
  if (!w) return;
  if (w.isMinimized()) w.restore();
  if (!w.isVisible()) w.show();
  w.focus();
}

export const doorIds = (): Door[] => DOORS.map((d) => d.id);
