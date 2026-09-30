"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Brain, Pin, Plus, Search, Trash2 } from "@/components/icons";
import { Agents, type MemoryNote } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { AgentFacts } from "./AgentFacts";
import { levelLabel, normalize } from "@/lib/visibility";
import { VisibilityPicker } from "@/components/ui/visibility";
import { friendlyError } from "@/lib/errors";
import { fmtDateTime } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { useAgent } from "./AgentLayout";
import { Tabs } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input, Textarea, Field, Select } from "@/components/ui/input";
import { Sheet } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Switch } from "@/components/ui/switch";
import { Markdown } from "@/components/chat/Markdown";
import { PageHeader } from "@/components/ui/misc";
import { confirm } from "@/lib/confirm";

type NS = "owner" | "shared" | "visitors";

export function AgentMemory() {
  const t = useT(); const locale = useLocale(); const a = useAgent(); const qc = useQueryClient();
  const [ns, setNs] = useState<NS | "facts">("owner");
  const [cat, setCat] = useState<string | null>(null);
  const [q, setQ] = useState(""); const dq = useDebounced(q, 300);
  const [open, setOpen] = useState<{ id?: string; ns: NS } | null>(null);
  const overview = useQuery({ queryKey: ["memory", a.id], queryFn: () => Agents.memory(a.id) });
  const notes = useQuery({ queryKey: ["memory", a.id, ns, cat], queryFn: () => Agents.notes(a.id, ns as NS, cat ?? undefined), enabled: ns !== "facts" && !dq });
  const search = useQuery({ queryKey: ["memory", a.id, "search", dq], queryFn: () => Agents.searchMemory(a.id, dq), enabled: !!dq });
  const counts = overview.data?.counts ?? {};
  const cats = ns === "facts" ? [] : Object.entries(counts[ns] ?? {}).filter(([k]) => k !== "total" && k !== "_total");
  const total = (n: string) => Object.entries(counts[n] ?? {}).filter(([k]) => k !== "total").reduce((s, [, v]) => s + (typeof v === "number" ? v : 0), 0);

  return (
    <Page>
      <PageHeader title={t("agent.tab_memory")} description={t("mem.desc")} action={ns === "facts" ? null : <Button onClick={() => setOpen({ ns: ns as NS })}><Plus className="h-4 w-4" />{t("mem.new_note")}</Button>} />
      {/* 방은 **누구에 대한 기억인가**로만 나눈다 (plan/48 §2). 예전에는 방 이름이
          곧 공개 여부여서(`shared` 는 방문자도 읽는 방) "남에게 보일까" 의 답이 칸을
          옮기는 일이었다. 이제 공개 범위는 기억마다 붙는다. `shared` 는 옛 방이라
          남아 있는 동안만 보인다. */}
      <Tabs value={ns} onChange={(v) => { setNs(v as NS | "facts"); setCat(null); }} items={[
        { key: "owner", label: t("mem.ns_owner"), count: total("owner") },
        ...(total("shared") ? [{ key: "shared", label: t("mem.ns_shared"), count: total("shared") }] : []),
        { key: "visitors", label: t("mem.ns_visitors"), count: total("visitors") },
        // 사실도 비서가 알게 된 것이라 같은 자리에 산다 (plan/49).
        { key: "facts", label: t("mem.facts") },
      ]} className="mb-4" />
      {ns === "facts" ? <AgentFacts agentId={a.id} /> : (
        <>
          <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="relative flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" /><Input className="pl-9" placeholder={t("mem.search_placeholder")} value={q} onChange={(e) => setQ(e.target.value)} /></div>
            {cats.length ? <div className="flex shrink-0 gap-1.5 overflow-x-auto scroll-fade-x">
              <button type="button" onClick={() => setCat(null)} className={cn("shrink-0 rounded-full px-3 py-1.5 text-xs", !cat ? "bg-fg text-bg" : "bg-muted text-muted-fg")}>{t("common.all")}</button>
              {cats.map(([k, v]) => <button key={k} type="button" onClick={() => setCat(k)} className={cn("shrink-0 rounded-full px-3 py-1.5 text-xs", cat === k ? "bg-fg text-bg" : "bg-muted text-muted-fg")}>{k} <span className="opacity-60">{v as number}</span></button>)}
            </div> : null}
          </div>
          {dq ? (
            search.isLoading ? <Skeleton className="h-40" /> : search.data?.items.length ? (
              <ul className="space-y-2">{search.data.items.map((h: any, i: number) => (
                <li key={i}><button type="button" onClick={() => setOpen({ id: h.id, ns: (h.namespace ?? ns) as NS })} className="w-full rounded-xl border border-border bg-card p-3 text-left hover:border-accent/50">
                  <div className="flex items-center gap-2 text-sm font-medium"><span className="truncate">{h.title ?? h.id}</span><Badge>{h.namespace}</Badge>{h.category ? <Badge tone="outline">{h.category}</Badge> : null}<span className="ml-auto text-xs text-muted-fg">{typeof h.score === "number" ? h.score.toFixed(2) : ""}</span></div>
                  <p className="mt-1 line-clamp-2 text-xs text-muted-fg">{h.snippet ?? h.body ?? h.text}</p>
                </button></li>
              ))}</ul>
            ) : <EmptyState title={t("mem.no_results")} />
          ) : notes.isLoading ? <Skeleton className="h-40" /> : notes.data?.items.length ? (
            <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">{notes.data.items.map((n) => (
              <li key={n.id}><button type="button" onClick={() => setOpen({ id: n.id, ns })} className="h-full w-full rounded-xl border border-border bg-card p-3 text-left hover:border-accent/50">
                <div className="flex items-center gap-1.5 text-sm font-medium">{n.pinned ? <Pin className="h-3.5 w-3.5 text-accent" /> : null}<span className="truncate">{n.title}</span></div>
                <p className="mt-1 line-clamp-3 text-xs text-muted-fg whitespace-pre-wrap">{n.body}</p>
                <div className="mt-2 flex flex-wrap items-center gap-1 text-[11px] text-muted-fg">
                  <Badge tone="outline">{n.category}</Badge>
                  <Badge tone={n.importance === "high" ? "warning" : "neutral"}>{n.importance}</Badge>
                  {ns === "visitors" ? null : <Badge tone={normalize(n.visibility) === "public" ? "warning" : "neutral"}>{levelLabel(n.visibility, locale)}</Badge>}
                  <span className="ml-auto">{fmtDateTime(n.updated)}</span>
                </div>
              </button></li>
            ))}</ul>
          ) : <EmptyState icon={<Brain />} title={t("mem.empty")} description={t("mem.empty_desc")} />}
        </>
      )}
      <NoteSheet agentId={a.id} target={open} onClose={() => setOpen(null)} onChanged={() => { qc.invalidateQueries({ queryKey: ["memory", a.id] }); }} />
    </Page>
  );
}

