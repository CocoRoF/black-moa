"use client";
/** 비서 트리거 이벤트 — 관리자가 정하는 리듬 (plan/54).
 *
 *  화면은 [진단]과 같은 틀을 쓴다: 위에 제목, 오른쪽에 탭, 아래에 그 탭 하나의 내용.
 *  네 가지를 한 화면에 세로로 쌓았더니 무엇을 보는 중인지 알 수 없었다 — 설정과
 *  그림과 편집기와 기록은 서로 다른 일이라 한 번에 하나만 보여야 한다. */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Admin, Agents, type TriggerLogItem, type TriggerRule, type TriggerTestResult, type TriggerView } from "@/lib/api";
import { DateRangePicker, toISODate } from "@cocorof/react-calendar";
import { Selector } from "@cocorof/react-selector";
import { useRcalTheme } from "@/lib/theme";
import { fmtDateTime, fmtNumber, fmtRelative } from "@/lib/format";
import { Sheet } from "@/components/ui/dialog";
import { friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Avatar, KeyValue, PageHeader, Stat } from "@/components/ui/misc";
import { HoverCard, useOverflow } from "@/components/ui/hover-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch, SwitchRow } from "@/components/ui/switch";
import { Segmented } from "@/components/ui/tabs";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Page } from "@/components/owner/Shell";
import { ChevronDown, ChevronUp, Plus, Send, Trash2 } from "@/components/icons";
import { cn } from "@/lib/utils";

type Tab = "overview" | "rules" | "simulate" | "log";

/** 사다리의 칸 순서. 대화가 칸을 옮긴다. */
const LADDER = ["cold", "active", "quiet", "lapsed", "pleading", "sleeping"] as const;
const EDGE: Record<string, string> = {
  cold: "첫 대화가 있으면",
  active: "하루가 지나도록 말이 없으면",
  quiet: "사흘 내리 말이 없으면",
  lapsed: "버림받은 말에도 답이 없으면",
  pleading: "마지막 말에도 답이 없으면",
};
/** 말의 종류. 종류마다 비서가 쓰는 법이 다르다(짧은 한마디인지, 안부인지). */
const KIND_LABEL: Record<string, string> = {
  checkin: "안부", nudge: "가벼운 한마디", morning: "아침 인사", anniversary: "함께한 날 인사", followup: "하던 이야기 잇기",
};
const TONE: Record<string, "neutral" | "accent" | "success" | "warning" | "danger"> = {
  cold: "neutral", active: "success", quiet: "accent", lapsed: "warning", pleading: "danger", sleeping: "neutral",
};

function summary(r: TriggerRule): string {
  const bits: string[] = [];
  const s = r.when.silent_days;
  if (s) {
    const [lo, hi] = s;
    bits.push(hi === null || hi === undefined ? `${lo}일 이상 조용` : lo === hi ? (lo === 0 ? "오늘 말한 날" : `조용한 지 ${lo}일`) : `조용한 지 ${lo}~${hi}일`);
  }
  if (r.when.after_days) bits.push(`${r.when.after_days[0]}~${r.when.after_days[1]}일 뒤 하루`);
  if (r.when.occasion === "anniversary") {
    const days = r.when.days ?? [];
    if (days.length) bits.push(`함께한 지 ${days.join("·")}일째`);
    if (r.when.stage_up) bits.push("사이가 가까워진 날");
  }
  bits.push(`${r.window[0]}~${r.window[1]}시`);
  if (r.once) bits.push("한 번만");
  return bits.join(" · ");
}

function RuleChip({ r }: { r: TriggerRule }) {
  return (
    <span className={cn("inline-flex items-baseline gap-1.5 rounded-lg border px-2 py-1 text-xs",
      r.enabled ? "border-accent/30 bg-accent/8" : "border-border text-muted-fg")}>
      <b className={cn("font-medium", r.enabled ? "text-fg" : "line-through")}>{r.label}</b>
      <span className="text-muted-fg">{summary(r)}</span>
    </span>
  );
}

/* ── 흐름도 ─────────────────────────────────────────────────────────────── */

