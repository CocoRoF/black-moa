"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { FileText, Globe, HelpCircle, Plus, RefreshCw, Search, StickyNote, Trash2, Upload } from "@/components/icons";
import { Files, Knowledge, type Faq, type KnowledgeDoc } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtBytes, fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useDebounced } from "@/lib/hooks";
import { Page } from "./Shell";
import { Tabs } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/input";
import { Dialog, Sheet } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/misc";
import { StorageBar } from "@/components/storage/StorageBar";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { confirm } from "@/lib/confirm";

type Tab = "docs" | "faq" | "search";

export function KnowledgePage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("docs");
  const docs = useQuery({ queryKey: ["knowledge", "docs"], queryFn: () => Knowledge.docs(), refetchInterval: (q) => (q.state.data?.items.some((d) => d.status === "queued" || d.status === "processing") ? 4000 : false) });
  const [addKind, setAddKind] = useState<"note" | "url" | null>(null);
  // The id, not the row. Holding the row froze the panel on the copy that existed when it
  // was opened: the list polls and turns 처리 중 into 준비됨, while the panel spun forever
  // and its [다시 색인] re-indexed a document that had been ready for minutes.
  const [openId, setOpenId] = useState<string | null>(null);
  const open = docs.data?.items.find((d) => d.id === openId) ?? null;
  const inval = () => { qc.invalidateQueries({ queryKey: ["knowledge"] }); qc.invalidateQueries({ queryKey: ["storage"] }); };
  const del = useMutation({ mutationFn: (id: string) => Knowledge.remove(id), onSuccess: () => { inval(); setOpenId(null); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const reindex = useMutation({ mutationFn: (id: string) => Knowledge.reindex(id), onSuccess: inval, onError: (e) => toast.error(friendlyError(e, locale)) });
  const upload = useCallback(async (files: File[]) => {
    for (const f of files) {
      const fd = new FormData(); fd.append("file", f); fd.append("kind", "file");
      try { await Knowledge.create(fd); } catch (e) { toast.error(`${f.name}: ${friendlyError(e, locale)}`); }
    }
    inval();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);
  const storage = useQuery({ queryKey: ["storage"], queryFn: Files.storage });
  return (
    <Page>
      <PageHeader title={t("nav.knowledge")} description={t("kn.desc")} action={<><Button variant="outline" onClick={() => setAddKind("note")}><StickyNote className="h-4 w-4" />{t("kn.add_note")}</Button><Button variant="outline" onClick={() => setAddKind("url")}><Globe className="h-4 w-4" />{t("kn.add_url")}</Button></>} />
      {/* 지식과 비서의 파일이 한 공간을 나눠 쓴다 (plan/55). 이 칸이 얼마인지와 전체를 한 줄에. */}
      {storage.data ? <StorageBar usage={storage.data} highlight="knowledge" compact className="mb-4" /> : null}
      {/* 외부인에게 무엇을 쓸지는 여기서 정하지 않는다 — 비서마다 [지식] 탭에서 고른다 (plan/57). */}
      <p className="-mt-1 mb-4 text-xs text-muted-fg">{t("kn.outsider_where")}</p>
      <Tabs value={tab} onChange={setTab} items={[{ key: "docs", label: t("kn.tab_docs"), count: docs.data?.items.length }, { key: "faq", label: t("kn.tab_faq") }, { key: "search", label: t("kn.tab_search") }]} className="mb-4" />
      {tab === "docs" ? (
        <>
          <Dropzone onFiles={upload} />
          {docs.data?.items.some((d) => d.status === "queued" || d.status === "processing") ? <p role="status" className="mt-3 flex items-center gap-1.5 text-xs text-muted-fg"><RefreshCw className="h-3 w-3 animate-spin" />{t("kn.processing_hint")}</p> : null}
          {docs.isLoading ? <Skeleton className="mt-4 h-40" /> : docs.data?.items.length ? (
            <ul className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {docs.data.items.map((d) => (
                <li key={d.id}><button type="button" onClick={() => setOpenId(d.id)} className="flex w-full items-start gap-3 rounded-xl border border-border bg-card p-3 text-left hover:border-accent/50">
                  <span className="mt-0.5 text-muted-fg">{d.kind === "url" ? <Globe className="h-5 w-5" /> : d.kind === "note" ? <StickyNote className="h-5 w-5" /> : <FileText className="h-5 w-5" />}</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{d.title || d.filename}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1 text-[11px] text-muted-fg"><StatusBadge s={d.status} />{d.size_bytes ? <span>{fmtBytes(d.size_bytes)}</span> : null}</div>
                    {d.error ? <div className="mt-1 truncate text-[11px] text-danger">{d.error}</div> : null}
                  </div>
                </button></li>
              ))}
            </ul>
          ) : <EmptyState className="mt-4" icon={<FileText />} title={t("kn.empty")} description={t("kn.empty_desc")} />}
        </>
      ) : tab === "faq" ? <FaqTab /> : <SearchTab />}

      <TextDocDialog kind={addKind} onClose={() => setAddKind(null)} onCreated={inval} />
      <Sheet open={!!open} onClose={() => setOpenId(null)} side="right" title={open?.title || open?.filename}>
        {open ? <DocDetail d={open} onDelete={async () => { if (await confirm({ title: t("kn.delete_confirm"), danger: true, confirmLabel: t("common.delete") })) del.mutate(open.id); }} onReindex={() => reindex.mutate(open.id)} /> : null}
      </Sheet>
    </Page>
  );
}

function StatusBadge({ s }: { s: string }) {
  const t = useT();
  const tone = s === "ready" ? "success" : s === "failed" ? "danger" : "warning";
  return <Badge tone={tone}>{s === "processing" || s === "queued" ? <RefreshCw className="h-3 w-3 animate-spin" /> : null}{t(`kn.status_${s}`) === `kn.status_${s}` ? s : t(`kn.status_${s}`)}</Badge>;
}

function Dropzone({ onFiles }: { onFiles: (f: File[]) => Promise<void> }) {
  const t = useT();
  const [over, setOver] = useState(false); const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const handle = async (fl: FileList | null) => { if (!fl?.length) return; setBusy(true); try { await onFiles(Array.from(fl)); } finally { setBusy(false); } };
  return (
    <div role="button" tabIndex={0} onClick={() => input.current?.click()} onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={(e) => { e.preventDefault(); setOver(false); void handle(e.dataTransfer.files); }}
      className={cn("flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-4 py-8 text-center transition-colors", over ? "border-accent bg-accent/8" : "border-border hover:bg-muted/50")}>
      <input ref={input} type="file" multiple hidden accept=".pdf,.txt,.md,.docx,.xlsx,.pptx,.csv,.html,.json" onChange={(e) => { void handle(e.target.files); e.target.value = ""; }} />
      <Upload className={cn("h-6 w-6 text-muted-fg", busy && "animate-bounce")} />
      <div className="mt-2 text-sm font-medium">{busy ? t("kn.uploading") : t("kn.drop_title")}</div>
      <div className="mt-0.5 text-xs text-muted-fg">{t("kn.drop_desc")}</div>
    </div>
  );
}

function TextDocDialog({ kind, onClose, onCreated }: { kind: "note" | "url" | null; onClose: () => void; onCreated: () => void }) {
  const t = useT(); const locale = useLocale();
  const [title, setTitle] = useState(""); const [body, setBody] = useState(""); const [url, setUrl] = useState("");
  const m = useMutation({
    mutationFn: () => { const fd = new FormData(); fd.append("kind", kind!); fd.append("title", title); fd.append("body", body); fd.append("url", url); return Knowledge.create(fd); },
    onSuccess: () => { onCreated(); onClose(); setTitle(""); setBody(""); setUrl(""); toast.success(t("kn.created")); }, onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <Dialog open={!!kind} onClose={onClose} title={kind === "url" ? t("kn.add_url") : t("kn.add_note")} footer={<><Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button><Button loading={m.isPending} disabled={kind === "url" ? !url : !body.trim()} onClick={() => m.mutate()}>{t("common.add")}</Button></>}>
      <div className="space-y-3">
        <Field label={t("kn.title")}><Input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        {kind === "url" ? <Field label="URL"><Input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" /></Field> : <Field label={t("kn.body")}><Textarea value={body} onChange={(e) => setBody(e.target.value)} className="min-h-[200px]" /></Field>}
      </div>
    </Dialog>
  );
}

function DocDetail({ d, onDelete, onReindex }: { d: KnowledgeDoc; onDelete: () => void; onReindex: () => void }) {
  const t = useT();
  const full = useQuery({ queryKey: ["knowledge", "doc", d.id], queryFn: () => Knowledge.get(d.id) });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5"><StatusBadge s={d.status} /><Badge tone="outline">{d.kind}</Badge>{d.mime ? <Badge tone="outline">{d.mime}</Badge> : null}<span className="text-xs text-muted-fg">{fmtDateTime(d.created_at)}</span></div>
      {d.source_url ? <a href={d.source_url} target="_blank" rel="noopener noreferrer" className="block truncate text-sm text-accent underline">{d.source_url}</a> : null}
      {d.error ? <p className="rounded-lg bg-danger/10 p-2 text-xs text-danger">{d.error}</p> : null}
      {full.data?.text_preview ? <div><div className="mb-1 text-sm font-medium">{t("kn.preview")}</div><pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded-xl bg-muted p-3 font-sans text-xs">{full.data.text_preview}</pre></div> : null}
      <div className="flex gap-2 pt-2"><Button variant="outline" size="sm" onClick={onReindex}><RefreshCw className="h-4 w-4" />{t("kn.reindex")}</Button><Button variant="ghost" size="sm" className="text-danger ml-auto" onClick={onDelete}><Trash2 className="h-4 w-4" />{t("common.delete")}</Button></div>
    </div>
  );
}

function FaqTab() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["knowledge", "faqs"], queryFn: Knowledge.faqs });
  const [edit, setEdit] = useState<Partial<Faq> | null>(null);
  const inval = () => qc.invalidateQueries({ queryKey: ["knowledge", "faqs"] });
  const save = useMutation({ mutationFn: (f: Partial<Faq>) => (f.id ? Knowledge.patchFaq(f.id, { question: f.question, answer: f.answer }) : Knowledge.createFaq({ question: f.question, answer: f.answer })), onSuccess: () => { inval(); setEdit(null); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const del = useMutation({ mutationFn: (id: string) => Knowledge.deleteFaq(id), onSuccess: inval });
  const imp = useMutation({ mutationFn: (f: File) => Knowledge.importFaqs(f), onSuccess: (r) => { inval(); toast.success(t("kn.imported", { n: r.imported })); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Button onClick={() => setEdit({})}><Plus className="h-4 w-4" />{t("kn.add_faq")}</Button>
        <label className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-xl border border-border px-3.5 text-sm hover:bg-muted"><Upload className="h-4 w-4" />{t("kn.import_csv")}<input type="file" accept=".csv,text/csv" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) imp.mutate(f); e.target.value = ""; }} /></label>
        <span className="text-xs text-muted-fg">{t("kn.csv_hint")}</span>
      </div>
      {q.isLoading ? <Skeleton className="h-40" /> : q.data?.items.length ? (
        <Table><THead><tr><TH>{t("kn.question")}</TH><TH>{t("kn.answer")}</TH><TH>{t("kn.source")}</TH><TH></TH></tr></THead>
          <TBody>{q.data.items.map((f) => (
            <TR key={f.id}><TD className="max-w-[240px]"><div className="line-clamp-2 text-sm font-medium">{f.question}</div></TD><TD className="max-w-[360px]"><div className="line-clamp-2 text-sm text-muted-fg">{f.answer}</div></TD><TD className="text-xs text-muted-fg">{f.source}</TD>
              <TD><div className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => setEdit(f)}>{t("common.edit")}</Button><Button size="sm" variant="ghost" className="text-danger" onClick={async () => { if (await confirm({ title: t("common.confirm_delete"), danger: true, confirmLabel: t("common.delete") })) del.mutate(f.id); }}><Trash2 className="h-4 w-4" /></Button></div></TD></TR>
          ))}</TBody></Table>
      ) : <EmptyState icon={<HelpCircle />} title={t("kn.faq_empty")} description={t("kn.faq_empty_desc")} />}
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? t("kn.edit_faq") : t("kn.add_faq")} footer={<><Button variant="outline" onClick={() => setEdit(null)}>{t("common.cancel")}</Button><Button loading={save.isPending} disabled={!edit?.question?.trim() || !edit?.answer?.trim()} onClick={() => edit && save.mutate(edit)}>{t("common.save")}</Button></>}>
        {edit ? <div className="space-y-3">
          <Field label={t("kn.question")}><Input value={edit.question ?? ""} onChange={(e) => setEdit({ ...edit, question: e.target.value })} /></Field>
          <Field label={t("kn.answer")}><Textarea value={edit.answer ?? ""} onChange={(e) => setEdit({ ...edit, answer: e.target.value })} className="min-h-[140px]" /></Field>
        </div> : null}
      </Dialog>
    </div>
  );
}

function SearchTab() {
  const t = useT();
  const [q, setQ] = useState(""); const dq = useDebounced(q, 350);
  const r = useQuery({ queryKey: ["knowledge", "search", dq], queryFn: () => Knowledge.search(dq), enabled: dq.length >= 2 });
  useEffect(() => { /* noop to keep hooks stable */ }, []);
  return (
    <div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" /><Input className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("kn.search_placeholder")} /></div>
      </div>
      <p className="mt-1 text-xs text-muted-fg">{t("kn.search_hint")}</p>
      <div className="mt-4">
        {r.isLoading ? <Skeleton className="h-40" /> : r.data ? r.data.items.length ? (
          <ul className="space-y-2">{r.data.items.map((h: any, i: number) => (
            <li key={i} className="rounded-xl border border-border bg-card p-3">
              <div className="flex items-center gap-2 text-sm font-medium"><span className="truncate">{h.title}</span>{h.heading ? <span className="truncate text-muted-fg font-normal">· {h.heading}</span> : null}{h.faq ? <Badge tone="accent">FAQ</Badge> : null}<span className="ml-auto text-xs text-muted-fg tabular-nums">{typeof h.score === "number" ? h.score.toFixed(2) : ""}</span></div>
              <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-xs text-muted-fg">{h.text}</p>
            </li>
          ))}</ul>
        ) : <EmptyState title={t("mem.no_results")} /> : null}
      </div>
    </div>
  );
}
