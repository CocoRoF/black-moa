/**
 * [업데이트 확인] (plan/68): 앱을 다시 켜지 않고 새 판을 안다.
 *
 * 지금 판이 최신이면 "최신이에요 (방금 확인했어요)". 그다음 앱의 판을 낮춰(새 판이 나온 것과 같다) 다시 누르면
 * 다시 켜지 않아도 [업데이트] 가 나타난다.
 */
import { _electron as electron } from '/home/workspace/.tools/pw/node_modules/playwright-core/index.mjs';
import { mkdirSync } from 'node:fs';
const SHOT = process.env.SHOT_DIR ?? '/tmp/blackmoa-shots';
mkdirSync(SHOT, { recursive: true });
const BIN = new URL('../node_modules/electron/dist/electron', import.meta.url).pathname;
let bad = 0;
const say = (ok, what, extra = '') => { if (!ok) bad++; console.log(`${ok ? '  ok' : '!! 실패'}  ${what}${extra ? '  ' + extra : ''}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const app = await electron.launch({ executablePath: BIN,
  args: ['.', '--no-sandbox', '--disable-gpu', `--user-data-dir=${process.env.PROFILE_DIR ?? '/tmp/blackmoa-conn'}`],
  env: { ...process.env, ELECTRON_RUN_AS_NODE: undefined, BLACKMOA_TEST_HOOKS: '1' } });
await app.firstWindow();
let shell = null;
for (let i = 0; i < 20 && !shell; i++) { await sleep(1000); shell = app.windows().find((w) => w.url().includes('shell.html')); }
for (let i = 0; i < 20 && !(await app.evaluate(() => globalThis.__blackmoaTest.state().signedIn)); i++) await sleep(1000);
await shell.evaluate(() => window.blackmoa.shell.select('settings'));
await sleep(1500);
const row = () => shell.evaluate(() => [...document.querySelectorAll('p')].find((p) => p.textContent === 'black-moa')?.parentElement?.parentElement?.innerText ?? '');
const btn = shell.getByRole('button', { name: '업데이트 확인' });
say((await btn.count()) === 1, '[정보] 에 [업데이트 확인] 이 있다');

await btn.click();
await sleep(150);
say((await row()).includes('확인하고 있어요'), '누르면 확인 중이라고 보인다', (await row()).replace(/\n/g, ' / '));
await sleep(1500);
const now = await row();
say(now.includes('최신이에요') && now.includes('방금 확인했어요'), '최신이면 방금 확인했다고 보인다', now.replace(/\n/g, ' / '));
await shell.screenshot({ path: `${SHOT}/update-latest.png` });

// 새 판이 나온 것과 같게: 앱의 판을 낮춘다. 다시 켜지 않는다.
await app.evaluate(({ app }) => app.setVersion('0.8.0'));
await shell.getByRole('button', { name: '업데이트 확인' }).click();
await sleep(1800);
const after = await row();
say(after.includes('새 버전') && (await shell.getByRole('button', { name: '업데이트', exact: true }).count()) === 1, '다시 켜지 않아도 새 판을 알고 [업데이트] 가 나온다', after.replace(/\n/g, ' / '));
await shell.screenshot({ path: `${SHOT}/update-newer.png` });
const tray = await app.evaluate(() => globalThis.__blackmoaTest.state().update);
say(tray.newer && tray.checkedAt > 0 && !tray.checking, '상태에 남는다', JSON.stringify({ latest: tray.latest, newer: tray.newer }));
await app.close();
console.log(bad ? `\n!! ${bad}건 실패` : '\n모두 정상');
process.exit(bad ? 1 : 0);
