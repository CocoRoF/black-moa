"use client";
import { useEffect, useRef, useState } from "react";
import { Network, type Mentionable } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { Avatar } from "@/components/ui/misc";

/** Where a description is written, and where `@` finds people (plan/42 §11).
 *
 *  A plain box, not a rounded field: what is being written here is the words under a
 *  photo, and a chat bubble around them reads as a different kind of thing. Typing `@`
 *  opens the people this person is connected to, so a mention is picked rather than
 *  spelled from memory.
 */
const MAX_AGENTS = 3;

export function CaptionBox({ value, onChange, onPick, placeholder, className, autoFocus, limit }: {
  value: string; onChange: (v: string) => void; onPick?: (who: Mentionable) => void;
  placeholder?: string; className?: string; autoFocus?: boolean;
  /** How long this kind of post runs to. Shown while it matters, and the box stops there
   *  rather than letting the server cut words off after they were typed. */
  limit?: number;
}) {
  const t = useT();
  const box = useRef<HTMLTextAreaElement | null>(null);
  const paint = useRef<HTMLDivElement | null>(null);
  //: Who has been named so far, so the words that stand for them can be painted.
  const [chosen, setChosen] = useState<Mentionable[]>([]);
  const [term, setTerm] = useState<string | null>(null);   // what follows the @ being typed
  const [rows, setRows] = useState<Mentionable[]>([]);
  const [at, setAt] = useState(0);

  // What is being typed right now: the @word the caret sits inside, and nothing else.
  const read = () => {
    const el = box.current;
    if (!el) return;
    const upto = value.slice(0, el.selectionStart ?? 0);
    const m = /(?:^|\s)@([A-Za-z0-9가-힣_.-]{0,32})$/.exec(upto);
    setTerm(m ? m[1] : null);
    setAt(0);
  };

  useEffect(() => {
    if (term === null) { setRows([]); return; }
    let live = true;
    const id = setTimeout(async () => {
      try {
        const r = await Network.mentionable(term);
        if (live) setRows(r.items);
      } catch { if (live) setRows([]); }
    }, 150);
    return () => { live = false; clearTimeout(id); };
  }, [term]);

  const pick = (who: Mentionable) => {
    const el = box.current;
    if (!el) return;
    // Every named secretary is a turn somebody pays for, so there is a ceiling. Nobody is
    // told about it until they reach it (plan/43 §6).
    if (who.kind === "agent" && !chosen.some((x) => x.id === who.id)
        && chosen.filter((x) => x.kind === "agent").length >= MAX_AGENTS) {
      toast.message(t("feed.agents_full", { n: MAX_AGENTS }));
      setTerm(null);
      return;
    }
    // Their address if they claimed one, their name if not: a mention points at a person,
    // and most people have no address (plan/42 §11).
    const label = who.handle || who.display_name;
    const caret = el.selectionStart ?? value.length;
    const head = value.slice(0, caret).replace(/@[A-Za-z0-9가-힣_.-]{0,32}$/, `@${label} `);
    const next = head + value.slice(caret);
    onChange(next);
    onPick?.(who);
    setChosen((p) => (p.some((x) => x.id === who.id) ? p : [...p, who]));
    setTerm(null);
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(head.length, head.length); });
  };

  const open = term !== null && rows.length > 0;
  return (
    <div className={cn("relative", className)}>
      {/* A name that looks like plain words is not a link, and nobody presses it. The
          chips are painted underneath and the box above is see-through, so the caret keeps
          working while the names stand out (plan/42 §11). */}
      <div ref={paint} aria-hidden
           className="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words text-[15px] leading-relaxed text-fg">
        {paintMentions(value, chosen)}
      </div>
      <textarea
        ref={box} value={value} autoFocus={autoFocus} placeholder={placeholder}
        maxLength={limit}
        onChange={(e) => { onChange(e.target.value); requestAnimationFrame(read); }}
        onScroll={(e) => { if (paint.current) paint.current.scrollTop = e.currentTarget.scrollTop; }}
        onKeyUp={read} onClick={read}
        onKeyDown={(e) => {
          if (!open) return;
          if (e.key === "ArrowDown") { e.preventDefault(); setAt((n) => (n + 1) % rows.length); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setAt((n) => (n - 1 + rows.length) % rows.length); }
          // 한글을 치는 중에 누르는 Enter 는 글자를 확정하는 Enter 다. 그것으로 사람을
          // 골라 버리면 이름을 부르려던 적도 없는 자리에서 이름이 박힌다.
          else if ((e.key === "Enter" && !e.nativeEvent.isComposing) || e.key === "Tab") { e.preventDefault(); pick(rows[at]); }
          else if (e.key === "Escape") { e.preventDefault(); setTerm(null); }
        }}
        onBlur={() => setTimeout(() => setTerm(null), 150)}
        className="relative h-full w-full resize-none bg-transparent text-[15px] leading-relaxed text-transparent caret-fg outline-none selection:bg-accent/25 placeholder:text-muted-fg/70"
      />
      {/* Under the line being typed, not over the header: the name of whoever is posting
          should not vanish behind a list of other people's names. */}
      {open ? (
        <ul className="absolute left-0 top-7 z-20 max-h-56 w-full max-w-[280px] overflow-auto rounded-xl border border-border bg-card p-1 shadow-lg scrollbar-thin">
          {rows.map((who, i) => (
            <li key={who.id}>
              <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => pick(who)}
                      className={cn("flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left", i === at ? "bg-muted" : "hover:bg-muted/60")}>
                <Avatar name={who.display_name} src={who.avatar_url} size={26} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{who.display_name}</span>
                  <span className="block truncate text-[11px] text-muted-fg">
                    {who.kind === "agent" ? t("feed.mention_agent") : who.handle ? `@${who.handle}` : ""}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {/* 마지막 백 자 안에 들어오면 그때 센다. 처음부터 숫자를 띄워 두면 한 줄 적는
          자리가 글자 수를 재는 자리가 된다. */}
      {limit && value.length > limit - 100 ? (
        <span className={cn("pointer-events-none absolute bottom-0 right-0 rounded-md bg-card/90 px-1.5 text-[11px] tabular-nums",
                            value.length >= limit ? "font-medium text-danger" : "text-muted-fg")}>
          {value.length} / {limit}
        </span>
      ) : null}
      <span className="sr-only">{t("feed.mention_hint")}</span>
    </div>
  );
}


/** The same rule the reader sees: `@` plus a name that was actually chosen. */
function paintMentions(text: string, named: Mentionable[]) {
  const labels = named.map((w) => w.handle || w.display_name).filter(Boolean).sort((a, b) => b.length - a.length);
  if (!labels.length) return text;
  const out: React.ReactNode[] = [];
  let rest = text;
  let key = 0;
  while (rest) {
    let at = -1;
    let hit = "";
    for (const label of labels) {
      const i = rest.indexOf(`@${label}`);
      if (i >= 0 && (at < 0 || i < at)) { at = i; hit = label; }
    }
    if (at < 0) { out.push(<span key={key++}>{rest}</span>); break; }
    if (at) out.push(<span key={key++}>{rest.slice(0, at)}</span>);
    out.push(<span key={key++} className="rounded bg-accent/10 font-medium text-accent">@{hit}</span>);
    rest = rest.slice(at + hit.length + 1);
  }
  return out;
}
