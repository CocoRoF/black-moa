/**
 * 쓰기 위한 앱인지 본다 (plan/62).
 *
 * 틀(아이콘 막대·제목 줄)이 앱의 것인지, 세 문의 안쪽이 웹의 앱 모드인지, 문 사이·문 밖의 링크가 제 길로
 * 가는지, 빠른 대화와 아바타가 도는지, 비서가 먼저 건넨 말이 아바타에 닿는지, 로그아웃하면 틀이 접히는지.
 *
 * 화면은 xwd 로 통째로 찍는다. 틀과 웹 뷰와 아바타가 서로 다른 창·뷰라서 한 장에 담으려면 그래야 한다.
 */
import { _electron as electron } from '/home/workspace/.tools/pw/node_modules/playwright-core/index.mjs';
import { execSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';

const SHOT = process.env.SHOT_DIR ?? '/tmp/memora-shots';
const PROFILE = process.env.PROFILE_DIR ?? '/tmp/memora-shell';
const XWD2PNG = new URL('./xwd2png.py', import.meta.url).pathname;
mkdirSync(SHOT, { recursive: true });
if (process.env.FRESH) rmSync(PROFILE, { recursive: true, force: true });
const BIN = new URL('../node_modules/electron/dist/electron', import.meta.url).pathname;
let bad = 0;
const say = (ok, what, extra = '') => {
  if (!ok) bad++;
  console.log(`${ok ? '  ok' : '!! 실패'}  ${what}${extra ? '  ' + extra : ''}`);
};
const shot = (name) => execSync(`xwd -root -silent | python3 ${XWD2PNG} ${SHOT}/${name}.png`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const app = await electron.launch({
  executablePath: BIN,
  args: ['.', '--no-sandbox', '--disable-gpu', `--user-data-dir=${PROFILE}`],
  env: { ...process.env, ELECTRON_RUN_AS_NODE: undefined, ELECTRON_DISABLE_SECURITY_WARNINGS: '1', MEMORA_TEST_HOOKS: '1' },
});
if (process.env.MEMORA_DEBUG) app.process().stdout.on('data', (d) => process.stdout.write(`[main] ${String(d).split('\n').filter((l) => l && !l.includes('pump] data')).join('\n[main] ')}\n`));
// 바깥 브라우저를 여는 대신 적어 둔다.
await app.evaluate(({ shell }) => {
  globalThis.__opened = [];
  shell.openExternal = async (u) => {
    globalThis.__opened.push(u);
  };
});
// 창을 화면에 맞춘다(설정에 남은 자리가 있으면 그대로 쓴다).
await app.evaluate(({ BrowserWindow }) => {
  const w = BrowserWindow.getAllWindows().find((x) => x.webContents.getURL().includes('shell.html'));
  w?.setBounds({ x: 40, y: 40, width: 1280, height: 820 });
});

const pages = () => app.context().pages();
const find = async (pred, ms = 20000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const p = pages().find((x) => pred(x.url()));
    if (p) return p;
    await sleep(300);
  }
  return null;
};
const state = () => app.evaluate(() => globalThis.__memoraTest.state());
const waitState = async (pred, ms = 20000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const s = await state();
    if (pred(s)) return s;
    await sleep(300);
  }
  return state();
};

const shell = await find((u) => u.includes('shell.html'));
say(!!shell, '본창의 틀은 앱이 그린다');
const errors = [];
shell.on('pageerror', (e) => errors.push(String(e).slice(0, 160)));
await sleep(4000);

// ── 로그인 ──
let chat = await find((u) => u.startsWith('https://memo-ora.com'));
say(!!chat, '대화의 문은 memo-ora.com 이다', chat?.url());
const host = await chat.evaluate(() => {
  const h = window.__memoraHost;
  return h ? { keys: Object.keys(h).sort().join(','), shell: h.shell, door: h.door } : null;
});
say(host?.shell === 2 && host?.door === 'chat', '웹 뷰는 제 문과 틀 세대를 안다', JSON.stringify(host));

