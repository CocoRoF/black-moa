/**
 * 앱이 하는 일들을 한 곳에서 잇는다: 계정과 비서, 아바타, 빠른 대화, 알림, 트레이, 테마, 단축키.
 *
 * 창을 그리는 것은 각 창의 모듈이, 서버와 말하는 것은 auth/stream/live 가 한다. 여기서는 "비서가 먼저 말을
 * 걸었다 → 알림을 띄우고 아바타가 말한다" 처럼 둘 이상을 잇는 일만 한다.
 */
import { app, Menu, Notification, Tray, nativeImage, nativeTheme, session } from 'electron';
import { join } from 'node:path';
import { CH, ORIGIN, doorOf, type AgentLite, type Door, type InboxLite, type Settings, type ShotPreview } from '@shared/contract';
import * as auth from './auth';
import * as avatar from './avatar-window';
import * as capture from './capture';
import * as chat from './chat';
import * as quick from './quick-window';
import * as settings from './settings';
import * as shortcuts from './shortcuts';
import * as state from './state';
import * as update from './update';
import * as voice from './voice';
import * as win from './window';
import { lite, targetOf, textOf, titleOf, type RawItem } from './alerts';
import { PARTITION, sendOnce } from './api';
import { Live } from './live';
import { openOutside } from './outside';
import { applyAutostart, autostartActive, UnreadWatcher } from './shell';

/** 새 판은 Memora 의 다운로드 센터에서 받는다(plan/64). 저장소가 비공개라 GitHub 에서는 받을 수 없다. */
export const DOWNLOADS = ORIGIN + '/app/downloads';

let paths: { preload: string; renderer: string; devUrl?: string };
let tray: Tray | null = null;
let meId: string | null = null;
/** 빠른 대화에서 고른 비서. 이번 실행 동안만 — 아바타의 비서(설정)는 바꾸지 않는다. */

export function init(p: typeof paths): void {
  paths = p;
}

// ───────────────────────── 계정과 비서 ─────────────────────────

interface MeRaw {
  id: string;
  display_name?: string;
  nickname?: string;
  email?: string;
  avatar_url?: string | null;
}
interface AgentRaw {
  id: string;
  name: string;
  avatar_url?: string | null;
  character_url?: string | null;
  status?: string;
  theme?: { accent?: string } | null;
}

let lastAccount = 0;

/** 나와 내 비서들. 로그인할 때, 그리고 본창에 돌아올 때 1분에 한 번까지. */
export async function refreshAccount(force = false): Promise<void> {
  if (!auth.state().signedIn) return;
  if (!force && Date.now() - lastAccount < 60_000) return;
  lastAccount = Date.now();
  // 관리자가 음성을 켜고 끈 것도 계정과 함께 다시 본다(plan/67).
  void voice.refresh();
  try {
    const [me, list] = await Promise.all([
      auth.call<MeRaw>('GET', '/api/auth/me'),
      auth.call<{ items?: AgentRaw[] }>('GET', '/api/agents'),
    ]);
    meId = me?.id ?? null;
    const agents: AgentLite[] = (list?.items ?? [])
      .filter((a) => a.status !== 'archived')
      .map((a) => ({ id: a.id, name: a.name, avatarUrl: a.avatar_url ?? null, characterUrl: a.character_url ?? null, accent: a.theme?.accent ?? null }));
    state.patch({
      me: me ? { name: (me.nickname || me.display_name || '').trim() || '나', email: me.email ?? '', avatarUrl: me.avatar_url ?? null } : null,
      agents,
    });
    syncAgent();
  } catch {
    lastAccount = 0; // 다음에 다시
  }
}

/** 아바타의 비서: 설정에서 고른 비서, 없으면(지웠거나 처음이면) 첫 비서. */
export function desktopAgent(): AgentLite | null {
  const { agents } = state.get();
  const want = settings.get().agentId;
  return agents.find((a) => a.id === want) ?? agents[0] ?? null;
}

