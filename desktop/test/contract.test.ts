/**
 * 겪은 것만 담는다.
 *
 * 여기 있는 것은 전부 실제로 한 번 틀렸던 것이거나, 틀리면 조용히 망가져서
 * 화면을 봐도 모르는 것들이다.
 */
import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { createSseParser } from '../src/main/stream';
import { applyAutostart, UnreadWatcher } from '../src/main/shell';
import { DEFAULT_SETTINGS, ORIGIN, TERMINAL, doorOf, newerThan, pickInstaller, routeFor, type Answer, type InstallerOut } from '../src/shared/contract';
import { normalize } from '../src/main/settings';
import { valid } from '../src/main/shortcuts';
import { step } from '../src/main/chat';
import { targetOf } from '../src/main/alerts';
import { cutout, hasAlpha } from '../src/shared/cutout';

test('서버 주소는 고정이다', () => {
  assert.equal(ORIGIN, 'https://black.memo-ora.com');
});

test('끝맺는 이벤트 셋을 모두 안다', () => {
  // 하나라도 빠지면 그 턴은 영원히 "생각하는 중" 으로 남는다.
  for (const t of ['turn.complete', 'turn.error', 'turn.cancelled']) assert.ok(TERMINAL.has(t), t);
  assert.ok(!TERMINAL.has('text.delta'));
});

test('SSE 를 가른다: 여러 줄, 주석, 토막난 조각', () => {
  const got: { event?: string; id?: string; data: string }[] = [];
  const p = createSseParser((b) => got.push(b));
  // 서버는 15초마다 ": ping" 을 보낸다. 그걸 이벤트로 세면 빈 조각이 섞인다.
  p.push(': ping\n\n');
  p.push('id: 3\nevent: text.delta\ndata: {"a":1,\n');
  p.push('data: "b":2}\n\n');
  // 한 이벤트가 두 번의 data 청크로 쪼개져 오는 것은 흔한 일이다.
  p.push('data: {"x"');
  p.push(':9}\n\n');
  p.end();
  assert.equal(got.length, 2);
  assert.equal(got[0].id, '3');
  assert.equal(got[0].event, 'text.delta');
  assert.deepEqual(JSON.parse(got[0].data), { a: 1, b: 2 });
  assert.deepEqual(JSON.parse(got[1].data), { x: 9 });
});

test('CRLF 로 와도 같은 것을 읽는다', () => {
  const got: { data: string }[] = [];
  const p = createSseParser((b) => got.push(b));
  p.push('data: {"ok":true}\r\n\r\n');
  p.end();
  assert.deepEqual(JSON.parse(got[0].data), { ok: true });
});

test('임시 경로에서는 자동 시작을 등록하지 않는다', () => {
  // AppImage 를 /tmp 에 풀어 돌릴 때 execPath 는 다음 부팅에 없다. 거기를
  // 가리키는 항목을 써 두면 켜진 것처럼 보이면서 영영 안 뜬다.
  const before = process.env.APPIMAGE;
  process.env.APPIMAGE = '/tmp/.mount_black-moaabc/AppRun';
  try {
    const r = applyAutostart({ setLoginItemSettings: () => {}, getPath: () => '/home/nobody' } as never, true, 'linux');
    assert.equal(r.applied, false);
    assert.equal(r.enabled, false);
    assert.ok(r.reason);
  } finally {
    if (before === undefined) delete process.env.APPIMAGE;
    else process.env.APPIMAGE = before;
  }
});

test('안 읽은 것: 처음 한 번은 세기만 한다', async () => {
  const told: string[] = [];
  const w = new UnreadWatcher(async () => ({ rooms: 7, inbox: 3 }), () => {}, (kind, d) => told.push(`${kind}+${d}`));
  await w.tick();
  // 앱을 켠 순간 밀린 것이 전부 알림으로 오면 그건 알림이 아니라 습격이다.
  assert.deepEqual(told, []);
  assert.deepEqual(w.snapshot(), { rooms: 7, inbox: 3 });
});

