"use client";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BookOpen, Brain, CalendarDays, Eye, Globe, HardDrive, Lock, MessagesSquare, Network, Search, User, Users } from "@/components/icons";
import { Agents, RoomAccess, type Outsider, type OutsiderItem, type OutsiderKind, type OutsiderLevel, type OutsiderScope, type OutsiderSettings } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtRelative } from "@/lib/format";
import { confirm } from "@/lib/confirm";
import { cn } from "@/lib/utils";
import { useAgent } from "./AgentLayout";
import { useWeeklyLabel } from "@/components/schedule/WeeklyGrid";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox, Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { Sheet } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Page } from "@/components/owner/Shell";

/* 비서의 [지식] 탭 = 외부인과의 대화에서 무엇을 쓰나 (plan/57).

   나와의 대화에서는 비서가 내 것을 전부 쓴다 — 그래서 여기에는 외부인 쪽만 있다. 공개 범위가
   있는 것은 [내 정보 → 정보](프로필) 하나이고, 나머지는 이 비서가 외부인에게 쓸지, 누구에게,
   무엇을 쓸지를 여기서 정한다. 줄마다 조작은 하나, 누르면 바로 저장되고 다음 말부터 적용된다. */

export function AgentKnowledge() {
  return <Page><OutsiderBoard /><RoomsSection /></Page>;
}

function OutsiderBoard() {
  const t = useT(); const locale = useLocale(); const a = useAgent(); const qc = useQueryClient();
  const key = ["outsider", a.id];
  const q = useQuery({ queryKey: key, queryFn: () => Agents.outsider(a.id), staleTime: 30_000 });
  const [picking, setPicking] = useState<OutsiderKind | null>(null);
  const save = useMutation({
    mutationFn: (b: Partial<OutsiderSettings>) => Agents.patchOutsider(a.id, b),
    // 누르는 순간 바뀐 것처럼 보이고, 서버가 거절하면 되돌린다.
    onMutate: async (b) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<Outsider>(key);
      if (prev) qc.setQueryData<Outsider>(key, { ...prev, settings: { ...prev.settings, ...b } });
      return { prev };
    },
    onError: (e, _b, ctx) => { if (ctx?.prev) qc.setQueryData(key, ctx.prev); toast.error(friendlyError(e, locale)); },
    onSuccess: (v) => qc.setQueryData(key, v),
  });
  const o = q.data;
  const s = o?.settings;
  const set = (b: Partial<OutsiderSettings>) => save.mutate(b);

  return (
    <Card>
      <CardHeader title={t("out.title")} description={t("out.desc")} />
      <CardBody className="pt-0">
        {!o || !s ? <Skeleton className="h-96" /> : (
          <div>
            <ProfileRow o={o} on={s.profile} onChange={(v) => set({ profile: v })} />
            <KnowledgeRow o={o} s={s} set={set} onPick={() => setPicking("knowledge")} />
            <FilesRow o={o} s={s} set={set} onPick={() => setPicking("files")} />
            <NetworkRow o={o} s={s} set={set} onPick={() => setPicking("network")} />
            <ScheduleRow o={o} s={s} set={set} />
            <MemoryRow o={o} s={s} set={set} />
            <Row icon={<Globe />} title={t("out.web")} on={s.web}
              summary={s.web ? t("out.web_on") : t("out.web_off")}
              control={<Switch checked={s.web} onChange={(v) => set({ web: v })} label={t("out.web")} />} />
            <p className="border-t border-border pt-3 text-xs text-muted-fg">{t("out.never")}</p>
          </div>
        )}
      </CardBody>
      {picking ? <PickSheet kind={picking} agentId={a.id} onClose={() => setPicking(null)}
        onSaved={(v) => { qc.setQueryData(key, v); setPicking(null); }} /> : null}
    </Card>
  );
}

/* ── 줄 하나 ──────────────────────────────────────────────────────────── */

function Row({ icon, title, on, summary, control, children }: { icon: ReactNode; title: string; on: boolean; summary: ReactNode; control?: ReactNode; children?: ReactNode }) {
  return (
    <div className="border-t border-border py-4 first:border-t-0 first:pt-1">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
        <div className="flex min-w-0 flex-1 gap-3">
          <span className={cn("inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl [&>svg]:h-[18px] [&>svg]:w-[18px]",
            on ? "bg-accent/10 text-accent" : "bg-muted text-muted-fg")}>{icon}</span>
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-semibold">{title}</div>
            <div className={cn("mt-0.5 text-sm", on ? "text-fg/80" : "text-muted-fg")}>{summary}</div>
          </div>
        </div>
        {control ? <div className="shrink-0 pl-12 sm:pl-0">{control}</div> : null}
      </div>
      {on && children ? <div className="mt-3 space-y-2 pl-12">{children}</div> : null}
    </div>
  );
}