function syncAgent(): void {
  const a = desktopAgent();
  state.patch({ agent: a });
  const shown = avatar.describe();
  const image = a ? a.characterUrl ?? a.avatarUrl : null;
  if (a && avatar.current() && (shown.agentId !== a.id || shown.imageUrl !== image || shown.name !== a.name)) {
    // 다른 비서를 골랐거나, 같은 비서의 그림·이름이 웹에서 바뀌었다.
    if (shown.agentId !== a.id) chat.avatar.clear();
    avatar.setSubject({ agentId: a.id, name: a.name, avatarUrl: a.avatarUrl, imageUrl: image });
  }
}

/** 빠른 대화의 비서 = 아바타의 비서(plan/69). 곁에 있는 비서는 하나다. */
export function quickAgent(): string | null {
  return desktopAgent()?.id ?? null;
}

/** 빠른 대화에서 다른 비서를 고르면 아바타의 비서도 바뀐다(설정에 적힌다). */
export function pickQuickAgent(id: string): void {
  if (state.get().agents.some((a) => a.id === id) && desktopAgent()?.id !== id) updateSettings({ agentId: id });
}

/**
 * 빠른 대화에서 물었다: 아바타가 받는다(Geny·Dex 처럼 답은 아바타의 말풍선으로).
 * 아바타가 꺼져 있으면 띄운다. 물음이 흐르기 시작하면 입력 줄은 닫는다 — 답을 가리지 않게.
 */
export async function askFromQuick(agentId: string, text: string): Promise<void> {
  pickQuickAgent(agentId);
  // 찍어 둔 화면이 있으면 먼저 올려 물음에 붙인다(plan/70). 글이 없으면 "이 화면을 봐 달라" 는 물음으로.
  const shot = pendingShot;
  let uploadIds: string[] = [];
  if (shot) uploadIds = [await chat.uploadImage(shot.jpeg)];
  const q = text.trim() || (shot ? '이 화면 좀 봐 줘.' : '');
  if (!q) return;
  if (!(await toggleAvatar(true))) throw Object.assign(new Error('아바타를 띄우지 못했어요.'), { code: 'no_avatar' });
  await chat.avatar.ask(agentId, q, uploadIds);
  const a = chat.avatar.current();
  if (a?.error) throw Object.assign(new Error(a.error), { code: 'ask_failed' });
  if (shot && pendingShot === shot) setShot(null);
  quick.hide();
}

// ───────────────────────── 화면 보여주기 (plan/70) ─────────────────────────

/** 찍어 두고 아직 보내지 않은 화면. 원본은 여기만 있고, 빠른 대화에는 작은 미리보기만 간다. */
let pendingShot: capture.Shot | null = null;

function setShot(s: capture.Shot | null): void {
  pendingShot = s;
  quick.send(CH.qShot, s ? { preview: s.preview, width: s.width, height: s.height } : null);
}

export const shotPreview = (): ShotPreview | null =>
  pendingShot ? { preview: pendingShot.preview, width: pendingShot.width, height: pendingShot.height } : null;

export function dropShot(): void {
  setShot(null);
}

function captureAllowed(): void {
  if (!settings.get().capture) throw Object.assign(new Error('설정에서 [화면 보여주기] 를 켜 주세요.'), { code: 'capture_off' });
  if (!auth.state().signedIn) throw Object.assign(new Error('로그인이 필요해요.'), { code: 'unauthorized' });
}

/** 빠른 대화의 [화면 보여주기]: 찍어서 이 물음에 붙인다. */
export async function captureForQuick(): Promise<ShotPreview> {
  captureAllowed();
  const s = await capture.take();
  setShot(s);
  return { preview: s.preview, width: s.width, height: s.height };
}

/**
 * 아바타의 [화면 보여주기]·단축키·트레이: 찍어서 빠른 대화에 붙여 연다. 무엇이 나갈지 보고, 물음을 적어 보낸다.
 * 실패하면(권한 없음 등) 까닭을 알린다.
 */
export async function captureToQuick(): Promise<void> {
  try {
    captureAllowed();
    const s = await capture.take();
    setShot(s);
    quick.show();
  } catch (e) {
    notify('화면을 보여 주지 못했어요', e instanceof Error ? e.message : '다시 해 주세요.');
  }
}

// ───────────────────────── 새 판 ─────────────────────────

/** 새 판이 있는가(plan/65 — 다운로드 센터에서). 있으면 트레이도 다시 그린다. */
export async function checkLatest(force = false, manual = false): Promise<void> {
  await update.check(force, manual);
  refreshTray();
}

