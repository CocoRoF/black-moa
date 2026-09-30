"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bell, Calendar, ChevronRight, FolderOpen, RefreshCw, RotateCw, TriangleAlert, Unplug, Users } from "@/components/icons";
import { Integrations, type Connection, type IntegrationProvider } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { codeMessage, friendlyError } from "@/lib/errors";
import { fmtRelative } from "@/lib/format";
import { useAuth } from "@/stores/auth";
import { Page } from "./Shell";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/input";
import { SwitchRow } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { PageHeader } from "@/components/ui/misc";
import { ConfirmDialog } from "@/components/ui/dialog";
import { ProviderIcon } from "@/components/integrations/ProviderIcon";

/** 바깥 서비스 연동 (plan/11, plan/59). 관리자가 [연결]에서 켜고 사용자에게 준 기능만 보인다.
 *  `bare` 는 계정 페이지가 "연결" 아래에 이 카드들을 그대로 싣게 하는 것 — 같은 로직을 두 벌 두지 않는다. */
export function IntegrationsPage({ bare = false }: { bare?: boolean }) {
  const t = useT(); const locale = useLocale(); const sp = useSearchParams();
  const isAdmin = useAuth((s) => s.user?.role === "admin");
  const q = useQuery({ queryKey: ["integrations"], queryFn: Integrations.list });
  useEffect(() => {
    const connected = sp.get("connected"); const partial = sp.get("partial"); const err = sp.get("error");
    if (connected && partial) toast.warning(t("integ.partial", { list: partial.split(",").map((c) => t(`integ.cap_${c}`)).join(", ") }));
    else if (connected) toast.success(t("integ.connected"));
    else if (err) toast.error(codeMessage(err, locale));
  }, [sp, t, locale]);
  const providers = q.data?.providers ?? [];
  const conns = q.data?.connections ?? [];
  // 관리자가 꺼 둔 공급자라도 이어 둔 연결은 보여 준다 — 끊을 수는 있어야 한다.
  const orphan = conns.filter((c) => !providers.some((p) => p.id === c.provider));
  const body = q.isLoading ? <Skeleton className="h-48" /> : (!providers.length && !orphan.length) ? (
    <EmptyState icon={<Unplug />} title={t("integ.none_title")} description={t("integ.none_desc")}
      action={isAdmin ? <Link href="/admin/connections" className="text-sm text-accent hover:underline">{t("integ.admin_link")}</Link> : null} />
  ) : (
    <div className="space-y-4">
      {providers.map((p) => <ProviderCard key={p.id} provider={p} conns={conns.filter((c) => c.provider === p.id)} />)}
      {orphan.map((c) => <ProviderCard key={c.id} provider={{ id: c.provider, label: c.provider_label, capabilities: [] }} conns={[c]} off />)}
    </div>
  );
  if (bare) return body;
  return <Page><PageHeader title={t("nav.integrations")} description={t("integ.desc")} />{body}</Page>;
}