function Chip({ children, icon, tone = "neutral" }: { children: ReactNode; icon?: ReactNode; tone?: "neutral" | "accent" }) {
  return (
    <span className={cn("inline-flex max-w-full items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] leading-4",
      tone === "accent" ? "bg-accent/10 text-accent" : "bg-muted text-fg")}>
      {icon}<span className="truncate">{children}</span>
    </span>
  );
}

function Chips({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap gap-1">{children}</div>;
}

function Hint({ children }: { children: ReactNode }) {
  return <p className="text-xs text-muted-fg">{children}</p>;
}

function LevelPicker({ value, onChange }: { value: OutsiderLevel; onChange: (v: OutsiderLevel) => void }) {
  const t = useT();
  return (
    <Segmented<OutsiderLevel> size="sm" value={value} onChange={onChange} ariaLabel={t("out.level")}
      options={[{ value: "off", label: t("out.lv_off") }, { value: "known", label: t("out.lv_known") }, { value: "public", label: t("out.lv_public") }]} />
  );
}

/** 수준이 켜져 있을 때 한 줄로: 누구에게 · 무엇을. */
function reach(t: ReturnType<typeof useT>, level: OutsiderLevel, what: string) {
  if (level === "off") return t("out.off");
  return t(level === "known" ? "out.reach_known" : "out.reach_public", { what });
}

type RowProps = { o: Outsider; s: OutsiderSettings; set: (b: Partial<OutsiderSettings>) => void };

function ProfileRow({ o, on, onChange }: { o: Outsider; on: boolean; onChange: (v: boolean) => void }) {
  const t = useT();
  const label = (k: string) => t(`profile.f_${k.replace(".", "_")}`);
  const pub = o.profile.fields.filter((f) => f.level === "public");
  const known = o.profile.fields.filter((f) => f.level === "known");
  const posts = o.profile.posts.public + o.profile.posts.known;
  return (
    <Row icon={<User />} title={t("out.profile")} on={on}
      summary={on ? t("out.profile_on") : t("out.profile_off", { name: o.profile.name })}
      control={<Switch checked={on} onChange={onChange} label={t("out.profile")} />}>
      {pub.length || known.length || posts ? (
        <Chips>
          {pub.map((f) => <Chip key={f.key} tone="accent" icon={<Eye className="h-3 w-3" />}>{label(f.key)}</Chip>)}
          {known.map((f) => <Chip key={f.key} icon={<Users className="h-3 w-3" />}>{label(f.key)}</Chip>)}
          {posts ? <Chip icon={<Eye className="h-3 w-3" />}>{t("out.posts_n", { n: posts })}</Chip> : null}
        </Chips>
      ) : <Hint>{t("out.profile_empty")}</Hint>}
      <Hint>{t("out.profile_hint")} <Link href="/app/profile" className="font-medium text-accent hover:underline">{t("out.profile_go")}</Link></Hint>
    </Row>
  );
}

function ScopeLine({ all, picked, names, empty, onPick, allLabel }: { all: boolean; picked: string; names: string[]; empty: boolean; onPick: () => void; allLabel: string }) {
  const t = useT();
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{all ? allLabel : picked}</span>
        <Button size="sm" variant="outline" className="h-8" onClick={onPick}>{t("out.pick")}</Button>
      </div>
      {!all && names.length ? <Chips>{names.map((n) => <Chip key={n}>{n}</Chip>)}</Chips> : null}
      {!all && empty ? <Hint>{t("out.picked_none")}</Hint> : null}
    </>
  );
}

