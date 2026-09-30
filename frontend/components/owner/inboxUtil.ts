import type { InboxItem } from "@/lib/api";
import type { TFn } from "@/lib/i18n";

export function inboxTitle(it: InboxItem, t: TFn) {
  const who = it.payload?.visitor_name || t("inbox.visitor");
  switch (it.kind) {
    case "message": return t("inbox.title_message", { who });
    case "meeting_request": return t("inbox.title_meeting", { who });
    case "contact_share": return t("inbox.title_contact", { who });
    case "question_unanswered": return t("inbox.title_question");
    // Community items name the person and the thread, not a visitor and a secretary.
    case "community_comment": return t("inbox.title_c_comment", { who: it.payload?.actor_name || "", post: it.payload?.post_title || "" });
    case "community_reply": return t("inbox.title_c_reply", { who: it.payload?.actor_name || "" });
    // Secretary-to-secretary exchanges (plan/38): the other secretary and its owner, never a "visitor".
    case "relay_result": return t("inbox.title_relay_result", { agent: it.payload?.target_agent_name || "", who: it.payload?.target_owner_name || "" });
    case "relay_visit": return t("inbox.title_relay_visit", { agent: it.payload?.initiator_agent_name || "", who: it.payload?.initiator_owner_name || "" });
    // A followed company moved (plan/40 §7).
    case "company_review": return t("inbox.title_company_review", { company: it.payload?.company_name || "" });
    case "company_job": return t("inbox.title_company_job", { company: it.payload?.company_name || "" });
    // Somebody wants to connect, or answered the owner's own request (plan/41 §9.1).
    // Written before connecting replaced 인맥 신청 (plan/43). They still have to read as
    // something, so they read as what they now are.
    case "link_request":
    case "link_accepted":
      return t("inbox.title_person_follow", { who: it.payload?.actor_name || "" });
    case "person_follow": return t("inbox.title_person_follow", { who: it.payload?.actor_name || "" });
    // Somebody replied under a post on my own page (plan/42 §5).
    case "post_comment": return t("inbox.title_post_comment", { who: it.payload?.actor_name || "" });
    case "post_reply": return t("inbox.title_post_reply", { who: it.payload?.actor_name || "" });
    case "post_mention": return t("inbox.title_post_mention", { who: it.payload?.actor_name || "" });
    case "storage_notice": return it.payload?.level >= 100 ? t("inbox.title_storage_full") : t("inbox.title_storage_warn");
    default: return it.kind;
  }
}