/** 켜 둔 채로 며칠을 지내도 새 판을 알도록 한 시간마다 묻는다(30분 하한은 update.check 가 지킨다). */
let latestTimer: NodeJS.Timeout | null = null;

/** [업데이트]: 설정 화면에서 진행을 보이며 받고, 설치하고, 다시 켠다. */
export function runUpdate(): void {
  openPane('settings');
  void update.run(() => quitFn());
}

// ───────────────────────── 문과 주소 ─────────────────────────

export function openDoor(door: Door, path?: string): void {
  win.focus();
  if (path) win.go(door, path);
  else win.select(door);
}

/** 서비스 안의 한 주소로: 문 안이면 그 문, 아니면 브라우저. */
export function goTo(path: string): void {
  const d = doorOf(path);
  if (d && d !== 'auth') openDoor(d, path);
  else void openOutside(ORIGIN + path);
}

// ───────────────────────── 아바타 ─────────────────────────

let offLocked: (() => void) | null = null;

// 찍는 동안 메모라의 창은 비킨다(plan/70).
capture.setStepAside((on) => {
  avatar.stepAside(on);
  quick.stepAside(on);
});

// 음성을 쓰는가(plan/67)는 틀의 설정 화면도 본다.
voice.onChange((v) => state.patch({ voice: v }));

export async function toggleAvatar(force?: boolean): Promise<boolean> {
  const on = !!avatar.current();
  if (on && force !== true) {
    avatar.close();
    chat.avatar.clear();
    state.patch({ avatarOn: false });
    refreshTray();
    return false;
  }
  if (on) return true;
  if (!auth.state().signedIn) {
    notify('로그인이 필요해요', '본창에서 로그인하면 비서를 띄울 수 있어요.', () => win.focus());
    return false;
  }
  await refreshAccount(true);
  const a = desktopAgent();
  if (!a) {
    notify('아직 비서가 없어요', '비서를 먼저 만들어 주세요.', () => openDoor('chat', '/app/onboarding'));
    return false;
  }
  const w = avatar.open({ agentId: a.id, name: a.name, avatarUrl: a.avatarUrl, imageUrl: a.characterUrl ?? a.avatarUrl }, paths.preload, paths.renderer, paths.devUrl);
  offLocked?.();
  offLocked = avatar.onLocked(() => refreshTray());
  w.once('closed', () => {
    state.patch({ avatarOn: false });
    refreshTray();
  });
  state.patch({ avatarOn: true });
  refreshTray();
  return true;
}

// ───────────────────────── 빠른 대화 ─────────────────────────

export function openQuick(): void {
  if (!auth.state().signedIn) {
    win.focus();
    return;
  }
  quick.toggle();
}

/** 빠른 대화에서 한 말을 본창의 그 대화에서 이어 본다. */
export function continueInMain(agentId: string, conversationId: string | null): void {
  quick.hide();
  const q = new URLSearchParams({ a: agentId });
  if (conversationId) q.set('c', conversationId);
  openDoor('chat', `/app/chat?${q.toString()}`);
}

// ───────────────────────── 알림 ─────────────────────────

export function notify(title: string, body: string, onClick?: () => void): void {
  if (!Notification.isSupported()) return;
  const n = new Notification({ title, body: body.slice(0, 180), silent: false });
  if (onClick) n.on('click', onClick);
  n.show();
}

/** 본창이 지금 그 문을 보여 주고 있고 사람이 보고 있으면 따로 알리지 않는다 — 화면이 이미 말한다. */
function watching(door: Door): boolean {
  const w = win.current();
  return !!w && w.isVisible() && w.isFocused() && state.get().pane === door;
}

