/**
 * 앱이 직접 그리는 창 셋(틀·아바타·빠른 대화)이 부를 수 있는 것의 전부, 그리고 세 문의 웹 뷰가 보내는
 * 한 방향 요청(다른 문으로, 브라우저로).
 */
import { ipcMain, type IpcMainInvokeEvent } from 'electron';
import { CH, ORIGIN, type AvatarActivity, type AvatarCommand, type HitArea, type Pane, type ResizeEdge, type Settings } from '@shared/contract';
import * as avatar from './avatar-window';
import * as chat from './chat';
import * as ctl from './controller';
import * as quick from './quick-window';
import * as settings from './settings';
import * as state from './state';
import * as win from './window';
import * as voice from './voice';
import { openOutside } from './outside';
import { sendOnce } from './api';

/**
 * 오류를 봉투에 담아 넘긴다.
 *
 * Electron 은 던져진 오류를 문자열로 납작하게 만들어 넘기므로, 그대로 두면
 * 창에는 "Error invoking remote method ..." 만 남고 서버가 준 한국어 문장은
 * 사라진다.
 */
function handle<T>(channel: string, fn: (e: IpcMainInvokeEvent, ...args: never[]) => Promise<T> | T): void {
  ipcMain.handle(channel, async (e, ...args) => {
    try {
      return { ok: true, value: await fn(e, ...(args as never[])) };
    } catch (err) {
      return {
        ok: false,
        error: {
          message: err instanceof Error ? err.message : '요청을 처리하지 못했어요.',
          code: (err as { code?: string })?.code ?? 'error',
        },
      };
    }
  });
}

const PANES: readonly Pane[] = ['chat', 'feed', 'community', 'alerts', 'settings'];
/** 서비스 안의 경로만. 다른 곳이나 스킴을 여는 길이 되지 않게. */
const okPath = (p: unknown): p is string => typeof p === 'string' && /^\/[A-Za-z0-9/_\-?=&%.]*$/.test(p) && !p.startsWith('//');
const okId = (v: unknown): v is string => typeof v === 'string' && /^[0-9a-f-]{36}$/i.test(v);

