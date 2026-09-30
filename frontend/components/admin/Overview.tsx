"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "@/components/icons";
import { Admin } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { fmtCredits, fmtDateTime, fmtRelative } from "@/lib/format";
import { useLocale } from "@/lib/i18n";
import { Page } from "@/components/owner/Shell";
import { Stat, PageHeader, KeyValue } from "@/components/ui/misc";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { buttonLook } from "@/components/ui/button";

export function AdminOverview() {
  const t = useT(); const locale = useLocale();
  const q = useQuery({ queryKey: ["admin", "overview"], queryFn: Admin.overview, refetchInterval: 30_000 });
  const d = q.data;
  return (
    <Page>
      <PageHeader title={t("adm.overview")} description={t("adm.overview_desc")} action={!d?.setup_completed ? <Link href="/admin/setup" className={buttonLook("accent", "md")}>{t("adm.run_setup")}</Link> : null} />
      {q.isLoading || !d ? <Skeleton className="h-40" /> : (
        <>
          {d.default_admin_password_in_use ? (
            <div role="alert" className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
              <ShieldAlert className="h-5 w-5 shrink-0" />
              <span className="flex-1 min-w-[240px]">{t("adm.default_password_desc")}</span>
              <Link href="/app/settings" className={buttonLook("danger", "sm")}>{t("settings.change_password")}</Link>
            </div>
          ) : null}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            <Stat label={t("adm.users")} value={d.users} /><Stat label={t("adm.agents")} value={d.agents} />
            <Stat label={t("adm.turns_today")} value={d.turns_today} /><Stat label={t("adm.credits_today")} value={fmtCredits(d.credits_today)} />
            <Stat label={t("adm.failed_today")} value={d.failed_today} className={d.failed_today ? "border-danger/40" : ""} />
            <Stat label={t("adm.worker")} value={d.worker ? <Badge tone={d.worker.stale ? "danger" : "success"}>{d.worker.stale ? t("adm.stale") : "OK"}</Badge> : <Badge tone="danger">{t("adm.no_worker")}</Badge>} hint={d.worker ? fmtRelative(d.worker.last_seen_at, locale) : undefined} />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card><CardHeader title="Claude Code" action={<Link href="/admin/providers" className="text-xs text-accent">{t("common.manage")}</Link>} />
              <CardBody><KeyValue items={[
                { k: t("adm.cc_mode"), v: d.claude?.auth_mode }, { k: t("adm.cc_version"), v: d.claude?.version ?? "–" },
                { k: t("adm.cc_credentials"), v: d.claude?.credentials_present ? <Badge tone={d.claude.expired ? "danger" : "success"}>{d.claude.expired ? t("adm.expired") : t("adm.present")}</Badge> : <Badge tone="danger">{t("adm.missing")}</Badge> },
                { k: t("adm.cc_subscription"), v: d.claude?.subscription ?? "–" }, { k: t("adm.cc_expires"), v: fmtDateTime(d.claude?.expires_at) },
                { k: t("adm.cc_last_probe"), v: d.claude?.last_probe?.at ? <span>{d.claude.last_probe.ok ? <Badge tone="success">OK</Badge> : <Badge tone="danger">FAIL</Badge>} {fmtRelative(d.claude.last_probe.at, locale)}</span> : "–" },
                // With a pool serving, the rows above describe a credential file nothing is
                // using; how many accounts are actually in rotation is the live number.
                ...(d.claude?.pool?.active ? [{ k: t("adm.pool"), v: <Link href="/admin/providers" className="inline-flex items-center gap-2"><Badge tone={d.claude.pool.eligible ? "success" : "danger"}>{d.claude.pool.eligible}/{d.claude.pool.total}</Badge><span className="text-xs text-accent underline">{t("adm.pool_eligible")}</span></Link> }] : []),
              ]} /></CardBody></Card>
            <Card><CardHeader title={t("adm.providers")} action={<Link href="/admin/providers" className="text-xs text-accent">{t("common.manage")}</Link>} />
              <CardBody>{Object.keys(d.providers_status ?? {}).length ? <ul className="space-y-1.5">{Object.entries<any>(d.providers_status).map(([k, v]) => <li key={k} className="flex items-center justify-between text-sm"><span>{k}</span><span className="flex items-center gap-2"><Badge tone={v.verdict === "ok" ? "success" : "danger"}>{v.verdict}</Badge><span className="text-xs text-muted-fg">{fmtRelative(v.at, locale)}</span></span></li>)}</ul> : <p className="text-sm text-muted-fg">{t("adm.no_providers")}</p>}</CardBody></Card>
            <Card><CardHeader title={t("adm.jobs")} action={<Link href="/admin/jobs" className="text-xs text-accent">{t("common.manage")}</Link>} />
              <CardBody><div className="flex flex-wrap gap-2">{Object.entries<number>(d.jobs ?? {}).map(([s, n]) => <Badge key={s} tone={s === "failed" || s === "dead" ? "danger" : s === "running" ? "accent" : "neutral"}>{s}: {n}</Badge>)}{!Object.keys(d.jobs ?? {}).length ? <span className="text-sm text-muted-fg">–</span> : null}</div></CardBody></Card>
            <Card><CardHeader title={t("adm.recent_users")} action={<Link href="/admin/users" className="text-xs text-accent">{t("common.view_all")}</Link>} />
              <CardBody><ul className="divide-y divide-border">{d.recent_users?.map((u: any) => <li key={u.id} className="flex items-center gap-2 py-1.5 text-sm"><span className="truncate">{u.display_name}</span><span className="truncate text-xs text-muted-fg">{u.email}</span><Badge tone={u.role === "admin" ? "accent" : "outline"} className="ml-auto">{u.role}</Badge><span className="text-xs text-muted-fg">{fmtRelative(u.created_at, locale)}</span></li>)}</ul></CardBody></Card>
          </div>
        </>
      )}
    </Page>
  );
}
