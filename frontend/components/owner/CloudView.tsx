"use client";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArchiveRestore, ChevronRight, HardDrive, Trash2 } from "@/components/icons";
import { Files, type CloudOverview, type FileKind } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtDate, fmtNumber } from "@/lib/format";
import { fmtBytes } from "@/lib/upload";
import { confirm } from "@/lib/confirm";
import { Page } from "@/components/owner/Shell";
import { Button, buttonLook } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Section } from "@/components/ui/card";
import { PageHeader, Stat } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { StorageBar } from "@/components/storage/StorageBar";
import { KindIcon, kindLabel } from "@/components/agent/AgentFiles";

/** [관리·설정 → 클라우드 관리] (plan/78) — black-moa 의 파일 시스템을 한 장에서 본다.
 *
 *  [내 정보 → 파일]은 모은 것을 쓰는 곳이고, 여기는 그것이 쓰는 공간을 돌보는 곳이다: 어디에 얼마나 쓰였나,
 *  어디서 들어왔나, 무엇이 큰가, 지운 것은 언제 사라지나(그 전에는 되살린다), Drive 는 이어져 있나. */

const SOURCE_KEY: Record<string, string> = { chat: "files.src_chat", visitor: "files.src_public", drive: "files.src_drive",
  messenger: "files.src_messenger", manual: "files.src_manual" };

