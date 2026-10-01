"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellRing, BookOpen, Bot, CalendarDays, ChevronDown, ChevronLeft, ChevronRight, CircleDollarSign, Cloud, HardDrive, History, Home, Inbox, LogOut, Mail, Menu, MessageSquare, MessagesSquare, MonitorDown, Moon, Network, Newspaper, PenLine, Settings, ShieldAlert, ShieldCheck, Sun, UserRound, X } from "@/components/icons";
import { LocaleProvider, useLocale, useT, type Locale } from "@/lib/i18n";
import { useRequireAuth } from "@/lib/hooks";
import { Auth, Credits, Inbox as InboxApi, Users, type InboxItem } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { useUI } from "@/stores/ui";
import { inAppShell } from "@/lib/desktop";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { fmtCredits, fmtRelative } from "@/lib/format";
import { Avatar } from "@/components/ui/misc";
import { Button, buttonLook } from "@/components/ui/button";
import { Sheet } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/skeleton";
import { Logo, LogoMark } from "@/components/brand/Logo";
import { MessengerDock } from "@/components/messenger/MessengerDock";
import { useMessenger } from "@/stores/messenger";
import { inboxTitle } from "./inboxUtil";
import { useShellLive } from "./useShellLive";
import { COMMUNITY_NAV, useCommunityNav, useIsActive, type NavItem } from "./nav";
import { AppFrame } from "./AppFrame";
import { TermsGate } from "./TermsGate";

export { COMMUNITY_NAV, useIsActive };

/** A tab in the phone's bottom bar. `match` is for the tabs whose section is wider
 *  than one path (a chat is any /app/chat/*, a feed is a board or a post). */
interface MobileTab {
  href: string; key: string; icon: ReactNode; exact?: boolean; match?: (p: string) => boolean; badge?: number;
  /** A tab that opens something here instead of going somewhere. */
  act?: () => void;
}
interface NavGroup { group: string; key: string; items: NavItem[] }
type NavEntry = NavItem | NavGroup;

/** Two products under one account: the secretary console and the community. The rail's top
 *  switches between them and lands on the other side's home — a section switch, not a page
 *  jump into whatever page you happened to be on. */
export const SECTIONS = [
  { key: "sec.console", home: "/app", match: (p: string) => !p.startsWith("/app/community") },
  { key: "sec.community", home: "/app/community", match: (p: string) => p.startsWith("/app/community") },
] as const;


/** The console's own navigation.
 *
 *  Twelve flat links made every destination shout equally loudly. What is left here is the
 *  work: home, and the three questions the rest of the app answers — the secretaries, what
 *  they know about me, and the account behind both. */
const NAV: NavEntry[] = [
  { href: "/app/feed", key: "nav.feed", icon: <Newspaper /> },
  { href: "/app", key: "nav.home", icon: <Home />, exact: true },
  { group: "agents", key: "navg.agents", items: [
    { href: "/app/chat", key: "nav.chat", icon: <MessageSquare /> },
    { href: "/app/agents", key: "nav.agents", icon: <Bot /> },
    { href: "/app/conversations", key: "nav.conversations", icon: <History /> },
  ] },
  { group: "me", key: "navg.me", items: [
    { href: "/app/profile", key: "nav.profile", icon: <UserRound /> },
    // 연락 가능 시간과 일정 — 내 것이고, 비서는 그것을 쓴다 (plan/56).
    { href: "/app/schedule", key: "nav.schedule", icon: <CalendarDays /> },
    { href: "/app/mail", key: "nav.mail", icon: <Mail /> },
    { href: "/app/blog", key: "nav.blog", icon: <PenLine /> },
    { href: "/app/knowledge", key: "nav.knowledge", icon: <BookOpen /> },
    // 지식과 비서들이 받은 파일이 함께 쓰는 한 저장 공간, 그리고 그 파일들 (plan/55 §3-3).
    { href: "/app/files", key: "nav.files", icon: <HardDrive /> },
    { href: "/app/network", key: "nav.network", icon: <Network /> },
  ] },
  { group: "settings", key: "navg.settings", items: [
    // 인증과 바깥 서비스 연결은 한 곳 — 연결은 이 계정에 잇는 일이라 관리 쪽이고, 가져온 것은 [내 정보]로 간다 (plan/49·81).
    { href: "/app/account", key: "nav.account", icon: <ShieldCheck /> },
    // black-moa 의 파일 시스템(파일·지식이 쓰는 공간)을 돌보는 곳 — 쓰는 곳은 [내 정보 → 파일] (plan/78).
    { href: "/app/cloud", key: "nav.cloud", icon: <Cloud /> },
    { href: "/app/credits", key: "nav.credits", icon: <CircleDollarSign /> },
    { href: "/app/notifications", key: "nav.notifications", icon: <BellRing /> },
    { href: "/app/settings", key: "nav.settings", icon: <Settings /> },
  ] },
];

