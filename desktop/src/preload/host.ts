/**
 * 세 문의 웹 뷰에 얹는 다리 (plan/46 §2, plan/62 §4).
 *
 * **토큰은 한 방향이다.** 앱이 웹과 같은 갱신 쿠키로 따로 갱신하면, 서버는 그걸 토큰 도난으로 보고 세션
 * 가족 전체를 끊는다(운영 기록에서 `refresh_reuse_detected` 로 실제 확인했다). 갱신하는 쪽은 **웹 하나여야
 * 한다.** 그래서 앱은 웹이 얻은 토큰을 듣기만 하고, 읽어 가는 길은 내주지 않는다.
 *
 * 0.8 부터는 몇 가지를 더 안다: 이 뷰가 어느 문인지(`door`), 틀을 앱이 그린다는 것(`shell`), 다른 문이나
 * 브라우저로 보내 달라는 요청, 그리고 앱이 웹에게 시키는 일(로그아웃·메신저 열기…).
 */
import { contextBridge, ipcRenderer } from 'electron';

const arg = (name: string): string | undefined => {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : undefined;
};

const door = arg('blackmoa-door');
// 테마는 앱이 정한다. 뜰 때마다(새로고침 포함) 지금 값을 한 번 묻는다 — 웹이 물을 수 있는 것은 이것뿐이다.
const theme = ipcRenderer.sendSync('host:theme-now') === 'dark' ? 'dark' : 'light';
const shell = Number(arg('blackmoa-shell') ?? 0) || 0;
const okPath = (p: unknown): p is string => typeof p === 'string' && p.startsWith('/') && !p.startsWith('//') && p.length < 2048;

contextBridge.exposeInMainWorld('__blackmoaHost', {
  /** 이 앱 안에서 돌고 있다는 표시. 웹은 이것이 있을 때만 아래를 부른다. */
  desktop: true,
  /** 틀 세대. 2 이상이면 웹은 문 안쪽만 그린다. */
  shell,
  door: door === 'chat' || door === 'feed' || door === 'community' ? door : undefined,
  /** 뜰 때의 테마. 바뀌면 onCommand('theme', 'dark' | 'light') 로 온다. */
  theme,
  /** 웹이 토큰을 얻었다. 문자열 하나만 받는다. */
  token(value: unknown): void {
    if (typeof value === 'string' && value.length > 20) ipcRenderer.send('host:token', value);
  },
  /** 웹에서 나갔다. */
  signedOut(): void {
    ipcRenderer.send('host:signout');
  },
  /** 다른 문의 자리로. */
  navigate(path: unknown): void {
    if (okPath(path)) ipcRenderer.send('host:navigate', path);
  },
  /** 문 밖의 자리는 브라우저로. */
  openInBrowser(path: unknown): void {
    if (okPath(path)) ipcRenderer.send('host:open', path);
  },
  /** 앱이 시키는 일. 돌려주는 함수를 부르면 끊긴다. */
  onCommand(fn: (cmd: string, arg?: string) => void): () => void {
    const h = (_e: unknown, cmd: unknown, a: unknown) => {
      if (typeof cmd === 'string') fn(cmd, typeof a === 'string' ? a : undefined);
    };
    ipcRenderer.on('host:command', h);
    return () => ipcRenderer.removeListener('host:command', h);
  },
});
