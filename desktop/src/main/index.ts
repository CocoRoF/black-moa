/**
 * 앱이 시작되는 곳.
 *
 * **쓰기 위한 앱이다** (plan/62). 틀 — 아이콘 막대, 제목 줄, 알림, 설정 — 은 앱이 그리고, 세 개의 문 —
 * 비서와 대화·소식·커뮤니티 — 의 안쪽은 black.memo-ora.com 이 "앱 모드" 로 그린다. 채팅을 앱이 다시 그리면
 * 사진·마크다운·도구 카드가 빠진 웹보다 못한 앱이 된다(plan/46 §9). 나머지 기능은 브라우저에서 연다.
 *
 * 앱만 하는 것: 곁에 떠 있는 아바타, 어디서든 부르는 빠른 대화, 비서가 먼저 건넨 말을 바로 알리는 것,
 * 트레이, 로그인할 때 시작.
 */
import { app, nativeTheme, powerMonitor } from 'electron';
import { join } from 'node:path';
import * as auth from './auth';
import * as avatarWin from './avatar-window';
import * as voiceState from './voice';
import * as chat from './chat';
import * as ctl from './controller';
import * as quick from './quick-window';
import * as settings from './settings';
import * as state from './state';
import * as strm from './stream';
import * as win from './window';
import { appSession } from './api';
import { registerIpc } from './ipc';
import { releaseAll } from './shortcuts';
import { autostartActive, launchedHidden } from './shell';

const here = __dirname;
const APP_PRELOAD = join(here, '../preload/index.js');
const HOST_PRELOAD = join(here, '../preload/host.js');
const RENDERER = join(here, '../renderer');
const DEV_URL = process.env.ELECTRON_RENDERER_URL;

// 리눅스의 웨이랜드에서는 창이 제 자리를 정할 수도, 항상 위에 있을 수도 없다. 아바타와 빠른 대화가
// 둘 다 그것으로 산다. XWayland 로 띄운다(Geny 와 같음). `BLACKMOA_OZONE=wayland` 로 끌 수 있다.
if (process.platform === 'linux' && !process.env.BLACKMOA_OZONE) {
  app.commandLine.appendSwitch('ozone-platform', 'x11');
}

// 곁에 떠 있는 창(아바타·그 컨트롤)은 다른 창에 가려졌다고 여겨지면 안 된다(plan/70). 크로미움은 가려진 창의
// 그리기를 멈추는데, 투명한 창이 겹치거나 본창이 떠 있지 않으면 그렇게 여기는 일이 있다 — 그러면 마우스를 올려도
// 컨트롤이 "나왔다" 는 그림이 그려지지 않는다. 가려짐 계산도, 뒤로 물러난 창 늦추기도 끈다.
app.commandLine.appendSwitch('disable-backgrounding-occluded-windows');
if (process.platform === 'win32') {
  app.commandLine.appendSwitch('disable-features', 'CalculateNativeWinOcclusion');
  // 화면 보여주기(plan/70): 옛 캡처 방식은 GPU 로 그리는 창(브라우저·VS Code·영상)을 검게 찍는다. Windows Graphics
  // Capture 로 합성된 화면을 그대로 찍는다(Geny 와 같음, Windows 10 2004 이후).
  app.commandLine.appendSwitch('enable-features', 'AllowWgcScreenCapturer,AllowWgcWindowCapturer');
}

let flushed = false;

function quit(): void {
  win.setQuitting();
  app.quit();
}

// 두 벌이 같은 세션 위에서 돌면 갱신 쿠키를 서로 무르게 만든다. 한 벌만 돈다.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => win.focus());

  app.whenReady().then(() => {
    settings.load(app.getPath('userData'));
    ctl.applyTheme(settings.get().theme);
    auth.listen();
    registerIpc();
    ctl.init({ preload: APP_PRELOAD, renderer: RENDERER, devUrl: DEV_URL });
    quick.init({ preload: APP_PRELOAD, renderer: RENDERER, devUrl: DEV_URL });
    ctl.watchSettings();
    state.patch({ autostart: autostartActive(app) });

    win.create({ appPreload: APP_PRELOAD, hostPreload: HOST_PRELOAD, renderer: RENDERER, devUrl: DEV_URL }, !launchedHidden());
    // 웹이 로그인 화면으로 갔다 = 세션이 없다. 12초를 기다리지 않고 바로 안다.
    win.onLandedOnAuth(() => auth.forget());
    // 웹이 토큰을 들고 오기 전까지는 판단을 미룬다.
    auth.settle();
    ctl.buildTray(quit);
    ctl.applyShortcuts();

    auth.onChange((s) => {
      state.patch({ signedIn: s.signedIn, restoring: s.restoring });
      if (s.signedIn) ctl.signedIn();
      else if (!s.restoring) {
        strm.cancelAll();
        ctl.signedOut();
      }
    });
    // 로그인 여부가 바뀌면 아이콘 막대가 생기거나 사라진다. 웹 뷰의 자리를 다시 잰다.
    let lastBar = '';
    state.onChange((s) => {
      const key = `${s.signedIn}:${s.restoring}`;
      if (key !== lastBar) {
        lastBar = key;
        win.layout();
      }
    });

    nativeTheme.on('updated', () => ctl.repaintAll());
    // 잠에서 깨면 실시간 흐름의 소켓은 대개 죽어 있다. 기다리지 않고 다시 붙는다.
    powerMonitor.on('resume', () => {
      ctl.live.kick();
      void ctl.unread.tick();
      void ctl.checkLatest();
    });
    win.current()?.on('focus', () => {
      void ctl.refreshAccount();
      void ctl.checkLatest();
    });

    // 손으로 돌리는 검사(test/shell.mjs)만 쓰는 손잡이. 서버가 먼저 말을 거는 것은 시험에서 만들 수 없어서
    // 그 이벤트를 흘려 넣는다. 켜는 변수가 없으면 아무것도 걸리지 않는다.
    if (process.env.BLACKMOA_TEST_HOOKS === '1') {
      Object.assign(globalThis, {
        __blackmoaTest: {
          live: ctl.onLiveEvent,
          state: state.get,
          quick: () => chat.avatar.current(),
          checkLatest: ctl.checkLatest,
          avatar: { locked: avatarWin.isLocked, setLocked: avatarWin.setLocked, status: avatarWin.status, say: avatarWin.say, flush: settings.flush, revealed: avatarWin.isRevealed },
          voice: { get: voiceState.get, set: voiceState.set, refresh: voiceState.refresh },
          // 검사가 서버에서 읽어 확인할 때(읽기만).
          api: (path: string) => auth.call('GET', path),
        },
      });
    }

  });

  app.on('window-all-closed', () => {
    // 창이 다 닫혀도 트레이에 남는다. 끝내기는 트레이 메뉴에서 한다.
  });

  app.on('activate', () => win.focus());
  app.on('before-quit', (e) => {
    win.setQuitting();
    strm.cancelAll();
    ctl.live.stop();
    settings.flush();
    // 갱신 쿠키는 Electron 이 늦게 디스크에 쓴다. 그 전에 끝나면 다음에 켰을 때
    // 로그인한 적이 없는 것이 된다. 한 번은 내려쓰기를 기다린다.
    if (!flushed) {
      e.preventDefault();
      void appSession()
        .cookies.flushStore()
        .catch(() => {})
        .finally(() => {
          flushed = true;
          app.quit();
        });
    }
  });
  app.on('will-quit', () => releaseAll());
}
