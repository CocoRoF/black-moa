"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { DatePicker, DateTimePicker, monthGrid } from "@cocorof/react-calendar";
import { CalendarDays, ChevronLeft, ChevronRight, Clock, MapPin, Plus, Trash2 } from "@/components/icons";
import { Schedule, type Availability, type DayInfo, type ScheduleEvent, type WeeklyRow } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { useRcalTheme } from "@/lib/theme";
import { useSpecialDays } from "@/lib/specialDays";
import { codeMessage, friendlyError } from "@/lib/errors";
import { confirm } from "@/lib/confirm";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/ui/card";
import { Sheet } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { KeyValue, PageHeader } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { SwitchRow } from "@/components/ui/switch";
import { Segmented } from "@/components/ui/tabs";
import { HoverCard } from "@/components/ui/hover-card";
import { SyncTab } from "./SyncTab";
import { WeeklyGrid } from "./WeeklyGrid";

/** [내 정보 → 스케줄] (plan/56). 연락 가능 시간과 일정은 내 것이고, 비서는 그것을 쓴다.
 *
 *  시각은 전부 **주인의 시간대**다. 서버는 주인 시간대로 적은 글자("2026-09-25T15:00:00+09:00")를
 *  주고, 화면은 그 글자의 날짜·시각을 그대로 쓴다 — 브라우저 시간대로 다시 계산하지 않는다. 입력도
 *  "15:00" 을 그대로 보내면 서버가 주인의 15시로 읽는다.
 */

