"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { EyeOff, Flag, Plus } from "@/components/icons";
import { Admin } from "@/lib/api";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { fmtRelative } from "@/lib/format";
import { Page } from "@/components/owner/Shell";
import { SettingsForm } from "./common";
import { Section } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Selector } from "@cocorof/react-selector";
import { BOARD_GLYPHS, BoardIcon } from "@/components/icons";
import { PageHeader, Stat } from "@/components/ui/misc";
import { Tabs } from "@/components/ui/tabs";
import { Dialog } from "@/components/ui/dialog";

/** Community moderation: what the boards are, what got reported, and what is on the wall. */
export function CommunityAdminPage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [tab, setTab] = useState<"boards" | "reports" | "posts" | "settings">("boards");
  const ov = useQuery({ queryKey: ["admin", "community"], queryFn: Admin.communityOverview });
  const reports = useQuery({ queryKey: ["admin", "community", "reports"], queryFn: () => Admin.communityReports("open"), enabled: tab === "reports" });
  const posts = useQuery({ queryKey: ["admin", "community", "posts"], queryFn: () => Admin.communityPosts("published"), enabled: tab === "posts" });
  const inval = () => qc.invalidateQueries({ queryKey: ["admin", "community"] });

  const patchBoard = useMutation({ mutationFn: (x: { id: string; b: Record<string, unknown> }) => Admin.patchBoard(x.id, x.b), onSuccess: inval, onError: (e) => toast.error(friendlyError(e, locale)) });
  const resolve = useMutation({ mutationFn: (x: { id: string; action: "hide" | "dismiss" }) => Admin.resolveReport(x.id, x.action), onSuccess: () => { inval(); toast.success(t("cadm.resolved")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const setStatus = useMutation({ mutationFn: (x: { id: string; status: string }) => Admin.setPostStatus(x.id, x.status), onSuccess: () => { inval(); toast.success(t("common.saved")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const [newOpen, setNewOpen] = useState(false);

  return (
    <Page>
      <PageHeader title={t("adm.community")} description={t("cadm.desc")} />
      {ov.isLoading ? <Skeleton className="h-28" /> : (
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Stat label={t("cadm.posts")} value={ov.data!.posts} hint={t("cadm.posts_7d", { n: ov.data!.posts_7d })} />
          <Stat label={t("cadm.comments")} value={ov.data!.comments} />
          <Stat label={t("cadm.open_reports")} value={ov.data!.open_reports} hint={ov.data!.open_reports ? t("cadm.needs_review") : t("cadm.all_clear")} />
          <Stat label={t("cadm.jobs")} value={ov.data!.jobs} />
          <Stat label={t("cadm.boards")} value={ov.data!.boards.length} />
        </div>
      )}

      <Tabs className="mb-4" value={tab} onChange={setTab} items={[
        { key: "boards", label: t("cadm.boards") },
        { key: "reports", label: t("cadm.reports"), count: ov.data?.open_reports },
        { key: "posts", label: t("cadm.recent_posts") },
        { key: "settings", label: t("cadm.settings") },
      ]} />


      {tab === "boards" ? (
        <Section title={t("cadm.boards")} description={t("cadm.boards_desc")}
                 >
          <div className="mb-3"><Button size="sm" variant="outline" onClick={() => setNewOpen(true)}><Plus className="h-4 w-4" />{t("cadm.new_board")}</Button></div>
          <Table>
            <THead><tr><TH>{t("cadm.icon")}</TH><TH>{t("cadm.name")}</TH><TH>{t("adm.col_slug")}</TH><TH>{t("cadm.kind")}</TH><TH>{t("cadm.count")}</TH><TH>{t("cadm.order")}</TH><TH>{t("cadm.enabled")}</TH></tr></THead>
            <TBody>
              {(ov.data?.boards ?? []).map((b) => (
                <TR key={b.id}>
                  <TD>
                    <Selector size="sm" className="w-40" ariaLabel={t("cadm.icon")} value={b.icon || "message-circle"}
                      onChange={(v) => patchBoard.mutate({ id: b.id, b: { icon: v } })}
                      options={BOARD_GLYPHS.map((g) => ({ value: g, label: <span className="inline-flex items-center gap-2"><BoardIcon name={g} className="h-4 w-4" />{g}</span>, keywords: g }))} />
                  </TD>
                  <TD><Input className="h-8 w-40 px-2 text-xs" defaultValue={b.name} onBlur={(e) => e.target.value !== b.name && patchBoard.mutate({ id: b.id, b: { name: e.target.value } })} /></TD>
                  <TD className="font-mono text-xs text-muted-fg">{b.slug}</TD>
                  <TD><Badge tone="outline">{b.kind}</Badge></TD>
                  <TD className="tabular-nums">{b.post_count}</TD>
                  <TD><Input type="number" className="h-8 w-20 px-2 text-xs" defaultValue={b.sort_order} onBlur={(e) => Number(e.target.value) !== b.sort_order && patchBoard.mutate({ id: b.id, b: { sort_order: Number(e.target.value) } })} /></TD>
                  <TD><Switch checked={b.enabled} onChange={(v) => patchBoard.mutate({ id: b.id, b: { enabled: v } })} label={b.name} /></TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Section>
      ) : null}

      {tab === "reports" ? (
        <Section title={t("cadm.reports")} description={t("cadm.reports_desc")}>
          {reports.isLoading ? <Skeleton className="h-32" /> : (reports.data?.items.length ?? 0) === 0 ? (
            <p className="py-6 text-center text-sm text-muted-fg">{t("cadm.all_clear")}</p>
          ) : (
            <ul className="space-y-2">
              {reports.data!.items.map((r: any) => (
                <li key={r.id} className="rounded-2xl border border-border p-3">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-fg">
                    <Flag className="h-4 w-4 text-danger" />
                    <Badge tone="outline">{r.target.kind}</Badge>
                    <span>{r.reason}</span>
                    <span>{fmtRelative(r.created_at, locale)}</span>
                    {r.target.gone ? <Badge tone="neutral">{t("cadm.target_gone")}</Badge> : null}
                    <span className="ml-auto flex gap-1">
                      <Button size="sm" variant="outline" className="text-danger" loading={resolve.isPending} onClick={() => resolve.mutate({ id: r.id, action: "hide" })}>
                        <EyeOff className="h-4 w-4" />{t("cadm.hide")}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => resolve.mutate({ id: r.id, action: "dismiss" })}>{t("cadm.dismiss")}</Button>
                    </span>
                  </div>
                  {r.target.title ? <div className="mt-1.5 text-sm font-medium">{r.target.title}</div> : null}
                  {r.target.excerpt ? <p className="mt-0.5 line-clamp-2 text-sm text-muted-fg">{r.target.excerpt}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </Section>
      ) : null}

      {tab === "posts" ? (
        <Section title={t("cadm.recent_posts")} description={t("cadm.posts_desc")}>
          {posts.isLoading ? <Skeleton className="h-32" /> : (
            <Table>
              <THead><tr><TH>{t("cadm.board")}</TH><TH>{t("cadm.title")}</TH><TH>{t("cadm.author")}</TH><TH>♥</TH><TH>💬</TH><TH></TH></tr></THead>
              <TBody>
                {(posts.data?.items ?? []).map((p: any) => (
                  <TR key={p.id}>
                    <TD className="text-xs text-muted-fg">{p.board}</TD>
                    <TD className="max-w-[360px] truncate text-sm">{p.title}</TD>
                    <TD className="text-xs text-muted-fg">{p.author}</TD>
                    <TD className="tabular-nums">{p.like_count}</TD>
                    <TD className="tabular-nums">{p.comment_count}</TD>
                    <TD><Button size="sm" variant="ghost" className="text-danger" onClick={() => setStatus.mutate({ id: p.id, status: "hidden" })}><EyeOff className="h-4 w-4" />{t("cadm.hide")}</Button></TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Section>
      ) : null}

      {tab === "settings" ? (
        <div className="space-y-4">
          <SettingsForm title={t("cadm.rules")} description={t("cadm.rules_desc")} prefix="community." fields={[
            { key: "community.require_verified_email", label: t("cadm.require_verified"), type: "bool", hint: t("cadm.require_verified_hint") },
          ]} />
          <SettingsForm title={t("cadm.ranking")} description={t("cadm.ranking_desc")} prefix="community." fields={[
            { key: "community.rank_like_weight", label: t("cadm.w_like"), type: "number" },
            { key: "community.rank_comment_weight", label: t("cadm.w_comment"), type: "number" },
            { key: "community.rank_view_weight", label: t("cadm.w_view"), type: "number" },
            { key: "community.rank_gravity", label: t("cadm.gravity"), type: "number", hint: t("cadm.gravity_hint") },
          ]} />
        </div>
      ) : null}

      <NewBoardDialog open={newOpen} onClose={() => setNewOpen(false)} onSaved={() => { setNewOpen(false); inval(); }} />
    </Page>
  );
}

function NewBoardDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const t = useT(); const locale = useLocale();
  const [f, setF] = useState({ slug: "", name: "", icon: "", description: "", sort_order: 100 });
  const save = useMutation({
    mutationFn: () => Admin.createBoard({ ...f, kind: "discussion" }),
    onSuccess: () => { setF({ slug: "", name: "", icon: "", description: "", sort_order: 100 }); toast.success(t("common.saved")); onSaved(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <Dialog open={open} onClose={onClose} title={t("cadm.new_board")} description={t("cadm.new_board_desc")}
      footer={<><Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
               <Button variant="accent" loading={save.isPending} disabled={!f.slug.trim() || !f.name.trim()} onClick={() => save.mutate()}>{t("cadm.create")}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("cadm.name")}><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label={t("adm.col_slug")} hint={t("cadm.slug_hint")}><Input value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value.replace(/[^a-z0-9-]/g, "") })} /></Field>
        <Field label={t("cadm.icon")}>
          <Select aria-label={t("cadm.icon")} value={f.icon || "message-circle"} onChange={(e) => setF({ ...f, icon: e.target.value })}
            options={BOARD_GLYPHS.map((g) => ({ value: g, label: <span className="inline-flex items-center gap-2"><BoardIcon name={g} className="h-4 w-4" />{g}</span>, keywords: g }))} />
        </Field>
        <Field label={t("cadm.order")}><Input type="number" value={f.sort_order} onChange={(e) => setF({ ...f, sort_order: Number(e.target.value) })} /></Field>
        <Field label={t("cadm.description")} className="sm:col-span-2"><Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      </div>
    </Dialog>
  );
}

/** 내 주변 맛집: are the keys there, is the provider answering, what have people written. */
