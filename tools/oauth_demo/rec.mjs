import { chromium } from '/home/workspace/.tools/pw/node_modules/playwright-core/index.mjs';
import fs from 'node:fs';
import { S, O, sleep, xdo, log, point, click, type, Recorder } from './helpers.mjs';

const PW = process.env.DEMO_PW ?? '';
if (!PW) throw new Error('DEMO_PW 를 넣어 주세요 (demo@memo-ora.com 비밀번호)');
const LINK = `${O}/secretary/p2urjttb`;
const CLIENT = '145625595263-e3496eus7scgtdjh534hv5a6evcejq7o.apps.googleusercontent.com';
const only = process.env.ONLY ?? '';   // 시험용: 한 장면만

const browser = await chromium.connectOverCDP('http://127.0.0.1:9333');
const ctx = browser.contexts()[0];
let page = await ctx.newPage();
for (const p of ctx.pages()) if (p !== page) await p.close().catch(() => {});
// 지난 녹화의 Memora 로그인은 지운다 — 영상은 로그인부터 보인다.
await (await ctx.newCDPSession(page)).send('Storage.clearDataForOrigin', { origin: O, storageTypes: 'all' }).catch((e) => log('clear', String(e)));
const shot = async (n) => { try { await page.screenshot({ path: `${S}/fail-${n}.png` }); } catch {} };

async function api(method, path, body) {
  const r = await fetch(`${O}/api/auth/login`, { method: 'POST', headers: { 'content-type': 'application/json', 'user-agent': 'Mozilla/5.0 memora-demo' }, body: JSON.stringify({ email: 'demo@memo-ora.com', password: PW }) });
  const tok = (await r.json()).access_token;
  const res = await fetch(`${O}${path}`, { method, headers: { authorization: `Bearer ${tok}`, 'content-type': 'application/json', 'user-agent': 'Mozilla/5.0 memora-demo' }, body: body ? JSON.stringify(body) : undefined });
  return res.json();
}
async function waitUrl(pred, ms = 30000) { const end = Date.now() + ms; while (Date.now() < end) { if (pred(page.url())) return true; await sleep(300); } return false; }
async function side(label, group) {
  // 배지가 붙은 링크는 이름이 "Inbox 1" 처럼 된다 — 앞머리로 찾는다.
  const link = page.locator('nav, aside').getByRole('link', { name: new RegExp(`^${label}( \\d+)?$`) }).first();
  if (group) {
    const g = page.locator('nav, aside').getByRole('button', { name: group, exact: true }).first();
    if ((await g.getAttribute('aria-expanded').catch(() => null)) === 'false') await click(page, g, 800);
  }
  await click(page, link, 2500);
}
async function hold(ms) { await sleep(ms); }
async function googleTab(url, ms, capText, rec) {
  const g = await ctx.newPage();
  await g.goto(url, { waitUntil: 'domcontentloaded' }).catch(() => {});
  if (capText) rec.caption(capText);
  if (url.includes('calendar.google.com')) { await sleep(2500); await g.mouse.move(1000, 600); await g.mouse.wheel(0, -260).catch(() => {}); }
  await sleep(ms);
  return g;
}

/** 주소창에서 client_id 가 보이게: 주소창에 들어가 client_id 끝까지 커서를 옮긴다. */
async function showClientId() {
  const url = page.url();
  const i = url.indexOf('client_id=');
  if (i < 0) return false;
  const j = url.indexOf('&', i);
  const end = j < 0 ? url.length : j;
  await moveTo(700, 63);
  xdo('key', 'ctrl+l'); await sleep(500);
  xdo('key', 'Home'); await sleep(300);
  xdo('key', '--delay', '2', '--repeat', end, 'Right');
  await sleep(6000);
  xdo('key', 'Escape'); await sleep(200); xdo('key', 'Escape');
  return true;
}
import { moveTo } from './helpers.mjs';

