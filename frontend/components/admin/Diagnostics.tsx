"use client";
import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Cpu, Database, HardDrive } from "@/components/icons";
import { Admin } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { fmtBytes, fmtMs, fmtNumber, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Section } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { KeyValue, Progress, PageHeader, Stat } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Segmented } from "@/components/ui/tabs";
import { DbView } from "./DbView";

type Tab = "server" | "database" | "dbview" | "storage";

/** The machine, in three parts, because that is how it fails.
 *
 *  A single "health" page mixed the process, the database and the object store into one
 *  list of green ticks, which is exactly the shape that hides which of the three is the
 *  problem. Each tab is one component and shows enough of it to act on. */
export function DiagnosticsPage() {
  const t = useT();
  const [tab, setTab] = useState<Tab>("server");
  return (
    <Page>
      <PageHeader title={t("adm.health")} description={t("adm.diag_desc")}
        action={<Segmented value={tab} onChange={(v) => setTab(v as Tab)} options={[
          { value: "server", label: t("adm.diag_server") },
          { value: "database", label: t("adm.diag_db") },
          { value: "dbview", label: t("adm.diag_dbview") },
          { value: "storage", label: t("adm.diag_storage") },
        ]} />} />
      {tab === "server" ? <Server /> : tab === "database" ? <Db /> : tab === "dbview" ? <DbView /> : <Storage />}
    </Page>
  );
}

function useTab(key: string, fn: () => Promise<any>) {
  return useQuery({ queryKey: ["admin", "diag", key], queryFn: fn, refetchInterval: 10_000, placeholderData: keepPreviousData });
}

function Server() {
  const t = useT();
  const q = useTab("server", Admin.diagServer);
  const d = q.data;
  if (!d) return <Skeleton className="h-60" />;
  const memUsed = d.host?.mem_total_mb && d.host?.mem_available_mb ? d.host.mem_total_mb - d.host.mem_available_mb : null;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label={t("adm.diag_rss")} value={d.process?.rss_mb ? `${fmtNumber(d.process.rss_mb)} MB` : "–"} icon={<Cpu />} />
        <Stat label={t("adm.diag_threads")} value={d.process?.threads ?? "–"} hint={t("adm.diag_fds", { n: d.process?.open_files ?? 0 })} />
        <Stat label={t("adm.diag_loop_lag")} value={`${(d.loop_lag_s ?? 0).toFixed(3)}s`} />
        <Stat label={t("adm.llm_sessions")} value={d.sessions ?? 0} hint={t("adm.diag_turns", { n: d.active_turns ?? 0 })} />
        <Stat label={t("adm.diag_load")} value={d.host?.load ? d.host.load.map((x: number) => x.toFixed(2)).join(" ") : "–"}
          hint={d.host?.cpus ? t("adm.diag_cpus", { n: d.host.cpus }) : undefined} />
        <Stat label={t("adm.diag_uptime")} value={d.process?.uptime_s ? hhmm(d.process.uptime_s) : "–"} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Section title={t("adm.diag_resources")}>
          <div className="space-y-3">
            {memUsed !== null ? (
              <Bar label={t("adm.diag_memory")} used={memUsed} total={d.host.mem_total_mb} unit="MB" warn={0.85} />
            ) : null}
            {d.disk?.total_gb ? (
              <Bar label={t("adm.diag_disk")} used={d.disk.total_gb - d.disk.free_gb} total={d.disk.total_gb} unit="GB" warn={0.85} />
            ) : null}
          </div>
        </Section>

        <Section title={t("adm.tr_pools")} description={t("adm.tr_pools_desc")}>
          <div className="space-y-2">
            {Object.entries(d.pools ?? {}).map(([name, p]: [string, any]) => (
              <div key={name}>
                <div className="flex items-baseline justify-between text-xs">
                  <span>{name}</span>
                  <span className="tabular-nums text-muted-fg">
                    {p.in_flight}/{p.size}{p.queued ? <span className="ml-1 text-warning">+{p.queued}</span> : null}
                    <span className="ml-2">{fmtNumber(p.calls)} calls</span>
                  </span>
                </div>
                <Progress className="mt-1 h-1.5" value={p.in_flight} max={p.size} tone={p.queued ? "danger" : "accent"} />
              </div>
            ))}
          </div>
        </Section>
      </div>

      <Section title={t("adm.diag_process")}>
        <KeyValue items={[
          { k: "PID", v: d.process?.pid ?? "–" },
          { k: "Python", v: d.process?.python ?? "–" },
          { k: t("adm.diag_cpu_time"), v: d.process?.cpu_seconds ? `${d.process.cpu_seconds}s` : "–" },
          { k: t("adm.diag_indexes"), v: d.open_indexes ?? 0 },
          { k: t("set.timezone"), v: d.settings?.timezone ?? "–" },
          { k: "PUBLIC_URL", v: d.settings?.public_url ?? "–" },
          { k: t("adm.diag_idle_evict"), v: `${d.settings?.idle_minutes ?? "–"}분` },
          { k: t("adm.diag_max_sessions"), v: d.settings?.max_sessions ?? "–" },
        ]} />
      </Section>
    </div>
  );
}

