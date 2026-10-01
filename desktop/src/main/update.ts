/**
 * 자동 업데이트 (plan/65) — black-moa 다운로드 센터에서 받아 설치하고 다시 켠다.
 *
 * 저장소가 비공개라 GitHub 에서는 받을 수 없다(electron-updater 가 늘 조용히 실패하던 이유). 새 판은 서버가
 * GitHub 릴리스를 옮겨 둔 다운로드 센터에 있다. 여기서 하는 일:
 *
 *   1. `/api/downloads` 에서 최신 판과 이 운영체제의 설치 프로그램(서명된 주소 · sha256 · 크기)을 받는다.
 *   2. 받는다(메인에서, 진행을 틀에 알리며). 크기와 sha256 이 맞지 않으면 설치하지 않는다.
 *   3. 설치하고 다시 켠다.
 *      - 윈도: 설치 마법사를 조용히(`--updated /S --force-run`) — electron-updater 가 NSIS 에 하는 것과 같다.
 *        사용자별 설치라 관리자 권한을 묻지 않고, 설치가 끝나면 설치 프로그램이 앱을 다시 켠다.
 *      - 맥: 디스크 이미지를 붙여 앱을 지금 자리에 덮어쓰는 작은 스크립트를 앱이 닫힌 뒤에 돌리고, 다시 연다.
 *        서명하지 않은 앱이라 Squirrel(자동 업데이트의 표준 길)은 쓸 수 없다. 덮어쓸 수 없는 자리면 이미지를
 *        열어 준다(끌어다 놓으면 된다).
 *      - 리눅스: `pkexec dpkg -i` 로 설치 꾸러미를 깐다(암호를 묻는 창이 뜬다). 끝나면 새 앱을 띄우고 닫는다.
 */
import { app, net, shell } from 'electron';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { accessSync, constants, createWriteStream, existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { ORIGIN, newerThan, pickInstaller as pickAsset, type InstallerOut as AssetOut, type UpdateInfo } from '@shared/contract';
import * as auth from './auth';
import { appSession } from './api';
import { respawnDetached } from './shell';
import * as state from './state';

interface Latest {
  version: string;
  assets: AssetOut[];
}

let latest: Latest | null = null;
let lastCheck = 0;
let running = false;

/** 저절로 묻는 간격의 하한. 본창에 돌아올 때·잠에서 깰 때·한 시간마다 묻되, 이보다 자주는 아니다. */
const CHECK_EVERY_MS = 30 * 60_000;

const DRY = process.env.BLACKMOA_UPDATE_DRYRUN === '1';

function set(p: Partial<UpdateInfo>): void {
  state.patch({ update: { ...state.get().update, ...p } });
}

/**
 * 새 판이 있는가. 로그인할 때, 본창에 돌아올 때·잠에서 깰 때·한 시간마다(30분에 한 번까지), 그리고 사용자가
 * [업데이트 확인] 을 누를 때(`manual` — 확인 중·결과·실패를 화면에 보인다). 앱을 다시 켜지 않아도 새 판을 안다.
 */
export async function check(force = false, manual = false): Promise<void> {
  if (!auth.state().signedIn || running) return;
  if (!force && Date.now() - lastCheck < CHECK_EVERY_MS) return;
  lastCheck = Date.now();
  if (manual) set({ checking: true, checkError: undefined });
  try {
    const [r] = await Promise.all([
      auth.call<{ latest?: Latest | null }>('GET', '/api/downloads'),
      // 손으로 누른 확인은 너무 빨리 끝나면 눌렸는지도 모른다. 잠깐은 "확인 중" 을 보인다.
      manual ? new Promise((res) => setTimeout(res, 600)) : null,
    ]);
    latest = r?.latest ?? null;
    const v = latest?.version ?? null;
    const newer = !!v && newerThan(v, app.getVersion());
    const was = state.get().update;
    set({
      latest: v,
      newer,
      installable: newer && !!latest && !!pickAsset(latest.assets),
      checking: false,
      checkedAt: Date.now(),
      checkError: undefined,
      // 지난 업데이트가 실패해 남은 문장은 새로 물은 결과로 바꾼다.
      ...(manual && was.phase === 'error' ? { phase: 'idle' as const, error: undefined } : {}),
    });
  } catch {
    lastCheck = 0; // 다음에 다시
    set({ checking: false, ...(manual ? { checkError: '확인하지 못했어요. 인터넷 연결을 확인해 주세요.' } : {}) });
  }
}

/** 받는다. 받는 동안 크기와 sha256 을 함께 센다. */
function download(url: string, dest: string, size: number, onProgress: (p: number) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const req = net.request({ method: 'GET', url: url.startsWith('http') ? url : ORIGIN + url, session: appSession(), useSessionCookies: true });
    const hash = createHash('sha256');
    let got = 0;
    let last = 0;
    req.on('response', (res) => {
      if ((res.statusCode ?? 0) !== 200) {
        res.on('data', () => {});
        res.on('end', () => reject(new Error(`다운로드 센터가 ${res.statusCode} 로 답했어요.`)));
        return;
      }
      const out = createWriteStream(dest);
      res.on('data', (c) => {
        const b = Buffer.from(c);
        hash.update(b);
        got += b.length;
        // 디스크가 못 따라오면 잠깐 멈춘다 — 200MB 를 메모리에 쌓지 않게.
        if (!out.write(b)) {
          const r = res as unknown as NodeJS.ReadableStream; // Electron 의 응답은 Readable 이지만 타입에는 pause 가 없다
          r.pause();
          out.once('drain', () => r.resume());
        }
        const p = size ? got / size : 0;
        if (p - last >= 0.01) {
          last = p;
          onProgress(Math.min(1, p));
        }
      });
      res.on('end', () => out.end(() => (got === size || !size ? resolve(hash.digest('hex')) : reject(new Error('받다가 끊겼어요.')))));
      res.on('error', (e) => {
        out.destroy();
        reject(e);
      });
    });
    req.on('error', reject);
    req.end();
  });
}

