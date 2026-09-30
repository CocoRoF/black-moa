"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Users as UsersIcon } from "@/components/icons";
import { Agents, type Fact } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtDateTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { VisibilityPicker } from "@/components/ui/visibility";

/** 이 비서가 대화에서 알게 된 사실 (plan/49).
 *
 *  **사실은 비서가 만든 것이라 그 비서의 것이다.** 기억이 비서별 금고에 사는 것과 같은
 *  이유다. 내가 직접 넣은 것(프로필·지식·인맥·내 글)은 [내 정보] 에 있고 모든 비서가
 *  전부 본다. 둘은 다른 것이고, 다른 자리에 있어야 한다.
 */
export function AgentFacts({ agentId }: { agentId: string }) {
  const t = useT();
  const locale = useLocale();
  const qc = useQueryClient();
  const [status, setStatus] = useState<"active" | "rejected">("active");
  const q = useQuery({ queryKey: ["facts", agentId, status], queryFn: () => Agents.facts(agentId, status) });
  const m = useMutation({
    mutationFn: (x: { id: string; body: Record<string, unknown> }) => Agents.patchFact(x.id, x.body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["facts", agentId] }),
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const items = q.data?.items ?? [];

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-fg">{t("mem.facts_desc")}</p>
        <Select value={status} onChange={(e) => setStatus(e.target.value as "active" | "rejected")} className="h-9 w-auto">
          <option value="active">{t("mem.fact_active")}</option>
          <option value="rejected">{t("mem.fact_rejected")}</option>
        </Select>
      </div>
      {q.isLoading ? <Skeleton className="h-40" /> : items.length ? (
        <Table>
          <THead><tr>
            <TH>{t("mem.fact_statement")}</TH><TH>{t("mem.fact_kind")}</TH>
            <TH>{t("vis.label")}</TH><TH></TH>
          </tr></THead>
          <TBody>{items.map((f) => <Row key={f.id} f={f} status={status} onPatch={(body) => m.mutate({ id: f.id, body })} />)}</TBody>
        </Table>
      ) : <EmptyState title={t("mem.facts_empty")} />}
    </div>
  );
}

function Row({ f, status, onPatch }: { f: Fact; status: string; onPatch: (b: Record<string, unknown>) => void }) {
  const t = useT();
  const kindLabel = t(`mem.fk_${f.kind}`) === `mem.fk_${f.kind}` ? f.kind : t(`mem.fk_${f.kind}`);
  return (
    <TR>
      <TD>
        <div className="text-sm">
          <span className="font-medium">{f.subject}</span> <span className="text-muted-fg">{f.predicate}</span> {f.object}
        </div>
        <div className="mt-0.5 text-[11px] text-muted-fg">
          {Math.round((f.confidence ?? 0) * 100)}% · {fmtDateTime(f.updated_at)}
        </div>
      </TD>
      <TD><Badge tone="outline">{kindLabel}</Badge></TD>
      <TD>
        {f.about_visitor ? (
          // 손님에 대한 사실은 범위 칸이 아니다. 바꾸게 두면 손님 얘기가 주인에 대한
          // 사실이 된다.
          <Badge tone="outline"><UsersIcon className="mr-1 h-3 w-3" />{t("facts.about_visitor")}</Badge>
        ) : (
          <VisibilityPicker value={f.visibility} onChange={(v) => onPatch({ visibility: v })} />
        )}
      </TD>
      <TD>
        {status === "active"
          ? <Button size="sm" variant="ghost" className="text-danger" onClick={() => onPatch({ status: "rejected" })}>{t("common.reject")}</Button>
          : <Button size="sm" variant="ghost" onClick={() => onPatch({ status: "active" })}>{t("common.restore")}</Button>}
      </TD>
    </TR>
  );
}
