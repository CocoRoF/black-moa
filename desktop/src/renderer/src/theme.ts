/**
 * 어두운 화면인지는 앱이 정해서 건넨다. 운영체제에 따라 Electron 의 테마가 prefers-color-scheme 에 닿지 않아서,
 * 미디어 쿼리 대신 <html class="dark"> 하나로 그린다.
 */
import { api } from './bridge';

const set = (dark: boolean) => {
  document.documentElement.classList.toggle('dark', dark);
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
};

try {
  set(api().dark);
  api().onTheme(set);
} catch {
  /* 다리가 없으면 밝게 */
}