function NoteSheet({ agentId, target, onClose, onChanged }: { agentId: string; target: { id?: string; ns: NS } | null; onClose: () => void; onChanged: () => void }) {
  const t = useT(); const locale = useLocale();
  const [edit, setEdit] = useState(false);
  const [draft, setDraft] = useState<Partial<MemoryNote>>({});
  const q = useQuery({ queryKey: ["memory-note", agentId, target?.ns, target?.id], queryFn: () => Agents.note(agentId, target!.ns, target!.id!), enabled: !!target?.id });
  const n = q.data;
  const isNew = !!target && !target.id;
  const cur = { title: draft.title ?? n?.title ?? "", body: draft.body ?? n?.body ?? "", category: draft.category ?? n?.category ?? "notes", tags: draft.tags ?? n?.tags ?? [], pinned: draft.pinned ?? n?.pinned ?? false, importance: draft.importance ?? n?.importance ?? "medium", visibility: normalize(draft.visibility ?? n?.visibility) };
  const save = useMutation({ mutationFn: () => Agents.writeNote(agentId, { ...cur, namespace: target!.ns, id: target?.id ?? null }), onSuccess: () => { toast.success(t("common.saved")); onChanged(); setEdit(false); setDraft({}); if (isNew) onClose(); else q.refetch(); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const del = useMutation({ mutationFn: () => Agents.deleteNote(agentId, target!.ns, target!.id!), onSuccess: () => { onChanged(); onClose(); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const editing = edit || isNew;
  return (
    <Sheet open={!!target} onClose={() => { onClose(); setEdit(false); setDraft({}); }} side="right" title={isNew ? t("mem.new_note") : n?.title ?? "…"}
      footer={<div className="flex justify-between gap-2">
        {!isNew ? <Button variant="ghost" className="text-danger" onClick={async () => { if (await confirm({ title: t("mem.delete_confirm"), danger: true, confirmLabel: t("common.delete") })) del.mutate(); }}><Trash2 className="h-4 w-4" />{t("common.delete")}</Button> : <span />}
        <div className="flex gap-2">{editing ? <><Button variant="outline" onClick={() => { setEdit(false); setDraft({}); if (isNew) onClose(); }}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => save.mutate()} disabled={!cur.title.trim()}>{t("common.save")}</Button></> : <Button onClick={() => setEdit(true)}>{t("common.edit")}</Button>}</div>
      </div>}>
      {q.isLoading ? <Skeleton className="h-40" /> : editing ? (
        <div className="space-y-3">
          <Field label={t("mem.title")}><Input value={cur.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></Field>
          <Field label={t("mem.body")}><Textarea value={cur.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} className="min-h-[220px] font-mono text-sm" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("mem.category")}><Input value={cur.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })} /></Field>
            <Field label={t("mem.importance")}><Select value={cur.importance} onChange={(e) => setDraft({ ...draft, importance: e.target.value })}><option value="low">low</option><option value="medium">medium</option><option value="high">high</option></Select></Field>
          </div>
          <Field label={t("mem.tags")}><Input value={cur.tags.join(", ")} onChange={(e) => setDraft({ ...draft, tags: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></Field>
          <div className="flex items-center justify-between rounded-xl border border-border px-3 py-2"><span className="text-sm">{t("mem.pinned")}</span><Switch checked={cur.pinned} onChange={(v) => setDraft({ ...draft, pinned: v })} label={t("mem.pinned")} /></div>
          {/* 이 기억이 어디까지 나가는가. 손님 방은 그 손님의 것이라 고를 것이 없다. */}
          {target?.ns === "visitors" ? null : (
            <Field label={t("vis.label")} hint={t("mem.visibility_hint")}>
              <VisibilityPicker value={cur.visibility} onChange={(v) => setDraft({ ...draft, visibility: v })} hint />
            </Field>
          )}
        </div>
      ) : n ? (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-1.5"><Badge tone="outline">{n.category}</Badge><Badge tone={n.importance === "high" ? "warning" : "neutral"}>{n.importance}</Badge>{target?.ns === "visitors" ? null : <Badge tone={normalize(n.visibility) === "public" ? "warning" : "neutral"}>{levelLabel(n.visibility, locale)}</Badge>}{n.pinned ? <Badge tone="accent"><Pin className="h-3 w-3" />{t("mem.pinned")}</Badge> : null}{n.tags?.map((x) => <Badge key={x}>#{x}</Badge>)}</div>
          <Markdown text={n.body} className="text-sm" />
          <div className="text-xs text-muted-fg">{t("mem.source")}: {n.source} · {fmtDateTime(n.updated)}</div>
        </div>
      ) : null}
    </Sheet>
  );
}