async function googleFlow(rec) {
  const end = Date.now() + 300000;
  let shownId = false, shownConsent = false, selectedAll = false;
  while (Date.now() < end) {
    const url = page.url();
    if (url.startsWith(O)) return true;
    if (!url.includes('accounts.google.com')) { await sleep(500); continue; }
    await page.waitForLoadState('domcontentloaded').catch(() => {});
    await sleep(1500);
    if (!shownId) {
      rec.caption(`Google OAuth for Memora. The client ID in the address bar: ${CLIENT}`);
      shownId = await showClientId();
    }
    const acct = page.locator('[data-identifier]').first();
    if (await acct.isVisible().catch(() => false)) { rec.caption('The user chooses the Google account to connect'); await sleep(1500); await click(page, acct, 3000); continue; }
    const adv = page.getByText('Advanced', { exact: true }).first();
    if (await adv.isVisible().catch(() => false)) {
      rec.caption('Google shows its unverified-app notice while verification is pending');
      await sleep(3000); await click(page, adv, 1500);
      await click(page, page.getByText(/Go to .*\(unsafe\)/).first(), 3000); continue;
    }
    // 권한 화면: 권한마다 체크박스가 있다. 하나씩 짚어 보이고 [Select all] 뒤 [Continue].
    const all = page.getByText('Select all', { exact: true }).first();
    if (!selectedAll && await all.isVisible().catch(() => false)) {
      rec.caption('Memora requests: contacts (read), Drive files used with the app (drive.file), calendar events (add accepted meetings), calendar (read)');
      await sleep(2500);
      for (const re of [/See and download your contacts/, /specific Google Drive files/, /View and edit events/, /See and download any calendar/]) {
        await point(page, page.getByText(re).first()).catch(() => {}); await sleep(1800);
      }
      rec.caption('The user grants each permission');
      await click(page, all, 1500);
      selectedAll = true;
      await page.mouse.wheel(0, 500).catch(() => {}); await sleep(1500);
    }
    const btn = page.getByRole('button', { name: /^(Continue|Allow)$/ }).first();
    if (await btn.isVisible().catch(() => false)) {
      if (!shownConsent && !selectedAll) { rec.caption('Sign in with Google: Memora receives the name, email address and profile picture'); await sleep(4000); }
      shownConsent = true;
      await click(page, btn, 3500); continue;
    }
    await sleep(1000);
  }
  return false;
}

