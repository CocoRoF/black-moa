/**
 * 턴 스트림. **메인에서 돈다.**
 *
 * 렌더러에서 돌리면 창을 닫는 순간 답이 끊긴다. 여기서 돌면 창은 화면일 뿐이고,
 * 닫았다 열어도 하던 말은 이어진다. 서버가 `?after=<seq>` 로 재개를 받아 주므로
 * 놓친 조각도 다시 받아 올 수 있다.
 */
import { net } from 'electron';
import { randomUUID } from 'node:crypto';
import { ORIGIN, TERMINAL, type TurnEvent } from '@shared/contract';
import { ApiError, appSession, toError, type RawResponse } from './api';
import { accessToken, authed } from './auth';

/** SSE 본문을 이벤트 블록으로 가른다. 주석 줄(`: ping`)은 버린다. */
export function createSseParser(onBlock: (b: { event?: string; id?: string; data: string }) => void) {
  let buf = '';
  let data = '';
  let event: string | undefined;
  let id: string | undefined;
  let has = false;
  const flush = () => {
    if (has) onBlock({ event, id, data: data.replace(/\n$/, '') });
    data = '';
    event = undefined;
    id = undefined;
    has = false;
  };
  return {
    push(text: string) {
      buf += text;
      let i: number;
      while ((i = buf.indexOf('\n')) >= 0) {
        let line = buf.slice(0, i);
        buf = buf.slice(i + 1);
        if (line.endsWith('\r')) line = line.slice(0, -1);
        if (line === '') {
          flush();
          continue;
        }
        if (line.startsWith(':')) continue;
        const c = line.indexOf(':');
        const field = c === -1 ? line : line.slice(0, c);
        let value = c === -1 ? '' : line.slice(c + 1);
        if (value.startsWith(' ')) value = value.slice(1);
        if (field === 'data') {
          data += value + '\n';
          has = true;
        } else if (field === 'event') event = value;
        else if (field === 'id') id = value;
      }
    },
    end() {
      flush();
    },
  };
}

interface PumpOptions {
  method: 'POST' | 'GET';
  path: string;
  body?: unknown;
  onTurnId?: (id: string) => void;
  onEvent: (ev: TurnEvent) => void;
  signal: AbortSignal;
}

/**
 * 이만큼 아무것도 안 오면 흐름이 죽은 것으로 본다.
 *
 * 서버는 조용할 때도 15초마다 한 줄(": ping")을 보낸다. 노트북이 잠들었다 깨거나 와이파이가 바뀌면 소켓은 오류도
 * 없이 멈춰 있고, 그러면 빠른 대화는 영영 "생각하는 중" 이다. 그래서 25초 동안 한 바이트도 없으면 끊고, 받은 데까지
 * (after=seq)에서 다시 붙는다. 실시간 알림(live.ts)과 같은 방식이다.
 */
export const STALL_MS = 25_000;

