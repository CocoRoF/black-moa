"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Newspaper, PenLine } from "@/components/icons";
import { useT } from "@/lib/i18n";
import { Auth } from "@/lib/api";
import { DOOR_HOME, currentDoor, desktopHost, interceptLinks, routeFor, type Door } from "@/lib/desktop";
import { cn } from "@/lib/utils";
import { useAuth } from "@/stores/auth";
import { useMessenger } from "@/stores/messenger";
import { MessengerDock } from "@/components/messenger/MessengerDock";
import { useCommunityNav, useIsActive, type NavItem } from "./nav";
import { useShellLive } from "./useShellLive";

const FEED_TABS: NavItem[] = [
  { href: "/app/feed", key: "nav.feed", icon: <Newspaper /> },
  { href: "/app/blog", key: "app.my_posts", icon: <PenLine /> },
];

/** PC 앱 안의 웹 (plan/62).
 *
 *  아이콘 막대·제목 줄·알림·설정은 앱이 그린다. 여기는 한 문의 안쪽만: 사이드바도, 크레딧·종·테마가 있는
 *  머리줄도, 휴대폰 탭 막대도 없다. 소식과 커뮤니티에는 그 문 안의 자리를 오가는 얇은 탭 줄이 하나 있다.
 *
 *  이 뷰는 제 문 밖으로 나가지 않는다. 다른 문은 앱이 옮기고, 문 밖(설정·지식·스케줄…)은 브라우저가 연다.
 *  링크는 누르는 순간 가로채고(`interceptLinks`), 코드가 옮긴 경우(router.push)는 도착한 뒤 되돌린다. */
export function AppFrame({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const door = useMemo<Door>(() => currentDoor(), []);
  useShellLive({ inboxToasts: false });

  useEffect(() => interceptLinks(door), [door]);

  const lastInDoor = useRef<string>(DOOR_HOME[door]);
  useEffect(() => {
    const here = path + window.location.search;
    const r = routeFor(here, door);
    if (r.kind === "stay") { lastInDoor.current = here; return; }
    if (r.kind === "door") desktopHost()?.navigate?.(here);
    else if (r.kind === "browser") desktopHost()?.openInBrowser?.(here);
    router.replace(r.kind === "home" ? DOOR_HOME[door] : lastInDoor.current);
  }, [path, door, router]);

  // 앱이 시키는 일. 로그아웃도 여기서 한다 — 갱신 쿠키를 쥔 쪽이 웹 하나라서다(plan/46 §2).
  useEffect(() => {
    const off = desktopHost()?.onCommand?.((cmd, arg) => {
      if (cmd === "logout") {
        void (async () => {
          try { await Auth.logout(); } catch { /* 서버가 못 받아도 여기서는 나간다 */ }
          useAuth.getState().clear(); qc.clear(); router.replace("/login");
        })();
      } else if (cmd === "go" && arg && routeFor(arg, door).kind === "stay") {
        router.push(arg);
        window.setTimeout(() => window.dispatchEvent(new Event("blackmoa:resync")), 0);
      } else if (cmd === "shown") {
        // 앱이 이 문을 다시 보여 줬다. 그사이 빠른 대화·아바타가 보탠 말을 채운다.
        window.dispatchEvent(new Event("blackmoa:resync"));
        void qc.invalidateQueries({ queryKey: ["inbox"] });
      } else if (cmd === "messenger") {
        if (arg) useMessenger.getState().openRoom(arg); else useMessenger.getState().show();
      } else if (cmd === "refresh") {
        void qc.invalidateQueries();
      }
    });
    return typeof off === "function" ? off : undefined;
  }, [door, qc, router]);

  const communityNav = useCommunityNav();
  const tabs = door === "community" ? communityNav : door === "feed" ? FEED_TABS : null;
  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-bg">
      {tabs ? <DoorTabs items={tabs} /> : null}
      <main className="flex min-h-0 flex-1 flex-col">{children}</main>
      {/* 대화의 문에서는 메신저를 띄우지 않는다 — 대화 위에 또 대화 창이 된다. */}
      {door !== "chat" ? <MessengerDock pill={false} /> : null}
    </div>
  );
}

/** 문 안의 자리들. 앱의 탭 줄(Dex)처럼 얇게, 지금 자리는 아래 선 하나로. 오른쪽 끝은 메신저. */
function DoorTabs({ items }: { items: NavItem[] }) {
  const t = useT();
  const isActive = useIsActive();
  const unread = useMessenger((m) => m.unread);
  const show = useMessenger((m) => m.show);
  return (
    <nav className="flex h-10 shrink-0 items-stretch gap-0.5 border-b border-border bg-card px-2" aria-label="sections">
      <div className="flex min-w-0 flex-1 items-stretch gap-0.5 overflow-x-auto scroll-fade-x">
        {items.map((it) => {
          const on = isActive(it.href, it.exact);
          return (
            <Link key={it.href} href={it.href} aria-current={on ? "page" : undefined}
              className={cn("relative inline-flex shrink-0 items-center gap-1.5 px-2.5 text-[13px] font-medium transition-colors [&>svg]:h-4 [&>svg]:w-4",
                on ? "text-fg" : "text-muted-fg hover:text-fg")}>
              {it.icon}<span className="whitespace-nowrap">{t(it.key)}</span>
              {on ? <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-accent" /> : null}
            </Link>
          );
        })}
      </div>
      <button type="button" onClick={show} aria-label={t("msg.title")}
        className="my-1 inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-[13px] font-medium text-muted-fg hover:bg-muted hover:text-fg">
        <MessageSquare className="h-4 w-4" /><span className="hidden sm:inline">{t("msg.title")}</span>
        {unread ? <span className="min-w-[18px] rounded-full bg-accent px-1 text-center text-[10px] leading-[18px] text-accent-fg">{unread > 99 ? "99+" : unread}</span> : null}
      </button>
    </nav>
  );
}
