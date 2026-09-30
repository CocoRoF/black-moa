"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, ExternalLink, MonitorDown, RefreshCw, ShieldCheck, XCircle } from "@/components/icons";
import { Admin, type AdminDownloads } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtBytes, fmtDate, fmtDateTime, fmtSecretTail } from "@/lib/format";
import { Page } from "@/components/owner/Shell";
import { Section } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { SwitchRow } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/misc";

/** 관리자 [다운로드 센터] (plan/64).
 *
 *  앱의 GitHub 릴리스를 어디서 읽어 오는지, 읽어 와 옮겨 둔 설치본이 어떤 상태인지. 저장소가 비공개라 읽기
 *  권한이 있는 토큰이 있어야 한다. 새 릴리스가 나가면 10분 안에 저절로 옮겨지고, [지금 읽어 오기] 로 당길 수 있다. */
export function DownloadsAdminPage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "downloads"], queryFn: Admin.downloads, refetchInterval: 15_000 });
  const [token, setToken] = useState("");
  const [repo, setRepo] = useState<string | null>(null);
  const [prefix, setPrefix] = useState<string | null>(null);
  const [result, setResult] = useState<{ ok: boolean; message?: string; private?: boolean; releases?: number } | null>(null);
  const put = (r: AdminDownloads) => { qc.setQueryData(["admin", "downloads"], r); };
  const save = useMutation({
    mutationFn: (b: Parameters<typeof Admin.saveDownloads>[0]) => Admin.saveDownloads(b),
    onSuccess: (r, b) => { put(r); if (b.token) setToken(""); setRepo(null); setPrefix(null); setResult(null); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const check = useMutation({ mutationFn: Admin.checkDownloads, onSuccess: setResult, onError: (e) => toast.error(friendlyError(e, locale)) });
  const sync = useMutation({
    mutationFn: Admin.syncDownloads,
    onSuccess: () => { toast.success(t("dla.sync_queued")); for (const ms of [3000, 10000]) setTimeout(() => qc.invalidateQueries({ queryKey: ["admin", "downloads"] }), ms); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  if (q.isLoading || !q.data) return <Page><Skeleton className="h-96" /></Page>;
  const d = q.data;
  const st = d.status ?? {};
  const edited = (repo !== null && repo !== d.repo) || (prefix !== null && prefix !== d.tag_prefix);
  return (
    <Page>
      <PageHeader title={t("adm.downloads")} description={t("dla.desc")}
        action={<a href="/app/downloads" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm text-accent hover:underline">{t("dla.open_center")}<ExternalLink className="h-3.5 w-3.5" /></a>} />
      <div className="space-y-4">
        <Section title={<span className="inline-flex items-center gap-2"><MonitorDown className="h-5 w-5 text-accent" />{t("dla.source")}</span>}
          description={t("dla.source_desc")}
          action={<Button size="sm" variant="outline" loading={sync.isPending} onClick={() => sync.mutate()}><RefreshCw className="h-4 w-4" />{t("dla.sync_now")}</Button>}>
          <SwitchRow title={t("dla.enable")} description={t("dla.enable_desc")} checked={d.enabled} disabled={save.isPending}
            onChange={(v) => save.mutate({ enabled: v })} />
          <p className="mt-2 flex items-center gap-2 text-sm">
            <Badge tone={d.ci.has_key ? "success" : "neutral"}>{d.ci.has_key ? t("dla.ci_on") : t("dla.ci_off")}</Badge>
            <span className="text-muted-fg">{d.ci.session ? t("dla.ci_session") : d.ci.has_key ? t("dla.ci_on_desc") : t("dla.ci_off_desc")}</span>
          </p>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <Field label={t("dla.repo")} htmlFor="dl-repo" hint={t("dla.repo_hint")}>
              <Input id="dl-repo" value={repo ?? d.repo} spellCheck={false} onChange={(e) => setRepo(e.target.value)} />
            </Field>
            <Field label={t("dla.prefix")} htmlFor="dl-prefix" hint={t("dla.prefix_hint")}>
              <Input id="dl-prefix" value={prefix ?? d.tag_prefix} spellCheck={false} onChange={(e) => setPrefix(e.target.value)} />
            </Field>
            <Field label={t("dla.token")} htmlFor="dl-token"
              hint={d.token.has_value ? <span className="inline-flex flex-wrap items-center gap-2"><span className="text-success">{t("adm.secret_set")} ({fmtSecretTail(d.token.masked)})</span>
                <button type="button" className="text-xs text-danger hover:underline" onClick={() => save.mutate({ clear_token: true })}>{t("conn.clear")}</button></span> : t("dla.token_hint")}>
              <Input id="dl-token" type="password" autoComplete="off" spellCheck={false} value={token} placeholder={d.token.has_value ? "••••••••" : undefined}
                onChange={(e) => setToken(e.target.value)} />
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button variant={token.trim() || edited ? "accent" : "outline"} disabled={!token.trim() && !edited} loading={save.isPending}
              onClick={() => save.mutate({ ...(token.trim() ? { token: token.trim() } : {}), ...(repo !== null ? { repo: repo.trim() } : {}), ...(prefix !== null ? { tag_prefix: prefix.trim() } : {}) })}>{t("common.save")}</Button>
            <Button variant="outline" disabled={!!token.trim() || edited} loading={check.isPending} onClick={() => check.mutate()}><ShieldCheck className="h-4 w-4" />{t("conn.check")}</Button>
            {token.trim() || edited ? <span className="text-xs text-warning">{t("conn.save_first")}</span> : null}
          </div>
          {result ? (
            <div className={`mt-3 flex items-start gap-2 rounded-xl border px-3 py-2 text-sm ${result.ok ? "border-success/40 bg-success/10 text-success" : "border-danger/40 bg-danger/10 text-danger"}`}>
              {result.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
              <span>{result.ok ? t("dla.check_ok", { n: result.releases ?? 0 }) : result.message}</span>
            </div>
          ) : null}
          <p className={`mt-3 text-xs ${st.ok === false ? "text-danger" : "text-muted-fg"}`}>
            {st.at ? (st.ok === false ? t("dla.last_error", { when: fmtDateTime(st.at), msg: st.error ?? "" }) : t("dla.last_ok", { when: fmtDateTime(st.at), n: st.releases ?? 0 })) : t("dla.never")}
          </p>
        </Section>

        <Section title={t("dla.files")} description={t("dla.files_desc")}>
          {!d.releases.length ? <p className="text-sm text-muted-fg">{t("dla.no_releases")}</p> : (
            <div className="space-y-3">
              {d.releases.map((r) => (
                <div key={r.tag} className="rounded-xl border border-border p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{r.version}</span>
                    <span className="text-xs text-muted-fg">{r.tag}{r.published_at ? ` · ${fmtDate(r.published_at)}` : ""}</span>
                    {r.prerelease ? <Badge tone="warning">{t("dla.prerelease")}</Badge> : null}
                  </div>
                  <ul className="divide-y divide-border text-sm">
                    {r.files.map((f) => (
                      <li key={f.name} className="flex flex-wrap items-center gap-2 py-1.5">
                        <span className="min-w-0 flex-1 truncate font-mono text-xs">{f.name}</span>
                        <span className="text-xs tabular-nums text-muted-fg">{fmtBytes(f.size)}</span>
                        <span className="w-20 text-right text-xs tabular-nums text-muted-fg">{t("dla.downloads_n", { n: f.downloads })}</span>
                        <Badge tone={f.status === "ready" ? "success" : f.status === "failed" ? "danger" : "neutral"}>{t(`dla.st_${f.status}`)}</Badge>
                        {f.status === "failed" && f.error ? <span className="w-full text-xs text-danger">{f.error}</span> : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </Section>
      </div>
    </Page>
  );
}
