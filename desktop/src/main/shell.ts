/**
 * 아무도 이름으로 부르지 않지만 없으면 모두가 알아채는 것들.
 *
 * 한 벌만 도는 것, 로그인할 때 뜨는 것, 새 말이 왔다고 알려 주는 것.
 */
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { App } from 'electron';

const LINUX_ENTRY = 'blackmoa.desktop';

const linuxAutostartPath = (home: string): string => join(home, '.config', 'autostart', LINUX_ENTRY);

export interface AutostartResult {
  enabled: boolean;
  /** 못 썼는데 켜졌다고 보여 주면 그건 거짓말이다. */
  applied: boolean;
  reason?: string;
}

export function applyAutostart(
  app: Pick<App, 'setLoginItemSettings' | 'getPath'>,
  enabled: boolean,
  platform: NodeJS.Platform = process.platform,
): AutostartResult {
  try {
    if (platform !== 'linux') {
      app.setLoginItemSettings({ openAtLogin: enabled, openAsHidden: enabled, args: ['--hidden'] });
      return { enabled, applied: true };
    }
    const path = linuxAutostartPath(app.getPath('home'));
    if (!enabled) {
      if (existsSync(path)) unlinkSync(path);
      return { enabled: false, applied: true };
    }
    // AppImage 의 진짜 경로는 $APPIMAGE 다. execPath 는 마운트 안을 가리키고,
    // --appimage-extract-and-run 으로 띄우면 그마저 /tmp 라 다음 부팅에는 없다.
    // 없는 곳을 가리키는 항목을 써 놓는 것은 안 쓴 것만 못하다.
    const exec = process.env.APPIMAGE ?? process.execPath;
    if (/^\/tmp\/(\.mount_|appimage_extracted)/.test(exec)) {
      return { enabled: false, applied: false, reason: '임시 경로에서 실행 중이라 자동 시작을 등록할 수 없어요' };
    }
    mkdirSync(join(app.getPath('home'), '.config', 'autostart'), { recursive: true });
    // Desktop Entry 규칙: 진짜 % 는 두 번 적어야 한다.
    const escaped = exec.replace(/%/g, '%%');
    writeFileSync(
      path,
      ['[Desktop Entry]', 'Type=Application', 'Name=black-moa', `Exec="${escaped}" --hidden`, 'Terminal=false', 'X-GNOME-Autostart-enabled=true', ''].join('\n'),
      'utf8',
    );
    return { enabled: true, applied: true };
  } catch (err) {
    return { enabled: false, applied: false, reason: err instanceof Error ? err.message : String(err) };
  }
}

export function autostartActive(app: Pick<App, 'getLoginItemSettings' | 'getPath'>, platform: NodeJS.Platform = process.platform): boolean {
  try {
    if (platform === 'linux') return existsSync(linuxAutostartPath(app.getPath('home')));
    return app.getLoginItemSettings().openAtLogin;
  } catch {
    return false;
  }
}

/** 자동 시작으로 켜진 것이면 창 없이 트레이에만 앉는다. */
export const launchedHidden = (argv: string[] = process.argv): boolean => argv.includes('--hidden');

/**
 * 리눅스 패키지에서 업데이트 뒤 다시 켜기.
 *
 * `app.relaunch()` 는 Electron 의 relauncher 를 거치는데, 그게 NoNewPrivs 를 물려줘서
 * SUID chrome-sandbox 가 권한을 올리지 못하고 SIGTRAP 으로 죽는다(우분투 24.04).
 * 직접 띄우면 NNP 가 0 으로 남는다.
 */
export function respawnDetached(execPath: string, delaySeconds = 3): void {
  const shim = execPath.replace(/\.bin$/, '');
  spawn('/bin/sh', ['-c', `sleep ${delaySeconds}; exec "$0"`, shim], { detached: true, stdio: 'ignore' }).unref();
}

export interface UnreadCounts {
  rooms: number;
  inbox: number;
}

/**
 * 안 읽은 것 세기.
 *
 * **새로 생긴 것만** 알린다. 매번 총 개수로 알리면 앱을 켜 두는 것만으로 30초마다
 * 같은 알림이 온다. 그러면 사람은 알림을 끈다.
 */
export class UnreadWatcher {
  private last: UnreadCounts = { rooms: 0, inbox: 0 };
  private timer: NodeJS.Timeout | null = null;
  private started = false;

  constructor(
    private readonly fetchCounts: () => Promise<UnreadCounts>,
    private readonly onChange: (u: UnreadCounts) => void,
    private readonly onNew: (kind: 'rooms' | 'inbox', delta: number, total: number) => void,
    private readonly intervalMs = 30_000,
  ) {}

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => void this.tick(), this.intervalMs);
    void this.tick();
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.started = false;
    this.last = { rooms: 0, inbox: 0 };
  }

  snapshot(): UnreadCounts {
    return { ...this.last };
  }

  async tick(): Promise<void> {
    let now: UnreadCounts;
    try {
      now = await this.fetchCounts();
    } catch {
      // 서버에 못 닿은 것은 "0개" 가 아니다. 그렇게 다루면 다시 닿았을 때
      // 있던 것이 전부 새것으로 보여 알림이 쏟아진다.
      return;
    }
    const first = !this.started;
    this.started = true;
    for (const kind of ['rooms', 'inbox'] as const) {
      const delta = now[kind] - this.last[kind];
      // 처음 한 번은 세기만 한다. 앱을 켠 순간 밀린 것이 전부 알림으로 오면
      // 그건 알림이 아니라 습격이다.
      if (!first && delta > 0) this.onNew(kind, delta, now[kind]);
    }
    const changed = now.rooms !== this.last.rooms || now.inbox !== this.last.inbox;
    this.last = now;
    if (changed || first) this.onChange(this.snapshot());
  }
}
