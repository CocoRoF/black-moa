"use client";
import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { RotateCcw, Trash2 } from "@/components/icons";
import { Admin } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { PageHeader } from "@/components/ui/misc";

const STATUSES = ["", "queued", "running", "done", "failed", "dead"];

export function JobsPage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const q = useQuery({ queryKey: ["admin", "jobs", status], queryFn: () => Admin.jobs(status || undefined), refetchInterval: 10_000, placeholderData: keepPreviousData });
  const inval = () => qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
  const retry = useMutation({ mutationFn: (id: string) => Admin.retryJob(id), onSuccess: inval, onError: (e) => toast.error(friendlyError(e, locale)) });
  const discard = useMutation({ mutationFn: (id: string) => Admin.discardJob(id), onSuccess: inval, onError: (e) => toast.error(friendlyError(e, locale)) });
  const d = q.data;
  return (
    <Page>
      <PageHeader title={t("adm.jobs")} description={t("adm.jobs_desc")} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {STATUSES.map((s) => <button key={s} type="button" onClick={() => setStatus(s)} className={cn("rounded-full px-3 py-1.5 text-xs", status === s ? "bg-fg text-bg" : "bg-muted text-muted-fg")}>{s || t("common.all")}{s && d?.counts?.[s] ? ` ${d.counts[s]}` : ""}</button>)}
        <div className="ml-auto flex flex-wrap gap-1.5">{d?.workers.map((w: any) => { const stale = Date.now() - new Date(w.last_seen_at).getTime() > 90_000; return <Badge key={w.id} tone={stale ? "danger" : "success"}>{w.id} · {fmtRelative(w.last_seen_at, locale)}</Badge>; })}{d && !d.workers.length ? <Badge tone="danger">{t("adm.no_worker")}</Badge> : null}</div>
      </div>
      {q.isLoading ? <Skeleton className="h-60" /> : (
        <Table><THead><tr><TH>{t("adm.kind")}</TH><TH>{t("turn.status")}</TH><TH>{t("adm.attempts")}</TH><TH>{t("adm.col_run_at")}</TH><TH>{t("adm.error")}</TH><TH>{t("adm.col_payload")}</TH><TH></TH></tr></THead>
          <TBody>{d?.items.map((j) => <TR key={j.id}><TD className="font-mono text-xs">{j.kind}</TD><TD><Badge tone={j.status === "done" ? "success" : j.status === "failed" || j.status === "dead" ? "danger" : j.status === "running" ? "accent" : "neutral"}>{j.status}</Badge></TD><TD className="tabular-nums">{j.attempts}</TD><TD className="whitespace-nowrap text-xs text-muted-fg">{fmtDateTime(j.run_at)}</TD><TD className="max-w-[240px] truncate text-xs text-danger" title={j.last_error ?? ""}>{j.last_error}</TD><TD className="max-w-[240px] truncate font-mono text-[11px] text-muted-fg" title={JSON.stringify(j.payload)}>{JSON.stringify(j.payload)}</TD>
            <TD><div className="flex gap-1">{j.status !== "queued" && j.status !== "running" ? <Button size="icon-sm" variant="ghost" aria-label={t("adm.retry")} onClick={() => retry.mutate(j.id)}><RotateCcw className="h-4 w-4" /></Button> : null}{j.status !== "dead" && j.status !== "done" ? <Button size="icon-sm" variant="ghost" className="text-danger" aria-label={t("adm.discard")} onClick={() => discard.mutate(j.id)}><Trash2 className="h-4 w-4" /></Button> : null}</div></TD></TR>)}</TBody></Table>
      )}
    </Page>
  );
}