/** [업데이트]: 받고, 확인하고, 설치하고, 다시 켠다. */
export async function run(quit: () => void): Promise<void> {
  if (running) return;
  running = true;
  try {
    await check(true);
    const asset = latest ? pickAsset(latest.assets) : null;
    if (!latest || !asset?.url || !asset.sha256) {
      set({ phase: 'error', error: '이 컴퓨터에 맞는 설치 파일을 찾지 못했어요.' });
      return;
    }
    const dir = join(app.getPath('temp'), 'blackmoa-update');
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });
    const file = join(dir, asset.name);
    set({ phase: 'downloading', progress: 0, error: undefined });
    const digest = await download(asset.url, file, asset.size, (p) => set({ progress: p }));
    if (digest !== asset.sha256) {
      rmSync(file, { force: true });
      set({ phase: 'error', error: '받은 파일이 올바르지 않아요. 잠시 뒤에 다시 시도해 주세요.' });
      return;
    }
    set({ phase: 'installing', progress: 1 });
    if (DRY) {
      // 손으로 돌리는 검사용: 받고 확인하는 데까지만(설치는 이 컴퓨터를 바꾼다).
      set({ phase: 'ready', error: undefined, file });
      return;
    }
    await install(file, quit);
  } catch (e) {
    set({ phase: 'error', error: e instanceof Error && /[가-힣]/.test(e.message) ? e.message : '업데이트를 받지 못했어요.' });
  } finally {
    running = false;
  }
}

async function install(file: string, quit: () => void): Promise<void> {
  if (process.platform === 'win32') {
    // electron-updater 의 NsisUpdater 와 같은 인자: 조용히 설치하고(/S), 끝나면 앱을 다시 켠다(--force-run).
    spawn(file, ['--updated', '/S', '--force-run'], { detached: true, stdio: 'ignore' }).unref();
    setTimeout(quit, 300);
    return;
  }
  if (process.platform === 'darwin') {
    installMac(file, quit);
    return;
  }
  await installLinux(file, quit);
}

