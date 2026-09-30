"use client";
import { Suspense, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Files } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { Page } from "@/components/owner/Shell";
import { PageHeader } from "@/components/ui/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { StorageBar } from "@/components/storage/StorageBar";
import { FilesBrowser, ViewToggle } from "@/components/agent/AgentFiles";
import { DriveImport } from "@/components/agent/DriveFiles";

/** [내 정보 → 파일] — 내 파일 전부 (plan/77). 공간을 돌보는 일은 [관리·설정 → 클라우드 관리] (plan/78). */
export function FilesView() {
  const t = useT(); const locale = useLocale();
  const [view, setView] = useState<"grid" | "list">("grid");
  const q = useQuery({ queryKey: ["storage"], queryFn: Files.storage });
  const u = q.data;
  return (
    <Page>
      <PageHeader title={t("files.title")} description={t("files.account_desc")} action={<div className="flex flex-wrap items-center gap-2"><Suspense fallback={null}><DriveImport /></Suspense><ViewToggle value={view} onChange={setView} /></div>} />
      {/* 공간을 돌보는 일은 [관리·설정 → 클라우드 관리]로 (plan/78) — 여기는 한 줄만. */}
      {q.isLoading ? <Skeleton className="mb-4 h-2" /> : q.error || !u ? (
        <p className="mb-4 text-sm text-danger">{friendlyError(q.error, locale)}</p>
      ) : (
        <div className="mb-5 space-y-2">
          {u.ratio >= 1 ? (
            <p role="alert" className="rounded-xl bg-danger/10 px-3 py-2 text-sm text-danger">{t("storage.full_banner")}</p>
          ) : u.ratio >= 0.9 ? (
            <p role="status" className="rounded-xl bg-warning/10 px-3 py-2 text-sm text-warning">{t("storage.warn_banner")}</p>
          ) : null}
          <StorageBar usage={u} compact />
        </div>
      )}
      <Suspense fallback={<Skeleton className="h-48" />}><FilesBrowser view={view} /></Suspense>
    </Page>
  );
}
