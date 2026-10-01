"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowLeft, AudioLines, Boxes, Building2, BrainCircuit, ChevronDown, ClipboardList, CreditCard, Gauge, KeyRound, LayoutDashboard, ListChecks, LogOut, Mail, Menu, MessagesSquare, Moon, Plug, Radar, Settings, ShieldAlert, Sun, Ticket, Users, Wand2, Waypoints, X, MonitorDown } from "@/components/icons";
import { LocaleProvider, useT, type Locale } from "@/lib/i18n";
import { useRequireAuth } from "@/lib/hooks";
import { Admin, Auth } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/skeleton";
import { Sheet } from "@/components/ui/dialog";
import { Logo } from "@/components/brand/Logo";

interface NavItem { href: string; key: string; icon: ReactNode; exact?: boolean }
interface NavGroup { group: string; key: string; items: NavItem[] }
type NavEntry = NavItem | NavGroup;

/** Sixteen flat links shouted equally loudly, and on a phone they were sixteen rows of a
 *  scrolling sheet. Grouped by the question being asked: what the AI runs on, who is using
 *  it and on what plan, what the service itself does, and how the machine is doing. */
const NAV: NavEntry[] = [
  { href: "/admin", key: "adm.overview", icon: <LayoutDashboard />, exact: true },
  { href: "/admin/setup", key: "adm.setup", icon: <Wand2 /> },
  { group: "ai", key: "admg.ai", items: [
    { href: "/admin/providers", key: "adm.providers", icon: <KeyRound /> },
    { href: "/admin/models", key: "adm.models", icon: <Boxes /> },
    { href: "/admin/audio", key: "adm.audio", icon: <AudioLines /> },
    { href: "/admin/embedding", key: "adm.embedding", icon: <Waypoints /> },
  ] },
  { group: "people", key: "admg.people", items: [
    { href: "/admin/users", key: "adm.users", icon: <Users /> },
    { href: "/admin/plans", key: "adm.plans", icon: <CreditCard /> },
    { href: "/admin/invites", key: "adm.invites", icon: <Ticket /> },
    { href: "/admin/usage", key: "adm.usage", icon: <Gauge /> },
  ] },
  { group: "service", key: "admg.service", items: [
    // 로그인(SSO)과 데이터 연동의 공급자 — Google · 카카오 (plan/59).
    { href: "/admin/connections", key: "adm.connections", icon: <Plug /> },
    { href: "/admin/triggers", key: "adm.triggers", icon: <Waypoints /> },
    { href: "/admin/community", key: "adm.community", icon: <MessagesSquare /> },
    { href: "/admin/companies", key: "adm.companies", icon: <Building2 /> },
    { href: "/admin/email", key: "adm.email", icon: <Mail /> },
    // 앱의 GitHub 릴리스를 옮겨 두고 내어 주는 곳 (plan/64).
    { href: "/admin/downloads", key: "adm.downloads", icon: <MonitorDown /> },
  ] },
  // Ordered the way an incident is actually worked: settings, then what the server is
  // serving, then the worker behind it (the worker is the server's, so it sits next to
  // traffic), then the LLM capacity that dominates both, then the record, then the machine.
  { group: "system", key: "admg.system", items: [
    { href: "/admin/settings", key: "adm.settings", icon: <Settings /> },
    { href: "/admin/traffic", key: "adm.traffic", icon: <Radar /> },
    { href: "/admin/jobs", key: "adm.jobs", icon: <ListChecks /> },
    { href: "/admin/llm", key: "adm.llm", icon: <BrainCircuit /> },
    { href: "/admin/audit", key: "adm.audit", icon: <ClipboardList /> },
    { href: "/admin/health", key: "adm.health", icon: <Activity /> },
  ] },
];

/** The phone's tab bar: the four screens an administrator opens without thinking, and the
 *  sheet for everything else. Same shape as the owner console, so crossing between the two
 *  does not change how the device works. */
const TABS: NavItem[] = [
  { href: "/admin", key: "adm.overview", icon: <LayoutDashboard />, exact: true },
  { href: "/admin/users", key: "adm.users", icon: <Users /> },
  { href: "/admin/providers", key: "adm.providers", icon: <KeyRound /> },
  { href: "/admin/usage", key: "adm.usage", icon: <Gauge /> },
];

const isGroup = (e: NavEntry): e is NavGroup => "group" in e;

export function AdminShell({ children }: { children: ReactNode }) {
  const { ok, user } = useRequireAuth("admin");
  const [locale, setLocale] = useState<Locale>("ko");
  useEffect(() => { if (user?.locale) setLocale(user.locale); }, [user?.locale]);
  if (!ok || !user) return <div className="flex h-dvh items-center justify-center"><Spinner /></div>;
  return <LocaleProvider locale={locale} setLocale={setLocale}><Inner>{children}</Inner></LocaleProvider>;
}

