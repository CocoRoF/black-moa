/**
 * 아바타 공간과 컨트롤 (plan/66). 트레이·단축키가 쓰는 그 길을 그대로 부른다.
 *
 *   잠김(기본) → 컨트롤 창이 사진 아래 가운데에 붙어 있다. 컨트롤을 끌면 아바타가 따라온다.
 *   풀림       → 컨트롤이 사라지고 점선 틀·막대가 나온다. 손잡이로 크기, 휠로 확대(커서를 붙잡고),
 *                끌어서 사진 옮기기, 두 번 눌러 처음 모양. 모양과 자리는 다시 켜도 그대로다.
 */
import { _electron as electron } from '/home/workspace/.tools/pw/node_modules/playwright-core/index.mjs';
import { mkdirSync, readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
const SHOT = process.env.SHOT_DIR ?? '/tmp/blackmoa-shots';
mkdirSync(SHOT, { recursive: true });
const PROFILE = process.env.PROFILE_DIR ?? '/tmp/blackmoa-conn';
const BIN = new URL('../node_modules/electron/dist/electron', import.meta.url).pathname;
let bad = 0;
const say = (ok, what, extra = '') => { if (!ok) bad++; console.log(`${ok ? '  ok' : '!! 실패'}  ${what}${extra ? '  ' + extra : ''}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launch() {
  const app = await electron.launch({ executablePath: BIN,
    // --avatar 는 진짜 스위치다. 로그인할 때 시작과 짝이 되는 것이라 테스트용 구멍이 아니다.
    args: ['.', '--avatar', '--no-sandbox', '--disable-gpu', `--user-data-dir=${PROFILE}`],
    env: { ...process.env, ELECTRON_RUN_AS_NODE: undefined, BLACKMOA_TEST_HOOKS: '1' } });
  const main = await app.firstWindow();
  await main.waitForLoadState('domcontentloaded');
  let av = null, chip = null;
  for (let i = 0; i < 30 && !(av && chip); i++) {
    await sleep(1000);
    av = app.windows().find((w) => w.url().includes('avatar.html')) ?? null;
    chip = app.windows().find((w) => w.url().includes('chip.html')) ?? null;
  }
  return { app, main, av, chip };
}

const bounds = (app, part) =>
  app.evaluate(({ BrowserWindow }, part) => {
    const w = BrowserWindow.getAllWindows().find((x) => x.webContents.getURL().includes(part + '.html'));
    if (!w || w.isDestroyed()) return null;
    const b = w.getBounds();
    return { ...b, visible: w.isVisible() };
  }, part);
const hook = (app, fn, ...args) => app.evaluate((_e, [fn, args]) => globalThis.__blackmoaTest.avatar[fn](...args), [fn, args]);
const figure = (av) => av.evaluate(() => { const r = document.querySelector('.ov-figure')?.getBoundingClientRect(); return r ? { x: r.x, y: r.y, w: r.width, h: r.height } : null; });
const stored = () => JSON.parse(readFileSync(`${PROFILE}/settings.json`, 'utf8'));
// 진짜 커서를 옮긴다(xdotool). 잠긴 컨트롤은 운영체제의 커서가 아바타 위에 있을 때만 나온다.
const pointer = (x, y) => execFileSync('xdotool', ['mousemove', String(Math.round(x)), String(Math.round(y))]);
const revealed = (app) => hook(app, 'revealed');
const chipShown = (chip) => chip.evaluate(() => document.querySelector('[data-shown]')?.getAttribute('data-shown') === '1');
/** 사진 한가운데로 커서를 옮기고 컨트롤이 나올 때까지. */
async function hover(app, av) {
  const b = await bounds(app, 'avatar');
  const f = await figure(av);
  pointer(b.x + (f ? f.x + f.w / 2 : b.width / 2), b.y + (f ? f.y + f.h * 0.4 : b.height / 2));
  for (let i = 0; i < 20 && !(await revealed(app)); i++) await sleep(100);
  await sleep(200);
}
const away = () => pointer(3, 3);

let { app, av, chip } = await launch();
say(!!av, '--avatar 로 켜면 아바타 공간이 뜬다');
say(!!chip, '컨트롤 창이 함께 뜬다');
if (!av || !chip) { await app.close(); process.exit(1); }
const errs = [];
av.on('pageerror', (e) => errs.push('av: ' + String(e).slice(0, 120)));
chip.on('pageerror', (e) => errs.push('chip: ' + String(e).slice(0, 120)));
await sleep(2500);

// ── 사진 ──
const pic = await av.evaluate(() => { const i = document.querySelector('.ov-figure img'); return i ? { blob: i.src.startsWith('blob:'), ok: i.complete && i.naturalWidth > 0, card: !!document.querySelector('.ov-figure.card') } : null; });
say(!!pic?.blob && pic.ok, '올린 사진이 그대로 선다', JSON.stringify(pic));
say(pic && !pic.card, '바탕 없이 선다(흰 판·동그라미가 아니다)');

// ── 잠김 ──
say(await hook(app, 'locked'), '처음에는 잠겨 있다');
say((await av.locator('.ov-dock').count()) === 0 && (await av.locator('.ov-resize-frame').count()) === 0, '잠겼을 때 아바타 창에는 단추가 없다');
let A = await bounds(app, 'avatar');
let C = await bounds(app, 'chip');
away();
await sleep(900);
C = await bounds(app, 'chip');
say(C && !C.visible, '잠겼을 때 컨트롤 창은 마우스를 올리기 전에는 떠 있지 않다');
await hover(app, av);
C = await bounds(app, 'chip');
say(C?.visible, '마우스를 올리면 컨트롤 창이 뜬다');
const centered = Math.abs(C.x + C.width / 2 - (A.x + A.width / 2)) <= 1 && C.y + C.height <= A.y + A.height && C.y + C.height >= A.y + A.height - 10;
say(centered, '컨트롤은 사진 아래 가운데에 붙어 있다', `avatar ${A.x},${A.y} ${A.width}x${A.height} / chip ${C.x},${C.y} ${C.width}x${C.height}`);
// 음성 단추는 서비스가 음성을 쓸 때만 있다(plan/67). 운영의 관리자 설정과 상관없이 컨트롤을 시험하도록 이 앱 안에서만
// 켠 것으로 둔다(서버의 설정은 건드리지 않는다).
const voiceOn = () => app.evaluate(() => globalThis.__blackmoaTest.voice.set({ stt: true, tts: true }));
await voiceOn();
for (let i = 0; i < 40 && !(await chip.locator('[title="말하기"]').count()); i++) await sleep(250);
for (const t of ['말하기', '소리 끄기', '글로 묻기', '대화 전체 보기', '잠금 풀기']) say((await chip.locator(`[title="${t}"]`).count()) === 1, `컨트롤에 [${t}]`);

// ── 마우스를 올렸을 때만 ──
away();
await sleep(900);
say(!(await revealed(app)) && !(await chipShown(chip)) && !(await bounds(app, 'chip')).visible, '마우스가 멀리 있으면 컨트롤은 숨어 있다');
await hover(app, av);
say((await revealed(app)) && (await chipShown(chip)) && (await bounds(app, 'chip')).visible, '사진 위에 마우스를 올리면 컨트롤이 나온다');
{
  const b = await bounds(app, 'avatar');
  const c = await bounds(app, 'chip');
  pointer(c.x + c.width / 2, c.y + c.height / 2);
  await sleep(700);
  say(await revealed(app), '사진에서 컨트롤로 내려가도 사라지지 않는다');
  pointer(b.x - 60, b.y + b.height / 2);
  await sleep(300);
  say(await revealed(app), '떠나도 잠깐은 기다린다');
  await sleep(700);
  say(!(await revealed(app)) && !(await chipShown(chip)) && !(await bounds(app, 'chip')).visible, '떠나면 조금 뒤에 숨는다');
  // 창 안이지만 사진이 아닌 곳(왼쪽 위 빈 자리)
  const f = await figure(av);
  const empty = f && f.x > 30 ? [b.x + f.x / 2, b.y + b.height / 3] : f && f.y > 30 ? [b.x + b.width / 2, b.y + f.y / 2] : null;
  if (empty) {
    pointer(empty[0], empty[1]);
    await sleep(700);
    say(!(await revealed(app)), '창 안이라도 사진이 없는 빈 자리에서는 나오지 않는다');
  } else say(true, '(사진이 창을 꽉 채워 빈 자리가 없다)');
}

// ── 관리자가 음성을 끄면 단추도 없다 (plan/67) ──
await hover(app, av);
await app.evaluate(() => globalThis.__blackmoaTest.voice.set({ stt: false, tts: false }));
await sleep(500);
say((await chip.locator('[title="말하기"]').count()) === 0 && (await chip.locator('[title="소리 끄기"]').count()) === 0, '음성을 끄면 컨트롤에서 [말하기]·[소리] 가 사라진다');
say((await chip.locator('[title="글로 묻기"]').count()) === 1, '글로 묻기는 그대로');
await app.evaluate(() => globalThis.__blackmoaTest.voice.set({ stt: true, tts: false }));
await sleep(400);
say((await chip.locator('[title="말하기"]').count()) === 1 && (await chip.locator('[title="소리 끄기"]').count()) === 0, '받아쓰기만 켜면 [말하기] 만');
await app.evaluate(() => globalThis.__blackmoaTest.voice.set({ stt: true, tts: true }));
await sleep(400);

// 잠겼을 때 휠은 사진을 건드리지 않는다
const f0 = await figure(av);
await av.mouse.move(A.width / 2, A.height / 2);
await av.mouse.wheel(0, -100);
await sleep(300);
say(JSON.stringify(await figure(av)) === JSON.stringify(f0), '잠겼을 때는 휠이 사진을 키우지 않는다');

// 컨트롤을 끌면 아바타가 따라온다
A = await bounds(app, 'avatar');
C = await bounds(app, 'chip');
await chip.evaluate(() => { window.blackmoa.chip.moveBy(-60, -30); window.blackmoa.chip.commitBounds(); });
await sleep(600);
const A2 = await bounds(app, 'avatar');
const C2 = await bounds(app, 'chip');
say(A2.x === A.x - 60 && A2.y === A.y - 30 && A2.width === A.width && A2.height === A.height, '컨트롤을 끌면 아바타가 옮겨진다(크기는 그대로)', `${A.x},${A.y} → ${A2.x},${A2.y}`);
say(C2.x - A2.x === C.x - A.x && C2.y - A2.y === C.y - A.y, '컨트롤도 같이 따라온다');
await hover(app, av);
await av.screenshot({ path: `${SHOT}/av-locked.png`, omitBackground: true });
await chip.screenshot({ path: `${SHOT}/chip-locked.png`, omitBackground: true });

// 소리 켜고 끄기(설정에 적힌다)
await voiceOn();
await hover(app, av);
await chip.locator('[title="소리 끄기"]').click();
await sleep(500);
say((await chip.locator('[title="소리 켜기"]').count()) === 1 && (await hook(app, 'status')).speak === false, '컨트롤에서 소리를 끈다');
await chip.locator('[title="소리 켜기"]').click();
await sleep(400);

// 먼저 건넨 말 → 말풍선과 [답하기]
await hook(app, 'say', { text: '오늘 오후 세 시에 회의가 있어요. 준비할 자료를 챙겨 드릴까요?', done: true, proactive: true });
await sleep(1800);
say((await chip.locator('[title="답하기"]').count()) === 1, '비서가 먼저 말을 걸면 컨트롤에 [답하기]');
const bub = await av.evaluate(() => { const w = document.querySelector('.ov-subtitle-wrap'); const s = document.querySelector('.ov-subtitle'); return w && s ? { text: s.textContent, bottom: parseFloat(w.style.bottom) } : null; });
say(!!bub?.text?.includes('회의'), '말풍선에 말이 나온다', bub?.text?.slice(0, 30));
say(bub && bub.bottom >= C.height, '말풍선은 컨트롤 위로 올라가 있다', `bottom ${bub?.bottom}px, 컨트롤 ${C.height}px`);
await hover(app, av);
await av.screenshot({ path: `${SHOT}/av-said.png`, omitBackground: true });
await chip.screenshot({ path: `${SHOT}/chip-reply.png`, omitBackground: true });

// ── 풀림 ──
await hover(app, av);
await chip.locator('[title="잠금 풀기"]').click();
await sleep(700);
say((await hook(app, 'locked')) === false, '[잠금 풀기] 로 풀린다');
say(!(await bounds(app, 'chip')).visible, '풀리면 컨트롤이 숨는다');
say((await av.locator('.ov-resize-frame .ov-rh').count()) === 8, '점선 틀에 손잡이 여덟');
for (const t of ['말하기', '답하기', '사진 숨기기', '사진 처음 모양으로', '잠그기', '닫기']) say((await av.locator(`.ov-dock [title="${t}"]`).count()) === 1, `막대에 [${t}]`);
// 컨트롤과 막대는 같은 단추다: 먼저 건넨 말이 기다리면 막대에도 [답하기]
await av.screenshot({ path: `${SHOT}/av-unlocked.png`, omitBackground: true });

// 크기: 오른쪽 아래, 왼쪽 위
A = await bounds(app, 'avatar');
await av.evaluate(() => { window.blackmoa.avatar.resizeBy('se', 40, 30); window.blackmoa.avatar.commitBounds(); });
await sleep(400);
let B = await bounds(app, 'avatar');
say(B.width === A.width + 40 && B.height === A.height + 30 && B.x === A.x && B.y === A.y, '오른쪽 아래 손잡이로 커진다', `${A.width}x${A.height} → ${B.width}x${B.height}`);
await av.evaluate(() => { window.blackmoa.avatar.resizeBy('nw', 20, 20); window.blackmoa.avatar.commitBounds(); });
await sleep(400);
const B2 = await bounds(app, 'avatar');
say(B2.width === B.width - 20 && B2.height === B.height - 20 && B2.x === B.x + 20 && B2.y === B.y + 20, '왼쪽 위 손잡이로 줄면 오른쪽 아래는 제자리');
await av.evaluate(() => { window.blackmoa.avatar.resizeBy('e', -2000, 0); window.blackmoa.avatar.commitBounds(); });
await sleep(400);
say((await bounds(app, 'avatar')).width === 240, '가장 작아도 240 — 단추가 사진을 다 가리지 않게');
await av.evaluate(() => { window.blackmoa.avatar.resizeBy('e', 100, 0); window.blackmoa.avatar.commitBounds(); });
await sleep(500);
// 진짜 손잡이를 마우스로 끌어 본다
A = await bounds(app, 'avatar');
await av.mouse.move(A.width - 4, A.height - 4);
await av.mouse.down();
await av.mouse.move(A.width + 16, A.height + 26, { steps: 5 });
await av.mouse.up();
await sleep(500);
B = await bounds(app, 'avatar');
say(B.width > A.width && B.height > A.height, '모서리 손잡이를 마우스로 끌어 키운다', `${A.width}x${A.height} → ${B.width}x${B.height}`);

// 휠: 커서가 가리키는 곳을 붙잡고 확대
await sleep(400);
const key = (await av.evaluate(() => window.blackmoa.avatar.subject())).imageUrl;
await hook(app, 'flush');
const scale0 = (stored().avatarViews ?? {})[key]?.scale ?? 1;
const W = B.width, H = B.height;
const g0 = await figure(av);
const px = g0.x + g0.w * 0.3, py = g0.y + g0.h * 0.35;
await av.mouse.move(px, py);
for (let i = 0; i < 3; i++) { await av.mouse.wheel(0, -100); await sleep(60); }
await sleep(300);
const g1 = await figure(av);
const k = g1.w / g0.w;
say(Math.abs(k - 1.08 ** 3) < 0.02, '휠 세 칸에 1.08배씩 커진다', `×${k.toFixed(3)}`);
const u0 = (px - g0.x) / g0.w, u1 = (px - g1.x) / g1.w, v0 = (py - g0.y) / g0.h, v1 = (py - g1.y) / g1.h;
say(Math.abs(u0 - u1) < 0.01 && Math.abs(v0 - v1) < 0.01, '커서 아래의 곳은 제자리에 있다', `(${u0.toFixed(3)},${v0.toFixed(3)}) → (${u1.toFixed(3)},${v1.toFixed(3)})`);
// 끌어서 사진 옮기기
await av.mouse.move(W / 2, H / 2);
await av.mouse.down();
await av.mouse.move(W / 2 - 30, H / 2 - 20, { steps: 6 });
await av.mouse.up();
await sleep(300);
const g2 = await figure(av);
say(Math.abs(g2.x - (g1.x - 30)) <= 1 && Math.abs(g2.y - (g1.y - 20)) <= 1, '끌면 사진이 옮겨진다', `(${(g2.x - g1.x).toFixed(1)}, ${(g2.y - g1.y).toFixed(1)})`);
await sleep(1200);
await hook(app, 'flush');
const views = stored().avatarViews ?? {};
say(!!views[key] && Math.abs(views[key].scale / scale0 - 1.08 ** 3) < 0.02, '사진의 모양이 사진마다 적힌다', `${key.slice(0, 40)}… ×${views[key]?.scale.toFixed(3)}`);
await av.screenshot({ path: `${SHOT}/av-zoomed.png`, omitBackground: true });

// 창을 키우면 사진도 같이 커지고 같은 자리에 머문다
await av.evaluate(() => { window.blackmoa.avatar.resizeBy('e', 60, 0); window.blackmoa.avatar.commitBounds(); });
await sleep(500);
const g3 = await figure(av);
say(g3.w >= g2.w, '창을 키우면 사진도 따라 커진다(줄지 않는다)', `${g2.w.toFixed(0)} → ${g3.w.toFixed(0)}`);

// 숨기기
await av.locator('.ov-dock [title="사진 숨기기"]').click();
await sleep(400);
say((await av.locator('.ov-figure').count()) === 0 && (await hook(app, 'status')).hidden, '[사진 숨기기] 로 말풍선만 남는다');
await av.locator('.ov-dock [title="사진 보이기"]').click();
await sleep(400);
say((await av.locator('.ov-figure').count()) === 1, '[사진 보이기] 로 돌아온다');

// 다시 잠그기
const beforeLock = await figure(av);
await av.locator('.ov-dock [title="잠그기"]').click();
await sleep(700);
say((await hook(app, 'locked')) && (await bounds(app, 'chip')).visible && (await av.locator('.ov-dock').count()) === 0, '[잠그기] 로 컨트롤이 돌아온다');
say(JSON.stringify(await figure(av)) === JSON.stringify(beforeLock), '잠그고 풀어도 사진은 움직이지 않는다');
const kept = await bounds(app, 'avatar');

// ── 다시 켜도 그대로 ──
// 닫기를 기다리지 않는다 — 답이 오기 전에 부른 창이 사라진다.
await av.evaluate(() => { void window.blackmoa.avatar.close(); });
await sleep(1200);
say(!(await bounds(app, 'avatar')) && !(await bounds(app, 'chip')), '닫으면 두 창이 함께 사라진다');
say(stored().avatarBounds?.width === kept.width, '닫을 때 자리를 적는다');
say(errs.length === 0, `오류 ${errs.length}건`, errs.join('; '));
await app.close();

({ app, av, chip } = await launch());
await sleep(2500);
const again = await bounds(app, 'avatar');
// 화면 밖으로 삐져나가 있었으면 작업 영역 안으로 들어와서 뜬다.
const wa = await app.evaluate(({ screen }) => screen.getPrimaryDisplay().workArea);
// 화면보다 커졌으면 화면 크기로 줄어든다(여러 번 돌린 시험에서 키운 만큼 쌓인다).
const kw = Math.min(kept.width, wa.width), kh = Math.min(kept.height, wa.height);
const want = { x: Math.min(Math.max(kept.x, wa.x), wa.x + wa.width - kw), y: Math.min(Math.max(kept.y, wa.y), wa.y + wa.height - kh) };
say(again && again.x === want.x && again.y === want.y && again.width === kw && again.height === kh, '다시 켜면 같은 자리·같은 크기(화면 안으로)', `${kept.x},${kept.y} ${kept.width}x${kept.height} / ${again?.x},${again?.y} ${again?.width}x${again?.height}`);
say(await hook(app, 'locked'), '다시 켜면 잠긴 채로 시작한다');
const g4 = await figure(av);
say(g4 && Math.abs(g4.w - beforeLock.w) < 1 && Math.abs(g4.x - beforeLock.x) < 1, '사진의 모양도 그대로', `${beforeLock.w.toFixed(0)} / ${g4?.w.toFixed(0)}`);

// 두 번 눌러 처음 모양으로(풀었을 때만)
await hover(app, av);
await chip.locator('[title="잠금 풀기"]').click();
await sleep(600);
await av.mouse.dblclick(again.width / 2, again.height / 2);
await sleep(1300);
await hook(app, 'flush');
const g5 = await figure(av);
say(g5.w < g4.w && !(stored().avatarViews ?? {})[key], '두 번 누르면 처음 모양으로(기억도 지운다)', `${g4.w.toFixed(0)} → ${g5.w.toFixed(0)}`);
await av.locator('.ov-dock [title="잠그기"]').click();
await sleep(300);

if (process.env.TALK) {
  await av.evaluate(() => window.blackmoa.avatar.ask('한 문장으로만 인사해 주세요.'));
  let text = '';
  for (let i = 0; i < 60; i++) {
    await sleep(1000);
    text = await av.evaluate(() => document.querySelector('.ov-subtitle')?.textContent ?? '');
    if (text.length > 5) break;
  }
  say(text.length > 5, '아바타가 답을 받는다', `"${text.slice(0, 40)}"`);
}
await app.close();
console.log(bad ? `\n!! ${bad}건 실패` : '\n모두 정상');
process.exit(bad ? 1 : 0);
