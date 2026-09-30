"use client";
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bot, EllipsisVertical, Mail as MailIcon, Plus, RefreshCw, Search, Send } from "@/components/icons";
import { Mail, type MailAccount, type MailItem } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { confirm } from "@/lib/confirm";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { PageHeader } from "@/components/ui/misc";
import { Segmented } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { DropdownMenu } from "@/components/ui/dropdown";
import { MailConnect } from "./MailConnect";

/* [내 정보 → 메일] (plan/57).

   바깥 메일함에서 가져온 메일이 모이는 곳이고, 비서는 나와의 대화에서 **여기만** 본다.
   메일함은 IMAP + 앱 비밀번호로 잇는다(plan/74, Gmail 도 같은 길). 여러 개를 이을 수 있다.
   메일은 외부인과의 대화에서 쓰지 않는다. */

export function MailView() {
  const t = useT();
  const router = useRouter(); const sp = useSearchParams();
  const tab = sp.get("tab") === "sent" ? "sent" : "inbox";
  const setTab = (v: "inbox" | "sent") => router.replace(v === "sent" ? "?tab=sent" : "?", { scroll: false });
  useEffect(() => { if (sp.get("connected")) toast.success(t("integ.connected")); }, [sp, t]);
  return (
    <Page>
      <PageHeader title={t("mail.title")} description={t("mail.desc")}
        action={<Segmented ariaLabel={t("mail.title")} value={tab} onChange={setTab}
          options={[{ value: "inbox", label: t("mail.tab_inbox") }, { value: "sent", label: t("mail.tab_sent") }]} />} />
      {tab === "sent" ? <SentTab /> : <InboxTab />}
    </Page>
  );
}

/** "홍길동 <hong@x.com>" → 이름, 없으면 주소. */
function sender(from: string): { name: string; addr: string } {
  const m = /^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/.exec(from || "");
  if (m) return { name: m[1].trim() || m[2], addr: m[2] };
  return { name: from || "?", addr: from || "" };
}

