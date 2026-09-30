/**
 * 앱의 설정과 창 자리. `userData/settings.json` 한 파일.
 *
 * 서버에 두지 않는다. 이 컴퓨터에서 아바타를 켜 두는지, 어느 단축키를 쓰는지는 이 컴퓨터의 일이다.
 * 읽다가 깨진 파일이면 기본값으로 시작한다 — 설정 파일 하나 때문에 앱이 안 뜨는 일은 없어야 한다.
 */
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { DEFAULT_SETTINGS, type PictureView, type Settings, type Shortcuts } from '@shared/contract';

export interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
  maximized?: boolean;
}

interface Stored {
  settings: Settings;
  mainBounds?: Bounds;
  /** 아바타 창의 자리와 크기(plan/66). 화면마다 따로 — 배율이 다른 화면으로 옮기면 그 화면에서 쓰던 크기로. */
  avatarByDisplay?: Record<string, Bounds>;
  /** 마지막으로 둔 자리. 다음에 켤 때 여기서 시작한다. */
  avatarBounds?: Bounds;
  /** 사진마다 놓은 모양(확대·위치). */
  avatarViews?: Record<string, PictureView>;
  avatarHidden?: boolean;
}

/** 사진 모양을 몇 장까지 기억하나. 비서를 바꿔 가며 쓰는 사람도 넉넉하다. */
const MAX_VIEWS = 24;

let file = '';
let data: Stored = { settings: structuredClone(DEFAULT_SETTINGS) };
const listeners = new Set<(s: Settings, prev: Settings) => void>();

/** 받은 값을 믿지 않는다. 모르는 키는 버리고, 모양이 틀린 값은 기본값으로. */
export function normalize(raw: unknown): Settings {
  const d = DEFAULT_SETTINGS;
  const r = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const bool = (v: unknown, dflt: boolean) => (typeof v === 'boolean' ? v : dflt);
  const n = (r.notify && typeof r.notify === 'object' ? r.notify : {}) as Record<string, unknown>;
  const k = (r.shortcuts && typeof r.shortcuts === 'object' ? r.shortcuts : {}) as Record<string, unknown>;
  const accel = (v: unknown, dflt: string) => (typeof v === 'string' && v.length <= 64 ? v : dflt);
  const shortcuts: Shortcuts = {
    quick: accel(k.quick, d.shortcuts.quick),
    avatar: accel(k.avatar, d.shortcuts.avatar),
    main: accel(k.main, d.shortcuts.main),
    capture: accel(k.capture, d.shortcuts.capture),
  };
  return {
    avatarOnStart: bool(r.avatarOnStart, d.avatarOnStart),
    agentId: typeof r.agentId === 'string' && /^[0-9a-f-]{36}$/i.test(r.agentId) ? r.agentId : null,
    speak: bool(r.speak, d.speak),
    notify: {
      proactive: bool(n.proactive, d.notify.proactive),
      inbox: bool(n.inbox, d.notify.inbox),
      messages: bool(n.messages, d.notify.messages),
    },
    shortcuts,
    theme: r.theme === 'light' || r.theme === 'dark' ? r.theme : 'system',
    capture: bool(r.capture, d.capture),
  };
}

export function load(userData: string): void {
  file = join(userData, 'settings.json');
  try {
    if (!existsSync(file)) return;
    const raw = JSON.parse(readFileSync(file, 'utf8')) as Partial<Stored> & { avatarPos?: { x: number; y: number } };
    const byDisplay: Record<string, Bounds> = {};
    for (const [k, b] of Object.entries(raw.avatarByDisplay ?? {})) if (k.length <= 80 && validBounds(b)) byDisplay[k] = pick(b);
    const views: Record<string, PictureView> = {};
    for (const [k, v] of Object.entries(raw.avatarViews ?? {}).slice(-MAX_VIEWS)) {
      const view = validView(v);
      if (k.length <= 300 && view) views[k] = view;
    }
    let avatarBounds = validBounds(raw.avatarBounds) ? pick(raw.avatarBounds) : undefined;
    // 0.8 까지는 오른쪽 아래 모서리만 적었다. 옮겨 둔 자리는 그대로 이어 간다.
    const old = raw.avatarPos;
    if (!avatarBounds && old && Number.isFinite(old.x) && Number.isFinite(old.y)) {
      avatarBounds = { x: Math.round(old.x - AVATAR_DEFAULT.width), y: Math.round(old.y - AVATAR_DEFAULT.height), ...AVATAR_DEFAULT };
    }
    data = {
      settings: normalize(raw.settings),
      mainBounds: validBounds(raw.mainBounds) ? raw.mainBounds : undefined,
      avatarByDisplay: byDisplay,
      avatarBounds,
      avatarViews: views,
      avatarHidden: raw.avatarHidden === true,
    };
  } catch {
    data = { settings: structuredClone(DEFAULT_SETTINGS) };
  }
}