/** Pinned to the foot of the rail, above the profile.
 *
 *  Neither is somewhere you go to work. The inbox is a tray you check, and the console is
 *  a door most people never open — parking them by the account they belong to keeps the
 *  top of the list about the job at hand. */
const NAV_FOOT: NavItem[] = [
  { href: "/app/inbox", key: "nav.inbox", icon: <Inbox /> },
];
const DOWNLOADS: NavItem = { href: "/app/downloads", key: "nav.downloads", icon: <MonitorDown /> };

const isGroup = (e: NavEntry): e is NavGroup => "group" in e;
const leaves = (entries: NavEntry[]): NavItem[] => entries.flatMap((e) => (isGroup(e) ? e.items : [e]));


export function OwnerShell({ children }: { children: ReactNode }) {
  const { ok, user } = useRequireAuth();
  const [locale, setLocale] = useState<Locale>("ko");
  useEffect(() => { if (user?.locale) setLocale(user.locale); }, [user?.locale]);
  if (!ok || !user) return <div className="flex h-dvh items-center justify-center"><Spinner /></div>;
  // PC 앱의 틀 안(plan/62)이면 틀은 앱이 그린다. 여기서는 문 안쪽만.
  return <LocaleProvider locale={locale} setLocale={setLocale}>{inAppShell() ? <AppFrame>{children}</AppFrame> : <ShellInner>{children}</ShellInner>}<TermsGate /></LocaleProvider>;
}

