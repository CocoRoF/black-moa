"use client";
import { useMemo, useState, type ReactNode } from "react";
import { Check, ChevronRight, CornerDownLeft, Search, X } from "@/components/icons";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Dialog } from "./dialog";
import { Button } from "./button";

export interface TaxoNode { value: string; label: string; keywords?: string; children?: TaxoNode[] }

/** Walk to a value, returning the labels along the way. */
export function trailOf(nodes: TaxoNode[] | undefined, value: string): string[] | null {
  for (const n of nodes ?? []) {
    if (n.value === value) return [n.label];
    const deeper = trailOf(n.children, value);
    if (deeper) return [n.label, ...deeper];
  }
  return null;
}

/** What to call a stored code. Anything the tree does not know is shown as typed, because
 *  it is what somebody typed — a taxonomy that cannot be escaped is a taxonomy that lies. */
export function labelOf(nodes: TaxoNode[] | undefined, value: string): string {
  return trailOf(nodes, value)?.slice(-1)[0] ?? value;
}

function flatten(nodes: TaxoNode[], trail: string[] = []): { node: TaxoNode; trail: string[] }[] {
  return nodes.flatMap((n) => [{ node: n, trail }, ...flatten(n.children ?? [], [...trail, n.label])]);
}

/** Pick from a tree — 직무, 지역, 업종 — in one dialog, everywhere.
 *
 *  Opening a category shows what is inside it and nothing else: it used to select the whole
 *  branch, so a tap meant to look around silently added twenty things. Selecting is the
 *  checkbox's job, at any level. And when the tree does not have the thing somebody is —
 *  "AI 매니저" — the search box offers to take it as typed rather than making them pick the
 *  nearest wrong answer.
 */
