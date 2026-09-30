"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { DateRangePicker, toISODate } from "@cocorof/react-calendar";
import { Selector } from "@cocorof/react-selector";
import { BookOpen, Download, ExternalLink, FileText, FileSpreadsheet, ImageIcon, LayoutGrid, List, MessageSquare, Presentation, Music, Search, Trash2, File as FileIcon, AlertCircle, Loader2 } from "@/components/icons";
import { Agents, Files, type AgentFileItem, type FileKind } from "@/lib/api";
import { useRcalTheme } from "@/lib/theme";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtDate, fmtDateTime, fmtNumber } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { fmtBytes } from "@/lib/upload";
import { confirm } from "@/lib/confirm";
import { Page } from "@/components/owner/Shell";
import { useAgent } from "./AgentLayout";
import { Button, buttonLook } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { KeyValue, PageHeader } from "@/components/ui/misc";
import { Segmented } from "@/components/ui/tabs";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { HoverCard, useOverflow } from "@/components/ui/hover-card";
import { usePhotoViewer } from "@/components/ui/photo-view";
import { StorageBar } from "@/components/storage/StorageBar";
import { DriveSave } from "./DriveFiles";

/** [파일] — 이 비서에게 들어온 자료 전부 (plan/55 §6-2).
 *
 *  대화에 붙인 사진·문서가 여기에 쌓이고, 비서는 이것을 다시 열어 본다. 표준 틀: 위에
 *  제목과 오른쪽 보기 전환, 한 줄 거르기(기간이 맨 앞), 칸 셋, 그리고 격자나 목록.
 */
const ALL = "";
export const FILE_KINDS: FileKind[] = ["image", "pdf", "document", "sheet", "slides", "text", "audio", "other"];
type TFn = (k: string, v?: Record<string, string | number>) => string;
export const kindLabel = (t: TFn, k: FileKind) => t(`files.kind_${k}`);
const sourceLabel = (t: TFn, k: string) => (t(`files.src_${k}`) === `files.src_${k}` ? k : t(`files.src_${k}`));

export function KindIcon({ kind, className }: { kind: FileKind; className?: string }) {
  const I = kind === "image" ? ImageIcon : kind === "sheet" ? FileSpreadsheet : kind === "slides" ? Presentation
    : kind === "audio" ? Music : kind === "other" ? FileIcon : FileText;
  return <I className={className} />;
}

export function AgentFiles() {
  const t = useT(); const a = useAgent();
  const [view, setView] = useState<"grid" | "list">("grid");
  const storage = useQuery({ queryKey: ["storage"], queryFn: Files.storage });
  return (
    <Page>
      <PageHeader title={t("files.title")} description={t("files.agent_desc")}
        action={<ViewToggle value={view} onChange={setView} />} />
      {storage.data ? <StorageBar usage={storage.data} highlight={`agent:${a.id}`} highlightLabel={a.name} compact className="mb-4" /> : null}
      <FilesBrowser agentId={a.id} view={view} />
    </Page>
  );
}

export function ViewToggle({ value, onChange }: { value: "grid" | "list"; onChange: (v: "grid" | "list") => void }) {
  const t = useT();
  return (
    <Segmented ariaLabel={t("files.view")} value={value} onChange={onChange} options={[
      { value: "grid", label: <span className="inline-flex items-center gap-1.5"><LayoutGrid className="h-4 w-4" />{t("files.view_grid")}</span> },
      { value: "list", label: <span className="inline-flex items-center gap-1.5"><List className="h-4 w-4" />{t("files.view_list")}</span> },
    ]} />
  );
}

/** 파일 목록 한 벌. 비서의 [파일] 탭은 그 비서의 것만(``agentId``), [내 정보 → 파일] 은 모든 비서의
 *  것을 [비서] 거르기와 함께 본다. 비서·정렬·열린 파일은 주소에 둔다 — 저장 공간 범례를 누르거나
 *  [여유 공간 확보] 를 누르면 같은 화면이 그 조건으로 바뀐다. */