function ProviderCard({ provider: p, conns, off = false }: { provider: IntegrationProvider; conns: Connection[]; off?: boolean }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient(); const here = usePathname();
  const offered = p.capabilities.map((c) => c.id);
  const [caps, setCaps] = useState<string[]>(offered);
  useEffect(() => { setCaps(offered); }, [offered.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const [disc, setDisc] = useState<Connection | null>(null);
  const start = useMutation({
    mutationFn: (want: string[]) => Integrations.start(p.id, want, here),
    onSuccess: (r) => { window.location.assign(r.url); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  // [지금 동기화] 를 누른 뒤에는 "마지막 동기화" 가 바뀔 때까지 가져오는 중으로 보인다 — 끝나면 서버가 알려 온다(plan/76).
  const [waiting, setWaiting] = useState<Record<string, string | null>>({});
  const sync = useMutation({
    mutationFn: (c: Connection) => Integrations.sync(c.id),
    onSuccess: (_r, c) => {
      setWaiting((w) => ({ ...w, [c.id]: c.last_sync_at }));
      window.setTimeout(() => setWaiting((w) => { const n = { ...w }; delete n[c.id]; return n; }), 60_000);
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const syncing = (c: Connection) => c.status === "active" && (!c.last_sync_at || (c.id in waiting && waiting[c.id] === c.last_sync_at));
  const patch = useMutation({
    mutationFn: (x: { id: string; caps: string[] }) => Integrations.patch(x.id, x.caps, here),
    // 아직 허락받지 않은 기능이면 서버가 바꾸지 않고 동의 화면을 준다 — 그리로 간다.
    onSuccess: (r) => { if (r.consent_url) window.location.assign(r.consent_url); else qc.invalidateQueries({ queryKey: ["integrations"] }); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => Integrations.disconnect(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["integrations"] }); qc.invalidateQueries({ queryKey: ["schedule"] }); setDisc(null); toast.success(t("integ.disconnected")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <Card>
      <CardHeader title={<span className="inline-flex items-center gap-2"><ProviderIcon provider={p.id} size={20} />{p.label}</span>}
                  description={t(`integ.desc_${p.id}`)} />
      <CardBody className="space-y-4">
        {off ? <p className="rounded-xl bg-warning/10 px-3 py-2 text-sm text-warning">{t("integ.turned_off")}</p> : null}
        {conns.length === 0 ? (
          <div className="space-y-3">
            <div className="grid gap-1 sm:grid-cols-2">
              {offered.map((c) => <Checkbox key={c} checked={caps.includes(c)} onChange={(v) => setCaps(v ? [...caps, c] : caps.filter((x) => x !== c))} label={t(`integ.cap_${c}`)} />)}
            </div>
            <Button variant="accent" loading={start.isPending} disabled={!caps.length} onClick={() => start.mutate(caps)}>
              <ProviderIcon provider={p.id} size={16} />{t("integ.connect_with", { name: p.label })}
            </Button>
          </div>
        ) : conns.map((c) => (
          <div key={c.id} className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 truncate font-medium">{c.account_label}</span>
              <Badge tone={c.status === "active" ? "success" : c.status === "expired" ? "warning" : "danger"}>{t(`integ.status_${c.status === "active" || c.status === "expired" ? c.status : "error"}`)}</Badge>
              {syncing(c)
                ? <span className="inline-flex items-center gap-1 text-xs text-muted-fg"><RefreshCw className="h-3 w-3 animate-spin" />{t("integ.syncing")}</span>
                : <span className="text-xs text-muted-fg">{t("integ.last_sync")}: {c.last_sync_at ? fmtRelative(c.last_sync_at, locale) : "–"}</span>}
            </div>
            {c.status === "active" && c.error && /^(calendar|contacts|mail)_(forbidden|failed)$/.test(c.error) ? (
              <p className="flex items-start gap-1.5 rounded-xl bg-warning/10 px-3 py-2 text-sm text-warning">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />{codeMessage(c.error, locale)}
              </p>
            ) : null}
            {c.status === "expired" && !off ? (
              <div className="flex flex-wrap items-center gap-2 rounded-xl bg-warning/10 px-3 py-2 text-sm text-warning">
                <span className="min-w-0 flex-1">{t("integ.expired_desc")}</span>
                <Button size="sm" variant="outline" loading={start.isPending} onClick={() => start.mutate(c.capabilities.length ? c.capabilities : offered)}>
                  <RotateCw className="h-4 w-4" />{t("integ.reconnect")}
                </Button>
              </div>
            ) : null}
            {!off ? (
              <div className="divide-y divide-border rounded-xl border border-border">
                {offered.map((cap) => (
                  <div key={cap} className="px-3">
                    <SwitchRow title={t(`integ.cap_${cap}`)}
                      description={!c.granted.includes(cap) && !c.capabilities.includes(cap) ? t("integ.needs_consent") : undefined}
                      checked={c.capabilities.includes(cap)} disabled={patch.isPending}
                      onChange={(v) => patch.mutate({ id: c.id, caps: v ? [...c.capabilities, cap] : c.capabilities.filter((x) => x !== cap) })} />
                  </div>
                ))}
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              {!off && c.capabilities.some((x) => x !== "talk_message" && x !== "calendar_write") ? (
                <Button variant="outline" size="sm" loading={sync.isPending} disabled={syncing(c)} onClick={() => sync.mutate(c)}><RefreshCw className="h-4 w-4" />{t("integ.sync_now")}</Button>
              ) : null}
              <Button variant="ghost" size="sm" className="text-danger" onClick={() => setDisc(c)}><Unplug className="h-4 w-4" />{t("integ.disconnect")}</Button>
            </div>
            {!off ? <WhereItGoes caps={c.capabilities} /> : null}
          </div>
        ))}
      </CardBody>
      <ConfirmDialog open={!!disc} onClose={() => setDisc(null)} onConfirm={() => { if (disc) remove.mutate(disc.id); }}
        title={t("integ.disconnect")} description={t("integ.disconnect_desc")} confirmLabel={t("integ.disconnect")}
        cancelLabel={t("common.cancel")} danger loading={remove.isPending} />
    </Card>
  );
}

/** 가져온 것은 [내 정보] 의 한 곳에 모이고, 비서는 거기를 본다 (plan/57). 미리보기를 여기 두면
 *  메일·스케줄 화면과 같은 목록이 두 벌이 된다 — 가는 곳을 알려 주고 그리로 보낸다. */
function WhereItGoes({ caps }: { caps: string[] }) {
  const t = useT();
  const go = [
    { on: caps.includes("calendar_read") || caps.includes("calendar_write"), href: "/app/schedule?tab=sync", icon: <Calendar className="h-4 w-4" />, label: t("integ.goes_schedule") },
    { on: caps.includes("contacts"), href: "/app/network", icon: <Users className="h-4 w-4" />, label: t("integ.goes_network") },
    { on: caps.includes("drive"), href: "/app/files", icon: <FolderOpen className="h-4 w-4" />, label: t("integ.goes_files") },
    { on: caps.includes("talk_message"), href: "/app/notifications", icon: <Bell className="h-4 w-4" />, label: t("integ.goes_notifications") },
  ].filter((g) => g.on);
  if (!go.length) return null;
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {go.map((g) => (
        <Link key={g.href} href={g.href} className="flex items-center gap-2 rounded-xl border border-border px-3 py-2.5 text-sm hover:border-accent/50">
          <span className="text-muted-fg">{g.icon}</span><span className="min-w-0 flex-1">{g.label}</span><ChevronRight className="h-4 w-4 text-muted-fg" />
        </Link>
      ))}
    </div>
  );
}