const plain = (s: string) =>
  s.replace(/```[\s\S]*?```/g, ' ').replace(/(\*\*|__|`+|~~)/g, '').replace(/^[#>\s-]+/gm, '').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\s+/g, ' ').trim();

export async function recentInbox(): Promise<InboxLite[]> {
  const r = await auth.call<{ items?: RawItem[]; new_count?: number }>('GET', '/api/inbox?limit=15');
  state.patch({ unread: { ...state.get().unread, inbox: Number(r?.new_count ?? 0) } });
  return (r?.items ?? []).map(lite);
}

export async function openInbox(id: string): Promise<void> {
  // 한 번 열어 읽은 것으로 만든다(서버가 이 요청에서 "새 것" 을 지운다).
  let item: RawItem | null = null;
  try {
    item = await auth.call<RawItem>('GET', `/api/inbox/${encodeURIComponent(id)}`);
  } catch {
    /* 못 읽어도 연다 */
  }
  const t = targetOf(id, item?.kind ?? '', item?.payload ?? {});
  if ('door' in t) openDoor(t.door, t.path);
  else void openOutside(ORIGIN + t.browser);
  void unread.tick();
}

interface MessageEvent {
  conversation_id?: string;
  agent_id?: string;
  audience?: string;
  message?: { role?: string; content?: string };
}
interface RoomEvent {
  room_id?: string;
  message?: { body?: string; sender_user_id?: string | null; sender_agent_id?: string | null };
}

export function onLiveEvent(kind: string, data: Record<string, unknown>): void {
  const s = settings.get();
  if (kind === 'message') {
    const d = data as MessageEvent;
    // 비서가 먼저 건넨 말(또는 비서끼리의 대화 결과가 그 대화에 들어온 것).
    if (d.audience !== 'owner' || d.message?.role !== 'assistant' || !d.agent_id) return;
    const text = plain(d.message.content ?? '');
    if (!text) return;
    const agent = state.get().agents.find((a) => a.id === d.agent_id);
    const open = () => openDoor('chat', `/app/chat?a=${d.agent_id}${d.conversation_id ? `&c=${d.conversation_id}` : ''}`);
    // 아바타가 떠 있고 그 비서라면, 아바타가 직접 말한다.
    if (avatar.current() && avatar.describe().agentId === d.agent_id) {
      avatar.say({ text: d.message.content ?? '', done: true, proactive: true });
    }
    if (s.notify.proactive && !watching('chat')) notify(agent?.name ?? '비서', text, open);
    return;
  }
  if (kind === 'inbox') {
    void unread.tick();
    const p = ((data.title_payload ?? {}) as Record<string, unknown>) || {};
    const id = typeof data.id === 'string' ? data.id : '';
    if (s.notify.inbox && id) notify(titleOf(String(data.kind ?? ''), p), textOf(p), () => void openInbox(id));
    return;
  }
  if (kind === 'room') {
    void unread.tick();
    const d = data as RoomEvent;
    const m = d.message;
    if (!m || !d.room_id || !s.notify.messages) return;
    if (m.sender_user_id && m.sender_user_id === meId) return; // 내가 한 말
    // 내 비서의 말은 위의 'message' 가 이미 알린다.
    if (m.sender_agent_id && state.get().agents.some((a) => a.id === m.sender_agent_id)) return;
    void (async () => {
      let title = '새 메시지';
      try {
        const rooms = await auth.call<{ items?: { id: string; title?: string; own_secretary?: boolean }[] }>('GET', '/api/rooms?limit=100');
        const row = rooms?.items?.find((r) => r.id === d.room_id);
        if (row?.own_secretary) return;
        if (row?.title) title = row.title;
      } catch {
        /* 이름 없이 알린다 */
      }
      if (watching('feed') || watching('community')) return;
      notify(title, plain(m.body ?? '') || '새 메시지가 왔어요', () => {
        openDoor('feed');
        win.send('feed', 'messenger', d.room_id);
      });
    })();
  }
}

/** 안 읽은 수. 알림은 실시간 흐름이 하고, 이것은 숫자만 맞춘다(흐름이 끊겼을 때의 바닥). */
export const unread = new UnreadWatcher(
  async () => {
    const [rooms, inbox] = await Promise.all([
      auth.call<{ unread?: number }>('GET', '/api/rooms/unread'),
      auth.call<{ new_count?: number }>('GET', '/api/inbox?limit=1'),
    ]);
    return { rooms: Number(rooms?.unread ?? 0), inbox: Number(inbox?.new_count ?? 0) };
  },
  (u) => {
    state.patch({ unread: u });
    const total = u.rooms + u.inbox;
    // 독·런처의 숫자. 지원하지 않는 곳에서는 아무 일도 없다.
    try {
      app.setBadgeCount(total);
    } catch {
      /* 배지가 없는 데스크톱 */
    }
    tray?.setToolTip(total ? `Memora · 안 읽은 알림 ${total}` : 'Memora');
  },
  () => {
    /* 새로 생긴 것은 실시간 흐름이 이미 알렸다 */
  },
  5 * 60_000,
);

export const live = new Live({
  token: () => auth.accessToken(),
  onEvent: onLiveEvent,
  onOpen: () => {
    void unread.tick();
    void refreshAccount();
  },
});

// ───────────────────────── 로그인과 로그아웃 ─────────────────────────

let avatarAtStart = false;

export function signedIn(): void {
  win.signedIn();
  void refreshAccount(true);
  void checkLatest(true);
  if (!latestTimer) latestTimer = setInterval(() => void checkLatest(), 60 * 60_000);
  unread.start();
  live.start();
  // 켤 때 한 번: 설정의 "시작할 때 아바타", 또는 `--avatar` 로 켰을 때(로그인할 때 시작과 짝이 되는 스위치).
  if (!avatarAtStart && (settings.get().avatarOnStart || process.argv.includes('--avatar'))) void toggleAvatar(true);
  avatarAtStart = true;
  refreshTray();
}

export function signedOut(): void {
  live.stop();
  if (latestTimer) clearInterval(latestTimer);
  latestTimer = null;
  unread.stop();
  avatar.close();
  quick.hide();
  chat.avatar.clear();
  meId = null;
  state.patch({ me: null, agents: [], agent: null, avatarOn: false, unread: { inbox: 0, rooms: 0 } });
  win.signedOut();
  refreshTray();
}

/** 로그아웃은 웹에게 맡긴다 — 갱신 쿠키를 쥔 쪽이 웹 하나다(plan/46 §2). 웹이 없으면 앱이 직접 끊는다. */
export async function signOut(): Promise<void> {
  const pane = state.get().pane;
  const first: Door = pane === 'feed' || pane === 'community' ? pane : 'chat';
  const target = [first, ...(['chat', 'feed', 'community'] as const).filter((d) => d !== first)].find((d) => win.hasApp(d));
  if (target) {
    win.send(target, 'logout');
    return;
  }
  // 웹이 떠 있는 문이 없다(서버에 못 닿았다). 서버에 알리고 쿠키를 지운 뒤 나간 것으로 한다.
  try {
    await sendOnce('/api/auth/logout', { method: 'POST', token: auth.accessToken() });
  } catch {
    /* 서버가 못 받아도 여기서는 나간다 */
  }
  await session.fromPartition(PARTITION).clearStorageData({ storages: ['cookies'] }).catch(() => {});
  auth.forget();
}

// ───────────────────────── 계정 메뉴 ─────────────────────────

export function accountMenu(x: number, y: number): void {
  const w = win.current();
  const me = state.get().me;
  if (!w) return;
  Menu.buildFromTemplate([
    ...(me
      ? [
          { label: me.name, enabled: false },
          ...(me.email ? [{ label: me.email, enabled: false }] : []),
          { type: 'separator' as const },
        ]
      : []),
    { label: '내 페이지', click: () => openDoor('feed', '/app/me') },
    { label: '웹에서 전체 기능 열기', click: () => void openOutside(ORIGIN + '/app') },
    { type: 'separator' },
    { label: '로그아웃', click: () => void signOut() },
  ]).popup({ window: w, x: Math.round(x), y: Math.round(y) });
}

// ───────────────────────── 설정 ─────────────────────────

export function applyTheme(t: Settings['theme']): void {
  nativeTheme.themeSource = t;
}

/** 모든 화면의 색을 지금 테마로. */
export function repaintAll(): void {
  win.repaint();
  quick.repaint();
  avatar.repaint(win.isDark());
}

export function applyShortcuts(): void {
  const failed = shortcuts.apply(settings.get().shortcuts, {
    quick: () => openQuick(),
    avatar: () => void toggleAvatar(),
    capture: () => void captureToQuick(),
    main: () => {
      const w = win.current();
      if (w?.isVisible() && w.isFocused()) w.hide();
      else win.focus();
    },
  });
  state.patch({ shortcutErrors: failed });
  refreshTray();
}

export function updateSettings(patch: Partial<Settings>): Settings {
  return settings.update(patch);
}

/** 설정이 바뀌면 그 효과를 바로 낸다. */
export function watchSettings(): void {
  settings.onChange((next, prev) => {
    if (next.theme !== prev.theme) {
      applyTheme(next.theme);
      repaintAll();
    }
    if (JSON.stringify(next.shortcuts) !== JSON.stringify(prev.shortcuts)) applyShortcuts();
    if (next.agentId !== prev.agentId) syncAgent();
    if (next.speak !== prev.speak || next.capture !== prev.capture) avatar.broadcastStatus();
    if (!next.capture && prev.capture) dropShot();
  });
}

export function setAutostart(on: boolean): boolean {
  const r = applyAutostart(app, on);
  const now = r.applied ? r.enabled : autostartActive(app);
  state.patch({ autostart: now });
  refreshTray();
  return now;
}

// ───────────────────────── 트레이 ─────────────────────────

function trayImage() {
  const img = nativeImage.createFromPath(join(process.resourcesPath, 'tray.png'));
  if (!img.isEmpty()) return img;
  // 개발 중에는 resources 가 없다. 아이콘이 없다고 트레이를 포기하지 않는다.
  const dev = nativeImage.createFromPath(join(__dirname, '../../build/tray.png'));
  return dev.isEmpty() ? nativeImage.createEmpty() : dev;
}

export function buildTray(quit: () => void): void {
  if (tray) return;
  tray = new Tray(trayImage());
  tray.setToolTip('Memora');
  quitFn = quit;
  refreshTray();
  tray.on('click', () => win.focus());
}

let quitFn: () => void = () => app.quit();

const pretty = (accel: string) =>
  accel.replace('CommandOrControl', process.platform === 'darwin' ? '⌘' : 'Ctrl').replace(/\+/g, '+');

export function refreshTray(): void {
  if (!tray) return;
  const s = state.get();
  const keys = settings.get().shortcuts;
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: 'Memora 열기', click: () => win.focus() },
      { type: 'separator' },
      { label: `빠른 대화${keys.quick ? `   ${pretty(keys.quick)}` : ''}`, enabled: s.signedIn, click: () => openQuick() },
      { label: s.avatarOn ? '아바타 닫기' : '아바타 띄우기', enabled: s.signedIn, click: () => void toggleAvatar() },
      // 무슨 일이 있어도 아바타를 다시 만질 수 있는 길(컨트롤이 화면 밖에 걸렸을 때 등).
      ...(s.avatarOn
        ? [
            avatar.isLocked()
              ? { label: '아바타 잠금 풀기', click: () => avatar.setLocked(false) }
              : { label: '아바타 잠그기', click: () => avatar.setLocked(true) },
          ]
        : []),
      { type: 'separator' },
      { label: '비서와 대화', click: () => openDoor('chat') },
      { label: '소식', click: () => openDoor('feed') },
      { label: '커뮤니티', click: () => openDoor('community') },
      { type: 'separator' },
      ...(s.update.newer && s.update.latest
        ? [
            s.update.installable
              ? { label: `새 버전 ${s.update.latest} 로 업데이트`, click: () => runUpdate() }
              : { label: `새 버전 ${s.update.latest} 받기`, click: () => void openOutside(DOWNLOADS) },
            { type: 'separator' as const },
          ]
        : []),
      ...(s.signedIn && settings.get().capture
        ? [{ label: `화면 보여주고 묻기${keys.capture ? `   ${pretty(keys.capture)}` : ''}`, click: () => void captureToQuick() }, { type: 'separator' as const }]
        : []),
      {
        label: s.update.checking ? '업데이트 확인 중…' : '업데이트 확인',
        enabled: s.signedIn && !s.update.checking,
        click: () => {
          openPane('settings');
          void checkLatest(true, true);
        },
      },
      { label: '설정', click: () => openPane('settings') },
      { label: '끝내기', click: () => quitFn() },
    ]),
  );
}

export function openPane(p: 'settings' | 'alerts'): void {
  win.focus();
  win.select(p);
}