const rec = new Recorder(`${S}/demo-raw.mp4`);
const want = (n) => !only || only.split(',').includes(n);
try {
  // ── 0. 첫 화면·처리방침 ─────────────────────────────────────────
  await page.goto(O, { waitUntil: 'domcontentloaded' }); await sleep(2500);
  rec.start();
  if (want('intro')) {
    rec.caption('Memora (memo-ora.com) is a personal AI secretary. This video shows how it uses Google user data.');
    await moveTo(960, 500); await hold(4000);
    await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })); await hold(2500);
    rec.caption('The privacy policy is linked from every page');
    await click(page, page.locator('footer a[href="/privacy"]').first(), 3000);
    await waitUrl((u) => u.includes('/privacy'));
    rec.caption('Privacy policy: how Memora accesses, uses, stores and shares Google user data (Limited Use)');
    await page.evaluate(() => { const h = [...document.querySelectorAll('h2,h3')].find((x) => /Google/.test(x.textContent || '')); h?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }); await hold(5000);
    await page.evaluate(() => { const h = [...document.querySelectorAll('p,li,strong')].find((x) => /Limited Use/.test(x.textContent || '')); h?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }); await hold(6000);
  }

  // ── 1. 로그인 ─────────────────────────────────────────────────
  rec.caption('Sign in to Memora');
  await page.goto(`${O}/login`, { waitUntil: 'domcontentloaded' }); await sleep(2000);
  await click(page, page.locator('input[type=email]')); await type('demo@memo-ora.com');
  await click(page, page.locator('input[type=password]')); await type(PW, 20);
  await click(page, page.locator('button[type=submit]'), 3000);
  await waitUrl((u) => u.includes('/app'));
  await sleep(2500);

  // ── 2. 연동 → 동의 ────────────────────────────────────────────
  if (want('connect')) {
    rec.caption('Integrations: the user chooses which Google features to turn on');
    await side('Integrations', 'Account');
    await hold(2500);
    for (const l of ['Import events', 'Add accepted meetings', 'Import contacts', 'Import and save Drive files']) { await point(page, page.getByText(l, { exact: true }).first()); await sleep(900); }
    await click(page, page.getByRole('button', { name: 'Connect Google' }), 1500);
    if (!(await googleFlow(rec))) throw new Error('google flow did not return');
    await sleep(3000);
    rec.caption('Connected. Memora shows where each kind of Google data goes.');
    await hold(5000);
  }

  // ── 3. calendar.readonly ─────────────────────────────────────
  if (want('calread')) {
    rec.caption('calendar.readonly: Google Calendar events are imported into the Memora schedule (read only)');
    await side('Schedule', 'My info');
    await click(page, page.getByRole('radio', { name: 'Connections' }).first(), 2500);
    await hold(3000);
    const fetchBtn = page.getByRole('button', { name: 'Fetch now' }).first();
    if (await fetchBtn.isVisible().catch(() => false)) { await click(page, fetchBtn, 4000); }
    await click(page, page.getByRole('radio', { name: 'Events' }).first(), 3000);
    rec.caption('Events from Google Calendar now appear in the Memora schedule');
    await hold(5000);
    const g = await googleTab('https://calendar.google.com/calendar/u/0/r/week?hl=en', 7000, 'The same events in the user\'s Google Calendar', rec);
    await g.close(); await page.bringToFront(); await sleep(1500);
    rec.caption('The secretary uses these events to tell the user about their day and to avoid double-booking');
    await side('Secretary home');
    await click(page, page.getByRole('link', { name: 'Chat with secretary' }).or(page.getByRole('button', { name: 'Chat with secretary' })).first(), 3500);
    const box = page.getByRole('textbox').last();
    await click(page, box, 500); await type("What's on my calendar this week?");
    xdo('key', 'Return');
    await page.getByRole('button', { name: 'Stop' }).waitFor({ state: 'visible', timeout: 20000 }).catch(() => {});
    await page.getByRole('button', { name: 'Stop' }).waitFor({ state: 'hidden', timeout: 120000 }).catch(() => {});
    await hold(6000);
  }

  // ── 4. calendar.events ───────────────────────────────────────
  if (want('calwrite')) {
    rec.caption('calendar.events: a visitor asks Alex\'s secretary for a meeting (visitor\'s browser)');
    const vctx = await browser.newContext({ viewport: null });
    const v = await vctx.newPage();
    try {
      const cdp = await vctx.newCDPSession(v);
      const { windowId } = await cdp.send('Browser.getWindowForTarget');
      await cdp.send('Browser.setWindowBounds', { windowId, bounds: { left: 0, top: 0, width: 1920, height: 1080 } });
    } catch (e) { log('bounds', String(e)); }
    await v.goto(LINK, { waitUntil: 'domcontentloaded' }); await sleep(3500);
    const anon = v.getByText('Continue anonymously', { exact: true });
    if (await anon.isVisible().catch(() => false)) await click(v, anon, 2500);
    const before = (await api('GET', '/api/inbox?kind=meeting_request')).items?.length ?? 0;
    await click(v, v.getByRole('textbox').last(), 400);
    await type("Hi Aria, I'm Jamie Lee from Northwind. I'd like to meet Alex next Tuesday at 3 pm for 30 minutes about a partnership pilot. My email is jamie.lee@example.com.", 25);
    xdo('key', 'Return');
    let got = false;
    for (let i = 0; i < 60 && !got; i++) {
      await sleep(2000);
      const n = (await api('GET', '/api/inbox?kind=meeting_request')).items?.length ?? 0;
      got = n > before;
      if ((i === 18 || i === 38) && !got) { await click(v, v.getByRole('textbox').last(), 300); await type('Tuesday, October 6 at 3 pm works best for me. Please send the meeting request to Alex to confirm.', 25); xdo('key', 'Return'); }
    }
    log('meeting request created', got);
    await hold(6000);
    await vctx.close();
    await page.bringToFront(); await sleep(1500);
    rec.caption('Alex accepts the request in the Inbox. Memora creates that one event in Google Calendar and invites the guest.');
    await side('Inbox');
    await hold(2000);
    await click(page, page.locator('main').getByText(/Jamie/).first(), 3000);
    const acc = page.getByRole('button', { name: /Accept and add to schedule|^Accept$/ }).first();
    await click(page, acc, 5000);
    await page.getByText('Also added to Google Calendar').waitFor({ timeout: 20000 }).catch(() => {});
    await point(page, page.getByText('Also added to Google Calendar').first()).catch(() => {});
    await hold(5000);
    const items = (await api('GET', '/api/inbox?kind=meeting_request')).items ?? [];
    const it = items.find((x) => x.status === 'accepted') ?? items[0];
    const when = it?.payload?.scheduled_at ? new Date(it.payload.scheduled_at) : new Date(Date.now() + 7 * 864e5);
    const d = `${when.getFullYear()}/${when.getMonth() + 1}/${when.getDate()}`;
    const g = await googleTab(`https://calendar.google.com/calendar/u/0/r/week/${d}?hl=en`, 4000, 'The accepted meeting in the user\'s Google Calendar', rec);
    const ev = g.getByText(/Meeting with/).first();
    if (await ev.isVisible().catch(() => false)) { await click(g, ev, 5000); } else await sleep(4000);
    await g.close(); await page.bringToFront(); await sleep(1000);
    xdo('key', 'Escape');
  }

  // ── 5. contacts.readonly ─────────────────────────────────────
  if (want('contacts')) {
    rec.caption('contacts.readonly: Google contacts are imported into the user\'s private Network (names blurred in this video)');
    rec.blurOn('net', 400, 87 + 262, 1360, 1080 - 349);   // 다른 사람의 이름은 영상에서 흐리게
    await side('Network', 'My info');
    await sleep(2000);
    await click(page, page.getByRole('radio', { name: /List/ }).first(), 1500).catch((e) => log('list', String(e).slice(0, 120)));
    await hold(5000);
    rec.blurOff('net');
    rec.blurOn('gc', 290, 87 + 85, 1630, 1080 - 172);
    const g = await googleTab('https://contacts.google.com/?hl=en', 6000, 'The same contacts in Google Contacts (personal details blurred in this video)', rec);
    await g.close(); await page.bringToFront(); await sleep(600);
    rec.blurOff('gc');
  }

  // ── 6. drive.file ────────────────────────────────────────────
  if (want('drive')) {
    rec.caption('drive.file: Memora only touches files the user saves from Memora or picks in the Google Picker');
    await side('Files', 'My info');
    await hold(2500);
    await click(page, page.getByText('Northwind partnership brief.docx').first(), 2500);
    rec.caption('Save a file from Memora into the user\'s Drive (a "Memora" folder)');
    const popup = ctx.waitForEvent('page', { timeout: 30000 }).catch(() => null);
    await click(page, page.getByRole('button', { name: 'Save to Google Drive' }), 3000);
    await click(page, page.getByRole('button', { name: 'Open in Drive' }).first(), 1000).catch(() => {});
    const dp = await popup;
    if (dp) { await dp.waitForLoadState('domcontentloaded').catch(() => {}); rec.caption('The saved file in Google Drive'); await sleep(7000); await dp.close(); }
    await page.bringToFront(); await sleep(800);
    xdo('key', 'Escape'); await sleep(1000);
    rec.caption('Import from Google Drive: the user picks files in Google\'s own file picker');
    await click(page, page.getByRole('button', { name: 'Import from Google Drive' }), 2000);
    await click(page, page.getByRole('button', { name: 'Pick from Drive' }), 5000);
    const frameEl = page.locator('iframe[src*="docs.google.com/picker"]').first();
    await frameEl.waitFor({ timeout: 30000 });
    const fb = await frameEl.boundingBox();
    const top = await page.evaluate(() => window.outerHeight - window.innerHeight);
    rec.blurOn('picker', fb.x, fb.y + top + 110, fb.width, fb.height - 110);   // 사용자의 다른 Drive 파일 이름은 흐리게
    const pf = page.frameLocator('iframe[src*="docs.google.com/picker"]').first();
    await sleep(3000);
    try {
      const search = pf.getByRole('combobox').or(pf.getByPlaceholder(/Search/i)).or(pf.getByRole('textbox')).first();
      await click(page, search, 500); await type('Northwind'); xdo('key', 'Return');
      await sleep(3500);
    } catch (e) { log('picker search', String(e).slice(0, 200)); }
    // 격자 칸의 이름(보이는 것)을 잡는다 — 같은 이름이 숨은 목록 보기에도 있다.
    const tile = pf.locator('text=/Northwind meeting notes/ >> visible=true').first();
    await tile.waitFor({ timeout: 30000 });
    rec.blurOff('picker');
    await sleep(2500);
    await click(page, tile, 1500);
    await click(page, pf.getByRole('button', { name: 'Select' }).first(), 4000);
    rec.caption('Only the picked file comes into the secretary\'s Files. A Google Doc arrives as a Word file (source: Google Drive).');
    await page.getByText(/Imported/).first().waitFor({ timeout: 30000 }).catch(() => {});
    await sleep(2500);
    await point(page, page.locator('main').getByText(/Northwind meeting notes/).first()).catch(() => {});
    await hold(5000);
  }

  // ── 7. 끝 ────────────────────────────────────────────────────
  rec.caption('Users can disconnect Google at any time. Memora then revokes its access and deletes imported events.');
  await side('Integrations', 'Account');
  await point(page, page.getByRole('button', { name: 'Disconnect' }).first()).catch(() => {});
  await hold(6000);
} catch (e) {
  log('ERROR', String(e).slice(0, 500));
  await shot('error');
} finally {
  if (rec.ff) await rec.stop();
  await browser.close().catch(() => {});
  log('done');
}
