/**
 * 화면 보여주기 (plan/70). 설정에서 켜면 아바타의 컨트롤에 [화면 보여주기] 가 생기고, 누르면 지금 화면을 한 장 찍어
 * 빠른 대화에 붙여 연다. 보내면 그 화면이 물음과 함께 비서에게 가고 아바타가 답한다.
 *
 * TALK=1 이면 진짜로 보낸다(운영, 크레딧을 조금 쓴다) — 웹의 그 대화에 화면이 붙은 말로 남는지까지 본다.
 */
import { _electron as electron } from '/home/workspace/.tools/pw/node_modules/playwright-core/index.mjs';
import { mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
const SHOT = process.env.SHOT_DIR ?? '/tmp/memora-shots';
mkdirSync(SHOT, { recursive: true });
const BIN = new URL('../node_modules/electron/dist/electron', import.meta.url).pathname;
let bad = 0;
const say = (ok, what, extra = '') => { if (!ok) bad++; console.log(`${ok ? '  ok' : '!! 실패'}  ${what}${extra ? '  ' + extra : ''}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const app = await electron.launch({ executablePath: BIN,
  args: ['.', '--avatar', '--no-sandbox', '--disable-gpu', `--user-data-dir=${process.env.PROFILE_DIR ?? '/tmp/memora-conn'}`],
  env: { ...process.env, ELECTRON_RUN_AS_NODE: undefined, MEMORA_TEST_HOOKS: '1' } });
await app.firstWindow();
let shell = null, chip = null, av = null;
for (let i = 0; i < 30 && !(shell && chip && av); i++) {
  await sleep(1000);
  shell = app.windows().find((w) => w.url().includes('shell.html')) ?? null;
  chip = app.windows().find((w) => w.url().includes('chip.html')) ?? null;
  av = app.windows().find((w) => w.url().includes('avatar.html')) ?? null;
}
say(!!(shell && chip && av), '틀·아바타·컨트롤이 뜬다');
await sleep(2000);

// 처음에는 꺼져 있다 — 화면은 사람이 켜야 나간다
await shell.evaluate(() => window.memora.shell.setSettings({ capture: false }));
await sleep(500);
say((await chip.locator('[title="화면 보여주기"]').count()) === 0, '꺼져 있으면 [화면 보여주기] 가 없다');
await shell.evaluate(() => window.memora.shell.select('settings'));
await sleep(1000);
say((await shell.getByText('화면 보여주기').count()) >= 1, '설정에 [화면 보여주기] 가 있다');
await shell.getByRole('switch', { name: '화면 보여주기' }).click();
await sleep(800);
say((await chip.locator('[title="화면 보여주기"]').count()) === 1, '켜면 컨트롤에 [화면 보여주기]');
say((await shell.getByText('화면 보여주고 묻기').count()) === 1, '단축키에 [화면 보여주고 묻기] 가 생긴다');

// 컨트롤의 [화면 보여주기] → 찍어서 빠른 대화에 붙여 연다
const b = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find((w) => w.webContents.getURL().includes('avatar.html')).getBounds());
execFileSync('xdotool', ['mousemove', String(b.x + b.width / 2), String(b.y + b.height / 2)]);
await sleep(600);
await chip.locator('[title="화면 보여주기"]').click();
let quick = null;
for (let i = 0; i < 20 && !quick; i++) {
  await sleep(500);
  quick = app.windows().find((w) => w.url().includes('quick.html')) ?? null;
}
const visible = () => app.evaluate(({ BrowserWindow }) => !!BrowserWindow.getAllWindows().find((w) => w.webContents.getURL().includes('quick.html'))?.isVisible());
for (let i = 0; i < 20 && !(await visible()); i++) await sleep(250);
say(await visible(), '빠른 대화가 열린다');
let img = null;
for (let i = 0; i < 20 && !img; i++) {
  await sleep(250);
  img = await quick.evaluate(() => { const i = document.querySelector('img[alt="붙인 화면"]'); return i && i.naturalWidth ? { w: i.naturalWidth, h: i.naturalHeight, src: i.src.slice(0, 23) } : null; });
}
say(!!img && img.src.startsWith('data:image/jpeg'), '찍은 화면이 작게 붙어 있다', JSON.stringify(img));
say((await quick.locator('textarea').getAttribute('placeholder'))?.includes('이 화면'), '입력칸은 "이 화면에 대해 물어보세요"');
// 찍는 동안 비켰던 아바타·컨트롤은 제자리에 돌아온다
const back = await app.evaluate(({ BrowserWindow }) => {
  const w = BrowserWindow.getAllWindows().find((x) => x.webContents.getURL().includes('avatar.html'));
  return { visible: w.isVisible(), opacity: w.getOpacity() };
});
say(back.visible && back.opacity === 1, '찍은 뒤 아바타는 제자리에', JSON.stringify(back));
execFileSync('xwd', ['-root', '-silent', '-out', `${SHOT}/capture-quick.xwd`]);

// 떼면 사라진다, 다시 찍으면 붙는다
await quick.locator('[title="화면 떼기"]').click();
await sleep(400);
say((await quick.locator('img[alt="붙인 화면"]').count()) === 0, '[화면 떼기] 로 뗀다');
await quick.locator('[title="화면 보여주기"]').click();
for (let i = 0; i < 20 && !(await quick.locator('img[alt="붙인 화면"]').count()); i++) await sleep(250);
say((await quick.locator('img[alt="붙인 화면"]').count()) === 1, '빠른 대화의 [화면 보여주기] 로 다시 붙인다');
say(await visible(), '찍는 동안 비켰던 빠른 대화도 다시 떠 있다');

if (process.env.TALK) {
  // 글 없이 보내면 "이 화면 좀 봐 줘." 로 묻고, 아바타가 답한다
  await quick.locator('textarea').fill('');
  await quick.locator('[title="보내기"]').click();
  let a = null;
  for (let i = 0; i < 120; i++) {
    await sleep(1000);
    a = await app.evaluate(() => globalThis.__memoraTest.quick());
    if (a?.done) break;
  }
  say(!!a?.done && !a?.error && (a?.text ?? '').length > 5, '화면을 보고 답한다', (a?.error ?? a?.text ?? '').slice(0, 60));
  // 웹의 그 대화에 화면이 붙은 말로 남는다(앱은 웹과 같은 대화에 말한다)
  const q = await app.evaluate(() => globalThis.__memoraTest.quick());
  const r = await app.evaluate((_e, path) => globalThis.__memoraTest.api(path), `/api/agents/${q.agentId}/conversations/${q.conversationId}/messages?limit=10`);
  const mine = [...(r?.items ?? [])].reverse().find((m) => m.role === 'user');
  say(mine?.content === '이 화면 좀 봐 줘.' && mine?.attachments?.length === 1 && String(mine.attachments[0].mime).startsWith('image/'),
      '웹의 그 대화에 화면이 붙은 말로 남는다', JSON.stringify({ content: mine?.content, atts: mine?.attachments?.map((a) => a.mime) }));
}
say((await chip.evaluate(() => 1)) === 1, '(컨트롤 창이 살아 있다)');
await shell.evaluate(() => window.memora.shell.setSettings({ capture: false }));
await app.close();
console.log(bad ? `\n!! ${bad}건 실패` : '\n모두 정상');
process.exit(bad ? 1 : 0);
