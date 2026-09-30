"use client";
import { useEffect } from "react";
import { RotateCcw } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/stores/auth";

const TEXT = {
  ko: { title: "문제가 생겼어요", body: "다시 시도해 주세요.", retry: "다시 시도" },
  en: { title: "Something went wrong", body: "Please try again.", retry: "Try again" },
};

/** What a client-side exception should look like.
 *
 *  Next.js has one behaviour for an uncaught render error and it is the whole app going
 *  white with "Application error: a client-side exception has occurred" — which is what a
 *  crash in one graph, one card, one list looked like to everyone who hit it. A segment
 *  boundary keeps the shell, keeps the navigation, and offers the one thing that usually
 *  works: render it again.
 */
export function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const locale = useAuth.getState().user?.locale === "en" ? "en" : "ko";
  const t = TEXT[locale];
  useEffect(() => { console.error("route error", error); }, [error]);
  return (
    <div className="flex min-h-[60vh] flex-1 items-center justify-center p-6">
      <div className="w-full max-w-md rounded-2xl border border-border bg-card p-6 text-center">
        <h1 className="text-base font-semibold">{t.title}</h1>
        <p className="mt-1.5 text-sm text-muted-fg">{t.body}</p>
        {error.digest ? <p className="mt-3 font-mono text-[11px] text-muted-fg">{error.digest}</p> : null}
        <Button className="mt-5" variant="accent" onClick={reset}><RotateCcw className="h-4 w-4" />{t.retry}</Button>
      </div>
    </div>
  );
}