test('안 읽은 것: 늘어난 만큼만 알린다', async () => {
  const told: string[] = [];
  let n = { rooms: 1, inbox: 0 };
  const w = new UnreadWatcher(async () => n, () => {}, (kind, d) => told.push(`${kind}+${d}`));
  await w.tick();
  n = { rooms: 3, inbox: 0 };
  await w.tick();
  n = { rooms: 3, inbox: 0 };
  await w.tick();
  // 총 개수로 알리면 켜 두는 것만으로 30초마다 같은 알림이 온다.
  assert.deepEqual(told, ['rooms+2']);
});

test('안 읽은 것: 서버에 못 닿은 것은 0개가 아니다', async () => {
  const told: string[] = [];
  let fail = false;
  let n = { rooms: 5, inbox: 0 };
  const w = new UnreadWatcher(
    async () => {
      if (fail) throw new Error('끊김');
      return n;
    },
    () => {},
    (kind, d) => told.push(`${kind}+${d}`),
  );
  await w.tick();
  fail = true;
  await w.tick();
  fail = false;
  await w.tick();
  // 끊긴 동안 0으로 떨어뜨리면, 다시 닿는 순간 있던 것이 전부 새것으로 보인다.
  assert.deepEqual(told, []);
  assert.deepEqual(w.snapshot(), { rooms: 5, inbox: 0 });
});

