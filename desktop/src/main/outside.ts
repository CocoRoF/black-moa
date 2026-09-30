import { shell } from 'electron';

/**
 * 우리 도메인 밖은 브라우저가 연다.
 *
 * http(s) 만 넘긴다. `file:` 이나 그 밖의 스킴을 그대로 셸에 넘기는 것은 링크
 * 한 줄로 아무 프로그램이나 여는 길을 내주는 것과 같다.
 */
export async function openOutside(url: string): Promise<void> {
  try {
    const u = new URL(url);
    if (u.protocol === 'http:' || u.protocol === 'https:') await shell.openExternal(url);
  } catch {
    /* 주소가 아니면 아무것도 하지 않는다 */
  }
}
