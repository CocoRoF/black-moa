"use client";
import { useEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { HardDrive, Upload } from "@/components/icons";
import { Drive } from "@/lib/api";
import { connectProvider } from "@/lib/connect";
import { confirm } from "@/lib/confirm";
import { pickDriveFiles } from "@/lib/drivePicker";
import { codeMessage, friendlyError } from "@/lib/errors";
import { useLocale, useT } from "@/lib/i18n";
import { Button } from "@/components/ui/button";

/* Google Drive 와 [파일] (plan/75).

   가져오기는 Google 의 파일 선택 창에서 고른 파일을 [내 정보 → 파일]로, 저장은 [파일]의 파일을 내 Drive 의
   "Memora" 폴더로. 이 앱은 고른 파일과 스스로 만든 파일만 열 수 있다(drive.file). 아직 Drive 를 잇지 않았으면
   먼저 잇고 이 화면으로 돌아온다. */

const MAX = 10;

function useDriveStatus() {
  return useQuery({ queryKey: ["drive"], queryFn: Drive.status, staleTime: 60_000 });
}

async function askToConnect(t: (k: string) => string, next: string): Promise<void> {
  if (await confirm({ title: t("drive.connect_q"), description: t("drive.connect_desc"), confirmLabel: t("drive.connect_ok") })) {
    await connectProvider("google", ["drive"], next);
  }
}

/** [Google Drive에서 가져오기] — [내 정보 → 파일]로 (plan/77). 파일은 계정의 것이라 어느 비서에게 넣을지 묻지 않는다.
 *  비서는 나와의 대화에서 내 파일을 모두 보고, 외부인에게 쓸 파일은 비서마다 [지식] 탭에서 잇는다. */
export function DriveImport() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const path = usePathname(); const sp = useSearchParams();
  const st = useDriveStatus();

  // Google 에서 돌아왔다 — 한 번만 알린다.
  const told = useRef(false);
  useEffect(() => {
    if (told.current || sp.get("connected") !== "google") return;
    told.current = true;
    if ((sp.get("partial") ?? "").split(",").includes("drive")) toast.warning(t("drive.not_granted"));
    else toast.success(t("drive.connected"));
  }, [sp, t]);

  const run = useMutation({
    mutationFn: async () => {
      const k = await Drive.picker();
      const picked = await pickDriveFiles({ token: k.access_token, apiKey: k.api_key, appId: k.app_id, locale, title: t("drive.picker_title"), max: MAX });
      if (!picked?.length) return null;
      return Drive.import(picked.map((p) => p.id));
    },
    onSuccess: (out) => {
      if (!out) return;
      qc.invalidateQueries({ queryKey: ["files"] });
      qc.invalidateQueries({ queryKey: ["storage"] });
      const n = out.imported.length; const bad = out.failed.length;
      if (n && !bad) toast.success(t("drive.imported", { n }));
      else if (n) toast.warning(t("drive.imported_some", { n, bad }), { description: codeMessage(out.failed[0].code, locale) });
      else toast.error(codeMessage(out.failed[0]?.code ?? "drive_failed", locale));
    },
    onError: (e) => toast.error(e instanceof Error && e.message === "drive_picker_load" ? codeMessage("drive_picker_load", locale) : friendlyError(e, locale)),
  });

  const s = st.data;
  if (!s?.available || !s.picker) return null;
  return (
    <Button variant="outline" loading={run.isPending}
            onClick={() => (s.connected ? run.mutate() : void askToConnect(t, path))}>
      <HardDrive className="h-4 w-4" />{t("drive.import")}
    </Button>
  );
}

/** 파일 상세의 [Google Drive에 저장]. */
export function DriveSave({ fileId }: { fileId: string }) {
  const t = useT(); const locale = useLocale();
  const path = usePathname();
  const st = useDriveStatus();
  const save = useMutation({
    mutationFn: () => Drive.save(fileId),
    onSuccess: (r) => toast.success(t("drive.saved"), r.link ? {
      action: { label: t("drive.open"), onClick: () => window.open(r.link, "_blank", "noopener,noreferrer") },
    } : undefined),
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const s = st.data;
  if (!s?.available) return null;
  return (
    <Button variant="outline" size="sm" loading={save.isPending}
            onClick={() => (s.connected ? save.mutate() : void askToConnect(t, path))}>
      <Upload className="h-4 w-4" />{t("drive.save")}
    </Button>
  );
}
