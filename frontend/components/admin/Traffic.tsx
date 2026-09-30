"use client";
import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, Database, Gauge, Layers, ListChecks, Radio, Users, Server} from "@/components/icons";
import { Admin } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { fmtMs, fmtNumber, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Section } from "@/components/ui/card";
import { Segmented } from "@/components/ui/tabs";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { Bars, PageHeader, Progress, Stat } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

const WINDOWS = ["15", "60", "360", "1440"] as const;

/** Lanes keep one colour everywhere on this page, so a busy stripe in the timeline and a
 *  busy row in the endpoint table are recognisably the same thing. */
const LANE_TONE: Record<string, BadgeTone> = {
  chat: "accent", docs: "warning", admin: "neutral", community: "success", public: "outline", other: "neutral",
};

function laneName(t: (k: string) => string, lane: string) {
  const k = `adm.lane_${lane}`; const v = t(k);
  return v === k ? lane : v;
}

/** How long something has been running, for a number that is still moving. */
function elapsed(ms: number) { return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`; }

export function TrafficPage() {
  const t = useT(); const locale = useLocale();
  const [minutes, setMinutes] = useState<(typeof WINDOWS)[number]>("60");
  const [live, setLive] = useState(true);
  const [order, setOrder] = useState("total_ms");

  // Two speeds on purpose. What is happening now is worth a poll every few seconds; an
  // hour of percentiles is not, and re-aggregating it that often would make the dashboard
  // the heaviest caller in its own table.
  const q = useQuery({ queryKey: ["admin", "traffic", minutes], queryFn: () => Admin.traffic(Number(minutes)),
    refetchInterval: live ? 4_000 : false, placeholderData: keepPreviousData });
  const eps = useQuery({ queryKey: ["admin", "traffic", "endpoints", minutes, order], queryFn: () => Admin.trafficEndpoints(Number(minutes), order),
    refetchInterval: live ? 30_000 : false, placeholderData: keepPreviousData });
  const an = useQuery({ queryKey: ["admin", "traffic", "anomalies", minutes], queryFn: () => Admin.trafficAnomalies(Number(minutes)),
    refetchInterval: live ? 30_000 : false, placeholderData: keepPreviousData });
  const cl = useQuery({ queryKey: ["admin", "traffic", "callers", minutes], queryFn: () => Admin.trafficCallers(Number(minutes)),
    refetchInterval: live ? 30_000 : false, placeholderData: keepPreviousData });
  const wq = useQuery({ queryKey: ["admin", "traffic", "queue"], queryFn: Admin.trafficQueue,
    refetchInterval: live ? 10_000 : false, placeholderData: keepPreviousData });

  const d = q.data;
  const o = d?.summary.overall;
  const errRate = o && o.n ? o.errors / o.n : 0;
  const lagMs = (d?.process.loop_lag_s ?? 0) * 1000;
  const stuck = (d?.in_flight ?? []).filter((r) => r.stuck).length;

  return (
    <Page full>
      <PageHeader title={t("adm.traffic")} description={t("adm.traffic_desc")}
        action={
          <>
            <Segmented value={minutes} onChange={setMinutes} size="sm" ariaLabel={t("adm.tr_window")}
              options={WINDOWS.map((w) => ({ value: w, label: t(`adm.tr_win_${w}`) }))} />
            <label className="inline-flex items-center gap-2 rounded-xl border border-border px-3 text-xs h-9">
              <Radio className={cn("h-3.5 w-3.5", live && "text-success")} />{t("adm.tr_live")}
              <Switch checked={live} onChange={setLive} label={t("adm.tr_live")} />
            </label>
          </>
        } />

      {!d ? <Skeleton className="h-72" /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 2xl:grid-cols-7">
            <Stat label={t("adm.tr_requests")} value={fmtNumber(o!.n)} icon={<Activity />}
              hint={t("adm.tr_served_total", { n: fmtNumber(d.process.served) })} />
            <Stat label={t("adm.tr_answer_time")} value={<span className="text-xl">{fmtMs(o!.p50)} <span className="text-muted-fg">/</span> {fmtMs(o!.p95)}</span>}
              hint={`p50 / p95 · p99 ${fmtMs(o!.p99)} · max ${fmtMs(o!.max_ms)}`} />
            <Stat label={t("adm.tr_errors")} value={fmtNumber(o!.errors)} icon={<AlertTriangle />}
              className={o!.errors ? "border-danger/40" : ""}
              hint={`${(errRate * 100).toFixed(errRate && errRate < 0.01 ? 2 : 1)}% · 429 ${o!.throttled}`} />
            <Stat label={t("adm.tr_slow")} value={fmtNumber(o!.slow)} hint={t("adm.tr_slow_hint")}
              className={o!.slow ? "border-warning/40" : ""} />
            <Stat label={t("adm.tr_longest")} value={fmtMs(o!.longest_ms)} hint={t("adm.tr_longest_hint")} />
            <Stat label={t("adm.tr_loop_lag")} value={fmtMs(lagMs)} icon={<Gauge />}
              className={lagMs > 250 ? "border-danger/40" : lagMs > 80 ? "border-warning/40" : ""}
              hint={t("adm.tr_loop_lag_hint")} />
            <Stat label={t("adm.tr_in_flight")} value={fmtNumber(d.in_flight.length)}
              className={stuck ? "border-danger/40" : ""}
              hint={stuck ? t("adm.tr_stuck_n", { n: stuck }) : t("adm.tr_sessions_n", { n: d.process.sessions })} />
          </div>

          {/* Running right now. First on the page because it is the only thing here that
              cannot wait for a row to be written — a call that has not come back yet. */}
          <Section title={<span className="inline-flex items-center gap-2">{t("adm.tr_now")}<Badge tone={d.in_flight.length ? "accent" : "neutral"}>{d.in_flight.length}</Badge></span>}
            description={t("adm.tr_now_desc")}>
            {!d.in_flight.length ? <div className="py-4 text-sm text-muted-fg">{t("adm.tr_now_empty")}</div> : (
              <Table><THead><tr><TH className="w-full">{t("adm.tr_route")}</TH><TH>{t("adm.tr_lane")}</TH><TH className="text-right">{t("adm.tr_elapsed")}</TH><TH>{t("adm.tr_ip")}</TH><TH>{t("adm.tr_owner")}</TH></tr></THead>
                <TBody>{[...d.in_flight].sort((a, b) => b.elapsed_ms - a.elapsed_ms).map((r) => (
                  <TR key={r.id} className={r.stuck ? "bg-danger/8" : ""}>
                    <TD className="w-full font-mono text-xs"><span className="text-muted-fg">{r.method}</span> {r.route}</TD>
                    <TD><Badge tone={LANE_TONE[r.lane] ?? "neutral"}>{laneName(t, r.lane)}</Badge></TD>
                    <TD className="text-right tabular-nums">
                      {elapsed(r.elapsed_ms)}
                      {r.streaming ? <Badge tone="accent" className="ml-2">{t("adm.tr_streaming")}</Badge> : null}
                      {r.stuck ? <Badge tone="danger" className="ml-2">{r.streaming ? t("adm.tr_silent") : t("adm.tr_stuck")}</Badge> : null}
                    </TD>
                    <TD className="text-xs text-muted-fg">{r.ip}</TD>
                    <TD className="font-mono text-[11px] text-muted-fg">{r.owner_id?.slice(0, 8) ?? "–"}</TD>
                  </TR>))}
                </TBody></Table>
            )}
          </Section>

          <div className="grid gap-4 xl:grid-cols-[3fr_2fr]">
            <Section title={t("adm.tr_timeline")} description={t("adm.tr_timeline_desc")}>
              <Bars height={150} emptyLabel={t("adm.tr_no_data")} format={(v) => fmtNumber(v)}
                data={d.series.map((s) => ({ label: `${new Date(s.at).toLocaleTimeString(locale)} · ${s.n} · p95 ${fmtMs(s.p95_ms)}`, value: s.n, secondary: s.errors }))} />
              <div className="mt-1 flex justify-between text-[10px] text-muted-fg">
                <span>{d.series.length ? new Date(d.series[0].at).toLocaleTimeString(locale) : ""}</span>
                <span>{d.series.length ? new Date(d.series[d.series.length - 1].at).toLocaleTimeString(locale) : ""}</span>
              </div>
            </Section>

            {/* Every process, not just the one that answered. The worker's pools and its
                share of the connection pool live in its own memory and appeared on no
                screen at all before this — a poor place to tune an allocation from. */}
            {d.fleet?.processes?.length ? (
              <Section title={<span className="inline-flex items-center gap-2"><Server className="h-4 w-4" />{t("adm.tr_fleet")}</span>}
                description={t("adm.tr_fleet_desc")}>
                <Table><THead><tr>
                  <TH>{t("adm.tr_process")}</TH><TH className="text-right">{t("adm.tr_threads")}</TH>
                  <TH className="text-right">{t("adm.tr_db")}</TH><TH className="text-right">{t("adm.tr_lag")}</TH>
                  <TH className="text-right">{t("adm.tr_seen")}</TH>
                </tr></THead>
                  <TBody>{d.fleet.processes.map((p) => {
                    const threads = Object.values(p.pools ?? {}).reduce((a: number, x: any) => a + (x.size ?? 0), 0);
                    const busy = Object.values(p.pools ?? {}).reduce((a: number, x: any) => a + (x.in_flight ?? 0), 0);
                    return (
                      <TR key={p.key} className={p.fresh ? "" : "opacity-50"}>
                        <TD className="font-mono text-xs">
                          <Badge tone={p.role === "worker" ? "outline" : "accent"}>{p.role}</Badge>{" "}{p.key.split(":").slice(1).join(":")}
                          {p.worker ? <span className="ml-2 text-[11px] text-muted-fg">{t("adm.tr_slots")} {p.worker.concurrency}</span> : null}
                        </TD>
                        <TD className="text-right tabular-nums">{busy}/{threads}</TD>
                        <TD className="text-right tabular-nums">{p.db?.checked_out ?? 0}/{p.db?.capacity ?? 0}</TD>
                        <TD className="text-right tabular-nums">{fmtMs((p.loop_lag_s ?? 0) * 1000)}</TD>
                        <TD className="text-right tabular-nums text-xs">
                          {p.fresh ? `${Math.round(p.age_s)}s` : <Badge tone="danger">{t("adm.tr_stale")}</Badge>}
                        </TD>
                      </TR>
                    );
                  })}</TBody></Table>
                <div className="mt-2 text-[11px] text-muted-fg tabular-nums">
                  {t("adm.tr_fleet_total", {
                    threads: Object.values(d.fleet.pools ?? {}).reduce((a: number, x: any) => a + (x.size ?? 0), 0),
                    conns: d.fleet.db?.capacity ?? 0,
                  })}
                </div>
              </Section>
            ) : null}

            {/* The isolation, as a number. Each class of blocking work has its own threads;
                a full pool with a queue behind it is the thing to see before users feel it. */}
            <Section title={<span className="inline-flex items-center gap-2"><Layers className="h-4 w-4" />{t("adm.tr_pools")}</span>}
              description={t("adm.tr_pools_desc")}>
              <div className="space-y-3">
                {Object.entries(d.process.pools).map(([name, p]) => (
                  <div key={name}>
                    <div className="flex items-baseline justify-between gap-2 text-sm">
                      <span className="font-medium">{laneName(t, name)}</span>
                      <span className="tabular-nums text-xs text-muted-fg">
                        {p.in_flight}/{p.size}{p.queued ? <span className="ml-1 text-warning">+{p.queued} {t("adm.tr_queued")}</span> : null}
                      </span>
                    </div>
                    <Progress className="mt-1" value={p.in_flight} max={p.size} tone={p.queued ? "danger" : p.in_flight >= p.size ? "warning" : "accent"} />
                    <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-muted-fg tabular-nums">
                      <span>{t("adm.tr_calls")} {fmtNumber(p.calls)}</span>
                      <span>{t("adm.tr_avg_wait")} {fmtMs(p.avg_wait_ms)}</span>
                      <span>{t("adm.tr_avg_run")} {fmtMs(p.avg_run_ms)}</span>
                      {p.slowest ? <span className="truncate" title={p.slowest}>{t("adm.tr_slowest")} {fmtMs(p.slowest_ms)} · {p.slowest}</span> : null}
                    </div>
                  </div>
                ))}
              </div>
              {d.process.dropped ? <div className="mt-3 text-xs text-danger">{t("adm.tr_dropped", { n: d.process.dropped })}</div> : null}
            </Section>

            {/* The pool everything shares. It is the layer that actually ran out — streams
                used to hold a connection each — so it is shown the same way as the threads:
                who is holding what, and whether anybody was turned away. */}
            <Section title={<span className="inline-flex items-center gap-2"><Database className="h-4 w-4" />{t("adm.tr_db")}</span>}
              description={t("adm.tr_db_desc")}
              action={<Badge tone={d.process.db.healthy ? "success" : "danger"}>
                {d.process.db.healthy ? t("adm.tr_db_ok") : t("adm.tr_db_down")}
              </Badge>}>
              <div className="mb-3 flex items-baseline justify-between gap-2 text-sm">
                <span className="font-medium">{t("adm.tr_db_conns")}</span>
                <span className="tabular-nums text-xs text-muted-fg">{d.process.db.checked_out}/{d.process.db.capacity}</span>
              </div>
              <Progress value={d.process.db.checked_out} max={d.process.db.capacity}
                tone={d.process.db.checked_out >= d.process.db.capacity ? "danger" : "accent"} />
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-fg tabular-nums">
                <span>{t("adm.tr_db_generation")} {d.process.db.generation}</span>
                {d.process.db.reconnects ? <span className="text-warning">{t("adm.tr_db_reconnects", { n: d.process.db.reconnects })}</span> : null}
                {d.process.db.retries ? <span className="text-warning">{t("adm.tr_db_retries", { n: d.process.db.retries })}</span> : null}
                {d.process.db.last_error ? <span className="truncate text-danger" title={d.process.db.last_error}>{d.process.db.last_error}</span> : null}
              </div>
              <div className="mt-3 space-y-2">
                {Object.entries(d.process.db.lanes).map(([name, l]) => (
                  <div key={name}>
                    <div className="flex items-baseline justify-between gap-2 text-xs">
                      <span>{laneName(t, name)}</span>
                      <span className="tabular-nums text-muted-fg">
                        {l.in_use}/{l.ceiling}
                        {l.rejected ? <span className="ml-1 text-danger">{t("adm.tr_db_rejected", { n: l.rejected })}</span> : null}
                      </span>
                    </div>
                    <Progress className="mt-1 h-1.5" value={l.in_use} max={l.ceiling}
                      tone={l.rejected ? "danger" : l.in_use >= l.ceiling ? "warning" : "accent"} />
                  </div>
                ))}
              </div>
            </Section>
          </div>

          <Section title={t("adm.tr_lanes")} description={t("adm.tr_lanes_desc")}>
            {!d.summary.lanes.length ? <div className="py-3 text-sm text-muted-fg">{t("adm.tr_no_data")}</div> : (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {d.summary.lanes.map((l) => (
                  <div key={l.lane} className="rounded-2xl border border-border p-3">
                    <div className="flex items-center justify-between">
                      <Badge tone={LANE_TONE[l.lane] ?? "neutral"}>{laneName(t, l.lane)}</Badge>
                      <span className="tabular-nums text-sm font-medium">{fmtNumber(l.n)}</span>
                    </div>
                    <Progress className="mt-2" value={l.n} max={o!.n || 1} tone={l.errors ? "danger" : "accent"} />
                    <div className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-muted-fg tabular-nums">
                      <span>p95 {fmtMs(l.p95_ms)}</span><span>avg {fmtMs(l.avg_ms)}</span><span>max {fmtMs(l.max_ms)}</span>
                      {l.errors ? <span className="text-danger">{t("adm.tr_errors")} {l.errors}</span> : null}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Section>

          <Section title={t("adm.tr_endpoints")} description={t("adm.tr_endpoints_desc")}
            action={<Segmented size="sm" value={order} onChange={setOrder} ariaLabel={t("adm.col_sort")}
              options={[{ value: "total_ms", label: t("adm.tr_by_total") }, { value: "p95", label: "p95" },
                        { value: "calls", label: t("adm.tr_by_calls") }, { value: "errors", label: t("adm.tr_errors") }]} />}>
            <Table><THead><tr><TH className="w-full">{t("adm.tr_route")}</TH><TH>{t("adm.tr_lane")}</TH><TH className="text-right">{t("adm.tr_by_calls")}</TH><TH className="text-right">avg</TH><TH className="text-right">p95</TH><TH className="text-right">max</TH><TH className="text-right">{t("adm.tr_total_time")}</TH><TH className="text-right">{t("adm.tr_errors")}</TH></tr></THead>
              <TBody>{(eps.data?.items ?? []).map((r, i) => (
                <TR key={`${r.method}${r.route}${i}`}>
                  <TD className="w-full font-mono text-xs"><span className="text-muted-fg">{r.method}</span> {r.route}</TD>
                  <TD><Badge tone={LANE_TONE[r.lane] ?? "neutral"}>{laneName(t, r.lane)}</Badge></TD>
                  <TD className="text-right tabular-nums">{fmtNumber(r.n)}</TD>
                  <TD className="text-right tabular-nums">{fmtMs(r.avg_ms)}</TD>
                  <TD className="text-right tabular-nums">{fmtMs(r.p95_ms)}</TD>
                  <TD className="text-right tabular-nums">{fmtMs(r.max_ms)}</TD>
                  <TD className="text-right tabular-nums font-medium">{fmtMs(r.total_ms)}</TD>
                  <TD className="text-right tabular-nums">{r.errors ? <span className="text-danger">{r.errors}</span> : "–"}{r.throttled ? <Badge tone="warning" className="ml-1">429 {r.throttled}</Badge> : null}</TD>
                </TR>))}
                {!eps.data?.items.length ? <TR><TD colSpan={8} className="text-sm text-muted-fg">{t("adm.tr_no_data")}</TD></TR> : null}
              </TBody></Table>
          </Section>

          {/* The list the whole dashboard exists for: calls that took absurdly long, or held
              the event loop while they ran. */}
          <Section title={<span className="inline-flex items-center gap-2"><AlertTriangle className="h-4 w-4" />{t("adm.tr_anomalies")}</span>}
            description={t("adm.tr_anomalies_desc")}>
            <Table><THead><tr><TH>{t("adm.tr_when")}</TH><TH className="w-full">{t("adm.tr_route")}</TH><TH>{t("adm.tr_lane")}</TH><TH className="text-right">{t("turn.status")}</TH><TH className="text-right">{t("adm.tr_answered_in")}</TH><TH className="text-right">{t("adm.tr_held")}</TH><TH className="text-right">{t("adm.tr_lag")}</TH><TH>{t("adm.tr_ip")}</TH><TH>{t("adm.error")}</TH></tr></THead>
              <TBody>{(an.data?.items ?? []).map((r, i) => (
                <TR key={i}>
                  <TD className="whitespace-nowrap text-xs text-muted-fg">{fmtRelative(r.at, locale)}</TD>
                  <TD className="w-full font-mono text-xs"><span className="text-muted-fg">{r.method}</span> {r.route}</TD>
                  <TD><Badge tone={LANE_TONE[r.lane] ?? "neutral"}>{laneName(t, r.lane)}</Badge></TD>
                  <TD className="text-right"><Badge tone={r.status >= 500 ? "danger" : r.status === 429 ? "warning" : "neutral"}>{r.status}</Badge></TD>
                  <TD className={cn("text-right tabular-nums", r.ttfb_ms > 10000 && "text-danger font-medium")}>{fmtMs(r.ttfb_ms)}</TD>
                  <TD className="text-right tabular-nums">{fmtMs(r.ms)}</TD>
                  <TD className={cn("text-right tabular-nums", r.lag_ms > 1000 && "text-danger font-medium")}>{r.lag_ms ? fmtMs(r.lag_ms) : "–"}</TD>
                  <TD className="text-xs text-muted-fg">{r.ip}</TD>
                  <TD className="max-w-[260px] truncate text-xs text-danger" title={r.error ?? ""}>{r.error}</TD>
                </TR>))}
                {!an.data?.items.length ? <TR><TD colSpan={9} className="text-sm text-muted-fg">{t("adm.tr_anomalies_none")}</TD></TR> : null}
              </TBody></Table>
          </Section>

          <div className="grid gap-4 xl:grid-cols-2">
            <Section title={<span className="inline-flex items-center gap-2"><Users className="h-4 w-4" />{t("adm.tr_callers")}</span>}
              description={t("adm.tr_callers_desc")}>
              <Table><THead><tr><TH>{t("adm.tr_owner")}</TH><TH>{t("adm.tr_ip")}</TH><TH className="text-right">{t("adm.tr_by_calls")}</TH><TH className="text-right">{t("adm.tr_total_time")}</TH><TH className="text-right">{t("adm.tr_errors")}</TH></tr></THead>
                <TBody>{(cl.data?.items ?? []).map((r, i) => (
                  <TR key={i}>
                    <TD className="max-w-[220px] truncate text-xs" title={r.email ?? r.owner_id ?? ""}>
                      {r.email ? <>{r.name ? <span className="font-medium">{r.name} </span> : null}<span className="text-muted-fg">{r.email}</span></>
                        : r.owner_id ? <span className="font-mono text-[11px]">{r.owner_id.slice(0, 8)}</span>
                        : <span className="text-muted-fg">{t("adm.tr_anonymous")}</span>}
                    </TD>
                    <TD className="text-xs text-muted-fg">{r.ip}</TD>
                    <TD className="text-right tabular-nums">{fmtNumber(r.n)}</TD>
                    <TD className="text-right tabular-nums">{fmtMs(r.total_ms)}</TD>
                    <TD className="text-right tabular-nums">{r.errors || "–"}{r.throttled ? <Badge tone="warning" className="ml-1">429 {r.throttled}</Badge> : null}</TD>
                  </TR>))}
                  {!cl.data?.items.length ? <TR><TD colSpan={5} className="text-sm text-muted-fg">{t("adm.tr_no_data")}</TD></TR> : null}
                </TBody></Table>
            </Section>

            {/* The worker's side of the same question: none of the above matters if the
                queue is not moving. */}
            <Section title={<span className="inline-flex items-center gap-2"><ListChecks className="h-4 w-4" />{t("adm.tr_queue")}</span>}
              description={t("adm.tr_queue_desc")}>
              <Table><THead><tr><TH>{t("adm.kind")}</TH><TH>{t("turn.status")}</TH><TH className="text-right">{t("adm.col_count")}</TH><TH className="text-right">{t("adm.tr_oldest")}</TH></tr></THead>
                <TBody>{(wq.data?.items ?? []).map((r, i) => (
                  <TR key={i}>
                    <TD className="font-mono text-xs">{r.kind}</TD>
                    <TD><Badge tone={r.status === "running" ? "accent" : "neutral"}>{r.status}</Badge></TD>
                    <TD className="text-right tabular-nums">{r.n}</TD>
                    <TD className={cn("text-right tabular-nums", r.oldest_running_s > 300 && "text-danger font-medium")}>{r.oldest_running_s ? `${Math.round(r.oldest_running_s)}s` : "–"}</TD>
                  </TR>))}
                  {!wq.data?.items.length ? <TR><TD colSpan={4} className="text-sm text-muted-fg">{t("adm.tr_queue_empty")}</TD></TR> : null}
                </TBody></Table>
              {wq.data?.dead_last_day ? <div className="mt-3 text-xs text-danger">{t("adm.tr_dead_jobs", { n: wq.data.dead_last_day })}</div> : null}
            </Section>
          </div>
        </div>
      )}
    </Page>
  );
}