export function TaxonomyPicker({ open, title, hint, nodes, value, onChange, onClose, max = 5, allowCustom = true }: {
  open: boolean; title: ReactNode; hint?: ReactNode; nodes: TaxoNode[] | undefined;
  value: string[]; onChange: (v: string[]) => void; onClose: () => void; max?: number; allowCustom?: boolean;
}) {
  const t = useT();
  const [draft, setDraft] = useState<string[]>(value);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [q, setQ] = useState("");
  // Re-seed when the dialog is opened for a different field.
  const [seed, setSeed] = useState(value);
  if (open && seed !== value && draft === seed) { setSeed(value); setDraft(value); }

  const top = nodes ?? [];
  const opened = top.find((n) => n.value === openKey) ?? null;
  const all = useMemo(() => (nodes ? flatten(nodes) : []), [nodes]);
  const needle = q.trim().toLowerCase();
  const found = needle
    ? all.filter(({ node }) => node.label.toLowerCase().includes(needle) || (node.keywords ?? "").toLowerCase().includes(needle)).slice(0, 60)
    : [];
  const exact = needle ? all.some(({ node }) => node.label.toLowerCase() === needle) : true;
  const full = draft.length >= max;

  const toggle = (v: string) => {
    if (draft.includes(v)) setDraft(draft.filter((x) => x !== v));
    else if (!full) setDraft([...draft, v]);
  };
  const addCustom = () => {
    const v = q.trim();
    if (!v || draft.includes(v) || full) return;
    setDraft([...draft, v]);
    setQ("");
  };

  return (
    <Dialog open={open} onClose={onClose} size="lg" title={title} description={hint}
      footer={<>
        <Button variant="ghost" onClick={() => setDraft([])}>{t("taxo.clear")}</Button>
        <span className="flex-1" />
        <Button variant="outline" onClick={onClose}>{t("common.close")}</Button>
        <Button variant="accent" onClick={() => { onChange(draft); onClose(); }}>{t("common.apply")}</Button>
      </>}>
      <div className="flex items-center gap-2 rounded-xl border border-border bg-input px-3">
        <Search className="h-4 w-4 shrink-0 text-muted-fg" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("common.search")}
               // 한글 조합을 확정하는 Enter 로 낱말이 등록되면, 쓰다 만 말이 항목이 된다.
               onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing && allowCustom && !exact) { e.preventDefault(); addCustom(); } }}
               className="h-10 min-w-0 flex-1 bg-transparent text-sm outline-none" />
        {q ? <button type="button" onClick={() => setQ("")} aria-label={t("common.close")} className="text-muted-fg hover:text-fg"><X className="h-4 w-4" /></button> : null}
      </div>

      {needle ? (
        <div className="mt-3 max-h-[min(52vh,420px)] overflow-y-auto rounded-xl border border-border">
          {allowCustom && !exact ? (
            <button type="button" onClick={addCustom} disabled={full}
                    className="flex w-full items-center gap-2 border-b border-border px-3 py-2.5 text-left text-sm hover:bg-muted/60 disabled:opacity-50">
              <CornerDownLeft className="h-4 w-4 shrink-0 text-accent" />
              <span className="min-w-0 truncate">{t("taxo.add_custom", { q: q.trim() })}</span>
            </button>
          ) : null}
          {found.length === 0 && exact ? <p className="px-3 py-8 text-center text-sm text-muted-fg">{t("taxo.empty")}</p> : null}
          <ul className="divide-y divide-border">
            {found.map(({ node, trail }) => (
              <li key={node.value}>
                <Option label={node.label} hint={trail.join(" › ")} on={draft.includes(node.value)}
                        disabled={full && !draft.includes(node.value)} onToggle={() => toggle(node.value)} />
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <ul className="max-h-[min(46vh,380px)] divide-y divide-border overflow-y-auto rounded-xl border border-border">
            {top.map((n) => (
              <li key={n.value}>
                <Option label={n.label} on={draft.includes(n.value)} disabled={full && !draft.includes(n.value)}
                        onToggle={() => toggle(n.value)}
                        opened={openKey === n.value} hasChildren={!!n.children?.length}
                        onOpen={n.children?.length ? () => setOpenKey(openKey === n.value ? null : n.value) : undefined} />
              </li>
            ))}
          </ul>
          <ul className="max-h-[min(46vh,380px)] divide-y divide-border overflow-y-auto rounded-xl border border-border">
            {opened?.children?.length ? opened.children.map((c) => (
              <li key={c.value}>
                <Option label={c.label} on={draft.includes(c.value)} disabled={full && !draft.includes(c.value)} onToggle={() => toggle(c.value)} />
              </li>
            )) : (
              <li className="px-3 py-8 text-center text-sm text-muted-fg">{t("taxo.pick_parent")}</li>
            )}
          </ul>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-muted-fg">{t("job.selected_max", { n: draft.length, max })}</span>
        {draft.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-full bg-accent/10 px-2.5 py-1 text-xs text-accent">
            {labelOf(nodes, v)}
            <button type="button" onClick={() => setDraft(draft.filter((x) => x !== v))} aria-label={t("common.delete")}><X className="h-3 w-3" /></button>
          </span>
        ))}
      </div>
    </Dialog>
  );
}

/** One row: the checkbox selects, the row opens. Two jobs, two targets, never confused. */
function Option({ label, hint, on, disabled, onToggle, onOpen, opened, hasChildren }: {
  label: string; hint?: string; on: boolean; disabled?: boolean; onToggle: () => void;
  onOpen?: () => void; opened?: boolean; hasChildren?: boolean;
}) {
  const t = useT();
  return (
    <div className={cn("flex items-stretch", opened && "bg-muted/60")}>
      <button type="button" onClick={onToggle} disabled={disabled} aria-pressed={on} aria-label={label}
              className="flex shrink-0 items-center pl-3 pr-2 disabled:opacity-40">
        <span className={cn("flex h-[18px] w-[18px] items-center justify-center rounded-[6px] border transition-colors",
                            on ? "border-accent bg-accent text-accent-fg" : "border-border")}>
          {on ? <Check className="h-3 w-3" /> : null}
        </span>
      </button>
      <button type="button" onClick={onOpen ?? onToggle} disabled={disabled && !onOpen}
              className="flex min-w-0 flex-1 items-center gap-2 py-2.5 pr-3 text-left text-sm hover:bg-muted/60 disabled:opacity-40">
        <span className="min-w-0 flex-1 truncate">{label}
          {hint ? <span className="ml-1.5 text-xs text-muted-fg">{hint}</span> : null}
        </span>
        {hasChildren ? <ChevronRight className={cn("h-4 w-4 shrink-0 text-muted-fg transition-transform", opened && "rotate-90")} aria-label={t("taxo.open")} /> : null}
      </button>
    </div>
  );
}
