"use client";
import { useEffect, useRef } from "react";

declare global { interface Window { turnstile?: { render: (el: HTMLElement, o: Record<string, unknown>) => string; reset: (id: string) => void } } }

export function Turnstile({ siteKey, onToken }: { siteKey: string; onToken: (t: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let id: string | null = null;
    const render = () => { if (ref.current && window.turnstile && !id) id = window.turnstile.render(ref.current, { sitekey: siteKey, callback: onToken, theme: "auto" }); };
    if (window.turnstile) render();
    else {
      const s = document.createElement("script");
      s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"; s.async = true; s.onload = render;
      document.head.appendChild(s);
    }
  }, [siteKey, onToken]);
  return <div ref={ref} className="min-h-[65px]" />;
}