function ShellInner({ children }: { children: ReactNode }) {
  const t = useT();
  const path = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const user = useAuth((s) => s.user)!;
  const { sidebarCollapsed, toggleSidebar, hydrate } = useUI();
  const { resolved, setPref } = useTheme();
  const [moreOpen, setMoreOpen] = useState(false);
  const isActive = useIsActive();
  const communityNav = useCommunityNav();
  const inCommunity = path.startsWith("/app/community");
  // One group open at a time, and it follows where you are: arriving at a page inside a
  // closed group opens it rather than leaving the sidebar disagreeing with the screen.
  const groupOfPath = useMemo(() => {
    const hit = NAV.find((e) => isGroup(e) && e.items.some((i) => path === i.href || path.startsWith(i.href + "/")));
    return hit && isGroup(hit) ? hit.group : null;
  }, [path]);
  const [openGroup, setOpenGroup] = useState<string | null>(groupOfPath);
  useEffect(() => { if (groupOfPath) setOpenGroup(groupOfPath); }, [groupOfPath]);
  useEffect(() => { hydrate(); }, [hydrate]);
  const { data: bal } = useQuery({ queryKey: ["credits", "balance"], queryFn: Credits.balance, staleTime: 30_000, refetchInterval: 60_000 });
  // The bell wants the most recent items whatever their state — new_count is counted
  // server-side over all of them, so the badge stays right without a second request.
  const { data: inbox } = useQuery({ queryKey: ["inbox", "recent"], queryFn: () => InboxApi.list({ limit: 8 }), staleTime: 30_000, refetchInterval: 60_000 });
  useShellLive({ inboxToasts: true });
  const chatHref = "/app/chat";
  const msgUnread = useMessenger((m) => m.unread);
  const msgOpen = useMessenger((m) => m.open);
  const showMessenger = useMessenger((m) => m.show);
  // Only the dedicated chat surface goes immersive. The simulator is a tab inside the agent
  // area, so it keeps the shell header and the tab bar — otherwise that one tab sits 57px
  // higher than its neighbours.
  const isChat = path.startsWith("/app/chat");
  const logout = async () => { try { await Auth.logout(); } catch { /* ignore */ } useAuth.getState().clear(); qc.clear(); router.replace("/login"); };
  const setLocale = useMemo(() => async (l: Locale) => { const u = await Users.patchMe({ locale: l }); useAuth.getState().setUser(u); }, []);

  // The phone's tab bar. The community used to have no entry point on a phone at all —
  // not a tab, not a line in the sheet — so half the product was reachable only by typing
  // the URL. It gets a permanent slot here, the way the desktop rail always shows both
  // sections; the agent list moves into the sheet, where it already lives under 비서관리
  // and is one tap from the home screen's own card.
  const consoleTabs: MobileTab[] = [
    { href: "/app", key: "nav.home", icon: <LogoMark size={24} muted={path !== "/app"} className="ring-0" />, exact: true },
    // The people I chose come first, then my own secretary, then the square.
    { href: "/app/feed", key: "nav.feed", icon: <Newspaper />, match: (p: string) => p.startsWith("/app/feed") },
    // 메신저 (plan/44 §7). A phone has no free corner for a dock, so the tab that used to
    // walk to the chat page opens the messenger over whatever is on screen.
    { href: chatHref, key: "msg.title", icon: <MessageSquare />, badge: msgUnread || undefined,
      match: () => msgOpen, act: () => showMessenger() },
    { href: "/app/community", key: "sec.community", icon: <MessagesSquare />, match: (p: string) => p.startsWith("/app/community") },
    { href: "/app/inbox", key: "nav.inbox", icon: <Inbox />, badge: inbox?.new_count },
  ];
  // Deliberately the same five wherever you are (chat aside, which takes the whole
  // screen). A bar that rearranges itself when you cross into the community means the
  // control you just used is somewhere else a tap later; the community's own
  // destinations live one tap deeper, in the sheet.
  const mobileTabs = consoleTabs;

  return (
    <div className="flex h-dvh overflow-hidden bg-bg">
      {/* desktop sidebar */}
      <aside className={cn("hidden md:flex md:flex-col border-r border-border bg-card transition-[width] duration-200 shrink-0", sidebarCollapsed ? "w-16" : "w-60")}>
        <div className={cn("flex h-14 items-center border-b border-border px-3", sidebarCollapsed ? "justify-center" : "justify-between")}>
          {sidebarCollapsed ? (
            // Collapsed, the mark IS the control: hovering swaps it for the expand arrow,
            // so the rail keeps one 40px target instead of stacking a second button under
            // the logo and growing taller than the header beside it.
            <button type="button" onClick={toggleSidebar} aria-label={t("nav.expand_sidebar")}
              className="group relative inline-flex h-10 w-10 items-center justify-center rounded-xl hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring">
              <LogoMark size={30} className="transition-opacity duration-150 group-hover:opacity-0" />
              <ChevronRight className="absolute h-5 w-5 text-fg opacity-0 transition-opacity duration-150 group-hover:opacity-100" />
            </button>
          ) : (
            <>
              <Logo href="/app" size={26} />
              <Button variant="ghost" size="icon-sm" onClick={toggleSidebar} aria-label={t("nav.collapse_sidebar")}><ChevronLeft className="h-4 w-4" /></Button>
            </>
          )}
        </div>
        {/* Section switcher. Collapsed, the rail has no room for two labels, so the icons
            below already say which side you are on. */}
        {!sidebarCollapsed ? (
          <div className="mx-2 mt-2 grid grid-cols-2 gap-0.5 rounded-xl bg-muted p-1">
            {SECTIONS.map((sec) => {
              const on = sec.match(path);
              return (
                <Link key={sec.key} href={sec.home}
                  className={cn("rounded-lg px-2 py-1.5 text-center text-[13px] font-medium transition-colors",
                    on ? "bg-card text-fg shadow-sm" : "text-muted-fg hover:text-fg")}>
                  {t(sec.key)}
                </Link>
              );
            })}
          </div>
        ) : null}
        {/* Two zones. The top one scrolls when the groups are open; the foot is pinned, so
            the inbox and the console stay put next to the account they belong to instead
            of drifting up under the last item. */}
        <nav className="flex min-h-0 flex-1 flex-col" aria-label={t(inCommunity ? "sec.community" : "sec.console")}>
          <div className="flex-1 overflow-y-auto scrollbar-thin p-2 space-y-0.5">
            {/* Collapsed, there is no room for a heading, so the rail flattens: every
                destination stays one click away instead of two. */}
            {(inCommunity ? communityNav : sidebarCollapsed ? leaves(NAV) : NAV).map((entry) => (
              isGroup(entry)
                ? <NavGroupRow key={entry.group} group={entry} open={openGroup === entry.group}
                               onToggle={() => setOpenGroup(openGroup === entry.group ? null : entry.group)}
                               isActive={isActive} inboxCount={inbox?.new_count ?? 0} />
                : <NavLink key={entry.href} item={entry} collapsed={sidebarCollapsed} isActive={isActive} />
            ))}
          </div>
          {!inCommunity ? (
            <div className="shrink-0 p-2 pt-1 space-y-0.5">
              {NAV_FOOT.map((n) => (
                <NavLink key={n.href} item={n} collapsed={sidebarCollapsed} isActive={isActive}
                         badge={n.key === "nav.inbox" ? inbox?.new_count : undefined} />
              ))}
              {user.role === "admin" ? (
                <NavLink item={{ href: "/admin", key: "nav.admin", icon: <ShieldCheck /> }} collapsed={sidebarCollapsed} isActive={isActive} />
              ) : null}
              {/* PC 앱 받기 (plan/64). 쓰러 오는 곳이 아니라 한 번 들르는 곳이라 발치에 둔다. */}
              <NavLink item={DOWNLOADS} collapsed={sidebarCollapsed} isActive={isActive} />
            </div>
          ) : null}
        </nav>
        {/* A face and a name at the foot of a rail is a profile link in every product that
            has one; here it did nothing. */}
        <div className={cn("border-t border-border p-3 flex items-center gap-2", sidebarCollapsed && "justify-center")}>
          <Link href="/app/me" className={cn("flex min-w-0 items-center gap-2 rounded-lg hover:opacity-90", sidebarCollapsed ? "" : "flex-1")}>
            <Avatar name={user.display_name} src={user.avatar_url} size={32} />
            {!sidebarCollapsed ? <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{user.display_name}</span><span className="block truncate text-xs text-muted-fg">{user.email}</span></span> : null}
          </Link>
          {!sidebarCollapsed ? <Button variant="ghost" size="icon-sm" onClick={logout} aria-label={t("auth.logout")}><LogOut className="h-4 w-4" /></Button> : null}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* `relative z-30` is load-bearing: backdrop-blur makes this header its own stacking
            context, and with no z-index it painted at the same level as <main> but *earlier*
            in the tree — so the notification panel that drops out of it rendered underneath
            the page, most visibly behind 커뮤니티's 인기글 column. */}
        <header className={cn("safe-pt relative z-30 shrink-0 bg-card/90 backdrop-blur", isChat && "hidden md:block")}>
          {/* The border belongs to the 14-height row, not to the wrapper: on the wrapper it
              added a 57th pixel that the sidebar's own h-14 border-b row did not have, and
              the two tops sat one pixel apart. */}
          <div className="flex h-14 items-center gap-2 border-b border-border px-3 md:px-5">
            <div className="md:hidden"><Logo href="/app" size={28} /></div>
            <div className="flex-1" />
            <Link href="/app/credits" className={cn("inline-flex h-9 items-center gap-1.5 rounded-full border px-3 text-xs font-medium tabular-nums", bal?.low ? "border-warning/50 bg-warning/10 text-warning" : "border-border bg-card")}>
              <CircleDollarSign className="h-3.5 w-3.5" />{bal ? fmtCredits(bal.balance) : "…"}<span className="hidden sm:inline text-muted-fg font-normal">{t("credits.unit")}</span>
            </Link>
            <NotificationBell count={inbox?.new_count ?? 0} items={inbox?.items ?? []} />
            <Button variant="ghost" size="icon" className="hidden md:inline-flex" onClick={() => setPref(resolved === "dark" ? "light" : "dark")} aria-label={t("common.toggle_theme")}>{resolved === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}</Button>
            <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setMoreOpen(true)} aria-label={t("nav.more")}><Menu className="h-5 w-5" /></Button>
          </div>
        </header>

        {!isChat ? <VerifyBanner /> : null}
        <main className={cn("flex min-h-0 flex-1 flex-col", !isChat && "pb-16 md:pb-0")}>{children}</main>

        {/* mobile tab bar */}
        {!isChat ? (
          <nav className="md:hidden fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card/95 backdrop-blur safe-pb" aria-label="primary">
            <div className="grid grid-cols-6">
              {mobileTabs.map((tb) => {
                const active = tb.match ? tb.match(path) : isActive(tb.href, tb.exact);
                return tb.act ? (
                    <button key={tb.key} type="button" onClick={tb.act} aria-current={active ? "page" : undefined}
                            className={cn("relative flex h-14 flex-col items-center justify-center gap-0.5 px-0.5 text-[10px] [&>svg]:h-5 [&>svg]:w-5", active ? "text-accent" : "text-muted-fg")}>
                      {tb.icon}<span className="w-full truncate text-center">{t(tb.key)}</span>
                      {tb.badge ? <span className="absolute right-[22%] top-2 min-w-[14px] rounded-full bg-accent px-1 text-center text-[9px] leading-[14px] text-accent-fg">{tb.badge}</span> : null}
                    </button>
                ) : (
                  <Link key={tb.key} href={tb.href} aria-current={active ? "page" : undefined} className={cn("relative flex h-14 flex-col items-center justify-center gap-0.5 px-0.5 text-[10px] [&>svg]:h-5 [&>svg]:w-5", active ? "text-accent" : "text-muted-fg")}>
                    {tb.icon}<span className="w-full truncate text-center">{t(tb.key)}</span>
                    {tb.badge ? <span className="absolute right-[22%] top-2 min-w-[14px] rounded-full bg-accent px-1 text-center text-[9px] leading-[14px] text-accent-fg">{tb.badge}</span> : null}
                  </Link>
                );
              })}
              <button type="button" onClick={() => setMoreOpen(true)} className={cn("flex h-14 flex-col items-center justify-center gap-0.5 text-[10px] [&>svg]:h-5 [&>svg]:w-5", moreOpen ? "text-accent" : "text-muted-fg")}><Menu /><span className="w-full truncate text-center">{t("nav.more")}</span></button>
            </div>
          </nav>
        ) : null}
      </div>

      {/* 메신저 (plan/44 §7). It lives in the shell so it is on every screen: a room can be
          read without leaving the page you were on. The full-screen chat is the one place
          it stays out of, because there it would be a window over a window. */}
      {!isChat ? <MessengerDock /> : null}

      <Sheet open={moreOpen} onClose={() => setMoreOpen(false)} title={t("nav.more")}>
        <div className="flex items-center gap-3 pb-3">
          <Link href="/app/me" onClick={() => setMoreOpen(false)} className="flex min-w-0 flex-1 items-center gap-3 rounded-lg hover:opacity-90">
            <Avatar name={user.display_name} src={user.avatar_url} size={40} />
            <span className="min-w-0 flex-1"><span className="block truncate font-medium">{user.display_name}</span><span className="block truncate text-xs text-muted-fg">{user.email}</span></span>
          </Link>
          <Button variant="ghost" size="icon-sm" onClick={() => setPref(resolved === "dark" ? "light" : "dark")} aria-label={t("common.toggle_theme")}>{resolved === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</Button>
        </div>
        {/* No section switcher here. The tab bar already crosses between 홈 and 커뮤니티
            on every screen, so a second control for the same move is one more thing to
            read past — the sheet just shows where you are. */}
        {/* The same grouping as the sidebar, laid flat: a sheet has room to show every
            heading at once, so nothing here needs opening first. */}
        <div className="space-y-4">
          {inCommunity ? (
            <div className="grid grid-cols-3 gap-2">
              {communityNav.map((n) => <SheetLink key={n.href} item={n} active={isActive(n.href, n.exact)} onGo={() => setMoreOpen(false)} />)}
            </div>
          ) : (
            <>
              {NAV.filter(isGroup).map((g) => (
                <div key={g.group}>
                  <div className="mb-1.5 px-0.5 text-xs font-medium text-muted-fg">{t(g.key)}</div>
                  <div className="grid grid-cols-3 gap-2">
                    {g.items.map((n) => <SheetLink key={n.href} item={n} active={isActive(n.href)} onGo={() => setMoreOpen(false)} />)}
                  </div>
                </div>
              ))}
              <div className="grid grid-cols-3 gap-2">
                {NAV_FOOT.map((n) => <SheetLink key={n.href} item={n} active={isActive(n.href)} onGo={() => setMoreOpen(false)} />)}
                {user.role === "admin" ? (
                  <SheetLink item={{ href: "/admin", key: "nav.admin", icon: <ShieldCheck /> }} active={false} onGo={() => setMoreOpen(false)} />
                ) : null}
                <SheetLink item={DOWNLOADS} active={isActive(DOWNLOADS.href)} onGo={() => setMoreOpen(false)} />
              </div>
            </>
          )}
        </div>
        <div className="mt-4 flex items-center justify-between gap-2">
          <div className="inline-flex rounded-lg bg-muted p-0.5 text-xs">
            {(["ko", "en"] as Locale[]).map((l) => <button key={l} type="button" onClick={() => void setLocale(l)} className={cn("rounded-md px-3 py-1.5", user.locale === l ? "bg-card shadow-sm" : "text-muted-fg")}>{l.toUpperCase()}</button>)}
          </div>
          <Button variant="outline" size="sm" onClick={logout}><LogOut className="h-4 w-4" />{t("auth.logout")}</Button>
        </div>
        <button type="button" className="sr-only" onClick={() => setMoreOpen(false)}><X /></button>
      </Sheet>
    </div>
  );
}

