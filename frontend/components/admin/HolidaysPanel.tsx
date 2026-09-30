"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarDays, CheckCircle2, ExternalLink, RefreshCw, ShieldCheck, XCircle } from "@/components/icons";
import { Admin, type AdminHolidays } from "@/lib/api";
import { forgetSpecialDays } from "@/lib/specialDays";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtDateTime, fmtSecretTail } from "@/lib/format";
import { Section } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { SwitchRow } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

const KINDS = ["holiday", "festival", "solar_term", "anniversary"] as const;
const CHECK_CODES = ["ok", "missing", "invalid_key", "not_approved", "quota", "ip_blocked", "expired", "unreachable"];

/** 관리자 [연결 → 공휴일] (plan/60).
 *
 *  공휴일·대체공휴일·명절·절기는 내장 계산으로 늘 나온다. 한국천문연구원 특일 정보를 이으면 받아 온 해가
 *  내장 계산을 대신한다 — 임시공휴일과 기념일 전부가 정부 발표대로. 해마다 어디서 온 자료인지, 두 출처가
 *  쉬는 날을 다르게 본 날이 있는지 여기서 본다. */
export function HolidaysPanel() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "holidays"], queryFn: Admin.holidays });
  const [key, setKey] = useState("");
  const [result, setResult] = useState<{ ok: boolean; code: string; detail?: string } | null>(null);
  const put = (r: AdminHolidays) => { qc.setQueryData(["admin", "holidays"], r); };
  const save = useMutation({
    mutationFn: (b: Parameters<typeof Admin.saveHolidays>[0]) => Admin.saveHolidays(b),
    onSuccess: (r, b) => { put(r); if (b.key) { setKey(""); setResult(null); } toast.success(t("common.saved")); if (b.enabled) later(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const check = useMutation({ mutationFn: Admin.checkHolidays, onSuccess: setResult, onError: (e) => toast.error(friendlyError(e, locale)) });
  // 받아 오기는 작업으로 돈다(다섯 가지 × 열두 달 × 두 해). 잠시 뒤 다시 읽는다.
  const later = () => {
    for (const ms of [4000, 12000, 30000]) setTimeout(() => {
      qc.invalidateQueries({ queryKey: ["admin", "holidays"] });
      // 이 기기의 달력도 새로 — 다른 사람들은 버전이 바뀐 것을 한 시간 안에 알아챈다.
      forgetSpecialDays(qc);
    }, ms);
  };
  const sync = useMutation({
    mutationFn: Admin.syncHolidays,
    onSuccess: () => { toast.success(t("hol.sync_queued")); later(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  if (q.isLoading || !q.data) return <Skeleton className="h-96" />;
  const d = q.data;
  const official = d.enabled && d.key.has_value;
  return (
    <div className="space-y-4">
      <Section title={<span className="inline-flex items-center gap-2"><CalendarDays className="h-5 w-5 text-danger" />{t("hol.title")}</span>}
        description={t("hol.about")}
        action={<Badge tone={official ? "success" : "neutral"}>{official ? t("hol.st_official") : t("hol.st_builtin")}</Badge>}>
        <SwitchRow title={t("hol.enable")} description={d.key.has_value ? t("hol.enable_desc") : t("hol.enable_needs_key")}
          checked={d.enabled} disabled={save.isPending || (!d.enabled && !d.key.has_value)} onChange={(v) => save.mutate({ enabled: v })} />
        {d.last_error ? (
          <p className="mt-2 flex items-start gap-2 rounded-xl bg-danger/10 px-3 py-2 text-sm text-danger">
            <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{t("hol.last_error", { when: fmtDateTime(d.last_error.at) })} {t(`hol.chk_${CHECK_CODES.includes(d.last_error.code) ? d.last_error.code : "other"}`)}</span>
          </p>
        ) : null}
      </Section>

      <Section title={t("hol.years_title")} description={t("hol.years_desc")}
        action={d.key.has_value ? <Button size="sm" variant="outline" loading={sync.isPending} onClick={() => sync.mutate()}><RefreshCw className="h-4 w-4" />{t("hol.sync_now")}</Button> : null}>
        <div className="space-y-3">
          {d.years.map((y) => (
            <div key={y.year} className="rounded-xl border border-border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold tabular-nums">{t("hol.year", { y: y.year })}</span>
                <span className="text-sm text-muted-fg">{t("hol.off_days", { n: y.off_days })}</span>
                {y.complete ? <Badge tone="success">{t("hol.complete")}</Badge> : null}
                <span className="ml-auto text-xs text-muted-fg">
                  {y.checked_at ? t("hol.checked", { when: fmtDateTime(y.checked_at) }) : t("hol.not_synced")}
                  {y.changed_at ? ` · ${t("hol.changed", { when: fmtDateTime(y.changed_at) })}` : ""}
                </span>
              </div>
              <div className="mt-2 grid gap-1.5 sm:grid-cols-4">
                {KINDS.map((k) => (
                  <div key={k} className="flex items-center justify-between gap-2 rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs">
                    <span>{t(`hol.kind_${k}`)} <span className="tabular-nums text-muted-fg">{y.counts[k]}</span></span>
                    <Badge tone={y.sources[k] === "kasi" ? "success" : "neutral"}>{y.sources[k] === "kasi" ? t("hol.src_kasi") : t("hol.src_builtin")}</Badge>
                  </div>
                ))}
              </div>
              {y.only_official.length || y.only_builtin.length ? (
                <div className="mt-2 space-y-1 text-xs">
                  {y.only_official.length ? <p><span className="font-medium">{t("hol.only_official")}</span> {y.only_official.map((x) => `${x.date.slice(5)} ${x.name}`).join(", ")}</p> : null}
                  {y.only_builtin.length ? <p className="text-warning"><span className="font-medium">{t("hol.only_builtin")}</span> {y.only_builtin.map((x) => `${x.date.slice(5)} ${x.name}`).join(", ")}</p> : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-fg">{t("hol.builtin_version", { v: d.builtin })}</p>
      </Section>

      <Section title={t("hol.key_title")} description={t("hol.key_desc")}
        action={<a href={d.dataset_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm text-accent hover:underline">{t("hol.portal")}<ExternalLink className="h-3.5 w-3.5" /></a>}>
        <Field label={t("hol.key")} htmlFor="hol-key"
          hint={d.key.has_value ? <span className="inline-flex flex-wrap items-center gap-2"><span className="text-success">{t("adm.secret_set")} ({fmtSecretTail(d.key.masked)})</span>
            <button type="button" className="text-xs text-danger hover:underline" onClick={() => save.mutate({ clear_key: true })}>{t("conn.clear")}</button></span> : t("hol.key_hint")}>
          <Input id="hol-key" type="password" autoComplete="off" spellCheck={false} value={key} placeholder={d.key.has_value ? "••••••••" : undefined}
            onChange={(e) => setKey(e.target.value)} />
        </Field>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button variant={key.trim() ? "accent" : "outline"} disabled={!key.trim()} loading={save.isPending} onClick={() => save.mutate({ key: key.trim() })}>{t("common.save")}</Button>
          <Button variant="outline" disabled={!!key.trim() || !d.key.has_value} loading={check.isPending} onClick={() => check.mutate()}><ShieldCheck className="h-4 w-4" />{t("conn.check")}</Button>
          {key.trim() ? <span className="text-xs text-warning">{t("conn.save_first")}</span> : null}
        </div>
        {result ? (
          <div className={`mt-3 flex items-start gap-2 rounded-xl border px-3 py-2 text-sm ${result.ok ? "border-success/40 bg-success/10 text-success" : "border-danger/40 bg-danger/10 text-danger"}`}>
            {result.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
            <div className="min-w-0">
              <div>{t(`hol.chk_${CHECK_CODES.includes(result.code) ? result.code : "other"}`)}</div>
              {!result.ok && result.detail ? <div className="mt-0.5 break-words text-xs opacity-80">{result.detail}</div> : null}
            </div>
          </div>
        ) : null}
      </Section>

      <Section title={t("conn.guide_title")}>
        <ol className="list-decimal space-y-1.5 pl-5 text-sm">
          {["hol.g1", "hol.g2", "hol.g3", "hol.g4"].map((k) => <li key={k}>{t(k)}</li>)}
        </ol>
      </Section>
    </div>
  );
}
