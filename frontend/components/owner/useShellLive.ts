"use client";
import { useCallback, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useT } from "@/lib/i18n";
import { checkFreshness, watchFreshness } from "@/lib/freshness";
import { onLive, startLive } from "@/lib/live";
import { applyLink, type LinkStatus } from "@/components/network/Connection";

/** 계정의 실시간 흐름을 이 탭에서 한 번 연다 — 웹의 틀과 PC 앱 안의 틀이 함께 쓴다.
 *
 *  `inboxToasts` 가 거짓이면 인박스 토스트를 띄우지 않는다. PC 앱은 같은 일을 OS 알림으로 알리므로,
 *  둘 다 울리면 한 일에 두 번 울린다 (plan/62 §4). */
export function useShellLive({ inboxToasts }: { inboxToasts: boolean }) {
  const t = useT();
  const qc = useQueryClient();
  // 새 화면이 올라왔다는 것만 한 줄로 말하고, 새로고침은 누를 때 한다. 쓰다 만 글이
  // 사라지는 것이 낡은 화면보다 나쁘다.
  const tellStale = useCallback(() => {
    toast(t("app.updated"), { duration: Infinity, action: { label: t("app.reload"), onClick: () => window.location.reload() } });
  }, [t]);
  useEffect(() => {
    // The poll is the floor, not the mechanism: the stream moves the badge when the thing
    // happens, and the refetch keeps the number honest if a message was missed.
    const stopStream = startLive();
    const offInbox = onLive("inbox", (data) => {
      qc.invalidateQueries({ queryKey: ["inbox"] });
      const p = (data ?? {}) as { kind?: string; title_payload?: Record<string, string> };
      const tp = p.title_payload ?? {};
      const who = tp.actor_name || tp.visitor_name || tp.target_agent_name || tp.initiator_agent_name || "";
      if (p.kind?.startsWith("relay_")) qc.invalidateQueries({ queryKey: ["relays"] });
      if (inboxToasts) toast(t(`inbox.kind_${p.kind ?? "message"}`), { description: who || undefined });
    });
    // A message written into a conversation by the server (not by a turn): the lists move now.
    const offMessage = onLive("message", (data) => {
      const d = (data ?? {}) as { agent_id?: string };
      if (d.agent_id) qc.invalidateQueries({ queryKey: ["conversations", d.agent_id] });
    });
    // 대화에서 답이 시작·끝났다, 대화가 생기고 바뀌고 지워졌다(plan/69) — 어느 화면에서 했든 대화 목록이 따라온다.
    // 열려 있는 대화 자체는 OwnerChat 이 같은 소식을 듣고 맞춘다.
    const offTurn = onLive("turn", (data) => {
      const d = (data ?? {}) as { agent_id?: string };
      if (d.agent_id) qc.invalidateQueries({ queryKey: ["conversations", d.agent_id] });
    });
    const offConv = onLive("conversation", (data) => {
      const d = (data ?? {}) as { agent_id?: string };
      if (d.agent_id) qc.invalidateQueries({ queryKey: ["conversations", d.agent_id] });
    });
    // 누군가와의 사이가 바뀌었다 — 여기서 바꿨든, 다른 탭·앱에서든, 상대가 했든(plan/69).
    // 그 사람을 보여 주는 모든 단추·표시가 같은 자리를 읽으므로 한 번 고치면 전부 맞는다.
    const offLink = onLive("link", (data) => {
      const d = (data ?? {}) as { user_id?: string; status?: LinkStatus };
      if (d.user_id && d.status) applyLink(qc, d.user_id, d.status);
    });
    // 바깥 연결(Google·카카오·메일함)이 가져오기를 마쳤거나 실패했다, 이어졌거나 끊겼다(plan/76) —
    // 그 자료를 보여 주는 화면이 지금 다시 읽는다. 예전에는 새로 고칠 때까지 "마지막 동기화: –" 로 남았다.
    const offConnection = onLive("connection", (data) => {
      const d = (data ?? {}) as { provider?: string; part?: string };
      qc.invalidateQueries({ queryKey: ["integrations"] });
      qc.invalidateQueries({ queryKey: ["schedule"] });
      if (d.provider === "imap") qc.invalidateQueries({ queryKey: ["mail"] });
      if (d.provider === "google" && d.part !== "calendar") {
        qc.invalidateQueries({ queryKey: ["network"] });
        qc.invalidateQueries({ queryKey: ["drive"] });
      }
    });
    // After a reconnect, whatever was missed is fetched rather than guessed.
    const offOpen = onLive("$open", () => {
      qc.invalidateQueries({ queryKey: ["inbox"] });
      qc.invalidateQueries({ queryKey: ["integrations"] });
      qc.invalidateQueries({ queryKey: ["schedule"] });
      // 끊긴 사이에 바뀐 인맥도 다시 받는다.
      qc.invalidateQueries({ queryKey: ["network"] });
      // 스트림이 다시 붙는 순간은 배포 직후이기도 하다(배포는 백엔드를 재시작하고,
      // 그때 열려 있던 스트림이 전부 끊긴다). 이 탭이 옛 번들을 물고 있으면 여기서
      // 알아챈다 — 드문 일이라 5분 간격을 건너뛰고 그 자리에서 묻는다.
      void checkFreshness(tellStale, true);
    });
    const offFresh = watchFreshness(tellStale);
    return () => { offInbox(); offMessage(); offTurn(); offConv(); offLink(); offConnection(); offOpen(); offFresh(); stopStream(); };
  }, [qc, t, tellStale, inboxToasts]);
}