function Ladder({ view, rules }: { view: TriggerView; rules: TriggerRule[] }) {
  const always = rules.filter((r) => r.when.state === "any");
  return (
    <div className="space-y-4">
      {always.length ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-border px-3 py-2">
          <span className="text-xs font-medium text-muted-fg">칸과 상관없이</span>
          {always.map((r) => <RuleChip key={r.key} r={r} />)}
        </div>
      ) : null}
      <ol className="relative space-y-1 pl-[104px]">
        {LADDER.map((state, i) => {
          const here = rules.filter((r) => r.when.state === state);
          return (
            <li key={state} className="relative">
              <div className="absolute -left-[104px] top-2 w-[92px] text-right">
                <Badge tone={TONE[state]}>{view.labels?.[state] ?? state}</Badge>
                <div className="mt-0.5 text-[11px] text-muted-fg">{view.states?.[state] ?? 0}쌍</div>
              </div>
              <div className={cn("min-h-[44px] rounded-xl border px-3 py-2",
                here.some((r) => r.enabled) ? "border-border bg-card" : "border-dashed border-border bg-muted/20")}>
                {here.length === 0 ? (
                  <p className="text-sm text-muted-fg">
                    {state === "cold" ? "먼저 걸지 않아요." : state === "sleeping" ? "그 뒤로는 걸지 않아요." : "이 칸에 걸린 규칙이 없어요."}
                  </p>
                ) : <div className="flex flex-wrap gap-2">{here.map((r) => <RuleChip key={r.key} r={r} />)}</div>}
              </div>
              {i < LADDER.length - 1 ? (
                <div className="flex items-center gap-2 py-1 pl-1">
                  <span className="h-4 w-px bg-border" />
                  <span className="text-[11px] text-muted-fg">{EDGE[state]}</span>
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/* ── 개요 ───────────────────────────────────────────────────────────────── */

/** 설정 한 줄: 왼쪽에 이름과 한 문장, 오른쪽에 조작. [SwitchRow] 와 같은 모양이라
 *  스위치 줄과 고르는 줄이 나란히 서도 같은 표의 줄로 읽힌다. 칸마다 테두리 상자를
 *  씌우던 것은 스위치 하나만 다른 물건처럼 보이게 했다. */
function SettingRow({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
      <div className="min-w-0">
        <div className="text-sm font-medium">{title}</div>
        {description ? <div className="mt-0.5 text-xs text-muted-fg">{description}</div> : null}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function NumberWithUnit({ value, min, max, unit, onSave }: { value: number; min: number; max: number; unit: string; onSave: (n: number) => void }) {
  return (
    <div className="flex items-center gap-2">
      <Input type="number" min={min} max={max} defaultValue={value} key={value} className="h-10 w-24 text-right"
             onBlur={(e) => { const n = Number(e.target.value); if (n !== value) onSave(n); }} />
      <span className="w-6 text-sm text-muted-fg">{unit}</span>
    </div>
  );
}

function Overview({ view, rules, save }: { view: TriggerView; rules: TriggerRule[]; save: (b: Record<string, unknown>) => void }) {
  const models = useQuery({ queryKey: ["admin", "models"], queryFn: Admin.models });
  return (
    <div className="space-y-4">
      <Section title="설정" description="여기서 정한 것이 모든 비서에 함께 적용돼요. 사용자의 크레딧은 쓰지 않아요.">
        <div className="divide-y divide-border">
          <SwitchRow title="먼저 말 걸기" description="끄면 어느 비서도 먼저 말하지 않아요."
                     checked={view.enabled} onChange={(v) => save({ enabled: v })} />
          <SettingRow title="트리거 모델"
            description={view.running.fell_back
              ? <span className="text-warning">고른 모델을 쓸 수 없어 {view.running.model} 로 답하고 있어요.</span>
              : "비서가 쓰는 모델과 따로 정해요."}>
            <Select className="h-10 w-72" value={view.provider && view.model ? `${view.provider}|${view.model}` : ""}
                    onChange={(e) => { const [p, m] = e.target.value.split("|"); save({ provider: p ?? "", model: m ?? "" }); }}>
              <option value="">기본 모델</option>
              {(models.data?.items ?? []).filter((m: { enabled: boolean }) => m.enabled).map((m: { provider: string; model_id: string; display_name?: string }) => (
                <option key={`${m.provider}|${m.model_id}`} value={`${m.provider}|${m.model_id}`}>{m.display_name || m.model_id} · {m.provider}</option>
              ))}
            </Select>
          </SettingRow>
          <SettingRow title="한 사람에게 하루 최대" description={`무슨 규칙을 더해도 ${view.hard_max_per_day}번을 넘지 않아요.`}>
            <NumberWithUnit value={view.max_per_day} min={1} max={view.hard_max_per_day} unit="번" onSave={(n) => save({ max_per_day: n })} />
          </SettingRow>
          <SettingRow title="두 번 사이 최소 간격" description="이 사이에는 두 번 보내지 않아요.">
            <NumberWithUnit value={view.min_gap_minutes} min={0} max={1440} unit="분" onSave={(n) => save({ min_gap_minutes: n })} />
          </SettingRow>
          <SettingRow title="멀어짐으로 넘어가는 날" description="이만큼 말이 없으면 매일 거는 것을 멈춰요.">
            <NumberWithUnit value={view.lapse_after_days} min={1} max={30} unit="일" onSave={(n) => save({ lapse_after_days: n })} />
          </SettingRow>
        </div>
        {view.rules_valid ? null : <p className="mt-3 text-sm text-danger">저장된 규칙을 읽지 못해서 기본 규칙으로 돌고 있어요.</p>}
      </Section>

      <Section title="흐름" description="사람과 비서 한 쌍은 늘 한 칸 위에 서 있어요. 대화가 칸을 옮겨요.">
        <Ladder view={view} rules={rules} />
      </Section>
    </div>
  );
}

/* ── 규칙 ───────────────────────────────────────────────────────────────── */

function RuleCard({ rule, view, onChange, onRemove, onMove }: {
  rule: TriggerRule; view: TriggerView; onChange: (r: TriggerRule) => void; onRemove: () => void; onMove: (d: -1 | 1) => void;
}) {
  const [open, setOpen] = useState(false);
  const set = (patch: Partial<TriggerRule>) => onChange({ ...rule, ...patch });
  const setWhen = (patch: Partial<TriggerRule["when"]>) => onChange({ ...rule, when: { ...rule.when, ...patch } });
  const silent = rule.when.silent_days ?? [0, null];
  const after = rule.when.after_days;
  // 쉼표로 적는 칸은 적는 동안 글자 그대로 두고, 칸을 떠날 때 숫자로 바꾼다.
  const [daysText, setDaysText] = useState((rule.when.days ?? []).join(", "));
  return (
    <div className={cn("rounded-xl border", rule.enabled ? "border-border bg-card" : "border-dashed border-border bg-muted/20")}>
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <Switch checked={rule.enabled} onChange={(v) => set({ enabled: v })} />
        <button type="button" onClick={() => setOpen(!open)} className="min-w-0 flex-1 text-left">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-medium">{rule.label}</span>
            <Badge tone="outline">{rule.when.state === "any" ? "어느 칸이든" : view.labels?.[rule.when.state] ?? rule.when.state}</Badge>
            <span className="truncate text-xs text-muted-fg">{summary(rule)}</span>
          </div>
        </button>
        <div className="flex shrink-0 items-center gap-1">
          <Button variant="ghost" size="icon" onClick={() => onMove(-1)} aria-label="위로"><ChevronUp className="h-4 w-4" /></Button>
          <Button variant="ghost" size="icon" onClick={() => onMove(1)} aria-label="아래로"><ChevronDown className="h-4 w-4" /></Button>
          <Button variant="ghost" size="icon" onClick={onRemove} aria-label="지우기"><Trash2 className="h-4 w-4" /></Button>
          <Button variant="outline" size="sm" onClick={() => setOpen(!open)}>{open ? "접기" : "고치기"}</Button>
        </div>
      </div>
      {open ? (
        <div className="border-t border-border px-4 py-4">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Field label="이름"><Input value={rule.label} onChange={(e) => set({ label: e.target.value })} /></Field>
            <Field label="어느 칸에서">
              <Select value={rule.when.state} onChange={(e) => setWhen({ state: e.target.value })}>
                <option value="any">어느 칸이든</option>
                {LADDER.map((s) => <option key={s} value={s}>{view.labels?.[s] ?? s}</option>)}
              </Select>
            </Field>
            <Field label="말의 종류" hint="종류마다 쓰는 법이 달라요">
              <Select value={rule.kind} onChange={(e) => set({ kind: e.target.value })}>
                {(view.kinds ?? []).map((k) => <option key={k} value={k}>{KIND_LABEL[k] ?? k}</option>)}
              </Select>
            </Field>
            <Field label="보낸 뒤 옮길 칸">
              <Select value={rule.next} onChange={(e) => set({ next: e.target.value })}>
                <option value="">그대로</option>
                {LADDER.map((s) => <option key={s} value={s}>{view.labels?.[s] ?? s}</option>)}
              </Select>
            </Field>
            {rule.when.occasion === "anniversary" ? (<>
              {/* 함께한 날은 칸이 아니라 달력으로 울린다. 무슨 날인지를 여기서 정한다. */}
              <Field label="함께한 지 며칠째" hint="처음 대화한 날이 1일째예요. 쉼표로 여러 날을 적어요.">
                <Input value={daysText} onChange={(e) => setDaysText(e.target.value)}
                       onBlur={() => setWhen({ days: daysText.split(/[,\s]+/).map(Number).filter((n) => Number.isInteger(n) && n > 0) })}
                       placeholder="7, 30, 100, 365" />
              </Field>
              <Field label="사이가 가까워진 날" hint="관계가 한 단계 올라간 날에도 울려요.">
                <div className="pt-1.5"><Switch checked={!!rule.when.stage_up} onChange={(v) => setWhen({ stage_up: v })} /></div>
              </Field>
            </>) : (<>
            <Field label="조용한 날" hint="비워 두면 따지지 않아요">
              <div className="flex items-center gap-1.5">
                <Input type="number" min={0} value={silent[0] ?? 0} onChange={(e) => setWhen({ silent_days: [Number(e.target.value), silent[1] ?? null] })} />
                <span className="text-muted-fg">~</span>
                <Input type="number" min={0} placeholder="끝없음" value={silent[1] ?? ""}
                       onChange={(e) => setWhen({ silent_days: [silent[0] ?? 0, e.target.value === "" ? null : Number(e.target.value)] })} />
              </div>
            </Field>
            <Field label="며칠 뒤 하루" hint="그 사이 하루를 골라요">
              <div className="flex items-center gap-1.5">
                <Input type="number" min={0} placeholder="—" value={after?.[0] ?? ""}
                       onChange={(e) => setWhen({ after_days: e.target.value === "" ? undefined : [Number(e.target.value), after?.[1] ?? Number(e.target.value)] })} />
                <span className="text-muted-fg">~</span>
                <Input type="number" min={0} placeholder="—" value={after?.[1] ?? ""}
                       onChange={(e) => setWhen({ after_days: e.target.value === "" ? undefined : [after?.[0] ?? 0, Number(e.target.value)] })} />
              </div>
            </Field>
            </>)}
            <Field label="몇 시에서 몇 시">
              <div className="flex items-center gap-1.5">
                <Input type="number" min={0} max={24} value={rule.window[0]} onChange={(e) => set({ window: [Number(e.target.value), rule.window[1]] })} />
                <span className="text-muted-fg">~</span>
                <Input type="number" min={0} max={24} value={rule.window[1]} onChange={(e) => set({ window: [rule.window[0], Number(e.target.value)] })} />
              </div>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="하루 몇 번"><Input type="number" min={1} max={view.hard_max_per_day} value={rule.per_day} onChange={(e) => set({ per_day: Number(e.target.value) })} /></Field>
              <Field label="한 번만"><div className="pt-1.5"><Switch checked={rule.once} onChange={(v) => set({ once: v })} /></div></Field>
            </div>
          </div>
          <Field label="말의 온도" hint="비서가 어떤 마음으로 건네는지 적어요. 그대로 프롬프트에 들어가요." className="mt-4">
            <Textarea value={rule.tone} maxLength={400} onChange={(e) => set({ tone: e.target.value })} className="min-h-[72px]" />
          </Field>
        </div>
      ) : null}
    </div>
  );
}

/* ── 미리보기 (규칙 탭 아래) ───────────────────────────────────────────── */

interface DayHit { label: string; hour: number; state: string; silent: number }

/** 칸 안에 들어가는 줄 수. 칸마다 높이가 달라 달력이 들쭉날쭉하던 것을 막으려고
 *  모든 칸을 이 줄 수만큼의 높이로 고정한다. 넘치면 말줄임하고, 전부는 호버로 본다. */
const DAY_LINES = 4;

function DayCell({ day, talked, hits, labels }: { day: number; talked: boolean; hits: DayHit[]; labels: Record<string, string> }) {
  const [boxRef, cut] = useOverflow<HTMLDivElement>();
  // "대화함" 도 한 줄을 차지한다. 줄이 모자라면 마지막 줄을 "외 N개" 로 쓴다.
  const room = DAY_LINES - (talked ? 1 : 0);
  const shown = hits.length > room ? hits.slice(0, Math.max(0, room - 1)) : hits;
  const more = hits.length - shown.length;
  const tone = talked ? "border-success/40 bg-success/10" : hits.length ? "border-accent/30 bg-accent/8" : "border-border bg-muted/20";
  return (
    <HoverCard
      as="div" focusable={cut || more > 0} disabled={!cut && more === 0} side="top" maxWidth={320}
      className={cn("rounded-xl border p-2 text-[11px] outline-none focus-visible:ring-2 focus-visible:ring-ring", tone,
        (cut || more > 0) && "cursor-default")}
      content={
        <div className="min-w-[200px]">
          <div className="flex items-center gap-2 text-xs text-muted-fg">
            <span className="font-medium text-fg">{day + 1}일째</span>
            {talked ? <Badge tone="success">대화한 날</Badge> : null}
          </div>
          {hits.length ? (
            <ul className="mt-2 space-y-2">
              {hits.map((h, i) => (
                <li key={i} className="flex gap-2.5">
                  <span className="w-9 shrink-0 tabular-nums text-muted-fg">{h.hour}시</span>
                  <span className="min-w-0">
                    <span className="block font-medium">{h.label}</span>
                    <span className="block text-xs text-muted-fg">{labels?.[h.state] ?? h.state} · 조용한 지 {h.silent}일</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : <p className="mt-2 text-xs text-muted-fg">이날은 먼저 말을 걸지 않아요.</p>}
        </div>
      }>
      <div className="font-medium leading-4 text-muted-fg">{day + 1}일</div>
      <div ref={boxRef} className="mt-1 overflow-hidden leading-4" style={{ height: `${DAY_LINES}rem` }}>
        {talked ? <div data-truncate className="truncate text-success">대화함</div> : null}
        {shown.map((h, i) => <div key={i} data-truncate className="truncate text-fg">{h.hour}시 {h.label}</div>)}
        {more > 0 ? <div className="truncate text-muted-fg">… 외 {more}개</div> : null}
      </div>
    </HoverCard>
  );
}

/** 편집 중인 규칙이 30일 동안 무엇을 보내는지 달력으로. 규칙을 고치는 자리 바로
 *  아래에 있어야 고친 것의 결과를 그 자리에서 본다 — 탭을 건너가서 보는 미리보기는
 *  미리보기가 아니다. */
function Preview({ rules, view }: { rules: TriggerRule[]; view: TriggerView }) {
  const locale = useLocale();
  const [talk, setTalk] = useState("0");
  const days = 30;
  const sim = useMutation({
    mutationFn: (b: { rules: TriggerRule[]; talk: string }) => Admin.simulateTriggers(
      { rules: b.rules, max_per_day: view.max_per_day, lapse_after_days: view.lapse_after_days, min_gap_minutes: view.min_gap_minutes },
      days, b.talk),
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const run = sim.mutate;
  // 글자 하나 칠 때마다 서버에 묻지 않는다. 손이 멈추면 그때 다시 그린다.
  useEffect(() => {
    const h = window.setTimeout(() => run({ rules, talk }), 400);
    return () => window.clearTimeout(h);
  }, [run, rules, talk]);
  const byDay = useMemo(() => {
    const m = new Map<number, DayHit[]>();
    for (const e of sim.data?.events ?? []) m.set(e.day, [...(m.get(e.day) ?? []), { label: e.label, hour: e.hour, state: e.state, silent: e.silent_days }]);
    return m;
  }, [sim.data]);
  const talked = new Set((sim.data?.talk_days ?? []).map(Number));
  return (
    <Section title="30일 미리보기" description="위의 규칙이면 30일 동안 언제 무엇이 가는지예요. 저장하기 전에 봐요."
             action={<label className="flex items-center gap-2 text-sm text-muted-fg">
               말을 건 날
               <Input value={talk} onChange={(e) => setTalk(e.target.value)} placeholder="0, 3, 4" className="h-9 w-40" />
             </label>}>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-10">
        {Array.from({ length: days }, (_, d) => (
          <DayCell key={d} day={d} talked={talked.has(d)} hits={byDay.get(d) ?? []} labels={view.labels} />
        ))}
      </div>
      <p className="mt-3 text-sm text-muted-fg">이 규칙이면 {days}일 동안 {sim.data?.events.length ?? 0}번 먼저 말을 걸어요.</p>
    </Section>
  );
}

/* ── 시뮬레이션: 내 비서로 받아 보기 ─────────────────────────────────────── */

/** 관리자가 **자기 비서로** 규칙 하나의 말을 실제로 받아 본다. 비서의 대화에도,
 *  사다리의 표에도, 사용량에도 아무것도 남지 않는다 — 시험이 운영을 건드리면 다음 날
 *  그 비서가 "어제 이미 보냈다" 며 입을 닫는다. 아직 저장하지 않은 규칙도 받아 볼 수
 *  있다: 편집 중인 그대로를 보낸다. */
function TestSend({ rules }: { rules: TriggerRule[] }) {
  const locale = useLocale();
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => Agents.list() });
  const mine = useMemo(() => agents.data?.items ?? [], [agents.data]);
  const [agentId, setAgentId] = useState("");
  const [ruleKey, setRuleKey] = useState(rules[0]?.key ?? "");
  const [tries, setTries] = useState<TriggerTestResult[]>([]);
  useEffect(() => { if (!agentId && mine[0]) setAgentId(mine[0].id); }, [agentId, mine]);
  const send = useMutation({
    mutationFn: () => {
      const rule = rules.find((r) => r.key === ruleKey);
      if (!rule) throw new Error("rule");
      return Admin.testTrigger(agentId, rule);
    },
    onSuccess: (r) => setTries((xs) => [r, ...xs].slice(0, 20)),
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  if (agents.isLoading) return <Skeleton className="h-40" />;
  return (
    <Section title="내 비서로 받아 보기" description="규칙 하나를 골라 내 비서가 실제로 어떻게 말을 거는지 받아 봐요. 비서에는 아무것도 남지 않아요.">
      {mine.length === 0 ? (
        <p className="text-sm text-muted-fg">받아 볼 내 비서가 없어요. 비서를 하나 만들면 여기서 시험할 수 있어요.</p>
      ) : (<>
        <div className="flex flex-wrap items-center gap-2">
          <Select className="h-10 w-56" value={agentId} onChange={(e) => setAgentId(e.target.value)} aria-label="비서">
            {mine.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </Select>
          <Select className="h-10 w-72" value={ruleKey} onChange={(e) => setRuleKey(e.target.value)} aria-label="규칙">
            {rules.map((r) => <option key={r.key} value={r.key}>{r.label}{r.enabled ? "" : " (꺼짐)"}</option>)}
          </Select>
          <Button className="h-10" loading={send.isPending} disabled={!agentId || !ruleKey} onClick={() => send.mutate()}>
            <Send className="h-4 w-4" />받아 보기
          </Button>
        </div>
        <div className="mt-5 space-y-4">
          {tries.length === 0 ? (
            <p className="text-sm text-muted-fg">받아 본 말이 여기 쌓여요.</p>
          ) : tries.map((r, i) => (
            <div key={i} className="flex items-start gap-3">
              <Avatar name={r.agent.name} src={r.agent.avatar_url} size={32} />
              <div className="min-w-0 flex-1">
                <div className="text-xs text-muted-fg">
                  <span className="font-medium text-fg">{r.agent.name}</span>
                  <span className="mx-1.5">·</span>{r.label}
                  {r.situation ? <><span className="mx-1.5">·</span>{r.situation}으로 받아 봤어요</> : null}
                </div>
                <div className={cn("mt-1 inline-block max-w-2xl whitespace-pre-wrap rounded-2xl rounded-tl-md px-4 py-2.5 text-sm",
                  r.empty ? "border border-dashed border-border text-muted-fg" : "bg-muted text-fg")}>
                  {r.empty ? "이어 갈 이야기가 없어서 말을 걸지 않아요." : r.text}
                </div>
                <div className="mt-1 text-[11px] text-muted-fg">
                  {KIND_LABEL[r.kind] ?? r.kind} · {r.model}{r.fell_back ? " (내려온 모델)" : ""} · 토큰 {r.tokens.input + r.tokens.output}
                </div>
              </div>
            </div>
          ))}
        </div>
      </>)}
    </Section>
  );
}

/* ── 발송 기록 ─────────────────────────────────────────────────────────── */

const ALL = "";

/** 발송 기록. 관리자가 여기 오는 이유는 보통 둘이다 — "이 사람이 왜 두 번 받았나" 와
 *  "이 기능이 얼마를 쓰고, 사람들이 답을 하나". 위에 기간과 거르기, 그 아래 합계,
 *  그 아래 한 줄씩, 줄을 누르면 실제로 간 말과 돌아온 답. */
function SendLog({ rules }: { rules: TriggerRule[] }) {
  const locale = useLocale();
  const rcal = useRcalTheme();
  const [range, setRange] = useState<[Date | null, Date | null]>(() => {
    const until = new Date(); const since = new Date(until); since.setDate(since.getDate() - 6);
    return [since, until];
  });
  const [agent, setAgent] = useState(ALL);
  const [rule, setRule] = useState(ALL);
  const [replied, setReplied] = useState(ALL);
  const [limit, setLimit] = useState(50);
  const [open, setOpen] = useState<TriggerLogItem | null>(null);
  const since = range[0] ? toISODate(range[0]) : undefined;
  const until = range[1] ? toISODate(range[1]) : undefined;
  const q = useQuery({
    queryKey: ["admin", "triggers", "log", { since, until, agent, rule, replied, limit }],
    queryFn: () => Admin.triggerLog({ since, until, agent: agent || undefined, rule: rule || undefined, replied: replied || undefined, limit }),
    placeholderData: keepPreviousData,
  });
  const d = q.data;
  const label = (key: string, kind: string) => (key ? d?.facets.rules.find((r) => r.key === key)?.label ?? rules.find((r) => r.key === key)?.label ?? key : KIND_LABEL[kind] ?? kind);
  const rate = d && d.summary.count ? Math.round((d.summary.replied / d.summary.count) * 100) : 0;
  return (
    <div className="space-y-4">
      {/* 한 줄: [기간] [비서] [규칙] [답]. 기간이 맨 앞인 것은 나머지가 모두 그 기간 안에서
          걸러지기 때문이다. 고를 거리는 그 기간에 실제로 나간 것에서만 뽑는다. */}
      <div className="filter-row flex flex-wrap items-center gap-2">
        <DateRangePicker value={range} onChange={(v) => { setRange(v); setLimit(50); }} locale={locale} clearable={false}
                         className={rcal} panelClassName={rcal} width="auto" aria-label="기간" placeholder="기간" />
        <Selector size="lg" ariaLabel="비서" value={agent} onChange={(v: string) => { setAgent(v); setLimit(50); }}
          options={[{ value: ALL, label: "모든 비서" }, ...(d?.facets.agents ?? []).map((a) => ({ value: a.id, label: a.name }))]} />
        <Selector size="lg" ariaLabel="규칙" value={rule} onChange={(v: string) => { setRule(v); setLimit(50); }}
          options={[{ value: ALL, label: "모든 규칙" }, ...(d?.facets.rules ?? []).map((r) => ({ value: r.key, label: r.label }))]} />
        <Selector size="lg" ariaLabel="답" value={replied} onChange={(v: string) => { setReplied(v); setLimit(50); }}
          options={[{ value: ALL, label: "답 여부 전체" }, { value: "yes", label: "답이 온 것" }, { value: "no", label: "답이 없는 것" }]} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="총 발송" value={d ? fmtNumber(d.summary.count) : "–"} hint={d ? `받은 사람 ${fmtNumber(d.summary.people)}명` : undefined} />
        <Stat label="총 사용 금액" value={d ? `${fmtNumber(d.summary.worth, 1)} 크레딧` : "–"}
              hint={d ? `약 $${d.summary.usd.toFixed(2)} · 사용자에게 청구하지 않아요` : undefined} />
        <Stat label="답이 온 비율" value={d ? `${rate}%` : "–"} hint={d ? `하루 안에 답이 온 ${fmtNumber(d.summary.replied)}건` : undefined} />
        <Stat label="연달아 보낸 수" value={d ? fmtNumber(d.summary.repeats) : "–"} hint="같은 사람에게 두 시간 안에 또 간 말" />
      </div>

      <Section title="보낸 말" description="줄을 누르면 실제로 간 말과 돌아온 답을 볼 수 있어요.">
        {!d ? <Skeleton className="h-40" /> : d.items.length === 0 ? (
          <p className="text-sm text-muted-fg">이 기간에 나간 말이 없어요.</p>
        ) : (<>
          <Table>
            <THead><TR><TH>시각</TH><TH>받은 사람</TH><TH>비서</TH><TH>규칙</TH><TH>보낸 말</TH><TH>답</TH></TR></THead>
            <TBody>
              {d.items.map((it) => (
                <TR key={it.id} tabIndex={0} role="button" onClick={() => setOpen(it)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(it); } }}
                    className={cn("cursor-pointer", it.repeat && "bg-warning/8")}>
                  <TD className="whitespace-nowrap tabular-nums">{fmtDateTime(it.at)}</TD>
                  <TD className="whitespace-nowrap">{it.owner.name}{it.repeat ? <Badge tone="warning" className="ml-2">연달아</Badge> : null}</TD>
                  <TD className="whitespace-nowrap text-muted-fg">{it.agent.name}</TD>
                  <TD className="whitespace-nowrap">{label(it.rule, it.kind)}</TD>
                  <TD className="max-w-[360px]"><span className="block truncate text-muted-fg">{it.text}</span></TD>
                  <TD className="whitespace-nowrap">{it.replied_at ? <Badge tone="success">답 옴</Badge> : <span className="text-muted-fg">–</span>}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {d.total > d.items.length ? (
            <div className="mt-3 flex justify-center">
              <Button variant="outline" size="sm" loading={q.isFetching} onClick={() => setLimit((n) => n + 50)}>
                더 보기 ({fmtNumber(d.total - d.items.length)}건 남음)
              </Button>
            </div>
          ) : null}
        </>)}
      </Section>

      <Sheet open={!!open} onClose={() => setOpen(null)} side="right" title="보낸 말">
        {open ? (
          <div className="space-y-5">
            <KeyValue items={[
              { k: "보낸 때", v: fmtDateTime(open.at) },
              { k: "받은 사람", v: open.owner.name },
              { k: "비서", v: open.agent.name },
              { k: "규칙", v: `${label(open.rule, open.kind)} · ${KIND_LABEL[open.kind] ?? open.kind}` },
              { k: "모델", v: open.model ? `${open.model} · 토큰 ${fmtNumber(open.tokens)}` : "–" },
              { k: "사용 금액", v: `${fmtNumber(open.worth, 2)} 크레딧` },
            ]} />
            {open.repeat ? <p className="rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning">두 시간 안에 같은 사람에게 또 간 말이에요.</p> : null}
            <div className="space-y-3">
              <div className="flex items-start gap-2.5">
                <Avatar name={open.agent.name} src={open.agent.avatar_url} size={30} />
                <div className="min-w-0">
                  <div className="text-xs text-muted-fg">{open.agent.name}</div>
                  <div className="mt-1 whitespace-pre-wrap rounded-2xl rounded-tl-md bg-muted px-3.5 py-2.5 text-sm">{open.text}</div>
                </div>
              </div>
              {open.replied_at ? (
                <div className="flex flex-col items-end">
                  <div className="text-xs text-muted-fg">{open.owner.name} · {fmtRelative(open.replied_at, locale)}</div>
                  <div className="mt-1 max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tr-md bg-accent px-3.5 py-2.5 text-sm text-accent-fg">{open.reply}</div>
                </div>
              ) : <p className="text-center text-xs text-muted-fg">하루 안에 돌아온 답이 없어요.</p>}
            </div>
          </div>
        ) : null}
      </Sheet>
    </div>
  );
}

/* ── 화면 ───────────────────────────────────────────────────────────────── */

export function TriggersAdmin() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("overview");
  const q = useQuery({ queryKey: ["admin", "triggers"], queryFn: Admin.triggers });
  const [rules, setRules] = useState<TriggerRule[] | null>(null);
  useEffect(() => { if (q.data) setRules(q.data.rules); }, [q.data]);
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => Admin.putTriggers(body),
    onSuccess: (v) => { qc.setQueryData(["admin", "triggers"], v); setRules(v.rules); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const view = q.data;
  const dirty = !!view && !!rules && JSON.stringify(rules) !== JSON.stringify(view.rules);
  const move = (i: number, d: -1 | 1) => {
    if (!rules) return;
    const j = i + d;
    if (j < 0 || j >= rules.length) return;
    const next = [...rules];
    [next[i], next[j]] = [next[j], next[i]];
    setRules(next);
  };
  return (
    <Page>
      <PageHeader title="비서 트리거 이벤트" description="비서가 먼저 말을 거는 리듬이에요. 모든 비서에 함께 적용되고, 사용자의 크레딧을 쓰지 않아요."
        action={<Segmented value={tab} onChange={(v) => setTab(v as Tab)} options={[
          { value: "overview", label: "개요" }, { value: "rules", label: "규칙" },
          { value: "simulate", label: "시뮬레이션" }, { value: "log", label: "발송 기록" },
        ]} />} />
      {!view || !rules ? <Skeleton className="h-64" /> : tab === "overview" ? (
        <Overview view={view} rules={rules} save={(b) => save.mutate(b)} />
      ) : tab === "rules" ? (
        <div className="space-y-4">
        {/* 머리의 오른쪽 자리는 flex 가 아니다. 버튼을 그대로 두면 글자처럼 늘어서
            높이와 간격이 제각각이 된다 — 한 줄의 묶음으로 세운다. */}
        <Section title="규칙" description="위에서부터 맞는 첫 규칙 하나가 울려요."
          action={<div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setRules(view.defaults)}>기본값으로</Button>
            <Button variant="outline" size="sm" onClick={() => setRules([...rules, {
              key: `rule${rules.length + 1}`, label: "새 규칙", enabled: false, kind: "checkin",
              when: { state: "quiet", silent_days: [1, 2] }, window: [9, 21], per_day: 1, once: false, next: "", tone: "",
            }])}><Plus className="h-4 w-4" />규칙 추가</Button>
            <Button size="sm" loading={save.isPending} disabled={!dirty} onClick={() => save.mutate({ rules })}>저장</Button>
          </div>}>
          <div className="space-y-2">
            {rules.map((r, i) => (
              <RuleCard key={`${r.key}:${i}`} rule={r} view={view}
                onChange={(next) => setRules(rules.map((x, j) => (j === i ? next : x)))}
                onRemove={() => setRules(rules.filter((_, j) => j !== i))}
                onMove={(d) => move(i, d)} />
            ))}
          </div>
          {dirty ? <p className="mt-3 text-sm text-warning">아직 저장하지 않은 고침이 있어요.</p> : null}
        </Section>
        <Preview rules={rules} view={view} />
        </div>
      ) : tab === "simulate" ? (
        <TestSend rules={rules} />
      ) : (
        <SendLog rules={rules} />
      )}
    </Page>
  );
}
