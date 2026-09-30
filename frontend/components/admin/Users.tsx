"use client";
import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search } from "@/components/icons";
import { Admin } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtCredits, fmtDateTime, fmtRelative } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { useAuth } from "@/stores/auth";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { PageHeader, KeyValue, Avatar } from "@/components/ui/misc";
import { Dialog, ConfirmDialog } from "@/components/ui/dialog";

export function UsersPage() {
  const t = useT(); const locale = useLocale();
  const [q, setQ] = useState(""); const dq = useDebounced(q, 300); const [page, setPage] = useState(1);
  const [sel, setSel] = useState<string | null>(null);
  const r = useQuery({ queryKey: ["admin", "users", dq, page], queryFn: () => Admin.users(dq, page), placeholderData: keepPreviousData });
  return (
    <Page>
      <PageHeader title={t("adm.users")} description={r.data ? t("adm.users_total", { n: r.data.total }) : undefined} />
      <div className="relative mb-3 max-w-sm"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" /><Input className="pl-9" placeholder={t("adm.search_users")} value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
      {r.isLoading ? <Skeleton className="h-60" /> : (
        <Table><THead><tr><TH>{t("auth.email")}</TH><TH>{t("auth.display_name")}</TH><TH>{t("adm.role")}</TH><TH>{t("credits.plan")}</TH><TH className="text-right">{t("credits.balance")}</TH><TH>{t("adm.agents")}</TH><TH>{t("adm.last_login")}</TH><TH>{t("turn.status")}</TH></tr></THead>
          <TBody>{r.data?.items.map((u) => <TR key={u.id} className="cursor-pointer" onClick={() => setSel(u.id)}><TD className="text-sm">{u.email}</TD><TD>{u.display_name}</TD><TD><span className="inline-flex items-center gap-1"><Badge tone={u.role === "admin" ? "accent" : "outline"}>{u.role}</Badge>{u.is_super ? <Badge tone="warning">{t("adm.super")}</Badge> : null}</span></TD><TD className="text-xs">{u.plan ?? "–"}</TD><TD className="text-right tabular-nums">{fmtCredits(u.balance)}</TD><TD className="tabular-nums">{u.agents}</TD><TD className="text-xs text-muted-fg">{u.last_login_at ? fmtRelative(u.last_login_at, locale) : "–"}</TD><TD><Badge tone={u.status === "active" ? "success" : "danger"}>{u.status}</Badge></TD></TR>)}</TBody></Table>
      )}
      {r.data && r.data.total > 50 ? <div className="mt-3 flex items-center justify-end gap-2 text-sm"><Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</Button><span>{page} / {Math.ceil(r.data.total / 50)}</span><Button size="sm" variant="outline" disabled={page * 50 >= r.data.total} onClick={() => setPage(page + 1)}>›</Button></div> : null}
      {/* A centred modal, not a right rail. Everything on this panel is two columns wide —
          credit grant, role and plan, the agent list — and a 420px drawer stacked it all
          into one narrow strip. */}
      <Dialog open={!!sel} onClose={() => setSel(null)} size="xl" title={t("adm.user_detail")}>
        {sel ? <UserDetail id={sel} onClose={() => setSel(null)} /> : null}
      </Dialog>
    </Page>
  );
}

function UserDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const me = useAuth((s) => s.user);
  const q = useQuery({ queryKey: ["admin", "user", id], queryFn: () => Admin.user(id) });
  const plans = useQuery({ queryKey: ["admin", "plans"], queryFn: Admin.plans });
  const [delta, setDelta] = useState(""); const [note, setNote] = useState(""); const [delOpen, setDelOpen] = useState(false);
  const inval = () => { qc.invalidateQueries({ queryKey: ["admin", "users"] }); q.refetch(); };
  const grant = useMutation({ mutationFn: () => Admin.grant(id, Number(delta), note), onSuccess: (r) => { inval(); setDelta(""); setNote(""); toast.success(t("adm.granted", { n: fmtCredits(r.balance) })); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const role = useMutation({ mutationFn: (role: string) => Admin.role(id, role), onSuccess: inval, onError: (e) => toast.error(friendlyError(e, locale)) });
  const patch = useMutation({ mutationFn: (b: Record<string, unknown>) => Admin.patchUser(id, b), onSuccess: inval, onError: (e) => toast.error(friendlyError(e, locale)) });
  const del = useMutation({ mutationFn: () => Admin.deleteUser(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin", "users"] }); onClose(); toast.success(t("adm.user_deleted")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const u = q.data;
  if (q.isLoading || !u) return <Skeleton className="h-72" />;
  const self = me?.id === u.id;
  // Who may narrow or widen the circle of people who run this install (plan/31): the
  // maintainer alone, and never against the maintainer.
  const iAmSuper = !!me?.is_super;
  const locked = !!u.is_super;
  const mayRole = iAmSuper && !self && !locked;
  const mayRemove = !self && !locked && (iAmSuper || u.role !== "admin");
  return (
    <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-5">
        <section className="rounded-2xl border border-border p-4">
          <h3 className="mb-3 text-sm font-semibold">{t("adm.grant_credits")}</h3>
          <div className="flex flex-wrap items-end gap-2">
            <Field className="w-32" label={t("adm.grant_amount")}>
              <Input type="number" step="any" placeholder="±100" value={delta} onChange={(e) => setDelta(e.target.value)} />
            </Field>
            <Field className="min-w-[200px] flex-1" label={t("adm.grant_note")}>
              <Input placeholder={t("adm.grant_note")} value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <Button loading={grant.isPending} disabled={!delta || !note.trim()} onClick={() => grant.mutate()}>{t("common.apply")}</Button>
          </div>
          {/* The amounts anyone actually types. Typing "1000" into a number field to hand
              out a monthly grant is a keystroke tax on a job that has four answers. */}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {[-1000, -100, 100, 1000].map((n) => (
              <button key={n} type="button" onClick={() => setDelta(String(n))}
                      className={cn("h-8 rounded-full border px-3 text-xs font-medium tabular-nums transition-colors",
                                    String(n) === delta ? "border-accent bg-accent/10 text-accent"
                                    : n < 0 ? "border-border text-danger hover:border-danger/60 hover:bg-danger/5"
                                            : "border-border hover:border-accent/60 hover:bg-accent/5")}>
                {n > 0 ? `+${n}` : n}
              </button>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-border p-4">
          <h3 className="mb-3 text-sm font-semibold">{t("adm.access")}</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("adm.role")} hint={locked ? t("adm.super_locked") : !iAmSuper ? t("adm.role_super_only") : undefined}>
              <Select value={u.role} disabled={!mayRole} onChange={(e) => role.mutate(e.target.value)}>
                <option value="user">user</option><option value="admin">admin</option>
              </Select>
            </Field>
            <Field label={t("credits.plan")}>
              <Select aria-label={t("credits.plan")} value={u.plan_id ?? ""} onChange={(e) => patch.mutate({ plan_id: e.target.value })}
                options={[{ value: "", label: "–" }, ...(plans.data?.items ?? []).map((p) => ({ value: p.id, label: `${p.name} (${p.code})`, keywords: `${p.name} ${p.code}` }))]} />
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
            {u.status === "active"
              ? <Button variant="outline" disabled={self || locked || (!iAmSuper && u.role === "admin")} loading={patch.isPending} onClick={() => patch.mutate({ status: "suspended" })}>{t("adm.suspend")}</Button>
              : <Button variant="outline" loading={patch.isPending} onClick={() => patch.mutate({ status: "active" })}>{t("adm.unsuspend")}</Button>}
            <Button variant="danger" className="ml-auto" disabled={!mayRemove} onClick={() => setDelOpen(true)}>{t("common.delete")}</Button>
          </div>
        </section>

        <section>
          <h3 className="mb-2 text-sm font-semibold">{t("adm.agents")} <span className="text-muted-fg">{u.agents_detail?.length ?? 0}</span></h3>
          {(u.agents_detail?.length ?? 0) === 0 ? <p className="text-sm text-muted-fg">–</p> : (
            <ul className="grid gap-1.5 sm:grid-cols-2">{u.agents_detail?.map((a: any) => (
              <li key={a.id} className="flex items-center gap-2 rounded-lg bg-muted px-2.5 py-1.5 text-sm">
                <span className="truncate">{a.name}</span><Badge tone="outline">{a.status}</Badge>
                <span className="ml-auto shrink-0 text-xs text-muted-fg">{a.provider}/{a.model_id}</span>
              </li>
            ))}</ul>
          )}
        </section>
      </div>

      {/* Identity on its own side: it is what you read, not what you change. */}
      <aside className="space-y-3 md:border-l md:border-border md:pl-5">
        <div className="flex items-center gap-3">
          <Avatar name={u.display_name} src={(u as any).avatar_url} size={44} />
          <div className="min-w-0">
            <div className="truncate font-medium">{u.display_name}</div>
            <div className="truncate text-xs text-muted-fg">{u.email}</div>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge tone={u.role === "admin" ? "accent" : "outline"}>{u.role}</Badge>
          {u.is_super ? <Badge tone="warning">{t("adm.super")}</Badge> : null}
          <Badge tone={u.status === "active" ? "success" : "danger"}>{u.status}</Badge>
          {self ? <Badge tone="outline">{t("adm.you")}</Badge> : null}
        </div>
        <KeyValue items={[
          { k: t("credits.balance"), v: fmtCredits(u.balance) },
          { k: t("credits.plan"), v: u.plan ?? "–" },
          { k: t("adm.joined"), v: fmtDateTime(u.created_at) },
          { k: t("adm.last_login"), v: u.last_login_at ? fmtDateTime(u.last_login_at) : "–" },
        ]} />
        {locked ? <p className="rounded-xl border border-warning/40 bg-warning/5 p-2.5 text-xs text-warning">{t("adm.super_hint")}</p> : null}
      </aside>

      <ConfirmDialog open={delOpen} onClose={() => setDelOpen(false)} onConfirm={() => del.mutate()} title={t("adm.delete_user")} description={t("adm.delete_user_desc", { email: u.email })} confirmLabel={t("common.delete")} cancelLabel={t("common.cancel")} danger loading={del.isPending} />
    </div>
  );
}
