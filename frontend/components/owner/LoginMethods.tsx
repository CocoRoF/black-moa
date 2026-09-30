"use client";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { KeyRound, Plus, Unplug } from "@/components/icons";
import { Auth, type LoginIdentity } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { codeMessage, friendlyError } from "@/lib/errors";
import { fmtDateTime } from "@/lib/format";
import { Section } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ConfirmDialog } from "@/components/ui/dialog";
import { ProviderIcon } from "@/components/integrations/ProviderIcon";

/** 이 계정에 들어오는 방법들 (plan/59): 비밀번호와 이어 둔 Google·카카오 계정.
 *  하나 남은 방법은 뗄 수 없다 — 들어올 길이 없어진다. 비밀번호가 없으면 아래 칸에서 만든다. */
export function LoginMethods() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient(); const sp = useSearchParams();
  const q = useQuery({ queryKey: ["identities"], queryFn: Auth.identities });
  const [off, setOff] = useState<LoginIdentity | null>(null);
  useEffect(() => {
    const linked = sp.get("linked"); const err = sp.get("error");
    if (linked) toast.success(t("login_methods.linked"));
    else if (err) toast.error(codeMessage(err, locale));
  }, [sp, t, locale]);
  const link = useMutation({
    mutationFn: (provider: string) => Auth.linkStart(provider, "/app/settings"),
    onSuccess: (r) => { window.location.assign(r.url); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const unlink = useMutation({
    mutationFn: (id: string) => Auth.unlink(id),
    onSuccess: () => { setOff(null); qc.invalidateQueries({ queryKey: ["identities"] }); toast.success(t("login_methods.unlinked")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const d = q.data;
  const methods = (d?.items.length ?? 0) + (d?.has_password ? 1 : 0);
  const addable = d?.providers.filter((p) => !p.linked) ?? [];
  return (
    <Section title={t("login_methods.title")} description={t("login_methods.desc")}>
      {q.isLoading || !d ? <Skeleton className="h-20" /> : (
        <div className="space-y-3">
          <ul className="divide-y divide-border rounded-xl border border-border">
            <li className="flex items-center gap-3 px-3 py-2.5 text-sm">
              <KeyRound className="h-[18px] w-[18px] shrink-0 text-muted-fg" />
              <span className="min-w-0 flex-1 font-medium">{t("login_methods.password")}</span>
              {d.has_password ? <Badge tone="success">{t("login_methods.in_use")}</Badge> : <span className="text-xs text-muted-fg">{t("login_methods.no_password")}</span>}
            </li>
            {d.items.map((i) => {
              const last = methods <= 1;
              return (
                <li key={i.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm">
                  <ProviderIcon provider={i.provider} size={18} />
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{i.label}</div>
                    <div className="truncate text-xs text-muted-fg">{[i.email || i.name, i.created_at ? t("login_methods.since", { when: fmtDateTime(i.created_at) }) : ""].filter(Boolean).join(" · ")}</div>
                  </div>
                  <Button variant="ghost" size="sm" className="text-danger" disabled={last} title={last ? t("login_methods.last") : undefined} onClick={() => setOff(i)}>
                    <Unplug className="h-4 w-4" />{t("login_methods.unlink")}
                  </Button>
                </li>
              );
            })}
          </ul>
          {addable.length ? (
            <div className="flex flex-wrap gap-2">
              {addable.map((p) => (
                <Button key={p.id} variant="outline" size="sm" loading={link.isPending && link.variables === p.id} onClick={() => link.mutate(p.id)}>
                  <Plus className="h-4 w-4" /><ProviderIcon provider={p.id} size={16} />{t("login_methods.add", { name: p.label })}
                </Button>
              ))}
            </div>
          ) : null}
          {methods <= 1 && d.items.length ? <p className="text-xs text-muted-fg">{t("login_methods.last")}</p> : null}
        </div>
      )}
      <ConfirmDialog open={!!off} onClose={() => setOff(null)} onConfirm={() => { if (off) unlink.mutate(off.id); }}
        title={t("login_methods.unlink_title", { name: off?.label ?? "" })} description={t("login_methods.unlink_desc")}
        confirmLabel={t("login_methods.unlink")} cancelLabel={t("common.cancel")} danger loading={unlink.isPending} />
    </Section>
  );
}