const EDGES: readonly ResizeEdge[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'];
const COMMANDS: readonly AvatarCommand[] = ['mic', 'stop', 'reply'];
/** 사진 모양의 열쇠는 그 사진의 주소 — 우리 서버가 내어 주는 두 자리만. */
const okImage = (u: unknown): u is string =>
  typeof u === 'string' && /^(https:\/\/memo-ora\.com)?\/(api\/public\/uploads\/[0-9a-fA-F-]{36}|presets\/[A-Za-z0-9_-]{1,64}\.png)(\?v=\d{1,4})?$/.test(u);

function noAgent(): never {
  throw Object.assign(new Error('어느 비서인지 모르겠어요.'), { code: 'no_agent' });
}

/** 아바타의 그림을 받아 온다. 우리 서버가 내어 주는 두 자리(올린 그림, 프리셋)만. 한 번 받은 것은 들고 있는다. */
const images = new Map<string, ArrayBuffer>();
async function avatarImage(url: string): Promise<ArrayBuffer | null> {
  const path = url.startsWith(ORIGIN) ? url.slice(ORIGIN.length) : url;
  if (!/^\/(api\/public\/uploads\/[0-9a-fA-F-]{36}|presets\/[A-Za-z0-9_-]{1,64}\.png)(\?v=\d{1,4})?$/.test(path)) return null;
  const hit = images.get(path);
  if (hit) return hit;
  const r = await sendOnce(path, { accept: 'image/*' });
  if (r.status !== 200 || !/^image\//.test(r.headers['content-type'] ?? '')) return null;
  const buf = r.body.buffer.slice(r.body.byteOffset, r.body.byteOffset + r.body.byteLength) as ArrayBuffer;
  if (images.size > 8) images.clear();
  images.set(path, buf);
  return buf;
}

export function registerIpc(): void {
  // ── 틀 ──
  handle(CH.state, () => state.get());
  handle(CH.select, (_e, pane: Pane) => {
    if (PANES.includes(pane)) win.select(pane);
  });
  handle(CH.back, () => win.back());
  handle(CH.reload, () => win.reload());
  handle(CH.openInBrowser, () => win.openHereInBrowser());
  handle(CH.openWeb, (_e, path: string) => {
    if (okPath(path)) void openOutside(ORIGIN + path);
  });
  handle(CH.accountMenu, (_e, x: number, y: number) => ctl.accountMenu(Number(x) || 0, Number(y) || 0));
  handle(CH.inbox, () => ctl.recentInbox());
  handle(CH.openInbox, (_e, id: string) => (okId(id) ? ctl.openInbox(id) : undefined));
  handle(CH.settings, () => settings.get());
  handle(CH.setSettings, (_e, patch: Partial<Settings>) => ctl.updateSettings(patch && typeof patch === 'object' ? patch : {}));
  handle(CH.setAutostart, (_e, on: boolean) => ctl.setAutostart(!!on));
  handle(CH.openQuick, () => ctl.openQuick());
  handle(CH.toggleAvatar, () => ctl.toggleAvatar().then(() => undefined));
  handle(CH.signOut, () => ctl.signOut());
  handle(CH.checkUpdate, () => ctl.checkLatest(true, true));
  handle(CH.openDownloads, () => void openOutside(ctl.DOWNLOADS));
  handle(CH.update, () => ctl.runUpdate());

  // ── 아바타 ──
  handle(CH.subject, () => avatar.describe());
  handle(CH.ask, async (_e, text: string) => {
    const who = avatar.describe().agentId ?? noAgent();
    await chat.avatar.ask(who, String(text ?? ''));
  });
  handle(CH.stop, () => chat.avatar.stop());
  handle(CH.stt, (_e, audio: ArrayBuffer, mime: string) => chat.transcribe(avatar.describe().agentId ?? noAgent(), audio, String(mime)));
  handle(CH.tts, (_e, text: string) => chat.speak(avatar.describe().agentId ?? noAgent(), String(text ?? '')));
  // 서비스가 읽어 주기를 끄면 설정과 상관없이 소리를 내지 않는다(plan/67).
  handle(CH.speaks, () => settings.get().speak && voice.get().tts);
  handle(CH.openChat, () => {
    const a = chat.avatar.current();
    const who = avatar.describe().agentId;
    if (who) ctl.continueInMain(who, a?.agentId === who ? a.conversationId : null);
    else ctl.openDoor('chat');
  });
  handle(CH.avatarImage, (_e, url: string) => avatarImage(String(url ?? '')));
  handle(CH.lastSay, () => avatar.recentSay());
  handle(CH.close, () => void ctl.toggleAvatar(false));
  handle(CH.setSpeak, (_e, on: boolean) => void ctl.updateSettings({ speak: !!on }));
  handle(CH.getStatus, () => avatar.status());
  handle(CH.setHidden, (_e, on: boolean) => avatar.setHidden(!!on));
  handle(CH.getLocked, () => avatar.isLocked());
  handle(CH.getView, (_e, url: string) => (okImage(url) ? settings.avatarView(url) : null));
  handle(CH.saveView, (_e, url: string, view: unknown) => {
    if (okImage(url)) settings.setAvatarView(url, view == null ? null : settings.validView(view));
  });
  // 끌기처럼 자주 오는 것은 답을 기다리지 않는다.
  ipcMain.on(CH.moveBy, (_e, dx: unknown, dy: unknown) => avatar.moveBy(Number(dx), Number(dy)));
  ipcMain.on(CH.resizeBy, (_e, edge: unknown, dx: unknown, dy: unknown) => {
    if (typeof edge === 'string' && EDGES.includes(edge as ResizeEdge)) avatar.resizeBy(edge as ResizeEdge, Number(dx), Number(dy));
  });
  ipcMain.on(CH.commitBounds, () => avatar.commitBounds());
  ipcMain.on(CH.setLocked, (_e, on: unknown) => avatar.setLocked(!!on));
  ipcMain.on(CH.avatarActivity, (_e, a: unknown) => {
    if (a && typeof a === 'object') avatar.reportActivity(a as AvatarActivity);
  });
  ipcMain.on(CH.chipSize, (_e, w: unknown, h: unknown) => avatar.setChipSize(Number(w), Number(h)));
  ipcMain.on(CH.hitArea, (_e, a: unknown) => avatar.setHitArea(a && typeof a === 'object' ? (a as HitArea) : null));
  ipcMain.on(CH.hoverPing, () => avatar.hoverPing());
  ipcMain.on(CH.chipHover, (_e, on: unknown) => avatar.setChipHovered(!!on));
  ipcMain.on(CH.avatarCommand, (_e, c: unknown) => {
    if (c === 'toggle-speak') void ctl.updateSettings({ speak: !settings.get().speak });
    else if (c === 'capture') void ctl.captureToQuick();
    else if (COMMANDS.includes(c as AvatarCommand)) avatar.relay(c as AvatarCommand);
  });

  // ── 빠른 대화 ──
  handle(CH.qAgents, () => ({ agents: state.get().agents, agentId: ctl.quickAgent(), capture: settings.get().capture, shot: ctl.shotPreview() }));
  handle(CH.qCapture, () => ctl.captureForQuick());
  handle(CH.qDropShot, () => ctl.dropShot());
  handle(CH.qPick, (_e, id: string) => {
    if (okId(id)) ctl.pickQuickAgent(id);
  });
  // 빠른 대화의 말은 아바타가 받는다(plan/69).
  handle(CH.qAsk, (_e, agentId: string, text: string) => {
    if (!okId(agentId)) noAgent();
    return ctl.askFromQuick(agentId, String(text ?? '').slice(0, 8000));
  });
  handle(CH.qStop, () => chat.avatar.stop());
  handle(CH.qStt, (_e, agentId: string, audio: ArrayBuffer, mime: string) => (okId(agentId) ? chat.transcribe(agentId, audio, String(mime)) : noAgent()));
  handle(CH.qHide, () => quick.hide());
  handle(CH.qResize, (_e, h: number) => quick.resize(Number(h)));

  handle(CH.getVoice, () => voice.get());

  // ── 테마: 창이 뜰 때 한 번 묻는다(동기 — 첫 그림부터 맞는 색이어야 한다) ──
  ipcMain.on(CH.themeNow, (e) => {
    e.returnValue = win.isDark() ? 'dark' : 'light';
  });
  ipcMain.on('host:theme-now', (e) => {
    e.returnValue = win.isDark() ? 'dark' : 'light';
  });

  // ── 웹 뷰의 한 방향 요청 (preload/host.ts) ──
  ipcMain.on(CH.hostNavigate, (_e, path: unknown) => {
    if (okPath(path)) ctl.goTo(path);
  });
  ipcMain.on(CH.hostOpen, (_e, path: unknown) => {
    if (okPath(path)) void openOutside(ORIGIN + path);
  });

  // ── 알림: 원본이 바뀌면 그리는 쪽으로 ──
  state.onChange((s) => win.current()?.webContents.send(CH.state, s));
  chat.avatar.on((a) => {
    if (a) avatar.say({ text: a.text, done: a.done, error: a.error, status: a.status });
    quick.send(CH.qAnswer, a);
  });
}