if (chat.url().includes('/login')) {
  const s0 = await waitState((s) => !s.restoring);
  say(!s0.signedIn, '로그인 전에는 틀이 접힌다(아이콘 막대 없음)');
  shot('d1-login');
  await chat.fill('input[type=email]', process.env.MEMORA_EMAIL);
  await chat.fill('input[type=password]', process.env.MEMORA_PASSWORD);
  await chat.click('button[type=submit]');
}
const s1 = await waitState((s) => s.signedIn && s.agents.length > 0);
say(s1.signedIn, '웹이 토큰을 건네면 틀이 열린다');
say(!!s1.me?.name && s1.agents.length > 0, '나와 내 비서를 안다', `${s1.me?.name} · ${s1.agents.map((a) => a.name).join(',')}`);
await chat.waitForURL(/\/app\/chat/, { timeout: 20000 }).catch(() => {});
await sleep(3500);
const mode = await chat.evaluate(() => ({
  attr: document.documentElement.hasAttribute('data-app-shell'),
  credits: !!document.querySelector('a[href="/app/credits"]'),
  sidebar: !!document.querySelector('aside nav'),
  tabbar: !!document.querySelector('nav[aria-label="primary"]'),
}));
say(mode.attr && !mode.credits && !mode.sidebar && !mode.tabbar, '웹은 앱 모드: 사이드바·머리줄·탭 막대가 없다', JSON.stringify(mode));
shot('d2-chat');

// ── 세 문 ──
await shell.click('button[aria-label="소식"]');
const feed = await find((u) => u.includes('/app/feed'));
say(!!feed, '소식의 문을 열면 소식의 웹 뷰가 생긴다');
await sleep(3500);
const feedTabs = await feed.evaluate(() => [...document.querySelectorAll('nav[aria-label="sections"] a')].map((a) => a.textContent));
say(feedTabs.join(',') === '소식,내 글', '소식의 문 안 탭 줄', feedTabs.join(','));
// 소식의 사진이 깨지지 않는다(앱의 세션으로 서명된 주소를 받는지).
const broken = await feed.evaluate(() => [...document.images].filter((i) => i.complete && i.src.startsWith('http') && i.naturalWidth === 0).map((i) => i.src.slice(0, 80)));
say(broken.length === 0, '소식의 사진이 깨지지 않는다', broken.join(' '));
shot('d3-feed');

await shell.click('button[aria-label="커뮤니티"]');
const comm = await find((u) => u.includes('/app/community'));
await sleep(3500);
say(!!comm, '커뮤니티의 문');
shot('d4-community');

// ── 링크 규칙 ──
// 다른 문으로: 커뮤니티 뷰에서 사람의 페이지 → 소식의 문으로 옮긴다.
const before = (await state()).pane;
await comm.evaluate(() => window.__memoraHost.navigate('/app/feed'));
const s2 = await waitState((s) => s.pane === 'feed', 5000);
say(before === 'community' && s2.pane === 'feed', '다른 문의 주소는 앱이 그 문으로 옮긴다');
// 문 밖으로: 스케줄은 브라우저가 연다. 링크를 누른 것처럼.
await feed.evaluate(() => {
  const a = document.createElement('a');
  a.href = '/app/schedule';
  a.textContent = 'x';
  document.body.appendChild(a);
  a.click();
  a.remove();
});
await sleep(800);
const opened = await app.evaluate(() => globalThis.__opened);
say(opened.some((u) => u.endsWith('/app/schedule')), '문 밖의 자리는 브라우저가 연다', opened.join(' '));
say(feed.url().includes('/app/feed'), '소식의 뷰는 제자리에 남는다', feed.url());

// ── 알림·설정 ──
await shell.click('button[aria-label="알림"]');
await sleep(2500);
shot('d5-alerts');
await shell.click('button[aria-label="설정"]');
await sleep(1500);
shot('d6-settings');