/** 한 번 붙어서 끝까지 읽는다. 돌려주는 것은 마지막 seq 와 종결 여부. */
function pump(token: string | null, o: PumpOptions): Promise<{ lastSeq: number; terminal: boolean; status: number; errorBody: Buffer }> {
  return new Promise((resolve, reject) => {
    let settled = false;
    let idle: NodeJS.Timeout | null = null;
    const finish = (v: { lastSeq: number; terminal: boolean; status: number; errorBody: Buffer }) => {
      if (settled) return;
      settled = true;
      if (idle) clearTimeout(idle);
      resolve(v);
    };
    const fail = (e: unknown) => {
      if (settled) return;
      settled = true;
      if (idle) clearTimeout(idle);
      reject(e);
    };
    // 멈춘 흐름을 끊는다. 종결이 아닌 채로 끝나므로 부른 쪽이 받은 데부터 다시 붙는다.
    const watch = () => {
      if (idle) clearTimeout(idle);
      idle = setTimeout(() => {
        finish({ lastSeq, terminal, status: 200, errorBody: Buffer.alloc(0) });
        try {
          req.abort();
        } catch {
          /* 이미 끝났다 */
        }
      }, STALL_MS);
    };
    const req = net.request({
      method: o.method,
      url: ORIGIN + o.path,
      session: appSession(),
      useSessionCookies: true,
    });
    req.setHeader('Accept', 'text/event-stream');
    if (token) req.setHeader('Authorization', `Bearer ${token}`);
    let payload: Buffer | undefined;
    if (o.body !== undefined) {
      payload = Buffer.from(JSON.stringify(o.body));
      req.setHeader('Content-Type', 'application/json');
    }

    let lastSeq = 0;
    let terminal = false;
    req.on('response', (res) => {
      const status = res.statusCode ?? 0;
      if (status >= 400) {
        const bad: Buffer[] = [];
        res.on('data', (c) => bad.push(Buffer.from(c)));
        res.on('end', () => finish({ lastSeq, terminal, status, errorBody: Buffer.concat(bad) }));
        return;
      }
      const tid = res.headers['x-turn-id'];
      if (tid) o.onTurnId?.(Array.isArray(tid) ? tid[0] : String(tid));
      const parser = createSseParser((b) => {
        if (!b.data) return;
        let ev: TurnEvent | null = null;
        try {
          ev = JSON.parse(b.data) as TurnEvent;
        } catch {
          return;
        }
        if (!ev || typeof ev !== 'object') return;
        if (typeof ev.seq !== 'number' && b.id) ev.seq = Number.parseInt(b.id, 10) || 0;
        if (!ev.type && b.event) ev.type = b.event;
        if (ev.seq > lastSeq) lastSeq = ev.seq;
        if (TERMINAL.has(ev.type)) terminal = true;
        o.onEvent(ev);
      });
      res.on('data', (c) => {
        watch();
        parser.push(Buffer.from(c).toString('utf8'));
      });
      res.on('end', () => {
        parser.end();
        finish({ lastSeq, terminal, status, errorBody: Buffer.alloc(0) });
      });
      res.on('error', fail);
    });
    req.on('error', (e) => fail(e));
    watch();
    if (o.signal.aborted) req.abort();
    else o.signal.addEventListener('abort', () => req.abort(), { once: true });
    if (payload) req.write(payload);
    req.end();
  });
}

export interface RunHandle {
  runId: string;
  cancel(): void;
}

interface RunOptions {
  agentId: string;
  conversationId: string;
  text: string;
  /** 물음에 붙인 첨부(찍은 화면 등, plan/70). */
  uploadIds?: string[];
  onEvent: (ev: TurnEvent) => void;
  onDone: (ok: boolean, error?: string) => void;
}

const running = new Map<string, { ac: AbortController; turnId: string | null; agentId: string; conversationId: string }>();

/** [그만] 을 누른 뒤 멈췄다는 소식을 이만큼 기다린다(그래야 다른 화면과 같게 "멈춤" 으로 끝난다). */
const STOP_WAIT_MS = 5000;

/** 재접속 간격: 0.5초에서 8초까지 늘려 가며 여섯 번. */
const BACKOFF = [500, 1000, 2000, 4000, 8000, 8000];

