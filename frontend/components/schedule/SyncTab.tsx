"use client";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { RefreshCw, TriangleAlert } from "@/components/icons";
import { Schedule, type CalendarSource } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { codeMessage, friendlyError } from "@/lib/errors";
import { fmtRelative } from "@/lib/format";
import { useAuth } from "@/stores/auth";
import { Card, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Segmented } from "@/components/ui/tabs";
import { SwitchRow } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { ProviderIcon } from "@/components/integrations/ProviderIcon";

/* 스케줄의 [연동] 탭 (plan/58).

   바깥 달력을 스케줄에 붙인다. 붙일 수 있는 달력은 서버의 목록 그대로 — 지금은 Google 하나이고,
   다른 달력이 생기면 화면을 고치지 않고 한 장이 늘어난다. 붙일 수 있는지는 관리 설정이 정하고,
   붙인 뒤 무엇을 가져올지·얼마나 자주·미팅을 거기에도 넣을지는 여기서 정한다.
   계정 연결을 끊는 것은 [관리·설정 → 연동] 의 일이다 — 한 연결이 메일·연락처도 함께 들고 있다. */

const EVERY = [0, 15, 60, 360, 1440] as const;

export function SyncTab() {
  const t = useT();
  const isAdmin = useAuth((st) => st.user?.role === "admin");
  const q = useQuery({ queryKey: ["schedule", "sources"], queryFn: Schedule.sources });
  if (q.isLoading) return <Skeleton className="h-64" />;
  // 이을 수 없고 이어 두지도 않은 달력은 관리자에게만 보인다(켜러 갈 수 있으니). 사용자에게는 할 수 있는 것이 없는 카드다.
  const items = (q.data?.items ?? []).filter((s) => s.available || s.connected || isAdmin);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-fg">{t("sync.desc")}</p>
      {items.map((s) => <SourceCard key={s.provider} s={s} />)}
    </div>
  );
}

function SourceCard({ s }: { s: CalendarSource }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const isAdmin = useAuth((st) => st.user?.role === "admin");
  const put = (items: CalendarSource[]) => qc.setQueryData(["schedule", "sources"], { items });
  const connect = useMutation({
    mutationFn: () => Schedule.connectSource(s.provider),
    onSuccess: (r) => { window.location.href = r.url; },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const patch = useMutation({
    mutationFn: (b: { read?: boolean; write?: boolean; auto_every?: number }) => Schedule.patchSource(s.provider, b),
    onSuccess: (r) => {
      // 아직 받지 않은 권한이면 바꾸지 않고 동의 화면으로 — 돌아오면 이 탭이다.
      if (r.consent_url) { window.location.href = r.consent_url; return; }
      put(r.items);
      qc.invalidateQueries({ queryKey: ["schedule"] });
      toast.success(t("common.saved"));
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const sync = useMutation({
    mutationFn: () => Schedule.syncSource(s.provider),
    onSuccess: (r) => { put(r.items); qc.invalidateQueries({ queryKey: ["schedule"] }); toast.success(t("sync.synced", { n: r.events })); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const broken = s.connected && s.status === "error";
  // 아직 받지 않은 권한은 동의 화면을 거쳐야 켜진다. 관리 설정에서 꺼져 있으면 그 길이 없으니 막고 까닭을 적는다.
  const locked = (on: boolean | undefined, granted: boolean | undefined) => !s.available && !on && !granted;

  return (
    <Card>
      <CardBody className="space-y-4 pt-5">
        <div className="flex flex-wrap items-center gap-2">
          <ProviderIcon provider={s.provider} size={20} />
          <span className="text-[15px] font-semibold">{s.label}</span>
          <Badge tone={broken ? "danger" : s.connected ? "success" : "neutral"}>
            {broken ? t("sync.st_broken") : s.connected ? t("sync.st_on") : t("sync.st_off")}
          </Badge>
          {s.connected && s.account ? <span className="min-w-0 truncate text-sm text-muted-fg">{s.account}</span> : null}
        </div>

        {!s.available && !s.connected ? (
          <p className="text-sm text-muted-fg">
            {t("sync.unavailable")}{" "}
            {isAdmin ? <Link href="/admin/connections" className="font-medium text-accent hover:underline">{t("sync.admin_go")}</Link> : null}
          </p>
        ) : !s.connected ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-fg">{t("sync.connect_desc", { name: s.label })}</p>
            <Button variant="accent" loading={connect.isPending} onClick={() => connect.mutate()}>{t("sync.connect", { name: s.label })}</Button>
          </div>
        ) : (
          <>
            {broken ? (
              <div className="flex flex-wrap items-center gap-2 rounded-xl bg-danger/10 px-3 py-2 text-sm text-danger">
                <TriangleAlert className="h-4 w-4 shrink-0" /><span className="min-w-0 flex-1">{t("sync.broken")}</span>
                {s.available ? <Button size="sm" variant="outline" loading={connect.isPending} onClick={() => connect.mutate()}>{t("sync.reconnect")}</Button> : null}
              </div>
            ) : null}
            {!broken && s.sync_error ? (
              <p className="flex items-start gap-1.5 rounded-xl bg-warning/10 px-3 py-2 text-sm text-warning">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />{codeMessage(s.sync_error, locale)}
              </p>
            ) : null}
            <div className="flex flex-wrap items-center gap-2 rounded-xl bg-muted/50 px-3 py-2.5 text-sm">
              <span className="min-w-0 flex-1 text-muted-fg">
                {s.read
                  ? t("sync.status", { when: s.last_sync ? fmtRelative(s.last_sync, locale) : t("sync.never"), n: s.events ?? 0 })
                  : t("sync.status_off")}
              </span>
              <Button size="sm" variant="ghost" disabled={!s.read || broken} loading={sync.isPending} onClick={() => sync.mutate()}>
                <RefreshCw className="h-3.5 w-3.5" />{t("sync.now")}
              </Button>
            </div>
            <div className="divide-y divide-border">
              <SwitchRow title={t("sync.read")} description={locked(s.read, s.read_granted) ? t("sync.locked") : t("sync.read_desc", { name: s.label })}
                checked={!!s.read} disabled={patch.isPending || locked(s.read, s.read_granted)} onChange={(v) => patch.mutate({ read: v })} />
              <div className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className={s.read ? "text-sm font-medium" : "text-sm font-medium text-muted-fg"}>{t("sync.auto")}</div>
                  <div className="mt-0.5 text-xs text-muted-fg">{t("sync.auto_desc")}</div>
                </div>
                <div className={s.read ? "" : "pointer-events-none opacity-50"}>
                  <Segmented<string> size="sm" ariaLabel={t("sync.auto")} value={String(s.auto_every ?? 15)}
                    onChange={(v) => patch.mutate({ auto_every: Number(v) })}
                    options={EVERY.map((m) => ({ value: String(m), label: t(`sync.every_${m}`) }))} />
                </div>
              </div>
              <SwitchRow title={t("sync.write", { name: s.label })} description={locked(s.write, s.write_granted) ? t("sync.locked") : t(s.provider === "google" ? "sync.write_desc" : "sync.write_desc_plain", { name: s.label })}
                checked={!!s.write} disabled={patch.isPending || locked(s.write, s.write_granted)} onChange={(v) => patch.mutate({ write: v })} />
            </div>
            <p className="text-xs text-muted-fg">
              {t("sync.disconnect_where")} <Link href="/app/account#connections" className="font-medium text-accent hover:underline">{t("sync.disconnect_go")}</Link>
            </p>
          </>
        )}
      </CardBody>
    </Card>
  );
}