/** One tile in the more-sheet. 44px of touch target, not a text link with an icon on it. */
function SheetLink({ item, active, onGo }: { item: NavItem; active: boolean; onGo: () => void }) {
  const t = useT();
  return (
    <Link href={item.href} onClick={onGo}
      className={cn("flex min-h-[76px] flex-col items-center justify-center gap-1.5 rounded-xl border border-border p-3 text-center text-xs [&>svg]:h-5 [&>svg]:w-5",
        active ? "border-accent/40 bg-accent/10 text-accent" : "")}>{item.icon}{t(item.key)}</Link>
  );
}

/** Standard scrollable page container. */
/** 화면 한 장의 폭은 하나다 — 최대 1400px (PC 에서 스케줄 화면의 비율, 2026-09-28). 예전에는 "넓은 화면" 만
 *  1400 이고 나머지는 1024 라, 내용이 적은 화면(정보·계정 설정…)이 가운데로 좁게 몰려 보였다. 피드처럼
 *  한 줄로 읽는 화면은 이 틀 안에 제 글 폭(560)을 따로 둔다. */
export const PAGE_MAX = "max-w-[1400px]";

export function Page({ children, className, full }: { children: ReactNode; className?: string; full?: boolean }) {
  return (
    // relative 는 빼면 안 된다. 화면 낭독기용 글(sr-only)처럼 absolute 로 놓인 것이 기준 상자를
    // 못 찾으면 이 스크롤 칸을 벗어나 문서 전체를 늘리고, 앱 아래로 빈 스크롤이 생긴다.
    <div className="relative flex-1 min-h-0 overflow-y-auto scrollbar-thin">
      {/* `full` is for the one shape a column cannot serve: a wide table whose last column
          is an action. Capped at 1400 it lost the delete button off the right edge. */}
      <div className={cn("mx-auto w-full px-4 py-5 md:px-6 md:py-6", full ? "max-w-none" : PAGE_MAX, className)}>{children}</div>
    </div>
  );
}