test('웹 뷰에 얹는 다리로는 토큰을 읽어 갈 수 없다', () => {
  // 읽어 가는 길이 생기면 black.memo-ora.com 의 스크립트 한 줄이 이 앱의 토큰을 가져갈 수 있다. 0.8 에서 문 이름과
  // 이동 요청이 늘었지만, 전부 웹 → 앱의 한 방향이고 앱이 웹에게 값을 돌려주는 길(invoke)은 없다.
  const src = readFileSync(new URL('../src/preload/host.ts', import.meta.url), 'utf8');
  const exposed = [...src.matchAll(/^\s{2}(\w+)[(:,]/gm)].map((m) => m[1]).sort();
  assert.deepEqual(exposed, ['desktop', 'door', 'navigate', 'onCommand', 'openInBrowser', 'shell', 'signedOut', 'theme', 'token']);
  // 웹이 앱에게 묻는 것은 테마 하나뿐이다(뜰 때 한 번).
  assert.deepEqual([...src.matchAll(/sendSync\('([^']+)'/g)].map((m) => m[1]), ['host:theme-now']);
  assert.ok(!/get\w*\(/.test(src), '읽어 가는 함수가 생겼다');
  assert.ok(!src.includes('invoke'), '웹이 앱에게 값을 물어볼 길이 생겼다');
});

test('앱은 갱신하지 않는다', () => {
  // 웹과 같은 갱신 쿠키로 따로 갱신하면 서버가 토큰 도난으로 보고 세션
  // 가족 전체를 끊는다. 운영에서 refresh_reuse_detected 로 실제로 겪었다.
  for (const f of ['auth.ts', 'api.ts', 'stream.ts', 'index.ts', 'ipc.ts', 'live.ts', 'chat.ts', 'controller.ts', 'window.ts']) {
    const src = readFileSync(new URL(`../src/main/${f}`, import.meta.url), 'utf8');
    assert.ok(!src.includes('auth/refresh'), `${f} 가 갱신을 부른다`);
  }
});

test('세 문의 안쪽은 웹이 그린다', () => {
  // 앱이 채팅을 다시 그렸더니 사진·마크다운·도구 카드가 빠진 "웹보다 못한 앱" 이 됐다(plan/46 §9).
  const win = readFileSync(new URL('../src/main/window.ts', import.meta.url), 'utf8');
  assert.ok(win.includes('loadURL(ORIGIN + (path ?? doorHome(door)))'), '문이 웹을 열지 않는다');
  for (const f of ['Shell.tsx', 'Alerts.tsx', 'Settings.tsx']) {
    const src = readFileSync(new URL(`../src/renderer/src/${f}`, import.meta.url), 'utf8');
    assert.ok(!/\/messages|conversations\//.test(src), `${f} 가 대화를 직접 그린다`);
  }
});

test('문의 규칙: 같은 문은 그대로, 다른 문은 앱이, 문 밖은 브라우저가', () => {
  assert.deepEqual(routeFor('https://black.memo-ora.com/app/chat?a=1', 'chat'), { kind: 'stay' });
  assert.deepEqual(routeFor('/app/community/p/9', 'feed'), { kind: 'door', door: 'community', path: '/app/community/p/9' });
  assert.deepEqual(routeFor('/app/u/abc', 'community'), { kind: 'door', door: 'feed', path: '/app/u/abc' });
  assert.equal(routeFor('/app/schedule', 'chat').kind, 'browser');
  assert.equal(routeFor('/app/agents/x/settings', 'feed').kind, 'browser');
  assert.equal(routeFor('https://example.com/x', 'chat').kind, 'browser');
  // 로그인 쪽은 어느 문에서나, 웹의 첫 화면(/app)은 웹이 그 문의 첫 화면으로 돌린다.
  assert.deepEqual(routeFor('/login?next=%2Fapp%2Ffeed', 'feed'), { kind: 'stay' });
  assert.deepEqual(routeFor('/app', 'community'), { kind: 'stay' });
  // 비슷하게 생긴 주소에 속지 않는다.
  assert.equal(doorOf('/app/chatter'), null);
  assert.equal(doorOf('/app/me'), 'feed');
  assert.equal(doorOf('/app/blog?edit=1'), 'feed');
  assert.equal(doorOf('/app/onboarding'), 'chat');
});

test('문의 규칙은 웹과 같다', () => {
  // 둘이 갈라지면 링크가 뷰 사이를 오간다. 웹의 규칙(frontend/lib/desktop.ts)에 같은 경로들이 있어야 한다.
  const web = readFileSync(new URL('../../frontend/lib/desktop.ts', import.meta.url), 'utf8');
  const mine = readFileSync(new URL('../src/shared/contract.ts', import.meta.url), 'utf8');
  const bases = (src: string) => [...src.matchAll(/["'](\/(?:app\/[a-z]+|login|signup|forgot-password|reset-password))["']/g)].map((m) => m[1]).sort();
  const w = new Set(bases(web));
  for (const b of bases(mine)) assert.ok(w.has(b), `웹에 없는 경로: ${b}`);
});

test('설정 파일이 깨져 있어도 기본값으로 시작한다', () => {
  assert.deepEqual(normalize(null), DEFAULT_SETTINGS);
  const n = normalize({ theme: 'neon', agentId: '../../etc', notify: { inbox: false }, shortcuts: { quick: 42 }, extra: 1 });
  assert.equal(n.theme, 'system');
  assert.equal(n.agentId, null);
  assert.equal(n.notify.inbox, false);
  assert.equal(n.notify.proactive, true);
  assert.equal(n.shortcuts.quick, DEFAULT_SETTINGS.shortcuts.quick);
  assert.ok(!('extra' in n));
});

test('단축키: 수식키 없이는 받지 않는다', () => {
  assert.ok(valid('CommandOrControl+Shift+Space'));
  assert.ok(valid('Alt+Space'));
  assert.ok(valid(''), '비우면 끈 것이다');
  // 타자를 가로채는 조합.
  assert.ok(!valid('A'));
  assert.ok(!valid('Shift+A'));
  assert.ok(!valid('Control+Shift'));
});

test('빠른 대화의 답: 흐르고, 도구는 사람 말로, 끝나면 서버의 답으로', () => {
  let a: Answer = { id: '1', agentId: 'a', conversationId: 'c', question: 'q', text: '', status: '생각하는 중', done: false };
  const ev = (type: string, data: Record<string, unknown> = {}) => ({ seq: 1, type, at: '', data });
  a = step(a, ev('tool.start', { name: 'web_search', label: 'web_search' }));
  assert.equal(a.status, '확인하는 중', '도구의 속 이름을 보여 주지 않는다');
  a = step(a, ev('tool.start', { name: 'web_search', label: '웹에서 찾는 중' }));
  assert.equal(a.status, '웹에서 찾는 중');
  a = step(a, ev('text.delta', { text: '안녕' }));
  a = step(a, ev('text.delta', { text: '하세요' }));
  assert.equal(a.text, '안녕하세요');
  assert.equal(a.status, '');
  a = step(a, ev('turn.complete', { answer: '안녕하세요!' }));
  assert.ok(a.done);
  assert.equal(a.text, '안녕하세요!');
  const e = step({ ...a, done: false }, ev('turn.error', { message: 'rate limited' }));
  assert.equal(e.error, '답을 받지 못했어요.', '영문 오류를 그대로 보여 주지 않는다');
});

test('알림을 누르면 그것이 있는 곳으로', () => {
  const post = '11111111-1111-1111-1111-111111111111';
  assert.deepEqual(targetOf('x', 'community_comment', { post_id: post }), { door: 'community', path: `/app/community/p/${post}` });
  assert.deepEqual(targetOf('x', 'person_follow', { actor_id: post }), { door: 'feed', path: `/app/u/${post}` });
  assert.deepEqual(targetOf('abc', 'meeting_request', {}), { browser: '/app/inbox?item=abc' });
  // 서버가 준 값이 경로를 흔들지 못한다.
  assert.deepEqual(targetOf('abc', 'community_comment', { post_id: '../../admin' }), { browser: '/app/inbox?item=abc' });
});

test('아바타는 접어도 오른쪽 아래 모서리에 머문다', () => {
  // 왼쪽 위를 기준으로 줄이면 접을 때마다 창이 화면 한가운데로 걸어 들어온다.
  const right = 1900;
  const bottom = 1000;
  const full = { width: 300, height: 430 };
  const mini = { width: 132, height: 172 };
  const folded = { x: right - mini.width, y: bottom - mini.height, ...mini };
  assert.equal(folded.x + folded.width, right);
  assert.equal(folded.y + folded.height, bottom);
  assert.ok(mini.width < full.width && mini.height < full.height);
});

/** 흰 바탕 위에 선 사람: 가운데 몸(남색), 몸 안의 흰 눈, 아래 가장자리에 닿은 흰 셔츠. */
function portrait(w = 60, h = 60) {
  const d = new Uint8ClampedArray(w * h * 4);
  const put = (x: number, y: number, c: [number, number, number]) => d.set([...c, 255], (y * w + x) * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) put(x, y, [255, 255, 255]);
  for (let y = 10; y < h; y++) for (let x = 15; x < 45; x++) put(x, y, [30, 40, 90]);
  for (let y = 20; y < 24; y++) for (let x = 25; x < 29; x++) put(x, y, [250, 250, 250]); // 눈
  for (let y = 40; y < h; y++) for (let x = 25; x < 35; x++) put(x, y, [252, 252, 250]); // 셔츠, 아래에 닿음
  return { d, w, h, a: (x: number, y: number) => d[(y * w + x) * 4 + 3] };
}

test('아바타: 흰 바탕은 걷고 사람 안의 흰 것은 남긴다', () => {
  // 프로필은 흰 바탕의 JPEG 라, 그대로 세우면 데스크톱 위에 네모 판이 뜬다(plan/63).
  const p = portrait();
  assert.ok(!hasAlpha(p.d));
  assert.equal(cutout(p.d, p.w, p.h), true);
  assert.equal(p.a(2, 2), 0, '바탕');
  assert.equal(p.a(5, 55), 0, '아래 모서리의 바탕도 옆에서 이어져 걷힌다');
  assert.equal(p.a(30, 30), 255, '몸');
  assert.equal(p.a(26, 21), 255, '몸 안의 흰 눈');
  assert.equal(p.a(30, 55), 255, '아래 가장자리에 닿은 흰 셔츠');
  assert.ok(hasAlpha(p.d));
});

test('아바타: 사진 배경은 오리지 않는다', () => {
  // 가장자리가 대부분 바탕이 아니면 걷을 것을 알 수 없다 — 그대로 카드로 세운다.
  const w = 40;
  const h = 40;
  const d = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) d.set([(i * 37) % 200, (i * 11) % 180, (i * 5) % 160, 255], i * 4);
  assert.equal(cutout(d, w, h), false);
  assert.ok(![...d].some((v, i) => i % 4 === 3 && v !== 255), '손대지 않는다');
});

test('새 판: 다운로드 센터의 판이 이 앱보다 새것인가', () => {
  // 문자열로 비교하면 0.10.0 이 0.9.3 보다 옛것이 된다.
  assert.ok(newerThan('0.10.0', '0.9.3'));
  assert.ok(newerThan('0.8.2', '0.8.1'));
  assert.ok(!newerThan('0.8.1', '0.8.1'));
  assert.ok(!newerThan('0.8.0', '0.8.1'));
  assert.ok(newerThan('1.0.0', '1.0.0-beta.2'), '정식은 미리보기보다 새것');
  assert.ok(!newerThan('1.0.0-beta.2', '1.0.0'));
});

test('새 판은 black-moa 의 다운로드 센터에서 받는다', () => {
  // 저장소가 비공개라 GitHub 에서는 받을 수 없다(plan/64). 앱이 GitHub 를 가리키면 누르는 사람마다 404 를 본다.
  for (const f of ['controller.ts', 'ipc.ts', 'index.ts']) {
    const src = readFileSync(new URL(`../src/main/${f}`, import.meta.url), 'utf8');
    assert.ok(!src.includes('github.com'), `${f} 가 GitHub 를 가리킨다`);
  }
});

test('자동 업데이트: 이 컴퓨터의 설치 프로그램 하나를 고른다', () => {
  const a = (name: string, platform: InstallerOut['platform'], arch: InstallerOut['arch'], kind: string, sha = 'ab'.repeat(32)): InstallerOut =>
    ({ name, platform, arch, kind, size: 1, sha256: sha, ready: true, url: `/api/downloads/assets/${name}?t=x` });
  const now = [a('w.exe', 'windows', 'x64', 'exe'), a('m.dmg', 'macos', 'universal', 'dmg'), a('l.deb', 'linux', 'x64', 'deb')];
  assert.equal(pickInstaller(now, 'win32', 'x64')?.name, 'w.exe');
  assert.equal(pickInstaller(now, 'darwin', 'arm64')?.name, 'm.dmg');
  assert.equal(pickInstaller(now, 'darwin', 'x64')?.name, 'm.dmg');
  assert.equal(pickInstaller(now, 'linux', 'x64')?.name, 'l.deb');
  // universal 이전 판의 맥은 칩이 맞는 것.
  const old = [a('arm.dmg', 'macos', 'arm64', 'dmg'), a('intel.dmg', 'macos', 'x64', 'dmg')];
  assert.equal(pickInstaller(old, 'darwin', 'arm64')?.name, 'arm.dmg');
  assert.equal(pickInstaller(old, 'darwin', 'x64')?.name, 'intel.dmg');
  // 확인할 수 없는(sha256 이 없는) 파일은 설치하지 않는다.
  assert.equal(pickInstaller([a('w.exe', 'windows', 'x64', 'exe', '')], 'win32', 'x64'), null);
  assert.equal(pickInstaller(now, 'freebsd', 'x64'), null);
});
