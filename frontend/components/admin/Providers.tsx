"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { KeyRound, ShieldCheck } from "@/components/icons";
import { Admin } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtRelative, fmtSecretTail } from "@/lib/format";
import { Page } from "@/components/owner/Shell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/misc";
import { ClaudeAccounts } from "./ClaudePool";

const PROVIDER_NAMES: Record<string, string> = { anthropic: "Anthropic API", openai: "OpenAI", google: "Google (Gemini)", elevenlabs: "ElevenLabs", voyage: "Voyage AI" };

export function ProvidersPage() {
  const t = useT();
  return (
    <Page>
      <PageHeader title={t("adm.providers")} description={t("adm.providers_desc")} />
      <div className="space-y-4">
        {/* One Claude Code surface. It used to be two — a card holding the single login and
            a pool of accounts beside it — and nothing on either said which one answered a
            turn. The provider *is* the list; an install with one login is a list of one. */}
        <ClaudeAccounts />
        <ProviderKeyCards />
      </div>
    </Page>
  );
}

/** verdict is a tri-state from the backend: true verified, false rejected, null unknown
 *  (network trouble, or a provider we cannot probe). It used to be compared against the
 *  string "ok", so a successful check painted a red toast. */
type Verdict = boolean | null | undefined;
const verdictTone = (v: Verdict) => (v === true ? "success" : v === false ? "danger" : "warning");

export function ProviderKeyCards() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "providers"], queryFn: Admin.providers });
  const [keys, setKeys] = useState<Record<string, string>>({});
  const detailOf = (d: unknown) => (typeof d === "string" ? d : d ? JSON.stringify(d).slice(0, 120) : "");
  const announce = (id: string, verdict: Verdict, detail?: unknown) => {
    const name = PROVIDER_NAMES[id] ?? id;
    const info = detailOf(detail);
    if (verdict === true) toast.success(t("adm.key_ok", { name }));
    else if (verdict === false) toast.error(`${t("adm.key_bad", { name })}${info ? ` — ${info}` : ""}`);
    else toast.warning(`${t("adm.key_unknown", { name })}${info ? ` — ${info}` : ""}`);
  };
  const put = useMutation({
    mutationFn: (x: { id: string; key: string }) => Admin.putProvider(x.id, x.key),
    onSuccess: (r, v) => { qc.invalidateQueries({ queryKey: ["admin"] }); setKeys((p) => ({ ...p, [v.id]: "" })); announce(v.id, r.verdict, r.detail); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const verify = useMutation({
    mutationFn: (id: string) => Admin.verifyProvider(id),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["admin"] }); announce(r.id, r.verdict, r.detail); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  if (q.isLoading) return <Skeleton className="h-60" />;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {q.data?.providers.map((p) => {
        const v = p.status?.verdict;
        const label = !p.configured ? t("adm.not_configured") : v === true ? t("adm.key_state_ok") : v === false ? t("adm.key_state_bad") : p.status ? t("adm.key_state_unknown") : t("adm.key_state_unchecked");
        const detail = p.status && v !== true ? detailOf(p.status.detail) : "";
        return (
          <Card key={p.id} className="flex flex-col gap-3 p-4">
            <div className="flex min-w-0 items-center gap-2">
              <KeyRound className="h-4 w-4 shrink-0 text-muted-fg" />
              <span className="truncate font-medium">{PROVIDER_NAMES[p.id] ?? p.id}</span>
              {/* The masked key used to live inside the badge, so a long mask stretched a
                  green pill across the card. It is metadata, not a status. */}
              <Badge tone={p.configured ? verdictTone(v) : "neutral"} className="ml-auto shrink-0">{label}</Badge>
            </div>
            <div className="min-h-[16px] truncate text-[11px] text-muted-fg">
              {p.configured ? <span className="font-mono">{fmtSecretTail(p.masked)}</span> : null}
              {p.configured && p.status?.at ? <span> · {t("adm.last_verified")} {fmtRelative(p.status.at, locale)}</span> : null}
              {detail ? <span className="text-danger"> · {detail}</span> : null}
            </div>
            <div className="flex gap-2">
              <Input className="min-w-0 flex-1" type="password" autoComplete="off" placeholder={p.configured ? "••••••••" : "sk-…"}
                     value={keys[p.id] ?? ""} onChange={(e) => setKeys({ ...keys, [p.id]: e.target.value })} />
              <Button variant="outline" className="shrink-0" disabled={!keys[p.id]} loading={put.isPending && put.variables?.id === p.id}
                      onClick={() => put.mutate({ id: p.id, key: keys[p.id] })}>{t("common.save")}</Button>
              <Button variant="ghost" className="shrink-0" disabled={!p.configured} loading={verify.isPending && verify.variables === p.id}
                      onClick={() => verify.mutate(p.id)}><ShieldCheck className="h-4 w-4" />{t("adm.verify")}</Button>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
