"use client";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Columns3, Copy, Database, Play, Search, ShieldCheck, TriangleAlert } from "@/components/icons";
import { Admin, type DbColumn, type DbResult, type DbTable } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

const LIMITS = [50, 100, 200, 500];

/** PostgreSQL's own names are too long for a narrow column, and truncating them mid-word
 *  ("character va") tells the reader less than nothing. */
const TYPES: Record<string, string> = {
  "character varying": "varchar", "timestamp with time zone": "timestamptz",
  "timestamp without time zone": "timestamp", "double precision": "float8",
  "USER-DEFINED": "enum", "ARRAY": "array[]", "boolean": "bool", "integer": "int",
  "bigint": "int8", "jsonb": "jsonb", "uuid": "uuid", "text": "text", "numeric": "numeric",
};
const shortType = (t: string) => TYPES[t] ?? (t.length > 11 ? t.slice(0, 10) + "…" : t);

/** The three parts of a query whose column list can be edited by clicking.
 *
 *  Clicking a column used to append its name to the end of the whole string, which turned
 *  `SELECT owner_id FROM agents LIMIT 100` into `… LIMIT 100 role_line` — a syntax error on
 *  the second click. A column belongs in the select list, so the select list is what gets
 *  parsed and rewritten; anything this cannot parse is left alone and the name is inserted
 *  where the caret is instead, which is what an editor does and cannot produce nonsense.
 */
function parseSelect(sql: string): { head: string; cols: string[]; tail: string } | null {
  const m = /^(\s*select\s+)(.+?)(\s+from\s+[\s\S]*)$/i.exec(sql);
  if (!m) return null;
  const cols = m[2].split(",").map((c) => c.trim()).filter(Boolean);
  // Only plain column names — an expression or a function call is the author's, not ours.
  if (!cols.every((c) => /^(\*|[a-z_][a-z0-9_]*)$/i.test(c))) return null;
  return { head: m[1], cols, tail: m[3] };
}

function toggleColumn(sql: string, name: string, all: string[]): string | null {
  const p = parseSelect(sql);
  if (!p) return null;
  // From `*`, the first click means "show me this one" — narrowing down is what somebody
  // clicking a column in a schema list is doing. From an explicit list it adds or removes.
  // Emptying the list, or naming every column, is `*` again.
  const next = p.cols.includes("*")
    ? [name]
    : p.cols.includes(name) ? p.cols.filter((c) => c !== name) : [...p.cols, name];
  if (!next.length || (all.length > 0 && next.length === all.length)) return `${p.head}*${p.tail}`;
  return `${p.head}${next.join(", ")}${p.tail}`;
}

/** A read-only window onto the database.
 *
 *  Two panes rather than one: the schema on the left is how you find a table when you do
 *  not already know its name, and the query is on the right because that is where the
 *  answer appears. Clicking a table writes the SELECT for you and runs it, so the common
 *  case needs no typing at all — and the SQL stays visible and editable, so the uncommon
 *  case is one edit away rather than a different screen.
 *
 *  The results grid is virtual-free but bounded by the server (500 rows, 2000 characters a
 *  cell), which keeps it a window rather than an export. Columns holding credentials come
 *  back already masked: the server never sends them, so nothing here has to be trusted to
 *  hide them. */