function Db() {
  const t = useT();
  const q = useTab("database", Admin.diagDatabase);
  const d = q.data;
  if (!d) return <Skeleton className="h-60" />;
  const pool = d.pool ?? {};
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label={t("adm.tr_db_conns")} value={`${pool.checked_out ?? 0}/${pool.capacity ?? 0}`} icon={<Database />} />
        <Stat label={t("turn.status")} value={pool.healthy ? t("adm.tr_db_ok") : t("adm.tr_db_down")} />
        <Stat label={t("adm.diag_db_size")} value={d.size_mb ? `${fmtNumber(d.size_mb)} MB` : "–"} />
        <Stat label={t("adm.diag_db_maxconn")} value={d.max_connections ?? "–"} />
        <Stat label={t("adm.diag_cache_hit")} value={d.cache_hit_ratio !== null && d.cache_hit_ratio !== undefined ? fmtPct(d.cache_hit_ratio) : "–"} />
        <Stat label={t("adm.tr_db_generation")} value={pool.generation ?? "–"}
          hint={pool.reconnects ? t("adm.tr_db_reconnects", { n: pool.reconnects }) : undefined} />
      </div>

      <Section title={t("adm.tr_db")} description={t("adm.tr_db_desc")}>
        <div className="space-y-2">
          {Object.entries(pool.lanes ?? {}).map(([name, l]: [string, any]) => (
            <div key={name}>
              <div className="flex items-baseline justify-between text-xs">
                <span>{name}</span>
                <span className="tabular-nums text-muted-fg">
                  {l.in_use}/{l.ceiling}{l.rejected ? <span className="ml-1 text-danger">{t("adm.tr_db_rejected", { n: l.rejected })}</span> : null}
                </span>
              </div>
              <Progress className="mt-1 h-1.5" value={l.in_use} max={l.ceiling} tone={l.rejected ? "danger" : "accent"} />
            </div>
          ))}
        </div>
        <div className="mt-3 text-xs text-muted-fg">PostgreSQL {d.version ?? "?"}</div>
      </Section>

      {d.long_transactions?.length ? (
        <Section title={t("adm.diag_long_tx")} description={t("adm.diag_long_tx_desc")}>
          <Table><THead><tr><TH>PID</TH><TH>{t("adm.diag_app")}</TH><TH>{t("turn.status")}</TH><TH className="text-right">{t("adm.llm_elapsed")}</TH><TH>{t("adm.diag_query")}</TH></tr></THead>
            <TBody>{d.long_transactions.map((r: any) => (
              <TR key={r.pid}>
                <TD className="tabular-nums">{r.pid}</TD>
                <TD className="text-xs">{r.app}</TD>
                <TD><Badge tone={r.wait ? "danger" : r.state === "active" ? "accent" : "warning"}>{r.state}{r.wait ? ` · ${r.wait}` : ""}</Badge></TD>
                <TD className="text-right tabular-nums">{r.xact_s}s</TD>
                <TD className="max-w-[380px] truncate font-mono text-[11px] text-muted-fg" title={r.query}>{r.query}</TD>
              </TR>))}</TBody></Table>
        </Section>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        <Section title={t("adm.diag_connections")}>
          <Table><THead><tr><TH>{t("adm.diag_app")}</TH><TH>{t("turn.status")}</TH><TH className="text-right">{t("adm.col_count")}</TH><TH className="text-right">{t("adm.wk_oldest")}</TH></tr></THead>
            <TBody>{(d.connections ?? []).map((c: any, i: number) => (
              <TR key={i}>
                <TD className="text-xs">{c.app}</TD>
                <TD><Badge tone={c.state === "active" ? "accent" : c.state === "idle in transaction" ? "warning" : "neutral"}>{c.state}</Badge></TD>
                <TD className="text-right tabular-nums">{c.n}</TD>
                <TD className="text-right tabular-nums">{c.oldest_s}s</TD>
              </TR>))}</TBody></Table>
        </Section>

        <Section title={t("adm.diag_tables")}>
          <Table><THead><tr><TH>{t("adm.diag_table")}</TH><TH className="text-right">{t("adm.diag_rows")}</TH><TH className="text-right">{t("adm.diag_size")}</TH><TH className="text-right">{t("adm.diag_dead")}</TH><TH>{t("adm.diag_vacuum")}</TH></tr></THead>
            <TBody>{(d.tables ?? []).map((r: any) => (
              <TR key={r.table}>
                <TD className="font-mono text-xs">{r.table}</TD>
                <TD className="text-right tabular-nums">{fmtNumber(r.rows)}</TD>
                <TD className="text-right tabular-nums">{r.size_mb} MB</TD>
                <TD className={cn("text-right tabular-nums", r.dead_rows > r.rows * 0.2 && r.dead_rows > 1000 && "text-warning")}>{fmtNumber(r.dead_rows)}</TD>
                <TD className="whitespace-nowrap text-xs text-muted-fg">{r.last_vacuum ?? "–"}</TD>
              </TR>))}</TBody></Table>
        </Section>
      </div>
    </div>
  );
}

function Storage() {
  const t = useT();
  const q = useTab("storage", Admin.diagStorage);
  const d = q.data;
  if (!d) return <Skeleton className="h-60" />;
  const ok = d.health?.ok;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={t("adm.diag_backend")} value={d.mode === "s3" ? "SeaweedFS (S3)" : t("adm.diag_local")} icon={<HardDrive />} />
        <Stat label={t("turn.status")} value={ok ? t("adm.tr_db_ok") : t("adm.tr_db_down")}
          hint={d.latency_ms !== undefined ? fmtMs(d.latency_ms) : undefined} />
        <Stat label={t("adm.diag_objects")} value={d.usage?.objects !== null && d.usage?.objects !== undefined ? fmtNumber(d.usage.objects) : "–"}
          hint={d.usage?.complete === false ? t("adm.diag_partial") : undefined} />
        <Stat label={t("adm.diag_stored")} value={d.usage?.bytes ? fmtBytes(d.usage.bytes) : d.usage?.free_gb ? `${d.usage.free_gb} GB ${t("adm.diag_free")}` : "–"} />
      </div>

      {!ok ? (
        <div className="rounded-2xl border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          {t("adm.diag_storage_down")} · {d.health?.detail ?? d.health?.error ?? ""}
        </div>
      ) : null}

      <Section title={t("adm.diag_endpoint")}>
        <KeyValue items={[
          { k: t("adm.diag_backend"), v: d.health?.backend ?? d.mode },
          { k: "Endpoint", v: d.endpoint || "–" },
          { k: "Bucket", v: d.bucket || "–" },
          { k: t("adm.diag_detail"), v: <span className="break-all">{d.health?.detail ?? d.health?.error ?? "–"}</span> },
        ]} />
      </Section>

      {/* What the application believes it stored, which is the number that should match the
          bucket — a gap between them is an upload that never landed. */}
      <Section title={t("adm.diag_contents")} description={t("adm.diag_contents_desc")}>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-border p-3">
            <div className="text-xs text-muted-fg">{t("adm.diag_uploads")}</div>
            <div className="mt-1 text-xl font-semibold tabular-nums">{fmtNumber(d.uploads?.count ?? 0)}</div>
            <div className="mt-0.5 text-xs text-muted-fg">
              {fmtBytes(d.uploads?.bytes ?? 0)} · {t("adm.diag_in_store", { n: d.uploads?.in_object_store ?? 0 })}
            </div>
          </div>
          <div className="rounded-2xl border border-border p-3">
            <div className="text-xs text-muted-fg">{t("adm.diag_documents")}</div>
            <div className="mt-1 text-xl font-semibold tabular-nums">{fmtNumber(d.documents?.count ?? 0)}</div>
            <div className="mt-0.5 text-xs text-muted-fg">
              {fmtBytes(d.documents?.bytes ?? 0)}
              {d.documents?.failed ? <span className="ml-1 text-danger">· {t("adm.diag_failed_docs", { n: d.documents.failed })}</span> : null}
            </div>
          </div>
        </div>
      </Section>
    </div>
  );
}

function Bar({ label, used, total, unit, warn }: { label: string; used: number; total: number; unit: string; warn: number }) {
  const frac = total ? used / total : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-xs text-muted-fg">{fmtNumber(Math.round(used))} / {fmtNumber(Math.round(total))} {unit}</span>
      </div>
      <Progress className="mt-1" value={used} max={total || 1} tone={frac > warn ? "danger" : frac > warn - 0.15 ? "warning" : "accent"} />
    </div>
  );
}

function hhmm(s: number) {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  return d ? `${d}일 ${h}시간` : h ? `${h}시간 ${Math.floor((s % 3600) / 60)}분` : `${Math.floor(s / 60)}분`;
}