function KnowledgeRow({ o, s, set, onPick }: RowProps & { onPick: () => void }) {
  const t = useT();
  const k = o.knowledge;
  const has = k.docs_total + k.faqs_total > 0;
  const all = s.knowledge_scope === "all";
  return (
    <Row icon={<BookOpen />} title={t("out.knowledge")} on={s.knowledge !== "off"}
      summary={reach(t, s.knowledge, t("out.knowledge_what"))}
      control={<LevelPicker value={s.knowledge} onChange={(v) => set({ knowledge: v })} />}>
      {has ? (
        <>
          <ScopeLine all={all} allLabel={t("out.knowledge_all")} names={k.titles} onPick={onPick}
            picked={t("out.knowledge_picked", { d: k.docs_picked, f: k.faqs_picked })} empty={k.docs_picked + k.faqs_picked === 0} />
          <label className="flex items-center justify-between gap-3 rounded-xl bg-muted/50 px-3 py-2">
            <span className="min-w-0">
              <span className="block text-sm font-medium">{t("out.knowledge_files")}</span>
              <span className="block text-xs text-muted-fg">{t("out.knowledge_files_desc")}</span>
            </span>
            <Switch checked={s.knowledge_files} onChange={(v) => set({ knowledge_files: v })} label={t("out.knowledge_files")} />
          </label>
        </>
      ) : <Hint>{t("out.knowledge_empty")} <Link href="/app/knowledge" className="font-medium text-accent hover:underline">{t("out.knowledge_go")}</Link></Hint>}
    </Row>
  );
}

function FilesRow({ o, s, set, onPick }: RowProps & { onPick: () => void }) {
  const t = useT();
  const f = o.files;
  return (
    <Row icon={<HardDrive />} title={t("out.files")} on={s.files !== "off"}
      summary={reach(t, s.files, t("out.files_what"))}
      control={<LevelPicker value={s.files} onChange={(v) => set({ files: v })} />}>
      {f.total ? <ScopeLine all={s.files_scope === "all"} allLabel={t("out.files_all")} names={f.names} onPick={onPick}
        picked={t("out.files_picked", { n: f.picked })} empty={f.picked === 0} /> : <Hint>{t("out.files_empty")}</Hint>}
      <Hint>{t("out.files_visitor")}</Hint>
    </Row>
  );
}

function NetworkRow({ o, s, set, onPick }: RowProps & { onPick: () => void }) {
  const t = useT();
  const n = o.network;
  return (
    <Row icon={<Network />} title={t("out.network")} on={s.network !== "off"}
      summary={reach(t, s.network, t("out.network_what"))}
      control={<LevelPicker value={s.network} onChange={(v) => set({ network: v })} />}>
      {n.total ? <ScopeLine all={s.network_scope === "all"} allLabel={t("out.network_all")} names={n.names} onPick={onPick}
        picked={t("out.network_picked", { n: n.picked })} empty={n.picked === 0} /> : <Hint>{t("out.network_empty")}</Hint>}
      <Hint><Lock className="mr-1 inline h-3 w-3" />{t("out.network_private")}</Hint>
    </Row>
  );
}

function ScheduleRow({ o, s, set }: RowProps) {
  const t = useT(); const locale = useLocale(); const weekly = useWeeklyLabel();
  const hours = weekly(o.schedule.weekly) + (o.schedule.weekly.length && o.schedule.skip_holidays !== false ? ` · ${t("sched.no_holidays")}` : "");
  const byDay = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const sl of o.schedule.preview) {
      const d = sl.start.slice(0, 10);
      m.set(d, [...(m.get(d) ?? []), `${sl.start.slice(11, 16)}–${sl.end.slice(11, 16)}`]);
    }
    return [...m.entries()];
  }, [o.schedule.preview]);
  const dayLabel = (d: string) => new Intl.DateTimeFormat(locale === "en" ? "en-US" : "ko-KR", { month: "long", day: "numeric", weekday: "short", timeZone: "UTC" })
    .format(new Date(`${d}T00:00:00Z`));
  return (
    <Row icon={<CalendarDays />} title={t("out.schedule")} on={s.schedule !== "off"}
      summary={reach(t, s.schedule, t("out.schedule_what"))}
      control={<LevelPicker value={s.schedule} onChange={(v) => set({ schedule: v })} />}>
      {hours ? (
        <>
          <Chips><Chip>{hours}</Chip></Chips>
          <Hint><Lock className="mr-1 inline h-3 w-3" />{t("out.schedule_private")}</Hint>
          <div className="rounded-xl bg-muted/50 px-3 py-2.5">
            <div className="mb-1.5 text-xs font-medium text-muted-fg">{t("out.schedule_preview")}</div>
            {byDay.length ? (
              <ul className="space-y-1.5">
                {byDay.map(([d, slots]) => (
                  <li key={d} className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-3">
                    <span className="w-24 shrink-0 text-xs font-medium tabular-nums">{dayLabel(d)}</span>
                    <span className="flex flex-wrap gap-1">{slots.map((x) => <span key={x} className="rounded-md bg-card px-1.5 py-0.5 text-[11px] tabular-nums">{x}</span>)}</span>
                  </li>
                ))}
              </ul>
            ) : <Hint>{t("out.schedule_none")}</Hint>}
          </div>
          <Hint><Link href="/app/schedule?tab=hours" className="font-medium text-accent hover:underline">{t("out.schedule_go")}</Link></Hint>
        </>
      ) : <Hint>{t("out.schedule_no_hours")} <Link href="/app/schedule?tab=hours" className="font-medium text-accent hover:underline">{t("out.schedule_set")}</Link></Hint>}
    </Row>
  );
}