function InboxTab() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [q, setQ] = useState(""); const dq = useDebounced(q.trim(), 300);
  const [pages, setPages] = useState<MailItem[][]>([]);
  const [syncing, setSyncing] = useState<number | null>(null);   // 가져오기를 건 때 — 끝날 때까지 목록을 다시 읽는다
  const list = useQuery({
    queryKey: ["mail", dq], queryFn: () => Mail.list({ q: dq || undefined }), placeholderData: keepPreviousData,
    refetchInterval: syncing ? 3000 : false,
  });
  const [openId, setOpenId] = useState<string | null>(null);
  const [connecting, setConnecting] = useState<{ preset?: string; email?: string } | null>(null);
  useEffect(() => { setPages([]); }, [dq]);
  // 가져오기가 끝나면(마지막으로 가져온 때가 바뀌면) 다시 읽기를 멈춘다. 늦어도 40초.
  const lastSync = (list.data?.accounts ?? []).map((a) => a.last_sync).join("|");
  const [syncFrom, setSyncFrom] = useState("");
  useEffect(() => {
    if (!syncing) return;
    if (lastSync !== syncFrom || Date.now() - syncing > 40_000) setSyncing(null);
  }, [lastSync, syncFrom, syncing]);
  const sync = useMutation({
    mutationFn: Mail.sync,
    onSuccess: () => { setSyncFrom(lastSync); setSyncing(Date.now()); toast.success(t("mail.syncing")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => Mail.removeAccount(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["mail"] }); toast.success(t("mail.disconnected")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const more = useMutation({
    mutationFn: (before: string) => Mail.list({ q: dq || undefined, before }),
    onSuccess: (r) => setPages((p) => [...p, r.items]),
    onError: (e) => toast.error(friendlyError(e, locale)),
  });

  if (list.isLoading) return <Skeleton className="h-96" />;
  const accounts = list.data?.accounts ?? [];
  const readable = accounts.filter((a) => a.can_read);
  const dialog = <MailConnect open={!!connecting} onClose={() => setConnecting(null)} initial={connecting ?? undefined} />;
  const bars = accounts.map((a) => (
    <AccountBar key={a.id} a={a} syncing={!!syncing || sync.isPending} onSync={() => sync.mutate()}
      onReconnect={() => setConnecting({ preset: a.preset, email: a.account })}
      onRemove={async () => {
        if (await confirm({ title: t("mail.disconnect_title", { account: a.account }), description: t("mail.disconnect_desc"), confirmLabel: t("mail.disconnect"), danger: true })) remove.mutate(a.id);
      }} />
  ));
  if (!accounts.length) {
    return (
      <>
        <EmptyState icon={<MailIcon />} title={t("mail.connect_title")} description={t("mail.connect_desc")}
          action={<Button variant="accent" onClick={() => setConnecting({})}><Plus className="h-4 w-4" />{t("mail.connect")}</Button>} />
        {dialog}
      </>
    );
  }
  if (!readable.length) {
    return (
      <div className="space-y-3">
        {bars}
        <EmptyState icon={<MailIcon />} title={t("mail.reconnect_title")} description={t("mail.reconnect_desc")} />
        {dialog}
      </div>
    );
  }
  const items = [...(list.data?.items ?? []), ...pages.flat()];
  const next = pages.length ? null : list.data?.next_before;
  const lastPage = pages[pages.length - 1];
  const nextBefore = pages.length ? (lastPage && lastPage.length >= 30 ? lastPage[lastPage.length - 1]?.received_at : null) : next;
  return (
    <div className="space-y-3">
      {bars}
      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onClick={() => setConnecting({})}><Plus className="h-3.5 w-3.5" />{t("mail.add")}</Button>
      </div>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" />
        <Input className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("mail.search")} />
      </div>
      {items.length ? (
        <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card">
          {items.map((m) => {
            const s = sender(m.from);
            return (
              <li key={m.id}>
                <button type="button" onClick={() => setOpenId(m.id)} className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-muted/50">
                  <span className={cn("mt-2 h-2 w-2 shrink-0 rounded-full", m.unread ? "bg-accent" : "bg-transparent")} aria-label={m.unread ? t("mail.unread") : undefined} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-2">
                      <span className={cn("min-w-0 flex-1 truncate text-sm", m.unread ? "font-semibold" : "font-medium")}>{s.name}</span>
                      <span className="shrink-0 text-xs text-muted-fg tabular-nums">{m.received_at ? fmtRelative(m.received_at, locale) : ""}</span>
                    </span>
                    <span className={cn("block truncate text-sm", m.unread ? "text-fg" : "text-fg/80")}>{m.subject || t("mail.no_subject")}</span>
                    {m.snippet ? <span className="block truncate text-xs text-muted-fg">{m.snippet}</span> : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : <EmptyState icon={<MailIcon />} title={dq ? t("mail.no_results") : t("mail.empty")} description={dq ? undefined : t("mail.empty_desc")} />}
      {nextBefore ? (
        <div className="flex justify-center"><Button variant="outline" loading={more.isPending} onClick={() => more.mutate(nextBefore)}>{t("mail.more")}</Button></div>
      ) : null}
      <MailSheet id={openId} onClose={() => { setOpenId(null); qc.invalidateQueries({ queryKey: ["mail"] }); }} />
      {dialog}
    </div>
  );
}

function AccountBar({ a, syncing, onSync, onReconnect, onRemove }: {
  a: MailAccount; syncing: boolean; onSync: () => void; onReconnect: () => void; onRemove: () => void;
}) {
  const t = useT(); const locale = useLocale();
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-border bg-card px-4 py-2.5 text-sm">
      <MailIcon className="h-4 w-4 text-muted-fg" />
      <span className="font-medium">{a.provider_label}</span>
      <span className="min-w-0 truncate text-muted-fg">{a.account}</span>
      {a.can_read ? (
        <span className="text-xs text-muted-fg">· {a.last_sync ? t("mail.synced", { when: fmtRelative(a.last_sync, locale) }) : t("mail.never_synced")}</span>
      ) : <span className="text-xs text-danger">· {t("mail.error")}</span>}
      <span className="ml-auto flex items-center gap-1">
        {a.can_read
          ? <Button variant="ghost" size="sm" loading={syncing} onClick={onSync}><RefreshCw className="h-3.5 w-3.5" />{t("mail.sync")}</Button>
          : <Button variant="outline" size="sm" onClick={onReconnect}>{t("mail.reconnect")}</Button>}
        <DropdownMenu items={[
          { key: "reconnect", label: t("mail.reconnect"), onSelect: onReconnect },
          { key: "remove", label: t("mail.disconnect"), danger: true, onSelect: onRemove },
        ]} trigger={<Button variant="ghost" size="icon-sm" aria-label={t("common.more")}><EllipsisVertical className="h-4 w-4" /></Button>} />
      </span>
    </div>
  );
}

function MailSheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const t = useT();
  const q = useQuery({ queryKey: ["mail", "one", id], queryFn: () => Mail.read(id!), enabled: !!id, retry: false });
  const m = q.data;
  const s = m ? sender(m.from) : null;
  return (
    <Sheet open={!!id} onClose={onClose} side="right" title={m?.subject || t("mail.no_subject")}>
      {q.isLoading ? <Skeleton className="h-64" /> : q.isError ? <p className="text-sm text-danger">{t("mail.read_failed")}</p> : m && s ? (
        <div className="space-y-4">
          <div className="space-y-0.5 text-sm">
            <div><span className="font-medium">{s.name}</span>{s.addr && s.addr !== s.name ? <span className="text-muted-fg"> &lt;{s.addr}&gt;</span> : null}</div>
            {m.to.length ? <div className="text-xs text-muted-fg">{t("mail.to")}: {m.to.join(", ")}</div> : null}
            <div className="text-xs text-muted-fg">{m.received_at ? fmtDateTime(m.received_at) : m.date}</div>
          </div>
          <pre className="whitespace-pre-wrap break-words rounded-xl bg-muted/50 p-3 font-sans text-sm leading-relaxed">{m.body || m.snippet}</pre>
          <p className="flex items-center gap-1.5 text-xs text-muted-fg"><Bot className="h-3.5 w-3.5" />{t("mail.secretary_reads")}</p>
        </div>
      ) : null}
    </Sheet>
  );
}

function SentTab() {
  const t = useT(); const locale = useLocale();
  const q = useQuery({ queryKey: ["mail", "sent"], queryFn: Mail.sent });
  if (q.isLoading) return <Skeleton className="h-64" />;
  const items = q.data?.items ?? [];
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-fg">{t("mail.sent_desc")}</p>
      {items.length ? (
        <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card">
          {items.map((m) => (
            <li key={m.id} className="flex items-start gap-3 px-4 py-3">
              <Send className="mt-0.5 h-4 w-4 shrink-0 text-muted-fg" />
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{m.subject || t("mail.no_subject")}</span>
                  <span className="shrink-0 text-xs text-muted-fg">{m.at ? fmtRelative(m.at, locale) : ""}</span>
                </span>
                <span className="block truncate text-xs text-muted-fg">{t("mail.sent_line", { to: m.to, agent: m.agent || t("mail.secretary") })}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : <EmptyState icon={<Send />} title={t("mail.sent_empty")} description={t("mail.sent_empty_desc")} />}
    </div>
  );
}
