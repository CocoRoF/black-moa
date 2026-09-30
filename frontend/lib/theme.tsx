"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { storageGet, storageSet } from "./utils";
import { desktopHost, inAppShell } from "./desktop";

export type ThemePref = "light" | "dark" | "system";
const KEY = "memora:theme";

/** Inline script (runs before hydration) — prevents FOUC.
 *
 *  PC 앱의 틀 안(plan/62)에서는 테마를 앱이 정해 다리(__memoraHost.theme)로 건넨다.
 *  같은 자리에서 `data-app-shell` 을 달아, 서버가 그린 머리줄·바닥글을 그리기 전에 CSS 로 숨긴다. */
export const THEME_INIT_SCRIPT = `(function(){try{var p=localStorage.getItem('${KEY}')||'system';var h=window.__memoraHost;if(h&&h.desktop&&h.shell>=2){p=h.theme==='dark'||h.theme==='light'?h.theme:'system';document.documentElement.setAttribute('data-app-shell','');}var d=p==='dark'||(p==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);var c=document.documentElement.classList;d?c.add('dark'):c.remove('dark');document.documentElement.style.colorScheme=d?'dark':'light';}catch(e){}})();`;

interface Ctx { pref: ThemePref; resolved: "light" | "dark"; setPref: (p: ThemePref) => void }
const ThemeCtx = createContext<Ctx>({ pref: "system", resolved: "light", setPref: () => {} });

function apply(pref: ThemePref): "light" | "dark" {
  const dark = pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
  return dark ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>("system");
  const [resolved, setResolved] = useState<"light" | "dark">("light");
  useEffect(() => {
    // PC 앱의 틀 안(plan/62)에서는 앱이 정한 테마를 쓰고, 바뀌면 앱이 알려 준다. 운영체제에 따라 앱의 테마가
    // prefers-color-scheme 에 닿지 않아서, 미디어 쿼리를 믿지 않고 앱이 건넨 값을 쓴다.
    if (inAppShell()) {
      const host = desktopHost();
      setResolved(apply(host?.theme ?? "system"));
      const off = host?.onCommand?.((cmd, arg) => { if (cmd === "theme" && (arg === "dark" || arg === "light")) setResolved(apply(arg)); });
      return typeof off === "function" ? off : undefined;
    }
    const p = (storageGet("local", KEY) as ThemePref | null) ?? "system";
    setPrefState(p);
    setResolved(apply(p));
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const h = () => { if ((storageGet("local", KEY) ?? "system") === "system") setResolved(apply("system")); };
    mq.addEventListener?.("change", h);
    return () => mq.removeEventListener?.("change", h);
  }, []);
  const setPref = useCallback((p: ThemePref) => { storageSet("local", KEY, p); setPrefState(p); setResolved(apply(p)); }, []);
  const v = useMemo(() => ({ pref, resolved, setPref }), [pref, resolved, setPref]);
  return <ThemeCtx.Provider value={v}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);

/** The class a portalled popover needs to keep the app's theme.
 *  A node under <body> sits outside the tree that carries `.dark`, so a component that
 *  portals (the calendar panel) has to be told which way it is dressed. */
/** 달력이 입을 테마. **OS 가 아니라 앱이 정한다.**
 *
 *  라이브러리는 `prefers-color-scheme` 을 따라가므로, 앱만 라이트로 바꿔 둔 사람의
 *  화면에서는 흰 바탕에 흰 글씨가 된다. 토큰 쪽에서도 이기게 해 두었지만(globals.css),
 *  이 클래스를 함께 주면 라이브러리 스스로도 같은 쪽을 본다. 테마를 바꾸면 이 값이
 *  다시 계산되도록 훅으로 둔다 — `panelTheme()` 는 한 번 읽고 마는 값이었다. */
export function useRcalTheme(): "rcal-dark" | "rcal-light" {
  return useTheme().resolved === "dark" ? "rcal-dark" : "rcal-light";
}

export function panelTheme(): string {
  if (typeof document === "undefined") return "";
  return document.documentElement.classList.contains("dark") ? "rcal-dark" : "rcal-light";
}