export function DbView() {
  const t = useT(); const locale = useLocale();
  const [table, setTable] = useState("");
  const [filter, setFilter] = useState("");
  const [sql, setSql] = useState("");
  const [limit, setLimit] = useState(100);
  const [result, setResult] = useState<DbResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const editor = useRef<HTMLTextAreaElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(520);

  const tables = useQuery({ queryKey: ["admin", "dbview", "tables"], queryFn: Admin.dbTables, staleTime: 60_000 });
  const cols = useQuery({
    queryKey: ["admin", "dbview", "cols", table],
    queryFn: () => Admin.dbColumns(table),
    enabled: !!table,
  });

  const run = useMutation({
    mutationFn: (q: { sql: string; limit: number; table: string }) => Admin.dbQuery(q.sql, q.limit, q.table),
    onSuccess: (d) => { setResult(d); setError(null); },
    onError: (e) => { setResult(null); setError(friendlyError(e, locale)); },
  });

  const execute = useCallback((text: string, n = limit, forTable = table) => {
    const q = text.trim();
    if (!q) return;
    run.mutate({ sql: q, limit: n, table: forTable });
  }, [run, limit, table]);

  /** Which columns the current query names, or null when it is `*` / not parseable. */
  const chosen = useMemo(() => {
    const p = parseSelect(sql);
    return !p || p.cols.includes("*") ? null : p.cols;
  }, [sql]);

  const clickColumn = (name: string) => {
    const all = (cols.data?.items ?? []).map((c) => c.name);
    const rewritten = toggleColumn(sql, name, all);
    if (rewritten !== null) { setSql(rewritten); return; }
    // Not a query we can rewrite: put the name where the caret is and leave the rest alone.
    const el = editor.current;
    const at = el ? el.selectionStart : sql.length;
    setSql(sql.slice(0, at) + name + sql.slice(at));
    requestAnimationFrame(() => el?.setSelectionRange(at + name.length, at + name.length));
  };

  const pick = (name: string) => {
    const q = `SELECT * FROM ${name} LIMIT ${limit}`;
    setTable(name);
    setSql(q);
    execute(q, limit, name);
  };

  // ⌘/Ctrl+Enter runs, the way every other query tool does it.
  useEffect(() => {
    const el = editor.current;
    if (!el) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); execute(sql); }
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, [sql, execute]);

  /** Fit the two panes to what is left of the window.
   *
   *  Measured rather than computed from a constant: what sits above this — the console
   *  header, the page title, the read-only banner — changes height when the banner wraps or
   *  the window narrows, and a `calc(100vh - 230px)` guess is wrong the moment it does.
   *  The result is a page that never scrolls as a whole; each pane scrolls inside itself.
   */
  useLayoutEffect(() => {
    const fit = () => {
      const el = frame.current;
      if (!el) return;
      // Measured against the scrolling container, not the window, and with its bottom
      // padding taken off: sizing to the viewport left the page eight pixels too tall,
      // which is exactly enough to put a scrollbar on the whole console.
      const scroller = el.closest<HTMLElement>(".overflow-y-auto");
      if (!scroller) {
        setHeight(Math.max(360, Math.round(window.innerHeight - el.getBoundingClientRect().top - 24)));
        return;
      }
      const inner = scroller.firstElementChild as HTMLElement | null;
      const padB = inner ? parseFloat(getComputedStyle(inner).paddingBottom || "0") : 0;
      const top = el.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
      setHeight(Math.max(360, Math.round(scroller.clientHeight - top - padB)));
    };
    fit();
    const ro = new ResizeObserver(fit);
    if (frame.current?.parentElement) ro.observe(frame.current.parentElement);
    window.addEventListener("resize", fit);
    return () => { ro.disconnect(); window.removeEventListener("resize", fit); };
  }, []);

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const items = tables.data?.items ?? [];
    return q ? items.filter((x) => x.name.toLowerCase().includes(q)) : items;
  }, [tables.data, filter]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-border bg-card px-3 py-2 text-xs text-muted-fg">
        <ShieldCheck className="h-4 w-4 text-success" />
        <span>{t("adm.db_readonly_note")}</span>
        {tables.data ? <Badge tone="outline" className="ml-auto font-mono">{tables.data.role}</Badge> : null}
      </div>

      <div ref={frame} style={{ height }} className="grid min-h-0 gap-3 lg:grid-cols-[260px_1fr]">
        {/* schema */}
        <div className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-card">
          <div className="shrink-0 border-b border-border p-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" />
              <Input className="h-9 pl-8" placeholder={t("adm.db_find_table")} value={filter}
                onChange={(e) => setFilter(e.target.value)} />
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin p-1.5">
            {tables.isLoading ? <Skeleton className="h-64" /> : shown.map((x: DbTable) => (
              <button key={x.name} type="button" onClick={() => pick(x.name)}
                className={cn("flex w-full items-baseline justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-xs",
                  table === x.name ? "bg-accent/12 text-accent" : "hover:bg-muted")}>
                <span className="truncate font-mono">{x.name}</span>
                <span className="shrink-0 tabular-nums text-[10px] text-muted-fg" title={t("adm.db_rows_estimate")}>
                  ~{fmtNumber(x.rows)}
                </span>
              </button>
            ))}
            {!tables.isLoading && !shown.length ? <div className="p-3 text-xs text-muted-fg">{t("adm.db_no_table")}</div> : null}
          </div>
          {table && cols.data ? (
            <div className="flex min-h-0 shrink-0 basis-[38%] flex-col border-t border-border p-2">
              <div className="mb-1 flex items-center gap-1.5 px-1 text-[11px] font-medium text-muted-fg">
                <Columns3 className="h-3.5 w-3.5" />{t("adm.db_columns")}
                <span className="ml-auto font-normal">{t("adm.db_columns_hint")}</span>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">
                {cols.data.items.map((c: DbColumn) => {
                  const on = chosen !== null && chosen.includes(c.name);
                  return (
                    <button key={c.name} type="button" title={c.type} onClick={() => clickColumn(c.name)}
                      className={cn("flex w-full items-baseline justify-between gap-2 rounded px-1 py-0.5 text-left text-[11px] hover:bg-muted",
                        chosen !== null && !on && "opacity-45")}>
                      <span className="flex min-w-0 items-baseline gap-1.5">
                        <span className={cn("shrink-0 text-[9px]", on ? "text-accent" : "text-transparent")}>●</span>
                        <span className="truncate font-mono">{c.name}</span>
                      </span>
                      <span className="shrink-0 text-[10px] text-muted-fg">{c.masked ? "🔒" : shortType(c.type)}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}
        </div>

        {/* query + results */}
        <div className="flex min-h-0 min-w-0 flex-col gap-3">
          <div className="shrink-0 rounded-2xl border border-border bg-card p-2">
            <textarea ref={editor} value={sql} onChange={(e) => setSql(e.target.value)} spellCheck={false}
              placeholder={t("adm.db_placeholder")} rows={3}
              className="w-full resize-y rounded-xl bg-input px-3 py-2 font-mono text-[13px] leading-relaxed outline-none focus-visible:outline-2 focus-visible:outline-ring" />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button size="sm" loading={run.isPending} disabled={!sql.trim()} onClick={() => execute(sql)}>
                <Play className="h-4 w-4" />{t("adm.db_run")}
              </Button>
              <span className="text-[11px] text-muted-fg">{t("adm.db_shortcut")}</span>
              <div className="ml-auto flex items-center gap-1">
                <span className="text-[11px] text-muted-fg">LIMIT</span>
                {LIMITS.map((n) => (
                  <button key={n} type="button" onClick={() => { setLimit(n); if (sql.trim()) execute(sql, n); }}
                    className={cn("rounded-md px-2 py-1 text-[11px] tabular-nums", limit === n ? "bg-fg text-bg" : "bg-muted text-muted-fg")}>{n}</button>
                ))}
              </div>
            </div>
          </div>

          {error ? (
            <div className="flex shrink-0 items-start gap-2 rounded-2xl border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="break-words font-mono text-[12px]">{error}</span>
            </div>
          ) : null}

          {result ? <Grid d={result} /> : !error ? (
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border text-sm text-muted-fg">
              <Database className="h-7 w-7 opacity-40" />
              {t("adm.db_empty")}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Grid({ d }: { d: DbResult }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const copy = () => {
    const head = d.columns.join("\t");
    const body = d.rows.map((r) => d.columns.map((c) => String(r[c] ?? "")).join("\t")).join("\n");
    navigator.clipboard?.writeText(`${head}\n${body}`).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-border bg-card">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-xs">
        <span className="font-medium tabular-nums">{t("adm.db_rows_n", { n: d.row_count })}</span>
        {d.truncated ? <Badge tone="warning">{t("adm.db_truncated", { n: d.limit })}</Badge> : null}
        {d.masked.length ? <Badge tone="outline">🔒 {d.masked.join(", ")}</Badge> : null}
        <Button size="sm" variant="ghost" className="ml-auto h-7" onClick={copy}>
          <Copy className="h-3.5 w-3.5" />{copied ? t("common.copied") : t("adm.db_copy")}
        </Button>
      </div>
      {/* Scrolls inside itself: a wide table must not push the page sideways. */}
      <div className="min-h-0 flex-1 overflow-auto scrollbar-thin">
        <table className="w-full text-[12px]">
          <thead className="sticky top-0 z-10 bg-muted/90 backdrop-blur">
            <tr>
              <th className="w-10 px-2 py-1.5 text-right font-normal text-muted-fg">#</th>
              {d.columns.map((c) => (
                <th key={c} className="whitespace-nowrap px-3 py-1.5 text-left font-medium">
                  {c}{d.masked.includes(c) ? <span className="ml-1 opacity-60">🔒</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {d.rows.map((r, i) => (
              <tr key={i} className="hover:bg-muted/40">
                <td className="px-2 py-1.5 text-right tabular-nums text-muted-fg">{i + 1}</td>
                {d.columns.map((c) => <Cell key={c} v={r[c]} />)}
              </tr>
            ))}
            {!d.rows.length ? (
              <tr><td colSpan={d.columns.length + 1} className="px-3 py-6 text-center text-muted-fg">{t("adm.db_no_rows")}</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Cell({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <td className="px-3 py-1.5 text-muted-fg/60 italic">null</td>;
  if (typeof v === "boolean") return <td className="px-3 py-1.5"><Badge tone={v ? "success" : "neutral"}>{String(v)}</Badge></td>;
  if (typeof v === "number") return <td className="px-3 py-1.5 text-right tabular-nums">{v}</td>;
  const s = String(v);
  return (
    <td className="max-w-[380px] truncate px-3 py-1.5 font-mono text-[11px]" title={s.length > 80 ? s : undefined}>{s}</td>
  );
}