function MemoryRow({ o, s, set }: RowProps) {
  const t = useT();
  const on = s.memory || s.visitors;
  return (
    <Row icon={<Brain />} title={t("out.memory")} on={true}
      summary={on ? t("out.memory_on") : t("out.memory_off")}>
      <label className="flex items-center justify-between gap-3 rounded-xl bg-muted/50 px-3 py-2">
        <span className="min-w-0">
          <span className="block text-sm font-medium">{t("out.memory_public")}</span>
          <span className="block text-xs text-muted-fg">{t("out.memory_public_desc", { n: o.memory.shared_notes, f: o.memory.public_facts })}</span>
        </span>
        <Switch checked={s.memory} onChange={(v) => set({ memory: v })} label={t("out.memory_public")} />
      </label>
      <label className="flex items-center justify-between gap-3 rounded-xl bg-muted/50 px-3 py-2">
        <span className="min-w-0">
          <span className="block text-sm font-medium">{t("out.memory_visitors")}</span>
          <span className="block text-xs text-muted-fg">{t("out.memory_visitors_desc")}</span>
        </span>
        <Switch checked={s.visitors} onChange={(v) => set({ visitors: v })} label={t("out.memory_visitors")} />
      </label>
    </Row>
  );
}

/* ── 고르기 ──────────────────────────────────────────────────────────── */