export function FilesBrowser({ agentId, view }: { agentId?: string; view: "grid" | "list" }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const rcal = useRcalTheme();
  const router = useRouter(); const sp = useSearchParams();
  const all = !agentId;
  const [range, setRange] = useState<[Date | null, Date | null]>([null, null]);
  const [source, setSource] = useState(ALL);
  const [kind, setKind] = useState(ALL);
  const [q, setQ] = useState(""); const dq = useDebounced(q, 300);
  const [limit, setLimit] = useState(60);
  const sort: "recent" | "size" = sp.get("sort") === "size" ? "size" : "recent";
  const pickedAgent = all ? sp.get("agent") ?? ALL : agentId;
  const openId = sp.get("open");
  const setParam = (k: string, v: string | null) => {
    const p = new URLSearchParams(sp.toString());
    if (v) p.set(k, v); else p.delete(k);
    router.replace(`?${p.toString()}`, { scroll: false });
  };
  const setOpen = (id: string | null) => setParam("open", id);
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => Agents.list(), enabled: all });
  const names = useMemo(() => Object.fromEntries((agents.data?.items ?? []).map((x) => [x.id, x.name])), [agents.data]);
  const since = range[0] ? toISODate(range[0]) : undefined;
  const until = range[1] ? toISODate(range[1]) : undefined;
  const list = useQuery({
    queryKey: ["files", pickedAgent || "all", { since, until, source, kind, dq, sort, limit }],
    queryFn: () => Files.list({ agent_id: pickedAgent || undefined, since, until, source: source || undefined, kind: kind || undefined, q: dq || undefined, sort, limit }),
    placeholderData: keepPreviousData,
    // 방금 올린 파일은 작업자가 읽는 중이다. 다 읽힐 때까지만 잠깐씩 다시 본다.
    refetchInterval: (query) => (query.state.data?.items.some((f) => f.status === "pending") ? 4000 : false),
  });
  useEffect(() => { setLimit(60); }, [since, until, source, kind, dq, sort, pickedAgent]);
  const d = list.data;
  const filtered = !!(since || until || source || kind || dq || (all && pickedAgent));

  return (
    <>
      <div className="filter-row mb-4 flex flex-wrap items-center gap-2">
        <DateRangePicker value={range} onChange={setRange} locale={locale} clearable className={rcal} panelClassName={rcal}
                         width="auto" aria-label={t("files.f_period")} placeholder={t("files.f_all_time")} />
        {all ? (
          <Selector size="lg" ariaLabel={t("files.f_agent")} value={pickedAgent ?? ALL} onChange={(v: string) => setParam("agent", v || null)}
            options={[{ value: ALL, label: t("files.f_all_agents") }, ...(agents.data?.items ?? []).map((x) => ({ value: x.id, label: x.name }))]} />
        ) : null}
        <Selector size="lg" ariaLabel={t("files.f_source")} value={source} onChange={(v: string) => setSource(v)}
          options={[{ value: ALL, label: t("files.f_all_sources") }, { value: "owner", label: t("files.src_chat") }, { value: "visitor", label: t("files.src_public") }, { value: "drive", label: t("files.src_drive") }]} />
        <Selector size="lg" ariaLabel={t("files.f_kind")} value={kind} onChange={(v: string) => setKind(v)}
          options={[{ value: ALL, label: t("files.f_all_kinds") }, ...FILE_KINDS.map((k) => ({ value: k, label: kindLabel(t, k) }))]} />
        <Selector size="lg" ariaLabel={t("files.f_sort")} value={sort} onChange={(v: string) => setParam("sort", v === "size" ? "size" : null)}
          options={[{ value: "recent", label: t("files.sort_recent") }, { value: "size", label: t("files.sort_size") }]} />
        <div className="relative min-w-[12rem] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" />
          <Input className="pl-9" placeholder={t("files.search_ph")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("files.search")} />
        </div>
      </div>

      <p className="mb-3 text-sm tabular-nums text-muted-fg">
        {d ? t(filtered ? "files.summary_filtered" : "files.summary", { n: fmtNumber(d.total), size: fmtBytes(d.total_bytes) }) : "\u00a0"}
        {d && d.unreadable ? <> · <span className="text-warning">{t("files.summary_unreadable", { n: fmtNumber(d.unreadable) })}</span></> : null}
      </p>

      {list.isLoading ? <Skeleton className="h-48" /> : list.error ? (
        <EmptyState title={friendlyError(list.error, locale)} />
      ) : !d?.items.length ? (
        <EmptyState title={filtered ? t("files.empty_filtered") : t("files.empty")}
          description={filtered ? undefined : t("files.empty_hint")} />
      ) : view === "grid" ? (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          {d.items.map((f) => <li key={f.id}><FileCard f={f} agentName={all ? (f.agent_id ? names[f.agent_id] ?? f.agent_name : t("files.no_agent")) : undefined} onOpen={() => setOpen(f.id)} /></li>)}
        </ul>
      ) : (
        <Table>
          <THead><TR><TH>{t("files.col_name")}</TH>{all ? <TH>{t("files.f_agent")}</TH> : null}<TH>{t("files.f_kind")}</TH><TH>{t("files.col_size")}</TH><TH>{t("files.f_source")}</TH><TH>{t("files.col_received")}</TH></TR></THead>
          <TBody>
            {d.items.map((f) => (
              <TR key={f.id} tabIndex={0} role="button" className="cursor-pointer" onClick={() => setOpen(f.id)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(f.id); } }}>
                <TD className="max-w-[360px]"><span className="flex items-center gap-2"><KindIcon kind={f.kind} className="h-4 w-4 shrink-0 text-muted-fg" /><span className="truncate">{f.filename}</span>{f.status === "unreadable" ? <Badge tone="warning">{t("files.unreadable_badge")}</Badge> : null}</span></TD>
                {all ? <TD className="whitespace-nowrap text-muted-fg">{f.agent_id ? names[f.agent_id] ?? f.agent_name : t("files.no_agent")}</TD> : null}
                <TD className="whitespace-nowrap text-muted-fg">{kindLabel(t, f.kind)}</TD>
                <TD className="whitespace-nowrap tabular-nums">{fmtBytes(f.size)}</TD>
                <TD className="whitespace-nowrap text-muted-fg">{sourceLabel(t, f.source)}</TD>
                <TD className="whitespace-nowrap tabular-nums text-muted-fg">{f.created_at ? fmtDateTime(f.created_at) : "–"}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      {d && d.total > d.items.length ? (
        <div className="mt-4 flex justify-center">
          <Button variant="outline" size="sm" loading={list.isFetching} onClick={() => setLimit((n) => n + 60)}>{t("files.more", { n: fmtNumber(d.total - d.items.length) })}</Button>
        </div>
      ) : null}

      <FileSheet id={openId} onClose={() => setOpen(null)}
        onDeleted={() => { setOpen(null); qc.invalidateQueries({ queryKey: ["files"] }); qc.invalidateQueries({ queryKey: ["storage"] }); }} />
    </>
  );
}

function FileCard({ f, agentName, onOpen }: { f: AgentFileItem; agentName?: string; onOpen: () => void }) {
  const t = useT();
  const [ref, cut] = useOverflow<HTMLDivElement>();
  return (
    <button type="button" onClick={onOpen} className="group flex w-full flex-col overflow-hidden rounded-xl border border-border bg-card text-left transition-colors hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-ring">
      <div className="relative flex aspect-[4/3] w-full items-center justify-center bg-muted">
        {f.thumb_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={f.thumb_url} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : f.status === "pending" ? <Loader2 className="h-6 w-6 animate-spin text-muted-fg" />
          : <KindIcon kind={f.kind} className="h-9 w-9 text-muted-fg" />}
        {f.status === "unreadable" ? <span className="absolute right-1.5 top-1.5 rounded-full bg-card/90 p-1 text-warning" title={t("files.stat_unreadable")}><AlertCircle className="h-3.5 w-3.5" /></span> : null}
        {f.scope === "visitor" ? <span className="absolute left-1.5 top-1.5 rounded-full bg-card/90 px-1.5 py-0.5 text-[10px] font-medium">{t("files.src_public")}</span> : null}
      </div>
      <HoverCard content={f.filename} disabled={!cut} tone="tip" side="bottom" className="block w-full">
        <div ref={ref} className="px-2.5 pt-2 text-[13px] font-medium"><span data-truncate className="block truncate">{f.filename}</span></div>
      </HoverCard>
      <div className="truncate px-2.5 pb-2 text-[11px] text-muted-fg tabular-nums">{agentName ? `${agentName} · ` : ""}{fmtBytes(f.size)} · {f.created_at ? fmtDate(f.created_at, { month: "short", day: "numeric" }) : ""}</div>
    </button>
  );
}

function FileSheet({ id, onClose, onDeleted }: { id: string | null; onClose: () => void; onDeleted: () => void }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const photo = usePhotoViewer();
  const q = useQuery({ queryKey: ["file", id], queryFn: () => Files.get(id!), enabled: !!id });
  const f = q.data;
  const remove = useMutation({
    mutationFn: (fid: string) => Files.remove(fid),
    onSuccess: () => { toast.success(t("files.deleted")); onDeleted(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const promote = useMutation({
    mutationFn: (fid: string) => Files.toKnowledge(fid),
    onSuccess: () => { toast.success(t("files.promoted")); q.refetch(); qc.invalidateQueries({ queryKey: ["storage"] }); qc.invalidateQueries({ queryKey: ["knowledge"] }); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const convHref = useMemo(() => {
    if (!f?.conversation_id) return null;
    return f.scope === "visitor" ? `/app/conversations?agent=${f.agent_id}&c=${f.conversation_id}` : `/app/chat?a=${f.agent_id}&c=${f.conversation_id}`;
  }, [f]);
  return (
    <Sheet open={!!id} onClose={onClose} side="right" title={f?.filename ?? t("files.title")}>
      {!f ? <Skeleton className="h-64" /> : (
        <div className="space-y-5">
          {f.kind === "image" ? (
            <button type="button" onClick={() => photo.view(f.url, f.filename)} className="block w-full overflow-hidden rounded-xl bg-muted">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={f.url} alt={f.filename} className="max-h-[50vh] w-full object-contain" />
            </button>
          ) : (
            <div className="flex items-center gap-3 rounded-xl border border-border bg-muted/40 p-4">
              <KindIcon kind={f.kind} className="h-8 w-8 text-accent" />
              <div className="min-w-0"><div className="truncate font-medium">{f.filename}</div><div className="text-xs text-muted-fg">{kindLabel(t, f.kind)} · {fmtBytes(f.size)}{f.pages ? ` · ${t("files.pages", { n: f.pages })}` : ""}</div></div>
            </div>
          )}
          {f.caption ? <p className="rounded-lg bg-muted px-3 py-2 text-sm"><span className="mr-1.5 text-xs text-muted-fg">{t("files.caption")}</span>{f.caption}</p> : null}
          {f.status === "pending" ? <p className="text-sm text-muted-fg">{t("files.reading")}</p> : null}
          {f.status === "unreadable" ? <p className="rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning">{t("files.unreadable_note")}</p> : null}
          {f.preview ? (
            <div>
              <div className="mb-1.5 text-xs font-medium text-muted-fg">{t("files.preview")}{f.text_chars ? ` · ${t("files.chars", { n: fmtNumber(f.text_chars) })}` : ""}</div>
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-card p-3 font-sans text-[13px] leading-relaxed">{f.preview}</pre>
            </div>
          ) : null}
          {/* 외부인에게 이 파일을 쓸지는 여기서 정하지 않는다 — 그 비서의 [지식] 탭에서 고른다 (plan/57). */}
          {f.scope === "owner" ? (
            <p className="text-xs text-muted-fg">
              {t("files.outsider_where")}{" "}
              <Link href={f.agent_id ? `/app/agents/${f.agent_id}/knowledge` : "/app/agents"} className="font-medium text-accent hover:underline">
                {t(f.agent_id ? "files.outsider_go" : "files.outsider_pick")}
              </Link>
            </p>
          ) : <p className="text-xs text-muted-fg">{t("files.visitor_note")}</p>}
          <KeyValue items={[
            { k: t("files.f_came_via"), v: f.agent_name || t("files.no_agent") },
            { k: t("files.f_kind"), v: kindLabel(t, f.kind) },
            { k: t("files.col_size"), v: `${fmtBytes(f.size)} (${t("files.bytes", { n: f.size.toLocaleString() })})` },
            { k: t("files.from"), v: sourceLabel(t, f.source) },
            { k: t("files.col_received"), v: f.created_at ? fmtDateTime(f.created_at) : "–" },
          ]} />
          <div className="flex flex-wrap gap-2">
            {convHref ? <Link href={convHref} className={buttonLook("outline", "sm")}><MessageSquare className="h-4 w-4" />{t("files.go_chat")}</Link> : null}
            <a href={f.url} target="_blank" rel="noopener noreferrer" className={buttonLook("outline", "sm")}><ExternalLink className="h-4 w-4" />{t("files.open")}</a>
            <a href={f.url} download={f.filename} className={buttonLook("outline", "sm")}><Download className="h-4 w-4" />{t("files.download")}</a>
            <DriveSave fileId={f.id} />
            {f.knowledge_document_id ? (
              <Link href="/app/knowledge" className={buttonLook("outline", "sm")}><BookOpen className="h-4 w-4" />{t("files.in_knowledge")}</Link>
            ) : f.can_promote && f.status === "ready" ? (
              <Button variant="outline" size="sm" loading={promote.isPending} onClick={async () => {
                if (await confirm({ title: t("files.promote_q"), description: t("files.promote_desc"), confirmLabel: t("files.promote_ok") })) promote.mutate(f.id);
              }}><BookOpen className="h-4 w-4" />{t("files.promote")}</Button>
            ) : null}
          </div>
          <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
            <p className="text-xs text-muted-fg">{t("files.delete_hint")}</p>
            <Button variant="danger" size="sm" loading={remove.isPending} onClick={async () => {
              if (await confirm({ title: t("files.delete_q"), description: t("files.delete_desc"), danger: true, confirmLabel: t("common.delete") })) remove.mutate(f.id);
            }}><Trash2 className="h-4 w-4" />{t("common.delete")}</Button>
          </div>
        </div>
      )}
      {photo.node}
    </Sheet>
  );
}