function Rows({ rows, total }: { rows: { key: string; label: React.ReactNode; files: number; bytes: number }[]; total: number }) {
  const t = useT();
  if (!rows.length) return <p className="text-sm text-muted-fg">{t("cloud.nothing_yet")}</p>;
  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li key={r.key} className="space-y-1.5">
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="flex min-w-0 items-center gap-2">{r.label}</span>
            <span className="shrink-0 tabular-nums text-muted-fg">{t("storage.files_n", { n: fmtNumber(r.files) })} · <b className="font-medium text-fg">{fmtBytes(r.bytes)}</b></span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-accent" style={{ width: `${total ? Math.max(2, (r.bytes / total) * 100) : 0}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function CloudView() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["cloud"], queryFn: Files.cloud });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["cloud"] }); qc.invalidateQueries({ queryKey: ["storage"] }); qc.invalidateQueries({ queryKey: ["files"] }); };
  const remove = useMutation({
    mutationFn: (id: string) => Files.remove(id),
    onSuccess: () => { toast.success(t("files.deleted")); refresh(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const restore = useMutation({
    mutationFn: (id: string) => Files.restore(id),
    onSuccess: () => { toast.success(t("cloud.restored")); refresh(); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const c: CloudOverview | undefined = q.data;
  return (
    <Page>
      <PageHeader title={t("cloud.title")} description={t("cloud.desc")}
        action={<Link href="/app/files" className={buttonLook("outline", "sm")}>{t("cloud.go_files")}<ChevronRight className="h-4 w-4" /></Link>} />
      {q.isLoading ? <Skeleton className="h-96" /> : q.error || !c ? <EmptyState title={friendlyError(q.error, locale)} /> : (
        <div className="space-y-4">
          <Section title={t("storage.title")} description={t("storage.plan", { plan: c.usage.plan })}
            action={<Link href="/app/credits" className={buttonLook("outline", "sm")}>{t("storage.more")}</Link>}>
            {c.usage.ratio >= 1 ? (
              <p role="alert" className="mb-3 rounded-xl bg-danger/10 px-4 py-3 text-sm text-danger">{t("storage.full_banner")}</p>
            ) : c.usage.ratio >= 0.9 ? (
              <p role="status" className="mb-3 rounded-xl bg-warning/10 px-4 py-3 text-sm text-warning">{t("storage.warn_banner")}</p>
            ) : null}
            <StorageBar usage={c.usage} segmentHref={(s) => s.kind === "knowledge" ? "/app/knowledge" : s.kind === "agent" && s.agent_id ? `/app/files?agent=${s.agent_id}` : s.kind === "files" ? "/app/files" : null} />
          </Section>

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label={t("cloud.stat_files")} value={fmtNumber(c.totals.files)} hint={t("cloud.stat_files_hint")} />
            <Stat label={t("cloud.stat_docs")} value={fmtNumber(c.totals.documents)} hint={t("cloud.stat_docs_hint")} />
            <Stat label={t("cloud.stat_trash")} value={fmtNumber(c.totals.trash_files)} hint={t("cloud.stat_trash_hint", { size: fmtBytes(c.totals.trash_bytes), days: c.keep_days })} />
            <Stat label={t("cloud.stat_unreadable")} value={fmtNumber(c.totals.unreadable)} hint={t("files.stat_unreadable_hint")} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Section title={t("cloud.by_source")} description={t("cloud.by_source_desc")}>
              <Rows total={c.by_source.reduce((n, r) => n + r.bytes, 0)}
                rows={c.by_source.map((r) => ({ key: r.source, files: r.files, bytes: r.bytes,
                  label: <span className="truncate">{SOURCE_KEY[r.source] ? t(SOURCE_KEY[r.source]) : r.source}</span> }))} />
            </Section>
            <Section title={t("cloud.by_kind")} description={t("cloud.by_kind_desc")}>
              <Rows total={c.by_kind.reduce((n, r) => n + r.bytes, 0)}
                rows={c.by_kind.map((r) => ({ key: r.kind, files: r.files, bytes: r.bytes,
                  label: <><KindIcon kind={r.kind as FileKind} className="h-4 w-4 shrink-0 text-muted-fg" /><span className="truncate">{kindLabel(t, r.kind as FileKind)}</span></> }))} />
            </Section>
          </div>

          <Section title={t("cloud.largest")} description={t("cloud.largest_desc")}>
            {c.largest.length ? (
              <ul className="divide-y divide-border">
                {c.largest.map((f) => (
                  <li key={f.id} className="flex items-center gap-3 py-2.5">
                    <KindIcon kind={f.kind} className="h-5 w-5 shrink-0 text-accent" />
                    <div className="min-w-0 flex-1">
                      <Link href={`/app/files?open=${f.id}`} className="block truncate text-sm font-medium hover:underline">{f.filename}</Link>
                      <div className="truncate text-xs text-muted-fg">{f.agent_name || t("files.no_agent")} · {fmtDate(f.created_at)}</div>
                    </div>
                    <span className="shrink-0 text-sm tabular-nums">{fmtBytes(f.size)}</span>
                    <Button variant="ghost" size="icon-sm" aria-label={t("common.delete")} loading={remove.isPending && remove.variables === f.id}
                      onClick={async () => {
                        if (await confirm({ title: t("files.delete_q"), description: t("cloud.delete_desc", { days: c.keep_days }), danger: true, confirmLabel: t("common.delete") })) remove.mutate(f.id);
                      }}><Trash2 className="h-4 w-4" /></Button>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-muted-fg">{t("cloud.nothing_yet")}</p>}
          </Section>

          <div className="grid gap-4 lg:grid-cols-3">
            <Section className="lg:col-span-2" title={t("cloud.trash")} description={t("cloud.trash_desc", { days: c.keep_days })}>
              {c.trash.length ? (
                <ul className="divide-y divide-border">
                  {c.trash.map((f) => (
                    <li key={f.id} className="flex items-center gap-3 py-2.5">
                      <KindIcon kind={f.kind} className="h-5 w-5 shrink-0 text-muted-fg" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm">{f.filename}</div>
                        <div className="truncate text-xs text-muted-fg">{t("cloud.purge_on", { date: fmtDate(f.purge_at) })} · {fmtBytes(f.size)}</div>
                      </div>
                      <Button variant="outline" size="sm" loading={restore.isPending && restore.variables === f.id} onClick={() => restore.mutate(f.id)}>
                        <ArchiveRestore className="h-4 w-4" />{t("cloud.restore")}
                      </Button>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-sm text-muted-fg">{t("cloud.trash_empty")}</p>}
            </Section>
            <Card>
              <CardHeader title={<span className="inline-flex items-center gap-2"><HardDrive className="h-4 w-4" />Google Drive</span>} />
              <CardBody className="space-y-3 text-sm">
                <p className="text-muted-fg">
                  {!c.drive.available ? t("cloud.drive_off") : c.drive.connected
                    ? t("cloud.drive_on", { n: fmtNumber(c.by_source.find((r) => r.source === "drive")?.files ?? 0) })
                    : t("cloud.drive_not_connected")}
                </p>
                {c.drive.available ? (
                  <Link href={c.drive.connected ? "/app/files" : "/app/account#connections"} className={buttonLook("outline", "sm")}>
                    {t(c.drive.connected ? "cloud.drive_import" : "cloud.drive_connect")}
                  </Link>
                ) : null}
              </CardBody>
            </Card>
          </div>
        </div>
      )}
    </Page>
  );
}
