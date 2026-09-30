/**
 * 틀이 그리는 것의 원본 하나.
 *
 * 로그인·문·안 읽은 수·아바타 켜짐이 여러 모듈에서 바뀐다. 각자 틀에게 따로 알리면 순서가 엇갈려
 * 화면이 한 박자씩 틀린다. 그래서 바꾸는 쪽은 여기에 적기만 하고, 알리는 것은 여기 한 곳이 한다.
 */
import { app } from 'electron';
import { VOICE_UNKNOWN, type ShellState } from '@shared/contract';

let s: ShellState = {
  signedIn: false,
  restoring: true,
  pane: 'chat',
  me: null,
  agents: [],
  agent: null,
  avatarOn: false,
  unread: { inbox: 0, rooms: 0 },
  canBack: false,
  loading: false,
  offline: false,
  platform: process.platform,
  version: app.getVersion(),
  autostart: false,
  shortcutErrors: [],
  update: { latest: null, newer: false, installable: false, phase: 'idle', progress: 0, checking: false, checkedAt: null },
  voice: VOICE_UNKNOWN,
};

const listeners = new Set<(s: ShellState) => void>();
let queued = false;

export const get = (): ShellState => s;

/** 한 틱 안의 여러 변경은 한 번으로 알린다. */
export function patch(p: Partial<ShellState>): void {
  let changed = false;
  for (const [k, v] of Object.entries(p)) {
    if (JSON.stringify((s as unknown as Record<string, unknown>)[k]) !== JSON.stringify(v)) {
      changed = true;
      break;
    }
  }
  if (!changed) return;
  s = { ...s, ...p };
  if (queued) return;
  queued = true;
  queueMicrotask(() => {
    queued = false;
    for (const fn of listeners) fn(s);
  });
}

export function onChange(fn: (s: ShellState) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
