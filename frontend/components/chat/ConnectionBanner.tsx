"use client";
import { WifiOff, RefreshCw } from "@/components/icons";
import { useT } from "@/lib/i18n";
import type { ConnState } from "@/stores/chat";

export function ConnectionBanner({ online, conn }: { online: boolean; conn: ConnState }) {
  const t = useT();
  if (online && conn !== "reconnecting") return null;
  return (
    <div role="status" className="flex items-center justify-center gap-2 bg-warning/15 px-3 py-1.5 text-xs text-warning">
      {!online ? <><WifiOff className="h-3.5 w-3.5" />{t("chat.offline")}</> : <><RefreshCw className="h-3.5 w-3.5 animate-spin" />{t("chat.reconnecting")}</>}
    </div>
  );
}