const pad = (n: number) => String(n).padStart(2, "0");
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const wallString = (d: Date) => `${ymd(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
/** 주인 시간대로 적힌 ISO 에서 벽시계 시각만 꺼내 같은 벽시계의 Date 로(피커가 쓰도록). */
const wallDate = (iso: string) => {
  const [d, t = "00:00"] = iso.slice(0, 16).split("T");
  const [y, m, dd] = d.split("-").map(Number);
  const [h, mi] = t.split(":").map(Number);
  return new Date(y, m - 1, dd, h, mi);
};
const addDay = (s: string, n: number) => { const d = wallDate(s); d.setDate(d.getDate() + n); return ymd(d); };
const hm = (iso: string | null) => (iso ? iso.slice(11, 16) : "");

/** 이 일정이 걸친 날들(주인 시간대). 자정에 끝나는 일정은 다음 날로 넘어가지 않는다. */
function daysOf(ev: ScheduleEvent): string[] {
  if (!ev.start_date) return [];
  let last = ev.end_date ?? ev.start_date;
  if (!ev.all_day && ev.end && hm(ev.end) === "00:00" && last > ev.start_date) last = addDay(last, -1);
  const out: string[] = [];
  for (let d = ev.start_date; d <= last && out.length < 62; d = addDay(d, 1)) out.push(d);
  return out;
}

/** 음력 1일·15일만 칸에 적는다 — 달력들이 흔히 그렇게 한다. */
const lunarMark = (info?: DayInfo) =>
  info?.lunar && (info.lunar.day === 1 || info.lunar.day === 15) ? `${info.lunar.leap ? "윤" : ""}${info.lunar.month}.${info.lunar.day}` : null;

/** 달력이 화면 아래까지 꼭 차게 — 넓은 화면에서는 페이지가 스크롤되지 않도록 (FHD 에서 조금 넘치던 것).
 *  달력의 위치에서 스크롤 칸의 바닥까지 남은 높이를 재고, 창 크기가 바뀌면 다시 잰다. 좁은 화면(휴대폰·태블릿
 *  세로)은 칸 높이를 고정하고 페이지를 스크롤한다 — 여섯 줄을 한 화면에 욱여넣으면 읽을 수 없다. */
function useFillHeight(ref: React.RefObject<HTMLElement | null>, { min = 440, bottom = 24 } = {}): number | null {
  const [h, setH] = useState<number | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const scroller = el.closest<HTMLElement>(".overflow-y-auto");
    const measure = () => {
      if (!scroller || window.innerWidth < 1024) { setH(null); return; }
      const top = el.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
      setH(Math.max(min, Math.floor(scroller.clientHeight - top - bottom)));
    };
    measure();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    if (scroller) ro?.observe(scroller);
    window.addEventListener("resize", measure);
    return () => { ro?.disconnect(); window.removeEventListener("resize", measure); };
  }, [ref, min, bottom]);
  return h;
}

const SOURCE_TONE: Record<string, string> = {
  owner: "bg-accent/12 text-accent", secretary: "bg-violet-500/12 text-violet-600 dark:text-violet-300",
  meeting: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300", google: "bg-sky-500/12 text-sky-700 dark:text-sky-300",
  kakao: "bg-amber-400/15 text-amber-800 dark:text-amber-200",
};

type Tab = "calendar" | "hours" | "sync";

export function ScheduleView() {
  const t = useT();
  const router = useRouter(); const sp = useSearchParams();
  const asked = sp.get("tab");
  const tab: Tab = asked === "hours" || asked === "sync" ? asked : "calendar";
  const setTab = (v: Tab) => router.replace(v === "calendar" ? "?" : `?tab=${v}`, { scroll: false });
  const locale = useLocale();
  useEffect(() => { if (sp.get("connected")) toast.success(t("integ.connected")); const e = sp.get("error"); if (e) toast.error(codeMessage(e, locale)); }, [sp, t, locale]);
  return (
    <Page>
      <PageHeader title={t("sched.title")} description={t("sched.desc")}
        action={<Segmented ariaLabel={t("sched.title")} value={tab} onChange={setTab}
          options={[{ value: "calendar", label: t("sched.tab_calendar") }, { value: "hours", label: t("sched.tab_hours") }, { value: "sync", label: t("sched.tab_sync") }]} />} />
      {tab === "hours" ? <HoursTab /> : tab === "sync" ? <SyncTab /> : <CalendarTab />}
    </Page>
  );
}

// ── 일정 ────────────────────────────────────────────────────────────────

type Draft = { id?: string; title: string; all_day: boolean; start: Date; end: Date; location: string; note: string; busy: boolean };

function CalendarTab() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  // ?date=2026-09-25 — 채팅의 [스케줄 보기] 가 그 날을 펼친 채로 연다.
  const asked = useSearchParams().get("date");
  const start = asked && /^\d{4}-\d{2}-\d{2}$/.test(asked) ? asked : ymd(new Date());
  const [month, setMonth] = useState(() => new Date(Number(start.slice(0, 4)), Number(start.slice(5, 7)) - 1, 1));
  const [day, setDay] = useState(start);
  const [open, setOpen] = useState<ScheduleEvent | "new" | null>(null);
  const grid = useMemo(() => monthGrid(month, 1), [month]);
  const from = ymd(grid[0]); const to = ymd(grid[grid.length - 1]);
  const q = useQuery({ queryKey: ["schedule", from, to], queryFn: () => Schedule.range(from, to), placeholderData: keepPreviousData });
  const byDay = useMemo(() => {
    const m = new Map<string, ScheduleEvent[]>();
    for (const ev of q.data?.events ?? []) for (const d of daysOf(ev)) m.set(d, [...(m.get(d) ?? []), ev]);
    for (const list of m.values()) list.sort((a, b) => Number(b.all_day) - Number(a.all_day) || (a.start ?? "").localeCompare(b.start ?? ""));
    return m;
  }, [q.data]);
  const today = ymd(new Date());
  const monthLabel = new Intl.DateTimeFormat(locale === "en" ? "en-US" : "ko-KR", { year: "numeric", month: "long" }).format(month);
  const dayLabel = (s: string) => new Intl.DateTimeFormat(locale === "en" ? "en-US" : "ko-KR", { month: "long", day: "numeric", weekday: "short" }).format(wallDate(s));
  const weekdays = [t("day.mon"), t("day.tue"), t("day.wed"), t("day.thu"), t("day.fri"), t("day.sat"), t("day.sun")];
  const shift = (n: number) => setMonth((m) => new Date(m.getFullYear(), m.getMonth() + n, 1));
  const chosen = byDay.get(day) ?? [];
  // 한국의 공휴일·명절·절기·기념일·음력 (plan/60). 공휴일과 일요일은 붉게. 한 해치로 받아 기기에 둔 것이라
  // 달을 넘길 때마다 다시 받지 않는다 — 위의 요청은 내 일정뿐이다.
  const days = useSpecialDays([grid[0].getFullYear(), grid[grid.length - 1].getFullYear()]);
  const chosenInfo = days[day];
  const boardRef = useRef<HTMLDivElement>(null);
  const fill = useFillHeight(boardRef);
  // 칸 하나에 들어가는 만큼 일정을 보인다. 칸 = 안쪽 여백 8 + 날짜 24 + (이름 줄 2+16) + 일정마다 2+18,
  // 다 못 들어가면 마지막 줄은 "+N"(2+16). 머리글 줄은 약 30.
  const rows = grid.length / 7;
  const rowH = fill ? (fill - 30) / rows : 96;
  const fits = (named: boolean, n: number) => {
    const base = 8 + 24 + (named ? 18 : 0);
    if (base + n * 20 <= rowH) return n;
    return Math.max(0, Math.floor((rowH - base - 18) / 20));
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon-sm" aria-label={t("sched.prev")} onClick={() => shift(-1)}><ChevronLeft className="h-4 w-4" /></Button>
          <Button variant="outline" size="sm" onClick={() => { const d = new Date(); setMonth(new Date(d.getFullYear(), d.getMonth(), 1)); setDay(ymd(d)); }}>{t("sched.today")}</Button>
          <Button variant="outline" size="icon-sm" aria-label={t("sched.next")} onClick={() => shift(1)}><ChevronRight className="h-4 w-4" /></Button>
        </div>
        <h2 className="text-lg font-semibold tabular-nums">{monthLabel}</h2>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <Button size="sm" onClick={() => setOpen("new")}><Plus className="h-4 w-4" />{t("sched.add")}</Button>
        </div>
      </div>

      <div ref={boardRef} className="grid gap-4 lg:grid-cols-[1fr_320px]" style={fill ? { height: fill } : undefined}>
        {/* 달력 한 장. 넓은 화면에서는 남은 높이를 여섯 줄이 나눠 갖고, 칸에 들어가는 만큼 일정을 보인 뒤
            나머지는 "+N" 에 올려 두면 전부. 좁은 화면에서는 칸 높이가 고정이다. */}
        <div className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-card">
          <div className="grid grid-cols-7 border-b border-border bg-muted/40 text-center text-[11px] font-medium text-muted-fg">
            {weekdays.map((w, i) => <div key={w} className={cn("py-1.5", i === 6 && "text-danger/80", i === 5 && "text-accent/80")}>{w}</div>)}
          </div>
          <div className="grid min-h-0 flex-1 grid-cols-7" style={fill ? { gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))` } : undefined}>
            {grid.map((d) => {
              const key = ymd(d);
              const list = byDay.get(key) ?? [];
              const inMonth = d.getMonth() === month.getMonth();
              const info = days[key];
              // 일요일·공휴일(대체공휴일·선거일 포함)은 붉게, 토요일은 머리글처럼 푸르게.
              const red = d.getDay() === 0 || !!info?.off;
              const blue = !red && d.getDay() === 6;
              const offNames = (info?.names ?? []).filter((n) => n.off).map((n) => n.name);
              const otherNames = (info?.names ?? []).filter((n) => !n.off).map((n) => n.name);
              const mark = lunarMark(info);
              const spoken = [...offNames, ...otherNames].join(", ");
              const shown = fill ? fits(offNames.length + otherNames.length > 0, list.length) : Math.min(2, list.length);
              return (
                <button key={key} type="button" onClick={() => setDay(key)} aria-pressed={day === key} aria-label={spoken ? `${dayLabel(key)} ${spoken}` : dayLabel(key)}
                  className={cn("flex min-h-0 flex-col gap-0.5 overflow-hidden border-b border-r border-border p-1 text-left align-top transition-colors hover:bg-muted/50",
                    fill ? "h-full" : "h-24 md:h-28",
                    !inMonth && "bg-muted/20 text-muted-fg", day === key && "ring-2 ring-inset ring-accent")}>
                  <span className="flex w-full items-center gap-1">
                    <span className={cn("inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs tabular-nums",
                      key === today ? "bg-accent font-semibold text-accent-fg"
                        : red ? cn("font-semibold text-danger", !inMonth && "opacity-50")
                        : blue ? cn("text-accent", !inMonth && "opacity-50") : "")}>{d.getDate()}</span>
                    {mark ? <span className="ml-auto hidden truncate text-[10px] tabular-nums text-muted-fg sm:inline">{t("sched.lunar_short", { md: mark })}</span> : null}
                  </span>
                  {offNames.length || otherNames.length ? (
                    <span className={cn("block truncate px-1 text-[11px] leading-4", !inMonth && "opacity-60")}>
                      {offNames.length ? <span className="font-medium text-danger">{offNames.join("·")}</span> : null}
                      {offNames.length && otherNames.length ? <span className="text-muted-fg"> · </span> : null}
                      {otherNames.length ? <span className="text-muted-fg">{otherNames.join("·")}</span> : null}
                    </span>
                  ) : null}
                  {list.slice(0, shown).map((ev) => (
                    // 칸 안의 일정을 누르면 그날을 고르는 데서 그치지 않고 그 일정이 바로 열린다.
                    <span key={ev.id + key} onClick={(e) => { e.stopPropagation(); setDay(key); setOpen(ev); }}
                      className={cn("block cursor-pointer truncate rounded px-1 text-[11px] leading-[18px] hover:brightness-95", SOURCE_TONE[ev.source] ?? SOURCE_TONE.owner, !ev.busy && "opacity-70")}>
                      {ev.all_day ? "" : <span className="mr-1 tabular-nums">{hm(ev.start)}</span>}{ev.title}
                    </span>
                  ))}
                  {list.length > shown ? (
                    <HoverCard tone="card" side="bottom" content={<DayList events={list} />} className="block">
                      <span className="block truncate px-1 text-[11px] font-medium text-muted-fg">{t("sched.more", { n: list.length - shown })}</span>
                    </HoverCard>
                  ) : null}
                </button>
              );
            })}
          </div>
          {q.isLoading ? <div className="p-3"><Skeleton className="h-4" /></div> : null}
        </div>

        {/* 고른 날의 일정 — 달력과 같은 높이, 넘치면 안에서 스크롤 */}
        <div className="min-h-0 space-y-3 overflow-y-auto rounded-2xl border border-border bg-card p-4 scrollbar-thin">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <h3 className={cn("font-semibold", (wallDate(day).getDay() === 0 || chosenInfo?.off) && "text-danger")}>{dayLabel(day)}</h3>
              {chosenInfo?.lunar ? (
                <p className="text-xs text-muted-fg">{t(chosenInfo.lunar.leap ? "sched.lunar_leap" : "sched.lunar", { m: chosenInfo.lunar.month, d: chosenInfo.lunar.day })}</p>
              ) : null}
            </div>
            <Button variant="outline" size="sm" onClick={() => setOpen("new")}><Plus className="h-4 w-4" />{t("sched.add_here")}</Button>
          </div>
          {chosenInfo?.names.length ? (
            <div className="flex flex-wrap gap-1.5">
              {chosenInfo.names.map((n) => (
                <span key={n.kind + n.name} className={cn("rounded-full px-2 py-0.5 text-xs",
                  n.off ? "bg-danger/10 font-medium text-danger" : "bg-muted text-muted-fg")}>
                  {n.name}{n.off ? ` · ${t("sched.day_off")}` : n.kind === "solar_term" ? ` · ${t("sched.solar_term")}` : ""}
                </span>
              ))}
            </div>
          ) : null}
          {chosen.length ? (
            <ul className="space-y-2">
              {chosen.map((ev) => (
                <li key={ev.id}>
                  <button type="button" onClick={() => setOpen(ev)} className="w-full rounded-xl border border-border px-3 py-2 text-left hover:bg-muted/50">
                    <div className="flex items-center gap-2 text-xs text-muted-fg">
                      <Clock className="h-3.5 w-3.5" />
                      <span className="tabular-nums">{ev.all_day ? t("sched.all_day") : `${hm(ev.start)}–${hm(ev.end)}`}</span>
                      <span className={cn("ml-auto rounded-full px-1.5 py-0.5 text-[10px]", SOURCE_TONE[ev.source])}>{t(`sched.src_${ev.source}`)}</span>
                    </div>
                    <div className="mt-0.5 truncate text-sm font-medium">{ev.title}</div>
                    {ev.location ? <div className="mt-0.5 flex items-center gap-1 truncate text-xs text-muted-fg"><MapPin className="h-3 w-3" />{ev.location}</div> : null}
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-muted-fg">{t("sched.day_empty")}</p>}
        </div>
      </div>

      <EventSheet open={open} day={day} onClose={() => setOpen(null)}
        onSaved={() => { setOpen(null); qc.invalidateQueries({ queryKey: ["schedule"] }); }} />
    </div>
  );
}

function DayList({ events }: { events: ScheduleEvent[] }) {
  const t = useT();
  return (
    <ul className="max-w-[260px] space-y-1 text-xs">
      {events.map((ev) => (
        <li key={ev.id} className="flex gap-2"><span className="w-20 shrink-0 tabular-nums text-muted-fg">{ev.all_day ? t("sched.all_day") : `${hm(ev.start)}–${hm(ev.end)}`}</span><span className="min-w-0 truncate">{ev.title}</span></li>
      ))}
    </ul>
  );
}

function EventSheet({ open, day, onClose, onSaved }: { open: ScheduleEvent | "new" | null; day: string; onClose: () => void; onSaved: () => void }) {
  const t = useT(); const locale = useLocale(); const rcal = useRcalTheme();
  const [d, setD] = useState<Draft | null>(null);
  const ev = open && open !== "new" ? open : null;
  useEffect(() => {
    if (!open) { setD(null); return; }
    if (open === "new") {
      const base = wallDate(`${day}T09:00`);
      setD({ title: "", all_day: false, start: base, end: new Date(base.getTime() + 3600_000), location: "", note: "", busy: true });
    } else {
      setD({ id: open.id, title: open.title, all_day: open.all_day,
             start: open.all_day ? wallDate(`${open.start_date}T00:00`) : wallDate(open.start ?? `${day}T09:00`),
             end: open.all_day ? wallDate(`${open.end_date}T00:00`) : wallDate(open.end ?? `${day}T10:00`),
             location: open.location, note: open.note, busy: open.busy });
    }
  }, [open, day]);
  const save = useMutation({
    mutationFn: async () => {
      if (!d) return;
      const body = { title: d.title, all_day: d.all_day, location: d.location, note: d.note, busy: d.busy,
                     start: d.all_day ? ymd(d.start) : wallString(d.start), end: d.all_day ? ymd(d.end) : wallString(d.end) };
      return d.id ? Schedule.update(d.id, body) : Schedule.create(body);
    },
    onSuccess: () => { toast.success(t("common.saved")); onSaved(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => Schedule.remove(id),
    onSuccess: () => { toast.success(t("sched.removed")); onSaved(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const invalid = !!d && (!d.title.trim() || (d.all_day ? ymd(d.end) < ymd(d.start) : d.end <= d.start));

  if (ev?.readonly) {
    // Google 일정은 여기서 고치지 않는다 — 고친 것이 다음 동기화에 사라지면 거짓말이 된다.
    return (
      <Sheet open={!!open} onClose={onClose} side="right" title={ev.title}>
        <div className="space-y-4">
          <p className="rounded-lg bg-sky-500/10 px-3 py-2 text-sm text-sky-700 dark:text-sky-300">{t("sched.google_readonly")}</p>
          <KeyValue items={[
            { k: t("sched.when"), v: ev.all_day ? `${ev.start_date}${ev.end_date !== ev.start_date ? ` – ${ev.end_date}` : ""} · ${t("sched.all_day")}` : `${ev.start?.slice(0, 16).replace("T", " ")} – ${hm(ev.end)}` },
            { k: t("sched.location"), v: ev.location || "–" },
            { k: t("sched.attendees"), v: ev.attendees.join(", ") || "–" },
            { k: t("sched.busy"), v: ev.busy ? t("sched.busy_yes") : t("sched.busy_no") },
          ]} />
          {ev.note ? <p className="whitespace-pre-wrap text-sm text-muted-fg">{ev.note}</p> : null}
        </div>
      </Sheet>
    );
  }

  return (
    <Sheet open={!!open} onClose={onClose} side="right" title={d?.id ? t("sched.edit") : t("sched.add")}
      footer={d ? (
        <div className="flex items-center gap-2">
          {d.id ? (
            <Button variant="ghost" className="text-danger" loading={remove.isPending} onClick={async () => {
              if (await confirm({ title: t("sched.remove_q"), description: t("sched.remove_desc"), danger: true, confirmLabel: t("common.delete") })) remove.mutate(d.id!);
            }}><Trash2 className="h-4 w-4" />{t("common.delete")}</Button>
          ) : null}
          <Button variant="outline" className="ml-auto" onClick={onClose}>{t("common.cancel")}</Button>
          <Button loading={save.isPending} disabled={invalid} onClick={() => save.mutate()}>{t("common.save")}</Button>
        </div>
      ) : null}>
      {!d ? <Skeleton className="h-48" /> : (
        <div className="space-y-4">
          <Field label={t("sched.name")}><Input autoFocus value={d.title} maxLength={200} onChange={(e) => setD({ ...d, title: e.target.value })} placeholder={t("sched.name_ph")} /></Field>
          <SwitchRow title={t("sched.all_day")} checked={d.all_day}
            onChange={(v) => setD({ ...d, all_day: v, busy: !v,
              ...(v ? { start: wallDate(`${ymd(d.start)}T00:00`), end: wallDate(`${ymd(d.start)}T00:00`) }
                    : { start: wallDate(`${ymd(d.start)}T09:00`), end: wallDate(`${ymd(d.start)}T10:00`) }) })} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("sched.start")}>
              {d.all_day ? <DatePicker value={d.start} onChange={(v) => v && setD({ ...d, start: v, end: ymd(d.end) < ymd(v) ? v : d.end })} locale={locale} className={rcal} panelClassName={rcal} />
                : <DateTimePicker value={d.start} minuteStep={10} locale={locale} className={rcal} panelClassName={rcal}
                    onChange={(v) => v && setD({ ...d, start: v, end: new Date(v.getTime() + Math.max(d.end.getTime() - d.start.getTime(), 30 * 60_000)) })} />}
            </Field>
            <Field label={t("sched.end")}>
              {d.all_day ? <DatePicker value={d.end} onChange={(v) => v && setD({ ...d, end: v })} locale={locale} className={rcal} panelClassName={rcal} />
                : <DateTimePicker value={d.end} minuteStep={10} locale={locale} className={rcal} panelClassName={rcal} onChange={(v) => v && setD({ ...d, end: v })} />}
            </Field>
          </div>
          {invalid && d.title.trim() ? <p className="text-xs text-danger">{t("sched.bad_range")}</p> : null}
          <Field label={t("sched.location")}><Input value={d.location} maxLength={500} onChange={(e) => setD({ ...d, location: e.target.value })} /></Field>
          <Field label={t("sched.note")}><Textarea value={d.note} maxLength={2000} onChange={(e) => setD({ ...d, note: e.target.value })} className="min-h-[80px]" /></Field>
          <SwitchRow title={t("sched.busy")} description={t("sched.busy_desc")} checked={d.busy} onChange={(v) => setD({ ...d, busy: v })} />
          {ev ? <p className="text-xs text-muted-fg">{t(`sched.src_${ev.source}`)}{ev.source === "meeting" ? ` · ${t("sched.from_meeting")}` : ""}</p> : null}
        </div>
      )}
    </Sheet>
  );
}

// ── 연락 가능 시간 ───────────────────────────────────────────────────────

function HoursTab() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["schedule", "availability"], queryFn: Schedule.availability });
  const [draft, setDraft] = useState<{ weekly: WeeklyRow[]; note: string; skip_holidays: boolean } | null>(null);
  const fromServer = (a: Availability) => ({ weekly: a.weekly, note: a.note, skip_holidays: a.skip_holidays !== false });
  useEffect(() => { if (q.data) setDraft(fromServer(q.data)); }, [q.data]);
  const dirty = !!q.data && !!draft && JSON.stringify(fromServer(q.data)) !== JSON.stringify(draft);
  const save = useMutation({
    mutationFn: () => Schedule.saveAvailability(draft!),
    onSuccess: (a: Availability) => {
      qc.setQueryData(["schedule", "availability"], a);
      // 비서 [지식] 탭의 미리보기가 새 시간으로 다시 계산되게.
      qc.invalidateQueries({ queryKey: ["outsider"] });
      toast.success(t("common.saved"));
    },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  if (!q.data || !draft) return <Skeleton className="h-64" />;
  const a = q.data;
  return (
    <div className="space-y-4">
      <Section title={t("sched.hours")} description={t("sched.hours_desc")}
        action={dirty ? <div className="flex gap-2"><Button variant="ghost" size="sm" onClick={() => setDraft(fromServer(a))}>{t("common.discard")}</Button><Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button></div> : null}>
        <WeeklyGrid value={draft.weekly} onChange={(w) => setDraft({ ...draft, weekly: w })} />
        {/* 추석에 미팅을 잡아 주면 안 된다 — 기본은 켜짐 (plan/60). */}
        <div className="mt-3 rounded-xl border border-border px-3">
          <SwitchRow title={t("sched.skip_holidays")} description={t("sched.skip_holidays_desc")}
            checked={draft.skip_holidays} onChange={(v) => setDraft({ ...draft, skip_holidays: v })} />
        </div>
        <Field label={t("profile.availability_note")} className="mt-4">
          <Input value={draft.note} maxLength={200} onChange={(e) => setDraft({ ...draft, note: e.target.value })} placeholder={t("profile.availability_note_placeholder")} />
        </Field>
        <p className="mt-4 flex items-center gap-1.5 text-xs text-muted-fg">
          <CalendarDays className="h-3.5 w-3.5" />{t("sched.tz", { tz: a.timezone })}
          <Link href="/app/settings" className="text-accent hover:underline">{t("sched.tz_change")}</Link>
        </p>
        {/* 외부인에게 빈 시간을 알려 줄지는 여기서 정하지 않는다 — 비서마다 [지식] 탭에서 (plan/57). */}
        <p className="mt-2 text-xs text-muted-fg">{t("sched.outsider_where")}</p>
      </Section>
    </div>
  );
}
