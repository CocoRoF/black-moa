/**
 * 어디서든 비서를 부르는 단축키.
 *
 * 다른 프로그램이 먼저 잡은 조합이면 등록이 실패한다. 예전에는 조용히 넘어갔는데, 그러면 설정에는 있는데
 * 눌러도 아무 일이 없는 단축키가 된다. 이제는 실패한 것을 틀에 알리고, 설정 화면이 그렇다고 말한다.
 */
import { globalShortcut } from 'electron';
import type { Shortcuts } from '@shared/contract';

export type Actions = Record<keyof Shortcuts, () => void>;

let active: Partial<Record<keyof Shortcuts, string>> = {};

/** 받아들일 수 있는 조합인가: 수식키 하나 이상 + 키 하나. 수식키 없는 단축키는 타자를 가로챈다. */
export function valid(accel: string): boolean {
  if (!accel) return true; // 비우면 끈 것
  const parts = accel.split('+');
  if (parts.length < 2 || parts.some((p) => !p)) return false;
  const mods = new Set(['CommandOrControl', 'CmdOrCtrl', 'Command', 'Cmd', 'Control', 'Ctrl', 'Alt', 'Option', 'AltGr', 'Shift', 'Super', 'Meta']);
  const key = parts[parts.length - 1];
  return parts.slice(0, -1).every((m) => mods.has(m)) && !mods.has(key) && parts.slice(0, -1).some((m) => m !== 'Shift');
}

/** 전부 풀고 다시 잡는다. 돌려주는 것은 잡지 못한 것들. */
export function apply(keys: Shortcuts, actions: Actions): (keyof Shortcuts)[] {
  for (const accel of Object.values(active)) {
    try {
      if (accel) globalShortcut.unregister(accel);
    } catch {
      /* 이미 풀렸다 */
    }
  }
  active = {};
  const failed: (keyof Shortcuts)[] = [];
  const used = new Set<string>();
  for (const name of Object.keys(keys) as (keyof Shortcuts)[]) {
    const accel = keys[name];
    if (!accel) continue;
    if (!valid(accel) || used.has(accel)) {
      failed.push(name);
      continue;
    }
    let ok = false;
    try {
      ok = globalShortcut.register(accel, actions[name]);
    } catch {
      ok = false;
    }
    if (ok) {
      active[name] = accel;
      used.add(accel);
    } else failed.push(name);
  }
  return failed;
}

export function releaseAll(): void {
  globalShortcut.unregisterAll();
  active = {};
}