export function run(o: RunOptions): RunHandle {
  const runId = randomUUID();
  const ac = new AbortController();
  const entry = { ac, turnId: null as string | null, agentId: o.agentId, conversationId: o.conversationId };
  running.set(runId, entry);

  const seen = new Set<number>();
  let lastSeq = 0;
  const onEvent = (ev: TurnEvent) => {
    // 재개하면 서버가 경계에서 한두 개를 다시 줄 수 있다. 같은 글자가 두 번 찍히면
    // 사용자는 모델이 이상해졌다고 생각한다.
    if (ev.seq) {
      if (seen.has(ev.seq)) return;
      seen.add(ev.seq);
      if (ev.seq > lastSeq) lastSeq = ev.seq;
    }
    o.onEvent(ev);
  };

  void (async () => {
    const token = () => accessToken();
    const start = `/api/agents/${o.agentId}/conversations/${o.conversationId}/turns`;
    const resume = () => `/api/agents/${o.agentId}/turns/${entry.turnId}/events?after=${lastSeq}`;
    try {
      let res = await pump(token(), {
        method: 'POST',
        path: start,
        // 같은 물음이 두 번 들어가지 않게(재시도·중복 전송), 그리고 웹이 이 턴을 알아보게(plan/69).
        body: { text: o.text, client_turn_id: randomUUID(), ...(o.uploadIds?.length ? { upload_ids: o.uploadIds } : {}) },
        onTurnId: (id) => (entry.turnId = id),
        onEvent,
        signal: ac.signal,
      });
      // 401 이면 여기서 갱신하지 않는다. 갱신하는 쪽은 웹 하나다(auth.ts).
      if (res.status >= 400) throw toError({ status: res.status, headers: {}, body: res.errorBody } as RawResponse);
      if (res.terminal || ac.signal.aborted) {
        o.onDone(true);
        return;
      }
      // 끝맺지 않고 끊겼다. 턴은 서버에서 아직 돌고 있다.
      for (const wait of BACKOFF) {
        if (ac.signal.aborted || !entry.turnId) break;
        await sleep(wait, ac.signal);
        if (ac.signal.aborted) break;
        try {
          const again = await pump(token(), { method: 'GET', path: resume(), onEvent, signal: ac.signal });
          if (again.status === 404) throw new ApiError(404, 'turn_not_found', '이어 받을 답을 서버가 더는 들고 있지 않아요.');
          if (again.terminal || ac.signal.aborted) {
            o.onDone(true);
            return;
          }
        } catch (e) {
          if (e instanceof ApiError && e.status === 404) throw e;
          // 그 밖의 실패는 다음 차례에 다시 시도한다
        }
      }
      o.onDone(false, '답이 끊겼어요. 대화를 다시 열면 이어서 볼 수 있어요.');
    } catch (e) {
      if (ac.signal.aborted) o.onDone(true);
      else o.onDone(false, e instanceof Error ? e.message : '답을 받지 못했어요.');
    } finally {
      running.delete(runId);
    }
  })();

  return { runId, cancel: () => cancel(runId) };
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(t);
        resolve();
      },
      { once: true },
    );
  });
}

/**
 * [그만]: 서버에 멈추라고 하고, 멈췄다는 소식이 흐름으로 올 때까지 잠깐 기다린다(plan/69) — 웹과 다른 화면도 같은
 * 소식을 받는다. 턴 번호를 알면 그 턴을, 아직 모르면(막 시작했다) 그 대화에서 흐르는 답을 멈춘다.
 */
export function cancel(runId: string): void {
  const e = running.get(runId);
  if (!e) return;
  void (async () => {
    try {
      if (e.turnId) await authed('POST', `/api/agents/${e.agentId}/turns/${e.turnId}/cancel`);
      else await authed('POST', `/api/agents/${e.agentId}/conversations/${e.conversationId}/cancel`);
    } catch {
      /* 못 알려도 아래에서 이쪽은 멈춘다 */
    }
  })();
  setTimeout(() => {
    if (running.get(runId) === e) detach(runId);
  }, STOP_WAIT_MS);
}

/** 이쪽에서만 놓는다. 서버의 답은 계속되고 저장된다 — 웹에서 이어 볼 수 있다. */
export function detach(runId: string): void {
  const e = running.get(runId);
  if (!e) return;
  e.ac.abort();
  running.delete(runId);
}

/** 앱을 끝낼 때: 흐르던 답은 서버에서 끝까지 가 저장된다(웹에서 본다). 이쪽 연결만 닫는다. */
export function cancelAll(): void {
  for (const id of [...running.keys()]) detach(id);
}
