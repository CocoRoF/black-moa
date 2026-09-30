/**
 * 계정의 실시간 흐름을 앱이 직접 듣는다 (plan/62 §5).
 *
 * 예전에는 30초마다 안 읽은 수를 물었다. 그러면 비서가 먼저 건넨 말이 최대 30초 늦게, 그것도 "새 메시지
 * 1개" 로만 왔다. 이제는 웹과 같은 `/api/notifications/stream` 을 듣는다: 말이 생기는 순간 그 말로 알린다.
 *
 * 끊기면 1초에서 30초까지 늘려 가며 다시 붙는다. 서버는 25초마다 빈 줄을 보내므로, 70초 동안 아무것도
 * 안 오면 끊긴 것으로 본다(노트북이 잠들었다 깨면 소켓이 조용히 죽어 있다).
 */
import { net } from 'electron';
import { ORIGIN } from '@shared/contract';
import { appSession } from './api';
import { createSseParser } from './stream';

export interface LiveHandlers {
  token: () => string | null;
  onEvent: (kind: string, data: Record<string, unknown>) => void;
  /** 붙었다(처음이든 다시든). 놓친 것은 여기서 다시 센다. */
  onOpen: () => void;
}

const QUIET_MS = 70_000;

export class Live {
  private req: Electron.ClientRequest | null = null;
  private timer: NodeJS.Timeout | null = null;
  private watchdog: NodeJS.Timeout | null = null;
  private attempt = 0;
  private running = false;

  constructor(private readonly h: LiveHandlers) {}

  start(): void {
    if (this.running) return;
    this.running = true;
    this.attempt = 0;
    this.connect();
  }

  stop(): void {
    this.running = false;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.drop();
  }

  /** 지금 붙어 있으면 끊고 바로 다시 붙는다(잠에서 깼을 때, 인터넷이 돌아왔을 때). */
  kick(): void {
    if (!this.running) return;
    this.drop();
    if (this.timer) clearTimeout(this.timer);
    this.attempt = 0;
    this.connect();
  }

  private drop(): void {
    if (this.watchdog) clearTimeout(this.watchdog);
    this.watchdog = null;
    const r = this.req;
    this.req = null;
    try {
      r?.abort();
    } catch {
      /* 이미 끝났다 */
    }
  }

  private retry(): void {
    this.drop();
    if (!this.running) return;
    const wait = Math.min(30_000, 1000 * 2 ** Math.min(this.attempt, 5));
    this.attempt += 1;
    this.timer = setTimeout(() => this.connect(), wait);
  }

  private feed(): void {
    if (this.watchdog) clearTimeout(this.watchdog);
    this.watchdog = setTimeout(() => this.retry(), QUIET_MS);
  }

  private connect(): void {
    this.timer = null;
    if (!this.running) return;
    const token = this.h.token();
    if (!token) {
      // 웹이 아직 토큰을 건네지 않았다. 잠깐 뒤에 다시 본다.
      this.timer = setTimeout(() => this.connect(), 1500);
      return;
    }
    const req = net.request({ method: 'GET', url: ORIGIN + '/api/notifications/stream', session: appSession(), useSessionCookies: true });
    this.req = req;
    req.setHeader('Accept', 'text/event-stream');
    req.setHeader('Authorization', `Bearer ${token}`);
    req.on('response', (res) => {
      if (this.req !== req) return;
      if ((res.statusCode ?? 0) >= 400) {
        // 401 은 토큰이 낡은 것이다. 갱신은 웹이 하므로(auth.ts) 여기서는 기다렸다가 새 토큰으로 붙는다.
        res.on('data', () => {});
        res.on('end', () => this.retry());
        return;
      }
      this.attempt = 0;
      this.feed();
      this.h.onOpen();
      const parser = createSseParser((b) => {
        if (!b.event || b.event === 'event') return;
        let data: Record<string, unknown> = {};
        try {
          data = b.data ? (JSON.parse(b.data) as Record<string, unknown>) : {};
        } catch {
          return;
        }
        try {
          this.h.onEvent(b.event, data);
        } catch {
          /* 받는 쪽 하나가 흐름 전체를 멈추지 않는다 */
        }
      });
      res.on('data', (c) => {
        this.feed();
        parser.push(Buffer.from(c).toString('utf8'));
      });
      res.on('end', () => {
        parser.end();
        if (this.req === req) this.retry();
      });
      res.on('error', () => {
        if (this.req === req) this.retry();
      });
    });
    req.on('error', () => {
      if (this.req === req) this.retry();
    });
    req.end();
  }
}