function PickSheet({ kind, agentId, onClose, onSaved }: { kind: OutsiderKind; agentId: string; onClose: () => void; onSaved: (v: Outsider) => void }) {
  const t = useT(); const locale = useLocale();
  const [q, setQ] = useState("");
  const [typed, setTyped] = useState("");
  useEffect(() => { const h = window.setTimeout(() => setQ(typed.trim()), 250); return () => window.clearTimeout(h); }, [typed]);
  // 목록은 검색어 없이 한 번 받고, 검색은 화면에서 거른다 — 고른 것이 검색으로 사라져 보이면 안 된다.
  const list = useQuery({ queryKey: ["outsider-items", agentId, kind], queryFn: () => Agents.outsiderItems(agentId, kind) });
  const [scope, setScope] = useState<OutsiderScope | null>(null);
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  useEffect(() => {
    if (list.data && chosen === null) {
      setChosen(new Set(list.data.items.filter((i) => i.picked).map((i) => i.id)));
      setScope(list.data.scope);
    }
  }, [list.data, chosen]);
  const items = list.data?.items ?? [];
  const shown = q ? items.filter((i) => `${i.title} ${i.sub}`.toLowerCase().includes(q.toLowerCase())) : items;
  const save = useMutation({
    mutationFn: () => {
      const ids = [...(chosen ?? [])];
      const byId = new Map(items.map((i) => [i.id, i]));
      return Agents.putPicks(agentId, {
        kind, scope: scope ?? "picked",
        ids: ids.filter((id) => byId.get(id)?.type !== "faq"),
        faq_ids: ids.filter((id) => byId.get(id)?.type === "faq"),
      });
    },
    onSuccess: (v) => { toast.success(t("common.saved")); onSaved(v); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const toggle = (id: string, v: boolean) => setChosen((prev) => { const n = new Set(prev ?? []); if (v) n.add(id); else n.delete(id); return n; });
  const all = scope === "all";
  const count = chosen?.size ?? 0;

  return (
    <Sheet open onClose={onClose} side="right" title={t(`out.pick_${kind}`)}
      footer={
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-fg">{all ? t("out.pick_all_note") : t("out.pick_count", { n: count })}</span>
          <Button variant="outline" className="ml-auto" onClick={onClose}>{t("common.cancel")}</Button>
          <Button loading={save.isPending} disabled={chosen === null} onClick={() => save.mutate()}>{t("common.save")}</Button>
        </div>
      }>
      <div className="space-y-3">
        <Segmented<OutsiderScope> value={scope ?? "picked"} onChange={setScope} ariaLabel={t("out.pick")}
          options={[{ value: "picked", label: t("out.scope_picked") }, { value: "all", label: t(`out.scope_all_${kind}`) }]} />
        {all ? <Hint>{t(`out.scope_all_desc_${kind}`)}</Hint> : (
          <>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" />
              <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={t("common.search")} className="pl-9" />
            </div>
            {list.isLoading || chosen === null ? <Skeleton className="h-48" /> : !items.length ? (
              <Hint>{t(`out.pick_empty_${kind}`)}</Hint>
            ) : (
              <>
                <div className="flex gap-3 text-xs">
                  <button type="button" className="font-medium text-accent hover:underline" onClick={() => setChosen(new Set([...(chosen ?? []), ...shown.map((i) => i.id)]))}>{t("out.pick_all_shown")}</button>
                  <button type="button" className="text-muted-fg hover:underline" onClick={() => setChosen(new Set([...(chosen ?? [])].filter((id) => !shown.some((i) => i.id === id))))}>{t("out.pick_none_shown")}</button>
                </div>
                <ul className="divide-y divide-border rounded-xl border border-border">
                  {shown.map((i) => <PickRow key={i.id} item={i} checked={chosen.has(i.id)} onChange={(v) => toggle(i.id, v)} />)}
                </ul>
              </>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}

function PickRow({ item, checked, onChange }: { item: OutsiderItem; checked: boolean; onChange: (v: boolean) => void }) {
  const t = useT();
  return (
    <li className="px-3">
      <Checkbox checked={checked} onChange={onChange} className="w-full py-2"
        label={
          <span className="flex min-w-0 flex-col">
            <span className="flex items-center gap-1.5">
              {item.type === "faq" ? <span className="rounded bg-muted px-1 text-[10px] font-medium text-muted-fg">FAQ</span> : null}
              <span className="truncate">{item.title}</span>
            </span>
            {item.sub ? <span className="truncate text-xs text-muted-fg">{item.sub}</span> : null}
            {item.status && item.status !== "ready" ? <span className="text-[11px] text-warning">{t("out.pick_not_ready")}</span> : null}
          </span>
        } />
    </li>
  );
}

/* ── 비서가 볼 수 있는 메신저 대화 ───────────────────────────────────── */

/** 나와의 대화에서 허락한 메신저 대화(plan/55 §6-4). 허락한 것이 있을 때만 보인다. 거두면 그때부터 못 읽는다. */
function RoomsSection() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient(); const a = useAgent();
  const q = useQuery({ queryKey: ["room-grants", "agent", a.id], queryFn: () => RoomAccess.list({ agent_id: a.id }) });
  const revoke = useMutation({
    mutationFn: (id: string) => RoomAccess.revoke(id),
    onSuccess: () => { toast.success(t("wire.rooms_revoked")); qc.invalidateQueries({ queryKey: ["room-grants"] }); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const items = q.data?.items ?? [];
  if (!items.length) return null;
  return (
    <Card className="mt-4">
      <CardHeader title={<span className="inline-flex items-center gap-2"><MessagesSquare className="h-4 w-4" />{t("out.rooms")}</span>} description={t("out.rooms_desc")} />
      <CardBody className="pt-0">
        <ul className="divide-y divide-border">
          {items.map((g) => (
            <li key={g.id} className="flex items-center gap-2 py-2.5 text-sm">
              <span className="min-w-0 flex-1 truncate">
                {g.person.name}{g.person.handle ? <span className="text-muted-fg"> @{g.person.handle}</span> : null}
                <span className="text-xs text-muted-fg"> · {g.scope === "always" ? t("wire.rooms_always") : t("wire.rooms_here")}
                  {" · "}{g.last_read_at ? t("wire.rooms_read", { when: fmtRelative(g.last_read_at, locale) }) : t("wire.rooms_unread")}</span>
              </span>
              <Button size="sm" variant="outline" className="h-8 shrink-0" loading={revoke.isPending && revoke.variables === g.id}
                onClick={async () => {
                  if (await confirm({ title: t("wire.rooms_revoke_q", { name: g.person.name }), confirmLabel: t("msg.access_revoke"), danger: true })) revoke.mutate(g.id);
                }}>{t("msg.access_revoke")}</Button>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
