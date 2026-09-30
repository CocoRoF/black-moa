"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { CreditCard, HandCoins } from "@/components/icons";
import { Credits } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtBytes, fmtCredits, fmtDate, fmtDateTime } from "@/lib/format";
import { Page } from "./Shell";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Stat, Bars, Progress, PageHeader } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

/** What a ledger line was for, in the owner's words. The note column holds what the code
 *  wrote at the time (a job name, a plan code); the owner reads what happened. */
function noteLabel(note: string | null | undefined, kind: string, t: (k: string) => string): string {
  const n = (note ?? "").trim();
  if (!n) return kind === "turn" ? t("credits.note_turn") : "";
  const fixed: Record<string, string> = { "memory distill": "credits.note_distill", "signup grant": "credits.note_signup", "default admin grant": "credits.note_grant",
    "studio verify": "credits.note_verify", "studio preview": "credits.note_preview", stt: "credits.note_stt", stripe: "credits.note_payment", "rollover cap": "credits.note_rollover", admin: "credits.note_grant" };
  if (fixed[n]) return t(fixed[n]);
  if (n.startsWith("proactive:")) { const k = `credits.note_pro_${n.slice(10)}`; const v = t(k); return v === k ? t("credits.note_proactive") : v; }
  if (/ monthly$/.test(n)) return t("credits.note_monthly");
  return n;
}

export function CreditsPage() {
  const t = useT(); const locale = useLocale();
  const bal = useQuery({ queryKey: ["credits", "balance"], queryFn: Credits.balance });
  const usage = useQuery({ queryKey: ["credits", "usage"], queryFn: () => Credits.usage(30) });
  const ledger = useQuery({ queryKey: ["credits", "ledger"], queryFn: Credits.ledger });
  const topup = useMutation({ mutationFn: Credits.topup, onSuccess: () => toast.success(t("credits.topup_sent")), onError: (e) => toast.error(friendlyError(e, locale)) });
  const checkout = useMutation({ mutationFn: (pkg: string) => Credits.checkout(pkg), onSuccess: (r) => window.location.assign(r.url), onError: (e) => toast.error(friendlyError(e, locale)) });
  const b = bal.data;
  const today = new Date().toISOString().slice(0, 10);
  const usedToday = usage.data?.daily?.find((d) => d.day === today)?.credits ?? 0; const monthly = b?.plan.monthly_credits ?? 0;
  const used30 = usage.data?.daily.reduce((s, d) => s + d.credits, 0) ?? 0;
  const days = (() => { const map = new Map(usage.data?.daily.map((d) => [d.day, d]) ?? []); const out = []; for (let i = 29; i >= 0; i--) { const d = new Date(); d.setDate(d.getDate() - i); const k = d.toISOString().slice(0, 10); const v = map.get(k); out.push({ label: k, value: v?.credits ?? 0, secondary: v?.turns ?? 0 }); } return out; })();
  return (
    <Page>
      <PageHeader title={t("nav.credits")} description={t("credits.desc")} action={<>
        <Button variant="outline" loading={topup.isPending} onClick={() => topup.mutate()}><HandCoins className="h-4 w-4" />{t("credits.request_topup")}</Button>
        {b?.stripe_enabled ? <Button variant="accent" loading={checkout.isPending} onClick={() => checkout.mutate("standard")}><CreditCard className="h-4 w-4" />{t("credits.buy")}</Button> : null}
      </>} />
      {bal.isLoading ? <Skeleton className="h-32" /> : b ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label={t("credits.balance")} value={<>{fmtCredits(b.balance)}<span className="ml-1 text-sm font-normal text-muted-fg">{t("credits.unit")}</span></>} hint={b.low ? <span className="text-warning">{t("credits.low_warning")}</span> : t("credits.cycle_ends", { d: fmtDate(b.cycle_ends_at) })} />
          <Stat label={t("credits.plan")} value={b.plan.name} hint={t("credits.plan_detail", { n: fmtCredits(monthly), a: b.plan.max_agents, l: b.plan.max_share_links, s: fmtBytes((b.plan.max_storage_mb ?? 0) * 1024 * 1024) })} />
          {/* Caps are set on each secretary now (plan/34), so this page shows what was
              actually spent rather than a ceiling that lives somewhere else. */}
          <Stat label={t("credits.used_30d")} value={fmtCredits(used30)} hint={t("credits.today_used", { n: fmtCredits(usedToday) })} />
        </div>
      ) : null}
      <Card className="mt-4">
        <CardHeader title={t("credits.usage_chart")} description={t("credits.usage_chart_desc")} />
        <CardBody>{usage.isLoading ? <Skeleton className="h-32" /> : <><Bars data={days} height={120} format={(v) => fmtCredits(v)} emptyLabel={t("credits.usage_empty")} /><div className="mt-1 flex justify-between text-[10px] text-muted-fg"><span>{days[0]?.label}</span><span>{days[days.length - 1]?.label}</span></div></>}
        </CardBody>
      </Card>
      {b ? (
        <Card className="mt-4"><CardBody className="pt-5">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2 text-sm">
            <span>{t("credits.monthly_progress")}</span>
            {/* A granted balance can exceed the monthly allowance, and "200,024 / 300" with a
                full bar reads as a bug. Show the balance, and the allowance as context. */}
            <span className="tabular-nums text-muted-fg">
              {fmtCredits(b.balance)}
              {monthly ? <span className="ml-1 text-xs">· {t("credits.monthly_grant", { n: fmtCredits(monthly) })}</span> : null}
            </span>
          </div>
          <Progress value={Math.min(b.balance, monthly || b.balance)} max={monthly || Math.max(1, b.balance)} tone={b.low ? "danger" : "accent"} />
        </CardBody></Card>
      ) : null}
      <Card className="mt-4">
        <CardHeader title={t("credits.ledger")} />
        <CardBody>
          {ledger.isLoading ? <Skeleton className="h-40" /> : ledger.data?.items.length ? (
            <Table><THead><tr><TH>{t("credits.when")}</TH><TH>{t("credits.kind")}</TH><TH className="text-right">{t("credits.delta")}</TH><TH className="text-right">{t("credits.balance_after")}</TH><TH>{t("credits.note")}</TH></tr></THead>
              <TBody>{ledger.data.items.map((r) => <TR key={r.id}><TD className="whitespace-nowrap text-xs text-muted-fg">{fmtDateTime(r.created_at)}</TD><TD><Badge tone="outline">{t(`credits.kind_${r.kind}`) === `credits.kind_${r.kind}` ? r.kind : t(`credits.kind_${r.kind}`)}</Badge></TD><TD className={`text-right tabular-nums ${r.delta < 0 ? "text-danger" : "text-success"}`}>{r.delta > 0 ? "+" : ""}{fmtCredits(r.delta)}</TD><TD className="text-right tabular-nums">{fmtCredits(r.balance_after)}</TD><TD className="max-w-[240px] truncate text-xs text-muted-fg">{noteLabel(r.note, r.kind, t)}</TD></TR>)}</TBody></Table>
          ) : <p className="text-sm text-muted-fg">{t("credits.ledger_empty")}</p>}
        </CardBody>
      </Card>
    </Page>
  );
}
