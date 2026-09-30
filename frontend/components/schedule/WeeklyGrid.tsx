"use client";
import { Plus, Trash2 } from "@/components/icons";
import type { WeeklyRow } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** 연락 가능 시간을 한 줄로: "월–금 10:00–18:00 · 토 11:00–14:00". 사흘 이상 이어진 요일은 줄여 쓴다. */
export function useWeeklyLabel() {
  const t = useT();
  const days = [t("day.mon"), t("day.tue"), t("day.wed"), t("day.thu"), t("day.fri"), t("day.sat"), t("day.sun")];
  return (rows: WeeklyRow[]) => rows.filter((r) => r.days?.length && r.start && r.end && r.end > r.start).map((r) => {
    const ds = [...new Set(r.days)].filter((d) => d >= 0 && d < 7).sort((a, b) => a - b);
    const runs: string[] = [];
    for (let i = 0; i < ds.length;) {
      let j = i;
      while (j + 1 < ds.length && ds[j + 1] === ds[j] + 1) j++;
      runs.push(j - i >= 2 ? `${days[ds[i]]}–${days[ds[j]]}` : ds.slice(i, j + 1).map((d) => days[d]).join("·"));
      i = j + 1;
    }
    return `${runs.join("·")} ${r.start}–${r.end}`;
  }).join(" · ");
}

/** 연락 가능 시간의 주간 표 (plan/56). 요일 몇 개 + 시작·끝 시각이 한 줄이고, 줄은 여럿 둘 수 있다
 *  (예: 평일 10–12시, 평일 14–18시). 끝이 시작보다 이르면 그 줄은 저장되지 않는다고 그 자리에서 말한다. */
export function WeeklyGrid({ value, onChange }: { value: WeeklyRow[]; onChange: (w: WeeklyRow[]) => void }) {
  const t = useT();
  const days = [t("day.mon"), t("day.tue"), t("day.wed"), t("day.thu"), t("day.fri"), t("day.sat"), t("day.sun")];
  const upd = (i: number, p: Partial<WeeklyRow>) => onChange(value.map((r, j) => (j === i ? { ...r, ...p } : r)));
  return (
    <div className="space-y-2">
      {value.map((r, i) => {
        const bad = r.end <= r.start || !r.days.length;
        return (
          <div key={i} className={cn("flex flex-col gap-2 rounded-xl border p-3 sm:flex-row sm:flex-wrap sm:items-center", bad ? "border-warning/50" : "border-border")}>
            {/* 휴대폰에서는 지우기 단추가 요일 줄 끝으로 가서, 시각 두 칸이 한 줄을 온전히 쓴다. */}
            <div className="flex items-center gap-1">
              <div className="flex gap-1" role="group" aria-label={t("sched.days")}>
                {days.map((d, di) => (
                  <button key={di} type="button" aria-pressed={r.days.includes(di)}
                          onClick={() => upd(i, { days: r.days.includes(di) ? r.days.filter((x) => x !== di) : [...r.days, di].sort() })}
                          className={cn("h-8 w-8 rounded-lg text-xs font-medium sm:h-9 sm:w-9", r.days.includes(di) ? "bg-accent text-accent-fg" : "bg-muted text-muted-fg")}>{d}</button>
                ))}
              </div>
              <Button variant="ghost" size="icon-sm" className="ml-auto sm:hidden" aria-label={t("common.delete")} onClick={() => onChange(value.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
            </div>
            <div className="flex items-center gap-2 sm:ml-auto">
              <Input type="time" value={r.start} onChange={(e) => upd(i, { start: e.target.value })} className="min-w-0 flex-1 px-2.5 text-sm sm:w-[150px] sm:flex-none sm:px-3.5 sm:text-[15px]" aria-label={t("sched.from")} />
              <span className="text-muted-fg">–</span>
              <Input type="time" value={r.end} onChange={(e) => upd(i, { end: e.target.value })} className="min-w-0 flex-1 px-2.5 text-sm sm:w-[150px] sm:flex-none sm:px-3.5 sm:text-[15px]" aria-label={t("sched.to")} />
              <Button variant="ghost" size="icon-sm" className="hidden sm:inline-flex" aria-label={t("common.delete")} onClick={() => onChange(value.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
            </div>
            {bad ? <p className="text-xs text-warning sm:basis-full">{t("sched.row_invalid")}</p> : null}
          </div>
        );
      })}
      <Button variant="outline" size="sm" onClick={() => onChange([...value, { days: [0, 1, 2, 3, 4], start: "10:00", end: "18:00" }])}>
        <Plus className="h-4 w-4" />{t("profile.add_window")}
      </Button>
    </div>
  );
}
