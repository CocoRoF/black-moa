"use client";
import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Layers, RotateCcw, Trash2, Users } from "@/components/icons";
import { Admin } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtDateTime, fmtNumber, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Section } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Bars, Progress, PageHeader, Stat } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Segmented } from "@/components/ui/tabs";

const STATUSES = ["", "queued", "running", "done", "failed", "dead"];

function secs(s: number) {
  if (s < 1) return `${Math.round(s * 1000)}ms`;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}분 ${Math.round(s % 60)}초`;
  return `${Math.floor(s / 3600)}시간 ${Math.round((s % 3600) / 60)}분`;
}

/** The worker, and the queue it is working through.
 *
 *  The list of rows is still here because it is what you need once you know *which* job to
 *  look at — but it is no longer the whole page. Everything above it answers the questions
 *  the list made you eyeball: is the queue keeping up, which kind fails, what is running
 *  right now, and is one person's bulk import holding up everybody else's work. */
export function WorkersPage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [hours, setHours] = useState("24");
  const [status, setStatus] = useState("");
  const ov = useQuery({ queryKey: ["admin", "jobs", "overview", hours], queryFn: () => Admin.jobsOverview(Number(hours)),
                        refetchInterval: 10_000, placeholderData: keepPreviousData });
  const list = useQuery({ queryKey: ["admin", "jobs", status], queryFn: () => Admin.jobs(status || undefined),
                          refetchInterval: 15_000, placeholderData: keepPreviousData });
  const inval = () => { qc.invalidateQueries({ queryKey: ["admin", "jobs"] }); };
  const retry = useMutation({ mutationFn: (id: string) => Admin.retryJob(id), onSuccess: inval, onError: (e) => toast.error(friendlyError(e, locale)) });
  const discard = useMutation({ mutationFn: (id: string) => Admin.discardJob(id), onSuccess: inval, onError: (e) => toast.error(friendlyError(e, locale)) });

  const d = ov.data;
  const totals = d?.kinds.reduce((a, k) => ({
    queued: a.queued + k.queued, running: a.running + k.running,
    done: a.done + k.done, failed: a.failed + k.failed + k.dead,
  }), { queued: 0, running: 0, done: 0, failed: 0 });
  const worstWait = d?.kinds.reduce((m, k) => Math.max(m, k.oldest_wait_s), 0) ?? 0;
  const live = d?.workers.filter((w) => !w.stale).length ?? 0;

  return (
    <Page>
      <PageHeader title={t("adm.jobs")} description={t("adm.jobs_desc")}
        action={<Segmented value={hours} onChange={setHours} options={[{ value: "1", label: "1h" }, { value: "24", label: "24h" }, { value: "168", label: "7d" }]} />} />

      {!d ? <Skeleton className="h-60" /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Stat label={t("adm.wk_queued")} value={fmtNumber(totals!.queued)}
              hint={worstWait > 60 ? <span className="text-warning">{t("adm.wk_oldest")} {secs(worstWait)}</span> : undefined} />
            <Stat label={t("adm.wk_running")} value={`${totals!.running}/${d.limits.concurrency}`} />
            <Stat label={t("adm.wk_done")} value={fmtNumber(totals!.done)} hint={t("adm.wk_window", { h: d.window_hours })} />
            <Stat label={t("adm.wk_failed")} value={fmtNumber(totals!.failed)} />
            <Stat label={t("adm.wk_workers")} value={live}
              hint={!live ? <span className="text-danger">{t("adm.no_worker")}</span> : undefined} />
            <Stat label={t("adm.wk_waiting_owners")} value={d.owners.length} icon={<Users />} />
          </div>

          {!live ? (
            <div className="flex items-center gap-2 rounded-2xl border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
              <AlertTriangle className="h-4 w-4" />{t("adm.wk_no_worker_warn")}
            </div>
          ) : null}

          <div className="grid gap-4 xl:grid-cols-2">
            <Section title={t("adm.wk_throughput")} description={t("adm.wk_throughput_desc")}>
              <Bars height={140} emptyLabel={t("adm.tr_no_data")}
                data={d.series.map((s) => ({ label: `${new Date(s.at).toLocaleString(locale)} · ${s.done} · ${secs(s.avg_s)}`, value: s.done, secondary: s.failed }))} />
              <div className="mt-1 flex justify-between text-[10px] text-muted-fg">
                <span>{d.series.length ? new Date(d.series[0].at).toLocaleString(locale) : ""}</span>
                <span>{d.series.length ? new Date(d.series[d.series.length - 1].at).toLocaleString(locale) : ""}</span>
              </div>
            </Section>

            {/* The ceilings, beside what is running: a queue that is not moving should be
                readable against the rule that is holding it. */}
            <Section title={<span className="inline-flex items-center gap-2"><Layers className="h-4 w-4" />{t("adm.wk_limits")}</span>}
              description={t("adm.wk_limits_desc")}>
              <div className="space-y-3">
                <div>
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="font-medium">{t("adm.wk_slots")}</span>
                    <span className="tabular-nums text-xs text-muted-fg">{totals!.running}/{d.limits.concurrency}</span>
                  </div>
                  <Progress className="mt-1" value={totals!.running} max={d.limits.concurrency}
                    tone={totals!.running >= d.limits.concurrency ? "warning" : "accent"} />
                </div>
                {Object.entries(d.limits.classes).map(([cls, limit]) => {
                  const kinds = Object.entries(d.limits.kind_class).filter(([, c]) => c === cls).map(([k]) => k);
                  const inUse = d.kinds.filter((k) => kinds.includes(k.kind)).reduce((n, k) => n + k.running, 0);
                  return (
                    <div key={cls}>
                      <div className="flex items-baseline justify-between text-xs">
                        <span>{t("adm.wk_class")} · {cls}</span>
                        <span className="tabular-nums text-muted-fg">{inUse}/{limit}</span>
                      </div>
                      <Progress className="mt-1 h-1.5" value={inUse} max={limit} tone={inUse >= limit ? "warning" : "accent"} />
                    </div>
                  );
                })}
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {Object.entries(d.limits.kinds).map(([k, n]) => <Badge key={k} tone="outline">{k} ≤ {n}</Badge>)}
                </div>
              </div>
            </Section>
          </div>

          <Section title={t("adm.wk_by_kind")} description={t("adm.wk_by_kind_desc")}>
            <Table><THead><tr><TH>{t("adm.kind")}</TH><TH className="text-right">{t("adm.wk_queued")}</TH><TH className="text-right">{t("adm.wk_running")}</TH><TH className="text-right">{t("adm.wk_done")}</TH><TH className="text-right">{t("adm.wk_failed")}</TH><TH className="text-right">{t("adm.wk_avg")}</TH><TH className="text-right">p95</TH><TH className="text-right">{t("adm.wk_oldest")}</TH></tr></THead>
              <TBody>{d.kinds.map((k) => (
                <TR key={k.kind}>
                  <TD className="font-mono text-xs">{k.kind}</TD>
                  <TD className={cn("text-right tabular-nums", k.queued > 20 && "text-warning font-medium")}>{k.queued}</TD>
                  <TD className="text-right tabular-nums">{k.running}</TD>
                  <TD className="text-right tabular-nums">{fmtNumber(k.done)}</TD>
                  <TD className={cn("text-right tabular-nums", (k.failed + k.dead) > 0 && "text-danger")}>{k.failed + k.dead}</TD>
                  <TD className="text-right tabular-nums">{k.done ? secs(k.avg_s) : "–"}</TD>
                  <TD className="text-right tabular-nums">{k.done ? secs(k.p95_s) : "–"}</TD>
                  <TD className={cn("text-right tabular-nums", k.oldest_wait_s > 300 && "text-warning")}>{k.queued ? secs(k.oldest_wait_s) : "–"}</TD>
                </TR>))}</TBody></Table>
          </Section>

          <div className="grid gap-4 xl:grid-cols-2">
            <Section title={t("adm.wk_now")} description={t("adm.wk_now_desc")}>
              {!d.running.length ? <div className="py-3 text-sm text-muted-fg">{t("adm.wk_idle")}</div> : (
                <Table><THead><tr><TH>{t("adm.kind")}</TH><TH>{t("adm.wk_worker")}</TH><TH className="text-right">{t("adm.attempts")}</TH><TH className="text-right">{t("adm.llm_elapsed")}</TH></tr></THead>
                  <TBody>{d.running.map((r) => (
                    <TR key={r.id} className={r.elapsed_s > 300 ? "bg-warning/5" : undefined}>
                      <TD className="font-mono text-xs">{r.kind}</TD>
                      <TD className="text-xs text-muted-fg">{r.worker}</TD>
                      <TD className="text-right tabular-nums">{r.attempts}</TD>
                      <TD className="text-right tabular-nums">{secs(r.elapsed_s)}</TD>
                    </TR>))}</TBody></Table>
              )}
            </Section>

            {/* Fairness, visible: the queue is round-robin across owners, so this is the
                view that shows it working — or shows who is waiting behind whom. */}
            <Section title={t("adm.wk_fairness")} description={t("adm.wk_fairness_desc")}>
              {!d.owners.length ? <div className="py-3 text-sm text-muted-fg">{t("adm.wk_queue_empty")}</div> : (
                <Table><THead><tr><TH>{t("adm.wk_owner")}</TH><TH className="text-right">{t("adm.wk_queued")}</TH><TH className="text-right">{t("adm.wk_oldest")}</TH></tr></THead>
                  <TBody>{d.owners.map((o) => (
                    <TR key={o.owner_id ?? "service"}>
                      <TD className="truncate">{o.name}</TD>
                      <TD className="text-right tabular-nums">{fmtNumber(o.queued)}</TD>
                      <TD className={cn("text-right tabular-nums", o.oldest_wait_s > 300 && "text-warning")}>{secs(o.oldest_wait_s)}</TD>
                    </TR>))}</TBody></Table>
              )}
            </Section>
          </div>

          <Section title={t("adm.wk_heartbeats")}>
            <div className="flex flex-wrap gap-1.5">
              {d.workers.map((w) => <Badge key={w.id} tone={w.stale ? "danger" : "success"}>{w.id} · {fmtRelative(w.last_seen_at, locale)}</Badge>)}
              {!d.workers.length ? <Badge tone="danger">{t("adm.no_worker")}</Badge> : null}
            </div>
          </Section>

          {/* The rows, for when you know which job you are looking for. */}
          <Section title={t("adm.wk_rows")} description={t("adm.wk_rows_desc")}>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              {STATUSES.map((s) => (
                <button key={s} type="button" onClick={() => setStatus(s)}
                  className={cn("rounded-full px-3 py-1.5 text-xs", status === s ? "bg-fg text-bg" : "bg-muted text-muted-fg")}>
                  {s || t("common.all")}{s && list.data?.counts?.[s] ? ` ${list.data.counts[s]}` : ""}
                </button>
              ))}
            </div>
            {list.isLoading ? <Skeleton className="h-40" /> : (
              <Table><THead><tr><TH>{t("adm.kind")}</TH><TH>{t("turn.status")}</TH><TH>{t("adm.attempts")}</TH><TH>{t("adm.col_run_at")}</TH><TH>{t("adm.error")}</TH><TH>{t("adm.col_payload")}</TH><TH></TH></tr></THead>
                <TBody>{list.data?.items.map((j: any) => (
                  <TR key={j.id}>
                    <TD className="font-mono text-xs">{j.kind}</TD>
                    <TD><Badge tone={j.status === "done" ? "success" : j.status === "failed" || j.status === "dead" ? "danger" : j.status === "running" ? "accent" : "neutral"}>{j.status}</Badge></TD>
                    <TD className="tabular-nums">{j.attempts}</TD>
                    <TD className="whitespace-nowrap text-xs text-muted-fg">{fmtDateTime(j.run_at)}</TD>
                    <TD className="max-w-[220px] truncate text-xs text-danger" title={j.last_error ?? ""}>{j.last_error}</TD>
                    <TD className="max-w-[220px] truncate font-mono text-[11px] text-muted-fg" title={JSON.stringify(j.payload)}>{JSON.stringify(j.payload)}</TD>
                    <TD><div className="flex gap-1">
                      {j.status !== "queued" && j.status !== "running" ? <Button size="icon-sm" variant="ghost" aria-label={t("adm.retry")} onClick={() => retry.mutate(j.id)}><RotateCcw className="h-4 w-4" /></Button> : null}
                      {j.status !== "dead" && j.status !== "done" ? <Button size="icon-sm" variant="ghost" className="text-danger" aria-label={t("adm.discard")} onClick={() => discard.mutate(j.id)}><Trash2 className="h-4 w-4" /></Button> : null}
                    </div></TD>
                  </TR>))}</TBody></Table>
            )}
          </Section>
        </div>
      )}
    </Page>
  );
}
