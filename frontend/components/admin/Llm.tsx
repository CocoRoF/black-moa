"use client";
import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, BrainCircuit, Cpu, KeyRound, MessagesSquare, Radio, X } from "@/components/icons";
import { Admin, type LlmOverview, type LlmSession } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtMs, fmtNumber, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Section } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress, PageHeader, Stat } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Segmented } from "@/components/ui/tabs";

/** Seconds as something a person reads at a glance while it is still moving. */
function secs(s: number | null | undefined) {
  if (s === null || s === undefined) return "–";
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}분 ${Math.round(s % 60)}초`;
  return `${Math.floor(s / 3600)}시간 ${Math.round((s % 3600) / 60)}분`;
}

export function LlmPage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [tab, setTab] = useState<"live" | "providers" | "sessions">("live");
  const q = useQuery({ queryKey: ["admin", "llm"], queryFn: Admin.llm, refetchInterval: 5000, placeholderData: keepPreviousData });
  const close = useMutation({
    mutationFn: (key: string) => Admin.closeSession(key),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin", "llm"] }); toast.success(t("adm.llm_session_closed")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const d = q.data;
  const pool = d?.load.llm_pool;

  return (
    <Page>
      <PageHeader title={t("adm.llm")} description={t("adm.llm_desc")}
        action={<Segmented value={tab} onChange={(v) => setTab(v as typeof tab)} options={[
          { value: "live", label: t("adm.llm_tab_live") },
          { value: "providers", label: t("adm.llm_tab_providers") },
          { value: "sessions", label: t("adm.llm_tab_sessions") },
        ]} />} />

      {!d ? <Skeleton className="h-60" /> : (
        <div className="space-y-4">
          {/* The headline: how much, how fast, how much is failing, and what it costs. */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Stat label={t("adm.llm_calls")} value={fmtNumber(d.totals.calls)} icon={<BrainCircuit />} />
            <Stat label={t("adm.llm_in_flight")} value={d.totals.in_flight}
              hint={d.totals.stuck ? <span className="text-danger">{t("adm.llm_stuck_n", { n: d.totals.stuck })}</span> : undefined} icon={<Radio />} />
            <Stat label={t("adm.llm_avg")} value={fmtMs(d.totals.avg_ms)} />
            <Stat label={t("adm.llm_errors")} value={fmtPct(d.totals.error_rate)}
              hint={`${fmtNumber(d.totals.failures)} / ${fmtNumber(d.totals.calls)}`} />
            <Stat label={t("adm.llm_sessions")} value={d.sessions.length} icon={<MessagesSquare />} />
            <Stat label={t("adm.llm_tokens")} value={`${fmtNumber(d.totals.input_tokens)} / ${fmtNumber(d.totals.output_tokens)}`}
              hint={t("adm.llm_tokens_hint")} />
          </div>

          {/* What the calls cost the machine — the reason this page and the traffic page
              belong to the same section. */}
          <Section title={<span className="inline-flex items-center gap-2"><Cpu className="h-4 w-4" />{t("adm.llm_load")}</span>}
            description={t("adm.llm_load_desc")}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <div className="flex items-baseline justify-between text-sm">
                  <span className="font-medium">{t("adm.llm_threads")}</span>
                  <span className="tabular-nums text-xs text-muted-fg">
                    {pool?.in_flight ?? 0}/{pool?.size ?? 0}
                    {pool?.queued ? <span className="ml-1 text-warning">+{pool.queued} {t("adm.tr_queued")}</span> : null}
                  </span>
                </div>
                <Progress className="mt-1" value={pool?.in_flight ?? 0} max={pool?.size || 1}
                  tone={pool?.queued ? "danger" : (pool?.in_flight ?? 0) >= (pool?.size ?? 1) ? "warning" : "accent"} />
                <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] tabular-nums text-muted-fg">
                  <span>{t("adm.tr_avg_wait")} {fmtMs(pool?.avg_wait_ms ?? 0)}</span>
                  <span>{t("adm.tr_avg_run")} {fmtMs(pool?.avg_run_ms ?? 0)}</span>
                </div>
              </div>
              <div>
                <div className="flex items-baseline justify-between text-sm">
                  <span className="font-medium">{t("adm.tr_loop_lag")}</span>
                  <span className={cn("tabular-nums text-xs", d.load.loop_lag_s > 0.5 ? "text-danger" : "text-muted-fg")}>
                    {d.load.loop_lag_s.toFixed(3)}s
                  </span>
                </div>
                <Progress className="mt-1" value={Math.min(d.load.loop_lag_s, 1)} max={1}
                  tone={d.load.loop_lag_s > 0.5 ? "danger" : d.load.loop_lag_s > 0.1 ? "warning" : "success"} />
                <div className="mt-1 text-[11px] text-muted-fg">{t("adm.llm_lag_hint")}</div>
              </div>
            </div>
          </Section>

          {tab === "live" ? <Live d={d} /> : null}
          {tab === "providers" ? <Providers d={d} /> : null}
          {tab === "sessions" ? <Sessions d={d} onClose={(k) => close.mutate(k)} closing={close.isPending} /> : null}
        </div>
      )}
    </Page>
  );
}

function Live({ d }: { d: LlmOverview }) {
  const t = useT();
  return (
    <>
      <Section title={t("adm.llm_now")} description={t("adm.llm_now_desc")}>
        {!d.in_flight.length ? <div className="py-3 text-sm text-muted-fg">{t("adm.llm_idle")}</div> : (
          <Table><THead><tr><TH>{t("adm.llm_kind")}</TH><TH>{t("adm.m_provider")}</TH><TH>{t("adm.m_model")}</TH><TH>{t("adm.llm_account")}</TH><TH className="text-right">{t("adm.llm_elapsed")}</TH></tr></THead>
            <TBody>{d.in_flight.map((c) => (
              <TR key={c.id} className={c.stuck ? "bg-danger/5" : undefined}>
                <TD><Badge tone={c.kind === "turn" ? "accent" : "neutral"}>{c.kind}</Badge></TD>
                <TD className="text-xs">{c.provider}</TD>
                <TD className="font-mono text-[11px]">{c.model}</TD>
                <TD className="text-xs text-muted-fg">{c.account || "–"}</TD>
                <TD className="text-right tabular-nums">
                  {secs(c.elapsed_ms / 1000)}
                  {c.stuck ? <Badge tone="danger" className="ml-2"><AlertTriangle className="h-3 w-3" />{t("adm.tr_stuck")}</Badge> : null}
                </TD>
              </TR>))}</TBody></Table>
        )}
      </Section>

      <Section title={t("adm.llm_recent")} description={t("adm.llm_recent_desc")}>
        <Table><THead><tr><TH>{t("adm.llm_kind")}</TH><TH>{t("adm.m_model")}</TH><TH>{t("adm.llm_account")}</TH><TH className="text-right">{t("adm.llm_took")}</TH><TH className="text-right">{t("adm.llm_tokens_short")}</TH><TH>{t("turn.status")}</TH></tr></THead>
          <TBody>{d.recent.slice(0, 25).map((r, i) => (
            <TR key={i}>
              <TD className="text-xs">{r.kind}</TD>
              <TD className="font-mono text-[11px]">{r.provider}/{r.model}</TD>
              <TD className="text-xs text-muted-fg">{r.account || "–"}</TD>
              <TD className="text-right tabular-nums">{fmtMs(r.ms)}</TD>
              <TD className="text-right tabular-nums text-xs text-muted-fg">{r.input_tokens}/{r.output_tokens}</TD>
              <TD>{r.ok ? <Badge tone="success">ok</Badge> : <Badge tone="danger" title={r.error}>{r.code ?? "error"}</Badge>}</TD>
            </TR>))}
            {!d.recent.length ? <TR><TD colSpan={6} className="text-sm text-muted-fg">{t("adm.tr_no_data")}</TD></TR> : null}
          </TBody></Table>
      </Section>
    </>
  );
}

function Providers({ d }: { d: LlmOverview }) {
  const t = useT();
  const accounts: any[] = d.pool?.accounts ?? [];
  return (
    <>
      <Section title={<span className="inline-flex items-center gap-2"><KeyRound className="h-4 w-4" />{t("adm.llm_providers")}</span>}
        description={t("adm.llm_providers_desc")}>
        <Table><THead><tr><TH>{t("adm.m_provider")}</TH><TH>{t("adm.llm_configured")}</TH><TH className="text-right">{t("adm.plan_models_col")}</TH><TH className="text-right">{t("adm.llm_calls")}</TH><TH className="text-right">{t("adm.llm_avg")}</TH><TH className="text-right">{t("adm.llm_errors")}</TH><TH>{t("adm.error")}</TH></tr></THead>
          <TBody>{d.providers_configured.map((p: any) => {
            const st = d.providers[p.id];
            return (
              <TR key={p.id}>
                <TD className="font-medium">{p.id}</TD>
                <TD>{p.configured ? <Badge tone="success">{t("adm.llm_yes")}</Badge> : <Badge tone="neutral">{t("adm.llm_no")}</Badge>}</TD>
                <TD className="text-right tabular-nums">{p.models}</TD>
                <TD className="text-right tabular-nums">{st ? fmtNumber(st.calls) : "–"}</TD>
                <TD className="text-right tabular-nums">{st ? fmtMs(st.avg_ms) : "–"}</TD>
                <TD className="text-right tabular-nums">{st && st.calls ? fmtPct(st.error_rate) : "–"}</TD>
                <TD className="max-w-[240px] truncate text-xs text-danger" title={st?.last_error}>{st?.last_error}</TD>
              </TR>);
          })}</TBody></Table>
      </Section>

      {accounts.length ? (
        <Section title={t("adm.llm_pool")} description={t("adm.llm_pool_desc")}>
          <Table><THead><tr><TH>{t("adm.pool_account")}</TH><TH>{t("turn.status")}</TH><TH className="text-right">{t("adm.llm_in_flight")}</TH><TH className="text-right">{t("adm.llm_leases")}</TH><TH>{t("adm.llm_eligible")}</TH><TH>{t("adm.error")}</TH></tr></THead>
            <TBody>{accounts.map((a: any) => (
              <TR key={a.id}>
                <TD className="font-medium">{a.label}</TD>
                <TD><Badge tone={a.status === "ready" ? "success" : a.status === "cooldown" ? "warning" : "danger"}>{a.status}</Badge></TD>
                <TD className="text-right tabular-nums">{a.in_flight ?? 0}/{a.max_concurrency ?? "–"}</TD>
                <TD className="text-right tabular-nums">{fmtNumber(a.total_leases ?? 0)}</TD>
                <TD>{a.eligible ? <Badge tone="success">{t("adm.llm_yes")}</Badge> : <Badge tone="warning">{a.ineligible_reason ?? t("adm.llm_no")}</Badge>}</TD>
                <TD className="max-w-[220px] truncate text-xs text-danger" title={a.last_error}>{a.last_error}</TD>
              </TR>))}</TBody></Table>
        </Section>
      ) : null}

      <Section title={t("adm.llm_models")} description={t("adm.llm_models_desc")}>
        <Table><THead><tr><TH>{t("adm.m_model")}</TH><TH className="text-right">{t("adm.llm_calls")}</TH><TH className="text-right">{t("adm.llm_avg")}</TH><TH className="text-right">{t("adm.llm_max")}</TH><TH className="text-right">{t("adm.llm_tokens_short")}</TH><TH className="text-right">{t("adm.llm_errors")}</TH></tr></THead>
          <TBody>{Object.entries(d.models as Record<string, any>).map(([name, m]) => (
            <TR key={name}>
              <TD className="font-mono text-[11px]">{name}</TD>
              <TD className="text-right tabular-nums">{fmtNumber(m.calls)}</TD>
              <TD className="text-right tabular-nums">{fmtMs(m.avg_ms)}</TD>
              <TD className="text-right tabular-nums">{fmtMs(m.max_ms)}</TD>
              <TD className="text-right tabular-nums text-xs">{fmtNumber(m.input_tokens)}/{fmtNumber(m.output_tokens)}</TD>
              <TD className="text-right tabular-nums">{m.calls ? fmtPct(m.error_rate) : "–"}</TD>
            </TR>))}
            {!Object.keys(d.models).length ? <TR><TD colSpan={6} className="text-sm text-muted-fg">{t("adm.tr_no_data")}</TD></TR> : null}
          </TBody></Table>
      </Section>
    </>
  );
}

function Sessions({ d, onClose, closing }: { d: { sessions: LlmSession[] }; onClose: (key: string) => void; closing: boolean }) {
  const t = useT();
  return (
    <Section title={t("adm.llm_sessions")} description={t("adm.llm_sessions_desc")}>
      {!d.sessions.length ? <div className="py-3 text-sm text-muted-fg">{t("adm.llm_no_sessions")}</div> : (
        <Table><THead><tr><TH>{t("adm.llm_agent")}</TH><TH>{t("adm.m_model")}</TH><TH>{t("adm.llm_account")}</TH><TH className="text-right">{t("adm.llm_turns")}</TH><TH className="text-right">{t("adm.llm_idle")}</TH><TH>{t("turn.status")}</TH><TH></TH></tr></THead>
          <TBody>{d.sessions.map((s) => (
            <TR key={s.key}>
              <TD>
                <div className="font-medium">{s.agent_name || s.agent_id.slice(0, 8)}</div>
                <div className="text-xs text-muted-fg">{s.owner_name} · {s.audience}</div>
              </TD>
              <TD className="font-mono text-[11px]">{s.provider}/{s.model}</TD>
              <TD className="text-xs">
                {s.account || "–"}
                {s.account_held_s !== null ? <div className="text-[11px] text-muted-fg">{secs(s.account_held_s)}</div> : null}
              </TD>
              <TD className="text-right tabular-nums">{s.turns}</TD>
              <TD className="text-right tabular-nums">{secs(s.idle_s)}</TD>
              <TD>{s.busy ? <Badge tone="accent">{t("adm.llm_busy")}</Badge> : <Badge tone="neutral">{t("adm.llm_waiting")}</Badge>}</TD>
              <TD>
                <Button size="icon-sm" variant="ghost" className="text-danger" disabled={closing}
                  aria-label={t("adm.llm_close_session")} title={t("adm.llm_close_session")}
                  onClick={() => onClose(s.key)}><X className="h-4 w-4" /></Button>
              </TD>
            </TR>))}</TBody></Table>
      )}
    </Section>
  );
}