function Inner({ children }: { children: ReactNode }) {
  const t = useT(); const path = usePathname(); const router = useRouter();
  const { resolved, setPref } = useTheme();
  const [open, setOpen] = useState(false);
  const ov = useQuery({ queryKey: ["admin", "overview"], queryFn: Admin.overview, staleTime: 60_000 });
  const active = (h: string, exact?: boolean) => (exact ? path === h : path.startsWith(h));
  const logout = async () => { try { await Auth.logout(); } catch { /* ignore */ } useAuth.getState().clear(); router.replace("/login"); };
  const setupPending = !!ov.data && !ov.data.setup_completed;

  // One group open at a time, and it follows where you are: arriving inside a closed group
  // opens it rather than leaving the rail disagreeing with the screen.
  const groupOfPath = useMemo(() => {
    const hit = NAV.find((e) => isGroup(e) && e.items.some((i) => path === i.href || path.startsWith(i.href + "/")));
    return hit && isGroup(hit) ? hit.group : null;
  }, [path]);
  const [openGroup, setOpenGroup] = useState<string | null>(groupOfPath);
  useEffect(() => { if (groupOfPath) setOpenGroup(groupOfPath); }, [groupOfPath]);

  const link = (n: NavItem, onGo?: () => void, nested = false) => (
    <Link key={n.href} href={n.href} onClick={onGo} aria-current={active(n.href, n.exact) ? "page" : undefined}
      className={cn("flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium [&>svg]:h-[18px] [&>svg]:w-[18px]",
        nested && "pl-9",
        active(n.href, n.exact) ? "bg-accent/12 text-accent" : "text-muted-fg hover:bg-muted hover:text-fg")}>
      {n.icon}{t(n.key)}
      {n.key === "adm.setup" && setupPending ? <span className="ml-auto h-2 w-2 rounded-full bg-warning" /> : null}
    </Link>
  );

  const rail = (
    <nav className="space-y-0.5 p-2" aria-label={t("adm.title")}>
      {NAV.map((e) => {
        if (!isGroup(e)) return link(e);
        const on = openGroup === e.group;
        const hasActive = e.items.some((i) => active(i.href, i.exact));
        return (
          <div key={e.group}>
            <button type="button" onClick={() => setOpenGroup(on ? null : e.group)} aria-expanded={on}
              className={cn("flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-sm font-medium",
                hasActive && !on ? "text-accent" : "text-muted-fg hover:bg-muted hover:text-fg")}>
              {t(e.key)}
              <ChevronDown className={cn("ml-auto h-4 w-4 transition-transform duration-200", on && "rotate-180")} />
            </button>
            {/* grid-rows animation: height:auto cannot be transitioned, and a fixed max-height
                either clips a long group or eases against empty space on a short one. */}
            <div className={cn("grid transition-[grid-template-rows] duration-200 ease-out", on ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
              <div className="overflow-hidden"><div className="space-y-0.5 pt-0.5">{e.items.map((i) => link(i, undefined, true))}</div></div>
            </div>
          </div>
        );
      })}
    </nav>
  );

  return (
    <div className="flex h-dvh overflow-hidden bg-bg">
      <aside className="hidden md:flex w-60 shrink-0 flex-col border-r border-border bg-card">
        <div className="flex h-14 items-center gap-2 border-b border-border px-4"><Logo href="/admin" size={26} /><span className="ml-1 rounded-md bg-fg px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-bg">Admin</span></div>
        <div className="flex-1 overflow-y-auto scrollbar-thin">{rail}</div>
        <div className="border-t border-border p-2"><Link href="/app" className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-muted-fg hover:bg-muted"><ArrowLeft className="h-4 w-4" />{t("adm.back_to_app")}</Link><button type="button" onClick={logout} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-muted-fg hover:bg-muted"><LogOut className="h-4 w-4" />{t("auth.logout")}</button></div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="safe-pt flex h-14 shrink-0 items-center gap-2 border-b border-border bg-card/90 px-3 md:px-5">
          <div className="md:hidden flex items-center gap-2"><Logo href="/admin" size={26} /><span className="rounded-md bg-fg px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-bg">Admin</span></div>
          <div className="flex-1" />
          {setupPending && !path.startsWith("/admin/setup") ? <Link href="/admin/setup" className="hidden sm:inline-flex items-center gap-1.5 rounded-full border border-warning/50 bg-warning/10 px-3 py-1 text-xs text-warning"><Wand2 className="h-3.5 w-3.5" />{t("adm.setup_incomplete")}</Link> : null}
          {ov.data?.default_admin_password_in_use ? <Link href="/app/settings" className="inline-flex items-center gap-1.5 rounded-full border border-danger/50 bg-danger/10 px-3 py-1 text-xs font-medium text-danger"><ShieldAlert className="h-3.5 w-3.5" />{t("adm.default_password")}</Link> : null}
          {/* A pool that is serving turns is a working install, whatever the legacy single
              credential file says — without this check the header cried wolf on every
              pooled deployment. */}
          {ov.data?.claude && !ov.data.claude.pool?.active && !ov.data.claude.credentials_present && !ov.data.claude.has_anthropic_key ? <Link href="/admin/providers" className="hidden sm:inline-flex items-center gap-1.5 rounded-full border border-danger/50 bg-danger/10 px-3 py-1 text-xs text-danger"><Mail className="h-3.5 w-3.5" />{t("adm.claude_missing")}</Link> : null}
          <Button variant="ghost" size="icon" onClick={() => setPref(resolved === "dark" ? "light" : "dark")} aria-label={t("common.toggle_theme")}>{resolved === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}</Button>
        </header>

        <main className="flex min-h-0 flex-1 flex-col pb-16 md:pb-0">{children}</main>

        {/* The admin console had no bottom bar at all: every move on a phone meant opening a
            sheet and scrolling sixteen rows. */}
        <nav className="md:hidden fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card/95 backdrop-blur safe-pb" aria-label="primary">
          <div className="grid grid-cols-5">
            {TABS.map((n) => {
              const on = active(n.href, n.exact);
              return (
                <Link key={n.href} href={n.href} aria-current={on ? "page" : undefined}
                  className={cn("relative flex h-14 flex-col items-center justify-center gap-0.5 text-[10px] [&>svg]:h-5 [&>svg]:w-5", on ? "text-accent" : "text-muted-fg")}>
                  {n.icon}<span>{t(n.key)}</span>
                </Link>
              );
            })}
            <button type="button" onClick={() => setOpen(true)}
              className={cn("relative flex h-14 flex-col items-center justify-center gap-0.5 text-[10px] [&>svg]:h-5 [&>svg]:w-5", open ? "text-accent" : "text-muted-fg")}>
              <Menu /><span>{t("nav.more")}</span>
              {setupPending ? <span className="absolute right-[26%] top-2.5 h-2 w-2 rounded-full bg-warning" /> : null}
            </button>
          </div>
        </nav>
      </div>

      <Sheet open={open} onClose={() => setOpen(false)} title={t("adm.title")}>
        {/* Flat, every heading at once: a sheet has the room, so nothing here needs opening
            before it can be read. */}
        <div className="space-y-4">
          {NAV.filter(isGroup).map((g) => (
            <div key={g.group}>
              <div className="mb-1.5 px-0.5 text-xs font-medium text-muted-fg">{t(g.key)}</div>
              <div className="grid grid-cols-3 gap-2">
                {g.items.map((n) => (
                  <Link key={n.href} href={n.href} onClick={() => setOpen(false)}
                    className={cn("flex min-h-[76px] flex-col items-center justify-center gap-1.5 rounded-xl border border-border p-3 text-center text-xs [&>svg]:h-5 [&>svg]:w-5",
                      active(n.href, n.exact) ? "border-accent/40 bg-accent/10 text-accent" : "")}>{n.icon}{t(n.key)}</Link>
                ))}
              </div>
            </div>
          ))}
          <div className="grid grid-cols-3 gap-2">
            <Link href="/admin/setup" onClick={() => setOpen(false)}
              className={cn("relative flex min-h-[76px] flex-col items-center justify-center gap-1.5 rounded-xl border border-border p-3 text-center text-xs [&>svg]:h-5 [&>svg]:w-5",
                active("/admin/setup") ? "border-accent/40 bg-accent/10 text-accent" : "")}>
              <Wand2 />{t("adm.setup")}
              {setupPending ? <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-warning" /> : null}
            </Link>
          </div>
        </div>
        <div className="mt-4 flex items-center justify-between gap-2">
          <Link href="/app" onClick={() => setOpen(false)} className="inline-flex items-center gap-1.5 text-sm text-muted-fg"><ArrowLeft className="h-4 w-4" />{t("adm.back_to_app")}</Link>
          <Button variant="outline" size="sm" onClick={logout}><LogOut className="h-4 w-4" />{t("auth.logout")}</Button>
        </div>
        <button type="button" className="sr-only" onClick={() => setOpen(false)}><X /></button>
      </Sheet>
    </div>
  );
}
