/**
 * 서버로 나가는 모든 요청이 지나는 한 군데.
 *
 * 렌더러에서 직접 `fetch` 하지 않는 이유가 세 가지다. 토큰이 렌더러로 내려가지 않고,
 * 갱신 쿠키가 한 세션에 모이고, CORS 라는 것이 아예 생기지 않는다.
 */
import { net, session, type Session } from 'electron';
import { ORIGIN } from '@shared/contract';

export const PARTITION = 'persist:blackmoa';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function appSession(): Session {
  return session.fromPartition(PARTITION);
}

interface RawOptions {
  method?: string;
  body?: unknown;
  /** 직접 넘기는 바이트. 파일 올리기처럼 JSON 이 아닌 몸통. */
  raw?: { data: Buffer; contentType: string };
  token?: string | null;
  accept?: string;
  signal?: AbortSignal;
}

export interface RawResponse {
  status: number;
  headers: Record<string, string>;
  body: Buffer;
}

/** 한 번 보낸다. 갱신도 재시도도 하지 않는다. 그건 위층 일이다. */
export function sendOnce(path: string, o: RawOptions = {}): Promise<RawResponse> {
  return new Promise((resolve, reject) => {
    const req = net.request({
      method: o.method ?? 'GET',
      url: path.startsWith('http') ? path : ORIGIN + path,
      session: appSession(),
      useSessionCookies: true,
      redirect: 'follow',
    });
    req.setHeader('Accept', o.accept ?? 'application/json');
    if (o.token) req.setHeader('Authorization', `Bearer ${o.token}`);

    let payload: Buffer | undefined;
    if (o.raw) {
      payload = o.raw.data;
      req.setHeader('Content-Type', o.raw.contentType);
    } else if (o.body !== undefined) {
      payload = Buffer.from(JSON.stringify(o.body));
      req.setHeader('Content-Type', 'application/json');
    }

    const chunks: Buffer[] = [];
    req.on('response', (res) => {
      res.on('data', (c) => chunks.push(Buffer.from(c)));
      res.on('end', () => {
        const headers: Record<string, string> = {};
        for (const [k, v] of Object.entries(res.headers)) headers[k.toLowerCase()] = Array.isArray(v) ? v.join(', ') : String(v);
        resolve({ status: res.statusCode ?? 0, headers, body: Buffer.concat(chunks) });
      });
      res.on('error', reject);
    });
    req.on('error', (e) => reject(new ApiError(0, 'network', networkMessage(e))));
    if (o.signal) {
      if (o.signal.aborted) req.abort();
      else o.signal.addEventListener('abort', () => req.abort(), { once: true });
    }
    if (payload) req.write(payload);
    req.end();
  });
}

/** 끊긴 이유를 사람 말로. 영문 errno 를 그대로 보여 주면 아무도 못 읽는다. */
function networkMessage(e: unknown): string {
  const s = e instanceof Error ? e.message : String(e);
  if (/ENOTFOUND|EAI_AGAIN|ERR_NAME_NOT_RESOLVED/i.test(s)) return '서버 주소를 찾지 못했어요. 인터넷 연결을 확인해 주세요.';
  if (/ECONNREFUSED|ERR_CONNECTION_REFUSED/i.test(s)) return '서버가 응답하지 않아요. 잠시 뒤에 다시 시도해 주세요.';
  if (/ETIMEDOUT|ERR_TIMED_OUT/i.test(s)) return '서버가 제때 답하지 않았어요.';
  if (/ERR_INTERNET_DISCONNECTED/i.test(s)) return '인터넷이 끊겨 있어요.';
  return '서버에 닿지 못했어요.';
}

/** 서버가 준 오류 봉투를 푼다. 한국어 문장이 들어 있으면 그것을 그대로 쓴다. */
export function toError(r: RawResponse): ApiError {
  let code = `http_${r.status}`;
  let message = '';
  let detail: unknown;
  try {
    const j = JSON.parse(r.body.toString('utf8')) as { error?: { code?: string; message?: string; detail?: unknown } };
    if (j?.error) {
      code = j.error.code ?? code;
      message = j.error.message ?? '';
      detail = j.error.detail;
    }
  } catch {
    /* 본문이 JSON 이 아닐 수 있다 */
  }
  if (r.status === 401) code = code.startsWith('http_') ? 'unauthorized' : code;
  if (r.status === 429) code = code.startsWith('http_') ? 'rate_limited' : code;
  if (!message || !/[가-힣]/.test(message)) message = friendly(r.status, code);
  return new ApiError(r.status, code, message, detail);
}

function friendly(status: number, code: string): string {
  if (code === 'stt_disabled') return '지금은 말로 물을 수 없어요.';
  if (code === 'tts_disabled') return '지금은 소리로 들을 수 없어요.';
  if (code === 'rate_limited' || status === 429) return '조금 빠르게 요청하셨어요. 잠시 뒤에 다시 시도해 주세요.';
  if (status === 401) return '로그인이 필요해요.';
  if (status === 403) return '이 작업을 할 수 있는 권한이 없어요.';
  if (status === 404) return '찾는 것이 없어요.';
  if (status === 422) return '입력한 내용을 다시 확인해 주세요.';
  if (status >= 500) return '서버에 문제가 생겼어요. 잠시 뒤에 다시 시도해 주세요.';
  return '요청을 처리하지 못했어요.';
}

export function parseJson<T>(r: RawResponse): T {
  const text = r.body.toString('utf8');
  if (!text) return null as T;
  return JSON.parse(text) as T;
}
