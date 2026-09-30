/**
 * 구워 낸 설치본이 진짜로 뜨는지 본다.
 *
 * `npm run dev` 가 되는 것과 설치본이 되는 것은 다른 문제다. asar 로 묶이면서
 * 빠진 파일, 개발에서만 있던 경로는 여기서만 드러난다.
 */
import { _electron as electron } from '/home/workspace/.tools/pw/node_modules/playwright-core/index.mjs';

const APP = process.argv[2];
let bad = 0;
const say = (ok, what, extra = '') => {
  if (!ok) bad++;
  console.log(`${ok ? '  ok' : '!! 실패'}  ${what}${extra ? '  ' + extra : ''}`);
};

const app = await electron.launch({
  executablePath: APP,
  args: ['--no-sandbox', '--disable-gpu', '--user-data-dir=/tmp/memora-packaged'],
  env: { ...process.env, ELECTRON_RUN_AS_NODE: undefined },
});
const win = await app.firstWindow();
const errors = [];
win.on('pageerror', (e) => errors.push(String(e).slice(0, 120)));
await win.waitForLoadState('domcontentloaded');
await win.waitForTimeout(9000);

say(true, '설치본이 창을 띄운다');
// 틀은 설치본 안의 화면이다. asar 로 묶이면서 빠진 파일(글꼴·그림)이 있으면 여기서 드러난다.
const shell = app.windows().find((w) => w.url().includes('shell.html'));
say(!!shell, '틀이 뜬다', shell?.url());
const fontOk = shell ? await shell.evaluate(() => document.fonts.check('13px "Pretendard Variable"')) : false;
say(fontOk, '글꼴이 함께 실린다');
// 세 문의 뷰가 memo-ora.com 이고, preload 가 asar 안에서 제대로 잡혀야 다리가 선다.
const door = app.windows().find((w) => w.url().startsWith('https://memo-ora.com'));
say(!!door, '문이 memo-ora.com 을 띄운다', door?.url());
const bridge = door
  ? await door.evaluate(() => {
      const h = window.__memoraHost;
      return h ? Object.keys(h).sort().join(',') : '';
    })
  : '';
say(bridge === 'desktop,door,navigate,onCommand,openInBrowser,shell,signedOut,theme,token', 'asar 안에서도 다리가 붙는다', bridge || '(없음)');
say(errors.length === 0, `오류 ${errors.length}건`, errors.join('; '));

await app.close();
console.log(bad ? `\n!! ${bad}건 실패` : '\n모두 정상');
process.exit(bad ? 1 : 0);
