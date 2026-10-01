/**
 * 앱이 직접 그리는 창 넷(틀·아바타·아바타의 컨트롤·빠른 대화)이 손댈 수 있는 것의 전부.
 *
 * 세 문의 웹 뷰에는 이것이 없다(그쪽은 preload/host.ts). 서버가 주는 화면에 앱만의 능력을 꽂는 순간,
 * 웹에서 쓰는 것과 앱에서 쓰는 것이 갈라진다.
 */
import { contextBridge, ipcRenderer } from 'electron';
import { CH, type Bridge } from '@shared/contract';

/** 메인이 담아 보낸 봉투를 푼다. 실패는 진짜 오류로 다시 던진다. */
async function call<T>(channel: string, ...args: unknown[]): Promise<T> {
  const r = (await ipcRenderer.invoke(channel, ...args)) as {
    ok: boolean;
    value?: T;
    error?: { message: string; code: string };
  };
  if (r?.ok) return r.value as T;
  const err = new Error(r?.error?.message ?? '요청을 처리하지 못했어요.');
  (err as Error & { code?: string }).code = r?.error?.code ?? 'error';
  throw err;
}

/** 구독 하나. 돌려주는 함수를 부르면 끊긴다. 안 끊으면 다시 그릴 때마다 쌓인다. */
function on<T>(channel: string, fn: (payload: T) => void): () => void {
  const listener = (_e: unknown, payload: T) => fn(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

const bridge: Bridge = {
  platform: process.platform,
  dark: ipcRenderer.sendSync(CH.themeNow) === 'dark',
  onTheme: (fn) => on<string>(CH.theme, (t) => fn(t === 'dark')),
  voice: () => call(CH.getVoice),
  onVoice: (fn) => on(CH.voice, fn),
  shell: {
    state: () => call(CH.state),
    onState: (fn) => on(CH.state, fn),
    select: (pane) => call(CH.select, pane),
    back: () => call(CH.back),
    reload: () => call(CH.reload),
    openInBrowser: () => call(CH.openInBrowser),
    openWeb: (path) => call(CH.openWeb, path),
    accountMenu: (x, y) => call(CH.accountMenu, x, y),
    inbox: () => call(CH.inbox),
    openInbox: (id) => call(CH.openInbox, id),
    settings: () => call(CH.settings),
    setSettings: (patch) => call(CH.setSettings, patch),
    setAutostart: (onOff) => call(CH.setAutostart, onOff),
    openQuick: () => call(CH.openQuick),
    toggleAvatar: () => call(CH.toggleAvatar),
    signOut: () => call(CH.signOut),
    checkUpdate: () => call(CH.checkUpdate),
    openDownloads: () => call(CH.openDownloads),
    update: () => call(CH.update),
  },
  avatar: {
    subject: () => call(CH.subject),
    onSubject: (fn) => on(CH.subject, fn),
    ask: (text) => call(CH.ask, text),
    stop: () => call(CH.stop),
    onSay: (fn) => on(CH.say, fn),
    transcribe: (audio, mime) => call(CH.stt, audio, mime),
    speak: (text) => call(CH.tts, text),
    speaks: () => call(CH.speaks),
    setSpeak: (onOff) => call(CH.setSpeak, onOff),
    status: () => call(CH.getStatus),
    onStatus: (fn) => on(CH.avatarStatus, fn),
    openChat: () => call(CH.openChat),
    openQuick: () => call(CH.openQuick),
    close: () => call(CH.close),
    image: (url) => call(CH.avatarImage, url),
    lastSay: () => call(CH.lastSay),
    moveBy: (dx, dy) => ipcRenderer.send(CH.moveBy, dx, dy),
    resizeBy: (edge, dx, dy) => ipcRenderer.send(CH.resizeBy, edge, dx, dy),
    commitBounds: () => ipcRenderer.send(CH.commitBounds),
    locked: () => call(CH.getLocked),
    setLocked: (locked) => ipcRenderer.send(CH.setLocked, locked),
    onLocked: (fn) => on(CH.lockedChanged, fn),
    onChipInset: (fn) => on(CH.chipInset, fn),
    reportHitArea: (area) => ipcRenderer.send(CH.hitArea, area),
    hoverPing: () => ipcRenderer.send(CH.hoverPing),
    capture: () => ipcRenderer.send(CH.avatarCommand, 'capture'),
    view: (url) => call(CH.getView, url),
    saveView: (url, view) => call(CH.saveView, url, view),
    setHidden: (hidden) => call(CH.setHidden, hidden),
    onCommand: (fn) => on(CH.avatarCommand, fn),
    reportActivity: (a) => ipcRenderer.send(CH.avatarActivity, a),
  },
  chip: {
    status: () => call(CH.getStatus),
    onStatus: (fn) => on(CH.avatarStatus, fn),
    command: (c) => ipcRenderer.send(CH.avatarCommand, c),
    unlock: () => ipcRenderer.send(CH.setLocked, false),
    moveBy: (dx, dy) => ipcRenderer.send(CH.moveBy, dx, dy),
    commitBounds: () => ipcRenderer.send(CH.commitBounds),
    reportSize: (w, h) => ipcRenderer.send(CH.chipSize, w, h),
    onReveal: (fn) => on(CH.chipReveal, fn),
    reportHover: (inside) => ipcRenderer.send(CH.chipHover, inside),
    openChat: () => call(CH.openChat),
    openQuick: () => call(CH.openQuick),
  },
  quick: {
    agents: () => call(CH.qAgents),
    pick: (agentId) => call(CH.qPick, agentId),
    ask: (agentId, text) => call(CH.qAsk, agentId, text),
    stop: () => call(CH.qStop),
    onAnswer: (fn) => on(CH.qAnswer, fn),
    transcribe: (agentId, audio, mime) => call(CH.qStt, agentId, audio, mime),
    hide: () => call(CH.qHide),
    resize: (h) => call(CH.qResize, h),
    onShown: (fn) => on(CH.qShown, () => fn()),
    capture: () => call(CH.qCapture),
    dropShot: () => call(CH.qDropShot),
    onShot: (fn) => on(CH.qShot, fn),
  },
};

contextBridge.exposeInMainWorld('blackmoa', bridge);
