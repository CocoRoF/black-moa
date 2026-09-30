"use client";
/** PC 앱 안의 웹 (plan/62).
 *
 *  새 앱(0.8~)은 틀(아이콘 막대·제목 줄·설정·알림·아바타·빠른 대화)을 직접 그리고, 세 개의 문 —
 *  비서와 대화 · 소식 · 커뮤니티 — 의 **안쪽만** 웹에게 맡긴다. 문마다 웹 뷰가 하나씩 있고, 이 파일은
 *  그 뷰 안의 웹이 지키는 규칙이다: 같은 문 안은 그대로, 다른 문은 앱이 옮기고, 문 밖은 브라우저.
 *
 *  옛 앱(0.7 이하)은 `shell` 을 알리지 않으므로 여기 있는 것은 하나도 켜지지 않는다.
 */

export type Door = "chat" | "feed" | "community";

/** 앱이 `window.__memoraHost` 로 내놓는 것. 브라우저에는 없다. */
export interface DesktopHost {
  desktop?: boolean;
  /** 앱의 틀 세대. 2 부터 앱이 틀을 그리고 웹은 문 안쪽만 그린다. */
  shell?: number;
  /** 이 웹 뷰가 맡은 문. */
  door?: Door;
  /** 앱이 정한 테마. 바뀌면 onCommand("theme", "dark" | "light") 로 온다. */
  theme?: "dark" | "light";
  token?(v: string): void;
  signedOut?(): void;
  /** 다른 문으로 옮긴다(앱이 그 문의 뷰를 열고 그 주소로 보낸다). */
  navigate?(path: string): void;
  /** 문 밖의 자리는 브라우저가 연다. */
  openInBrowser?(path: string): void;
  /** 앱이 웹에게 시키는 일(로그아웃, 메신저 열기…). 돌려주는 함수로 끊는다. */
  onCommand?(fn: (cmd: string, arg?: string) => void): (() => void) | void;
}

export function desktopHost(): DesktopHost | null {
  try { return (window as unknown as { __memoraHost?: DesktopHost }).__memoraHost ?? null; } catch { return null; }
}

/** 앱이 틀을 그리고 있나. 서버에서 그릴 때는 늘 아니다. */
export function inAppShell(): boolean {
  if (typeof window === "undefined") return false;
  const h = desktopHost();
  return !!h?.desktop && (h.shell ?? 0) >= 2;
}

export const DOOR_HOME: Record<Door, string> = {
  chat: "/app/chat",
  feed: "/app/feed",
  community: "/app/community",
};

const starts = (p: string, base: string) => p === base || p.startsWith(base + "/");

/** 주소가 어느 문의 것인가. 로그인 쪽은 어느 뷰에서나 열린다("auth"). 문 밖이면 null. */
export function doorOf(path: string): Door | "auth" | null {
  const p = path.split(/[?#]/)[0] || "/";
  if (starts(p, "/app/chat") || starts(p, "/app/onboarding")) return "chat";
  // 소식의 문: 소식, 내가 쓴 글, 사람의 페이지(나도 사람이다).
  if (starts(p, "/app/feed") || starts(p, "/app/blog") || starts(p, "/app/u") || starts(p, "/app/me")) return "feed";
  if (starts(p, "/app/community")) return "community";
  if (["/login", "/signup", "/forgot-password", "/reset-password"].some((b) => starts(p, b))) return "auth";
  return null;
}

/** 이 뷰의 문. 앱이 알려 주지 않았으면 지금 주소로 짐작한다. */
export function currentDoor(): Door {
  const h = desktopHost();
  if (h?.door) return h.door;
  const d = doorOf(window.location.pathname);
  return d && d !== "auth" ? d : "chat";
}

export type Route = { kind: "stay" } | { kind: "door"; door: Door } | { kind: "browser" } | { kind: "home" };

/** 이 뷰에서 `path` 로 가려 할 때 할 일. `/app` 자체(웹의 비서 홈)는 이 문의 첫 화면으로 돌린다. */
export function routeFor(path: string, here: Door): Route {
  const p = path.split(/[?#]/)[0] || "/";
  if (p === "/app") return { kind: "home" };
  const d = doorOf(path);
  if (d === "auth" || d === here) return { kind: "stay" };
  if (d) return { kind: "door", door: d };
  return { kind: "browser" };
}

/** 링크를 누르는 순간 가로챈다. 문을 넘는 링크가 이 뷰 안에서 한 번 그려졌다가 튕기지 않게. */
export function interceptLinks(here: Door): () => void {
  const host = desktopHost();
  const onClick = (e: MouseEvent) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
    if (!a || a.hasAttribute("download")) return;
    let url: URL;
    try { url = new URL(a.href, window.location.href); } catch { return; }
    if (url.origin !== window.location.origin) return;          // 바깥 주소는 앱이 브라우저로 넘긴다
    const path = url.pathname + url.search + url.hash;
    const r = routeFor(path, here);
    if (r.kind === "stay" || r.kind === "home") return;
    e.preventDefault();
    e.stopPropagation();
    if (r.kind === "door") host?.navigate?.(path);
    else host?.openInBrowser?.(path);
  };
  document.addEventListener("click", onClick, true);
  return () => document.removeEventListener("click", onClick, true);
}