/** The bell shows what arrived; the inbox is where it gets handled.
 *
 *  Jumping straight to the inbox made the bell useless for the thing a bell is for —
 *  glancing. The list is read-only on purpose: one tap goes to the item itself. */
function NotificationBell({ count, items }: { count: number; items: InboxItem[] }) {
  const t = useT(); const locale = useLocale();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const recent = items.slice(0, 6);
  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="menu"
        className="relative inline-flex h-10 w-10 items-center justify-center rounded-xl hover:bg-muted" aria-label={t("nav.inbox")}>
        <Bell className="h-5 w-5" />
        {count ? <span className="absolute right-1.5 top-1.5 min-w-[16px] rounded-full bg-accent px-1 text-center text-[10px] leading-4 text-accent-fg">{count > 99 ? "99+" : count}</span> : null}
      </button>
      {open ? (
        <div role="menu" className="fade-up absolute right-0 top-12 z-50 w-[336px] max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-2xl border border-border bg-card shadow-xl">
          <div className="flex items-center gap-2 border-b border-border px-3.5 py-2.5">
            <span className="text-sm font-semibold">{t("nav.notifications")}</span>
            {count ? <span className="rounded-full bg-accent/12 px-1.5 text-[11px] tabular-nums text-accent">{count}</span> : null}
          </div>
          {recent.length === 0 ? (
            <p className="px-3.5 py-6 text-center text-sm text-muted-fg">{t("inbox.empty")}</p>
          ) : (
            <ul className="max-h-[60vh] divide-y divide-border overflow-y-auto scrollbar-thin">
              {recent.map((it) => (
                <li key={it.id}>
                  <Link href={`/app/inbox?item=${it.id}`} onClick={() => setOpen(false)}
                    className="flex gap-2.5 px-3.5 py-2.5 hover:bg-muted/60">
                    <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", it.status === "new" ? "bg-accent" : "bg-transparent")} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium">{inboxTitle(it, t)}</span>
                      {it.payload?.text ? <span className="mt-0.5 block truncate text-xs text-muted-fg">{String(it.payload.text)}</span> : null}
                      <span className="mt-0.5 block text-[11px] text-muted-fg">{fmtRelative(it.created_at, locale)}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <Link href="/app/inbox" onClick={() => setOpen(false)}
            className="block border-t border-border px-3.5 py-2.5 text-center text-[13px] text-accent hover:bg-muted/60">
            {t("common.more")}
          </Link>
        </div>
      ) : null}
    </div>
  );
}

/** A standing reminder that the account is not verified yet.
 *
 *  It sits under the header on every page of both sections rather than only where a
 *  feature refuses, because the refusal itself is the bad place to learn about it — by
 *  then the person is already trying to do the thing. It is dismissible for the session,
 *  not forever: the state is real and comes back on the next visit. */
function VerifyBanner() {
  const t = useT();
  const user = useAuth((st) => st.user);
  const pathname = usePathname();
  const [hidden, setHidden] = useState(false);
  if (!user || user.email_verified || hidden) return null;
  if (pathname?.startsWith("/app/account")) return null;   // already looking at it
  const name = (user.nickname || user.display_name || "").trim();
  return (
    <div className="border-b border-warning/30 bg-warning/10 px-3 py-2.5 md:px-5">
      <div className={cn("mx-auto flex items-center gap-3", PAGE_MAX)}>
        <ShieldAlert className="h-5 w-5 shrink-0 text-warning" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{name ? t("verify.banner_named", { name }) : t("verify.banner")}</p>
          <p className="truncate text-xs text-muted-fg">{t("verify.banner_hint")}</p>
        </div>
        <Link href="/app/account" className={buttonLook("accent", "sm", "shrink-0")}>{t("verify.cta")}</Link>
        <button type="button" onClick={() => setHidden(true)} aria-label={t("common.close")}
                className="-mr-1 shrink-0 rounded-lg p-1.5 text-muted-fg hover:bg-warning/15 hover:text-fg">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}


/** One nav destination. */
function NavLink({ item, collapsed, isActive, badge, nested, onNavigate }: {
  item: NavItem; collapsed?: boolean; isActive: (href: string, exact?: boolean) => boolean;
  badge?: number; nested?: boolean; onNavigate?: () => void;
}) {
  const t = useT();
  const on = isActive(item.href, item.exact);
  return (
    <Link href={item.href} title={t(item.key)} onClick={onNavigate} aria-current={on ? "page" : undefined}
      className={cn("flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors [&>svg]:h-[18px] [&>svg]:w-[18px] [&>svg]:shrink-0",
        collapsed && "justify-center px-0", nested && "py-2",
        on ? "bg-accent/12 text-accent" : "text-muted-fg hover:bg-muted hover:text-fg")}>
      {item.icon}
      {!collapsed ? <span className="truncate">{t(item.key)}</span> : null}
      {!collapsed && badge ? <span className="ml-auto rounded-full bg-accent px-1.5 text-[10px] text-accent-fg">{badge}</span> : null}
    </Link>
  );
}

/** A heading that opens to reveal its pages.
 *
 *  The panel is animated with grid rows rather than a max-height guess: the row goes from
 *  0fr to 1fr, so the transition is exactly as tall as the content and never clips a
 *  fourth item or leaves a gap under a third. */
function NavGroupRow({ group, open, onToggle, isActive, inboxCount }: {
  group: NavGroup; open: boolean; onToggle: () => void;
  isActive: (href: string, exact?: boolean) => boolean; inboxCount: number;
}) {
  const t = useT();
  const holdsActive = group.items.some((i) => isActive(i.href, i.exact));
  return (
    <div>
      {/* Closed over the page you are on, the heading says so by wearing the colour of the
          page it holds. It used to put an accent dot on the right instead, which is the
          same mark the inbox uses for something new: people read it as an alarm they could
          not find, because there was nothing to find. */}
      <button type="button" onClick={onToggle} aria-expanded={open} aria-controls={`nav-${group.group}`}
        className={cn("flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors hover:bg-muted",
          holdsActive && !open ? "text-accent hover:text-accent" : "text-muted-fg hover:text-fg")}>
        <ChevronDown className={cn("h-[18px] w-[18px] shrink-0 transition-transform duration-200", !open && "-rotate-90")} />
        <span className="truncate">{t(group.key)}</span>
      </button>
      <div id={`nav-${group.group}`} role="group" aria-label={t(group.key)}
        className={cn("grid transition-[grid-template-rows,opacity] duration-200 ease-out", open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0")}>
        <div className="overflow-hidden">
          <div className="ml-4 space-y-0.5 border-l border-border pl-2 pt-0.5">
            {group.items.map((i) => (
              <NavLink key={i.href} item={i} isActive={isActive} nested
                       badge={i.key === "nav.inbox" ? inboxCount : undefined} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
