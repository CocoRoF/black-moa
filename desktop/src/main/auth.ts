/**
 * 세션. **앱은 갱신하지 않는다.**
 *
 * 앱이 웹과 같은 갱신 쿠키로 따로 갱신하면 서버는 그것을 토큰 도난으로 보고
 * 세션 가족 전체를 끊는다. 운영 기록에 `refresh_reuse_detected` 로 남아 있고,
 * 증상은 "이유 없이 로그아웃" 하나뿐이라 알아채기도 어렵다.
 *
 * 그래서 갱신하는 쪽은 웹 하나다. 앱은 웹이 얻은 토큰을 받아 들고만 있는다.
 * 토큰은 메모리에만 산다.
 */
import { ipcMain } from 'electron';
import type { AuthState } from '@shared/contract';
import { appSession, parseJson, sendOnce, toError } from './api';

let token: string | null = null;
let restoring = true;
const listeners = new Set<(s: AuthState) => void>();

export const state = (): AuthState => ({ signedIn: !!token, restoring });

function announce(): void {
  const s = state();
  for (const fn of listeners) fn(s);
}

export function onChange(fn: (s: AuthState) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export const accessToken = (): string | null => token;

/** 웹이 알려 준다. 본창의 한 방향 다리가 유일한 입구다. */
export function listen(): void {
  ipcMain.on('host:token', (_e, value: string) => {
    if (typeof value !== 'string' || value.length < 20) return;
    const was = !!token;
    token = value;
    restoring = false;
    // 새 토큰이 왔다 = 웹이 방금 갱신 쿠키를 돌렸다. 바로 디스크에 내려쓴다. Electron 은 쿠키를 30초쯤 모았다가
    // 쓰므로, 그 사이에 앱이 죽으면 다음에 켤 때 이미 버린 쿠키를 내밀어 서버가 도난으로 보고 세션을 끊는다.
    // 문이 셋이라 갱신도 그만큼 잦다(plan/62).
    void appSession().cookies.flushStore().catch(() => {});
    if (!was) announce();
  });
  ipcMain.on('host:signout', () => {
    if (!token) return;
    token = null;
    restoring = false;
    announce();
  });
}

/**
 * 웹이 로그인 화면으로 갔다 — 세션이 없다는 뜻이다. 웹이 "나갔다" 를 알리지 않는 경우(처음부터 로그인이
 * 안 돼 있었거나, 다른 곳에서 끊겼다)에도 틀이 바로 알아채게 한다.
 */
export function forget(): void {
  const was = !!token || restoring;
  token = null;
  restoring = false;
  if (was) announce();
}

/**
 * 앱이 뜬 직후의 짧은 기다림.
 *
 * 웹이 아직 토큰을 받기 전이다. 그동안 로그인 안 된 것으로 단정하면 아바타가
 * 뜨자마자 죽는다. 그렇다고 영원히 기다릴 수도 없다.
 */
export function settle(afterMs = 12_000): void {
  setTimeout(() => {
    if (!token) {
      restoring = false;
      announce();
    }
  }, afterMs);
}

/**
 * 인증이 붙은 요청 한 번.
 *
 * 401 이면 **기다린다.** 갱신은 웹이 하고, 새 토큰은 다리로 들어온다.
 * 여기서 갱신하면 그 순간 다시 두 갱신자가 된다.
 */
export async function authed(method: string, path: string, body?: unknown, raw?: { data: Buffer; contentType: string }) {
  let r = await sendOnce(path, { method, body, raw, token });
  if (r.status === 401) {
    const fresh = await waitForNewToken();
    if (fresh) r = await sendOnce(path, { method, body, raw, token });
  }
  return r;
}

/** 웹이 새 토큰을 들고 올 때까지 잠깐. 안 오면 그대로 401 을 돌려준다. */
function waitForNewToken(timeoutMs = 8_000): Promise<boolean> {
  const before = token;
  return new Promise((resolve) => {
    const started = Date.now();
    const timer = setInterval(() => {
      if (token && token !== before) {
        clearInterval(timer);
        resolve(true);
      } else if (Date.now() - started > timeoutMs) {
        clearInterval(timer);
        resolve(false);
      }
    }, 250);
  });
}

export async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await authed(method, path, body);
  if (r.status >= 400) throw toError(r);
  return parseJson<T>(r);
}

/** 쓰는 곳이 남아 있어 남겨 두지만, 앱은 더는 갱신하지 않는다. */
export const refresh = async (): Promise<boolean> => false;

export { sendOnce as _sendOnce };
