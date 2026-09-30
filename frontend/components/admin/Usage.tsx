"use client";
import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Admin } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { fmtCredits, fmtNumber } from "@/lib/format";
import { Page } from "@/components/owner/Shell";
import { Segmented } from "@/components/ui/tabs";
import { Section } from "@/components/ui/card";
import { Bars, PageHeader, Stat } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

export function UsagePage() {
  const t = useT();
  const [days, setDays] = useState("30");
  const q = useQuery({ queryKey: ["admin", "usage", days], queryFn: () => Admin.usage(Number(days)), placeholderData: keepPreviousData });
  const d = q.data;
  const totals = d?.daily.reduce((a: any, x: any) => ({ credits: a.credits + x.credits, turns: a.turns + x.turns, visitor: a.visitor + x.visitor_turns }), { credits: 0, turns: 0, visitor: 0 });
  const cost = d?.by_model.reduce((s: number, m: any) => s + (m.cost_usd ?? 0), 0) ?? 0;
  return (
    <Page>
      <PageHeader title={t("adm.usage")} description={t("adm.usage_desc")} action={<Segmented value={days} onChange={setDays} options={[{ value: "7", label: "7d" }, { value: "30", label: "30d" }, { value: "90", label: "90d" }]} />} />
      {q.isLoading || !d ? <Skeleton className="h-60" /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4"><Stat label={t("adm.total_credits")} value={fmtCredits(totals.credits)} /><Stat label={t("adm.total_turns")} value={fmtNumber(totals.turns)} /><Stat label={t("adm.visitor_turns")} value={fmtNumber(totals.visitor)} /><Stat label={t("adm.cost_usd")} value={`$${cost.toFixed(2)}`} /></div>
          <Section title={t("adm.daily")}><Bars data={d.daily.map((x: any) => ({ label: x.day, value: x.credits, secondary: x.turns }))} height={140} format={(v) => fmtCredits(v)} /><div className="mt-1 flex justify-between text-[10px] text-muted-fg"><span>{d.daily[0]?.day}</span><span>{d.daily[d.daily.length - 1]?.day}</span></div></Section>
          <div className="grid gap-4 lg:grid-cols-2">
            <Section title={t("adm.by_model")}>
              <Table><THead><tr><TH>{t("adm.m_model")}</TH><TH className="text-right">{t("adm.col_credits")}</TH><TH className="text-right">{t("adm.col_usd")}</TH><TH className="text-right">{t("adm.col_in_tokens")}</TH><TH className="text-right">{t("adm.col_out_tokens")}</TH><TH className="text-right">{t("adm.col_count")}</TH></tr></THead>
                <TBody>{d.by_model.map((m: any) => <TR key={`${m.provider}/${m.model_id}`}><TD className="text-xs"><Badge tone="outline">{m.provider}</Badge> {m.model_id}</TD><TD className="text-right tabular-nums">{fmtCredits(m.credits)}</TD><TD className="text-right tabular-nums">${(m.cost_usd ?? 0).toFixed(3)}</TD><TD className="text-right tabular-nums text-xs">{fmtNumber(m.input_tokens)}</TD><TD className="text-right tabular-nums text-xs">{fmtNumber(m.output_tokens)}</TD><TD className="text-right tabular-nums">{m.count}</TD></TR>)}</TBody></Table>
            </Section>
            <div className="space-y-4">
              <Section title={t("adm.top_users")}><ul className="divide-y divide-border text-sm">{d.top_users.map((u: any) => <li key={u.user_id} className="flex justify-between py-1.5"><span className="truncate">{u.email}</span><span className="tabular-nums">{fmtCredits(u.credits)}</span></li>)}{!d.top_users.length ? <li className="text-muted-fg">–</li> : null}</ul></Section>
              <Section title={t("adm.errors_7d")}><div className="flex flex-wrap gap-1.5">{d.errors_7d.map((e: any) => <Badge key={e.code} tone="danger">{e.code ?? "?"}: {e.count}</Badge>)}{!d.errors_7d.length ? <span className="text-sm text-muted-fg">{t("adm.no_failed")}</span> : null}</div></Section>
            </div>
          </div>
        </div>
      )}
    </Page>
  );
}