/** 지금 도는 앱의 .app 자리(…/black-moa.app). */
function bundlePath(): string {
  return dirname(dirname(dirname(process.execPath)));
}

function installMac(dmg: string, quit: () => void): void {
  const dest = bundlePath();
  let writable = dest.endsWith('.app') && !dest.startsWith('/Volumes/');
  try {
    accessSync(dirname(dest), constants.W_OK);
  } catch {
    writable = false;
  }
  if (!writable) {
    // 덮어쓸 수 없는 자리(다른 계정이 깔았거나 이미지에서 바로 켰다) — 이미지를 열어 준다.
    void shell.openPath(dmg);
    set({ phase: 'error', error: '열린 창에서 black-moa 를 [응용 프로그램] 폴더로 끌어다 놓아 주세요.' });
    return;
  }
  const script = join(dirname(dmg), 'install.sh');
  writeFileSync(
    script,
    [
      '#!/bin/sh',
      // 앱이 완전히 닫힐 때까지 기다린다.
      `while kill -0 ${process.pid} 2>/dev/null; do sleep 0.5; done`,
      'MNT=$(mktemp -d /tmp/blackmoa-update.XXXXXX)',
      `hdiutil attach -nobrowse -readonly -noautoopen -mountpoint "$MNT" "${dmg}" >/dev/null || { open "${dest}"; exit 1; }`,
      'SRC=$(ls -d "$MNT"/*.app 2>/dev/null | head -1)',
      'if [ -n "$SRC" ]; then',
      `  rm -rf "${dest}.old"; mv "${dest}" "${dest}.old"`,
      // 덮어쓰기에 실패하면 옛 앱을 되돌린다 — 앱이 사라지는 것보다 옛 판이 남는 것이 낫다.
      `  if ditto "$SRC" "${dest}"; then rm -rf "${dest}.old"; else rm -rf "${dest}"; mv "${dest}.old" "${dest}"; fi`,
      `  xattr -dr com.apple.quarantine "${dest}" 2>/dev/null`,
      'fi',
      'hdiutil detach "$MNT" -quiet',
      `open "${dest}"`,
      '',
    ].join('\n'),
    { mode: 0o755 },
  );
  spawn('/bin/sh', [script], { detached: true, stdio: 'ignore' }).unref();
  setTimeout(quit, 300);
}

function installLinux(deb: string, quit: () => void): Promise<void> {
  return new Promise((resolve) => {
    const pkexec = ['/usr/bin/pkexec', '/bin/pkexec'].find((p) => existsSync(p));
    if (!pkexec) {
      // 암호를 묻는 창을 띄울 수 없다 — 설치 프로그램(소프트웨어 센터)으로 연다.
      void shell.openPath(deb);
      set({ phase: 'error', error: '열린 설치 프로그램에서 [설치] 를 눌러 주세요.' });
      resolve();
      return;
    }
    const p = spawn(pkexec, ['dpkg', '-i', deb], { stdio: 'ignore' });
    p.on('exit', (code) => {
      if (code === 0) {
        // 새 앱을 띄우고 닫는다. AppImage 로 쓰던 사람도 이제 설치된 앱으로 옮겨 간다.
        const target = existsSync('/opt/black-moa/blackmoa-desktop') ? '/opt/black-moa/blackmoa-desktop' : process.execPath;
        respawnDetached(target, 2);
        setTimeout(quit, 300);
      } else {
        set({
          phase: 'error',
          error: code === 126 || code === 127 ? '설치를 취소했어요.' : '설치하지 못했어요. 다운로드 센터에서 받아 설치해 주세요.',
        });
      }
      resolve();
    });
    p.on('error', () => {
      set({ phase: 'error', error: '설치하지 못했어요. 다운로드 센터에서 받아 설치해 주세요.' });
      resolve();
    });
  });
}