// ── 빠른 대화 ──
await shell.evaluate(() => window.memora.shell.openQuick());
const quick = await find((u) => u.includes('quick.html'), 8000);
say(!!quick, '빠른 대화 창이 뜬다');
if (quick && process.env.TALK) {
  // 빠른 대화는 입력 줄이다(plan/69): 보내면 줄이 닫히고, 답은 아바타의 말풍선으로 나온다.
  const ask = `데스크톱 앱에서 보내는 시험 ${Date.now() % 100000}. "잘 받았어요" 한 마디만 답해 줘.`;
  await quick.waitForSelector('textarea');
  await quick.fill('textarea', ask);
  await quick.keyboard.press('Enter');
  let hidden = false;
  for (let i = 0; i < 20 && !hidden; i++) {
    await sleep(500);
    hidden = await app.evaluate(({ BrowserWindow }) => !BrowserWindow.getAllWindows().find((w) => w.webContents.getURL().includes('quick.html'))?.isVisible());
  }
  say(hidden, '보내면 빠른 대화 줄이 닫힌다');
  const avq = await find((u) => u.includes('avatar.html'), 10000);
  say(!!avq, '아바타가 뜬다(꺼져 있었으면 띄운다)');
  let a = null;
  for (let i = 0; i < 120; i++) {
    await sleep(1000);
    a = await app.evaluate(() => globalThis.__memoraTest.quick());
    if (a?.done) break;
  }
  say(!!a?.done && !a?.error && !!a?.text, '답이 흘러 끝난다', a?.error ?? a?.text?.slice(0, 30));
  await sleep(1500);
  const bubble = avq ? await avq.evaluate(() => document.querySelector('.ov-subtitle')?.textContent ?? '') : '';
  say(!!a?.text && bubble.includes(a.text.slice(0, 6)), '답은 아바타의 말풍선에 나온다', bubble.slice(0, 40));
  shot('d7-quick');
  // 실시간 동기화(plan/69): 대화의 문을 누르지 않아도, 문 안의 웹이 방금 한 말과 답을 이미 들고 있다.
  let seen = false;
  let landed = false;
  for (let i = 0; i < 20 && !(seen && landed); i++) {
    seen = await chat.evaluate((q) => document.body.innerText.includes(q.slice(0, 20)), ask).catch(() => false);
    landed = !!a?.text && (await chat.evaluate((t) => document.body.innerText.includes(t.slice(0, 8)), a.text).catch(() => false));
    if (!(seen && landed)) await sleep(1000);
  }
  say(seen, '빠른 대화에서 한 말이 대화의 문에 곧바로 있다(누르지 않아도)');
  say(landed, '그 답도 곧바로 있다', a?.text?.slice(0, 30));
  await shell.evaluate(() => window.memora.shell.select('chat'));
  await sleep(1500);
  shot('d8-continue');
}

// ── 아바타와 먼저 건넨 말 ──
// 빠른 대화에서 물었으면 아바타는 이미 떠 있다(plan/69). 켜는 길을 시험하려고 먼저 내린다.
if ((await app.evaluate(() => globalThis.__memoraTest.state().avatarOn))) {
  await shell.evaluate(() => window.memora.shell.toggleAvatar());
  await waitState((s) => !s.avatarOn, 5000);
  await sleep(800);
}
await shell.evaluate(() => window.memora.shell.toggleAvatar());
const av = await find((u) => u.includes('avatar.html'), 10000);
say(!!av, '아바타가 뜬다');
const s4 = await waitState((s) => s.avatarOn, 5000);
say(s4.avatarOn, '틀이 아바타가 켜진 것을 안다');
await sleep(2000);
const agentId = s4.agent?.id;
await app.evaluate(
  (_e, id) =>
    globalThis.__memoraTest.live('message', {
      conversation_id: null,
      agent_id: id,
      audience: 'owner',
      message: { role: 'assistant', content: '오늘 하루는 어떠셨어요? 저녁은 챙겨 드셨는지 궁금해요.' },
    }),
  agentId,
);
await sleep(1500);
const bubble = av ? await av.evaluate(() => document.body.innerText) : '';
// 잠긴 아바타는 클릭을 흘려보내므로 [답하기] 는 사진 아래의 컨트롤에 붙는다(plan/66).
const chipPage = pages().find((p) => p.url().includes('chip.html'));
const reply = chipPage ? await chipPage.locator('[title="답하기"]').count() : 0;
say(bubble.includes('저녁은 챙겨') && reply === 1, '비서가 먼저 건넨 말을 아바타가 말하고, 컨트롤에 답하기가 붙는다');
shot('d9-avatar');

// ── 오래 켜 두기 ──
// 세 문의 웹이 각자 갱신하고 앱은 받기만 한다. 다투면 서버가 도난으로 보고 세션을 끊는다(refresh_reuse_detected).
if (process.env.HOLD_S) {
  await sleep(Number(process.env.HOLD_S) * 1000);
  const sh = await state();
  say(sh.signedIn && !chat.url().includes('/login'), `${process.env.HOLD_S}초를 켜 두어도 로그아웃되지 않는다`, chat.url());
}

// ── 로그아웃 ──
if (process.env.SIGNOUT) {
  await shell.evaluate(() => window.memora.shell.signOut());
  const s5 = await waitState((s) => !s.signedIn && !s.restoring, 15000);
  say(!s5.signedIn, '로그아웃하면 틀이 접힌다');
  await sleep(2500);
  say(!pages().some((p) => p.url().includes('avatar.html') || p.url().includes('chip.html')), '아바타도 컨트롤도 내려간다');
  shot('d10-signedout');
}

say(errors.length === 0, '틀에 스크립트 오류가 없다', errors.join(' | '));
await app.close();
console.log(bad ? `\n실패 ${bad}건` : '\n전부 통과');
process.exit(bad ? 1 : 0);