function validBounds(b: unknown): b is Bounds {
  const x = b as Bounds | undefined;
  return !!x && [x.x, x.y, x.width, x.height].every(Number.isFinite) && x.width >= 200 && x.height >= 200;
}

const pick = (b: Bounds): Bounds => ({ x: Math.round(b.x), y: Math.round(b.y), width: Math.round(b.width), height: Math.round(b.height) });

/** 아바타 창의 처음 크기. 전신 그림이 서기 좋은 세로로 긴 모양. */
export const AVATAR_DEFAULT = { width: 340, height: 460 };

export function validView(v: unknown): PictureView | null {
  const r = v as PictureView | undefined;
  if (!r || ![r.scale, r.x, r.y].every((n) => typeof n === 'number' && Number.isFinite(n))) return null;
  return { scale: Math.min(5, Math.max(0.2, r.scale)), x: Math.min(1, Math.max(-1, r.x)), y: Math.min(1, Math.max(-1, r.y)) };
}

let saveTimer: NodeJS.Timeout | null = null;

/** 창을 끌 때마다 디스크에 쓰지 않는다. 잠깐 모았다가 한 번. */
function save(now = false): void {
  if (!file) return;
  const write = () => {
    saveTimer = null;
    try {
      mkdirSync(dirname(file), { recursive: true });
      // 쓰다가 꺼져도 반쪽 파일이 남지 않게 옆에 쓰고 바꿔 끼운다.
      writeFileSync(file + '.tmp', JSON.stringify(data, null, 2), 'utf8');
      renameSync(file + '.tmp', file);
    } catch {
      /* 설정을 못 써도 앱은 돈다 */
    }
  };
  if (saveTimer) clearTimeout(saveTimer);
  if (now) write();
  else saveTimer = setTimeout(write, 400);
}

export const flush = (): void => save(true);

export const get = (): Settings => data.settings;

export function update(patch: Partial<Settings>): Settings {
  const prev = data.settings;
  const next = normalize({
    ...prev,
    ...patch,
    notify: { ...prev.notify, ...(patch.notify ?? {}) },
    shortcuts: { ...prev.shortcuts, ...(patch.shortcuts ?? {}) },
  });
  data.settings = next;
  save();
  for (const fn of listeners) fn(next, prev);
  return next;
}

export function onChange(fn: (s: Settings, prev: Settings) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export const mainBounds = (): Bounds | undefined => data.mainBounds;
export function setMainBounds(b: Bounds): void {
  data.mainBounds = b;
  save();
}

export const avatarBounds = (): Bounds | undefined => data.avatarBounds;
export const avatarBoundsOn = (display: string): Bounds | undefined => data.avatarByDisplay?.[display];
export function setAvatarBounds(display: string, b: Bounds, now = false): void {
  const v = pick(b);
  data.avatarBounds = v;
  data.avatarByDisplay = { ...(data.avatarByDisplay ?? {}), [display]: v };
  save(now);
}

export const avatarView = (key: string): PictureView | null => data.avatarViews?.[key] ?? null;
export function setAvatarView(key: string, view: PictureView | null): void {
  const views = { ...(data.avatarViews ?? {}) };
  delete views[key];
  if (view) views[key] = view; // 뒤로 보내 가장 최근 것으로
  const keys = Object.keys(views);
  for (const k of keys.slice(0, Math.max(0, keys.length - MAX_VIEWS))) delete views[k];
  data.avatarViews = views;
  save();
}

export const avatarHidden = (): boolean => !!data.avatarHidden;
export function setAvatarHidden(on: boolean): void {
  data.avatarHidden = on;
  save();
}
