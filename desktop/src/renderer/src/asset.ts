import { ORIGIN } from '@shared/contract';

/**
 * 서버가 주는 사진 주소는 `/presets/...` 처럼 앞이 잘려 있다.
 *
 * 브라우저에서는 그게 곧 memo-ora.com 이지만, 앱의 창은 `file://` 위에 서 있어서
 * 그대로 두면 아무것도 안 뜬다. 앞을 붙여 준다.
 */
export function asset(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (/^(https?:|data:|blob:)/.test(url)) return url;
  return ORIGIN + (url.startsWith('/') ? url : `/${url}`);
}
