/**
 * 알림(인박스)을 앱의 말로.
 *
 * 웹의 인박스 제목과 같은 문장을 쓴다(웹 `components/owner/inboxUtil.ts`). 누르면 갈 곳도 여기서 정한다:
 * 세 문 안에 그 자리가 있으면 그 문으로(커뮤니티 글, 사람의 페이지, 기업), 없으면 브라우저의 인박스로.
 */
import type { Door, InboxLite } from '@shared/contract';

type P = Record<string, unknown>;
const s = (v: unknown) => (typeof v === 'string' ? v : '');

export function titleOf(kind: string, p: P): string {
  const who = s(p.actor_name);
  switch (kind) {
    case 'message': return `${s(p.visitor_name) || '방문자'}님의 메시지`;
    case 'meeting_request': return `${s(p.visitor_name) || '방문자'}님의 미팅 요청`;
    case 'contact_share': return `${s(p.visitor_name) || '방문자'}님의 연락처 요청`;
    case 'question_unanswered': return '비서가 답하지 못한 질문';
    case 'community_comment': return `${who}님이 내 글에 댓글을 남겼어요`;
    case 'community_reply': return `${who}님이 내 댓글에 답글을 남겼어요`;
    case 'relay_result': return `${s(p.target_agent_name)} 비서와의 대화가 끝났어요`;
    case 'relay_visit': return `${s(p.initiator_owner_name)}님의 비서 ${s(p.initiator_agent_name)}가 문의하고 갔어요`;
    case 'company_review': return `${s(p.company_name)}에 새 리뷰가 올라왔어요`;
    case 'company_job': return `${s(p.company_name)}가 채용을 시작했어요`;
    case 'link_request':
    case 'link_accepted':
    case 'person_follow': return `${who}님이 나를 연결했어요`;
    case 'post_comment': return `${who}님이 내 글에 댓글을 남겼어요`;
    case 'post_reply': return `${who}님이 내 댓글에 답글을 남겼어요`;
    case 'post_mention': return `${who}님이 글에서 나를 언급했어요`;
    case 'storage_notice': return Number(p.level) >= 100 ? '저장 공간이 가득 찼어요' : '저장 공간이 거의 찼어요';
    default: return '새 알림';
  }
}

/** 알림 한 줄 아래의 짧은 글. */
export function textOf(p: P): string {
  return (s(p.excerpt) || s(p.text) || s(p.question) || '').replace(/\s+/g, ' ').trim().slice(0, 140);
}

export type Target = { door: Door; path: string } | { browser: string };

export function targetOf(id: string, kind: string, p: P): Target {
  const uuid = (v: unknown) => (typeof v === 'string' && /^[0-9a-f-]{36}$/i.test(v) ? v : null);
  const post = uuid(p.post_id);
  if ((kind === 'community_comment' || kind === 'community_reply') && post) return { door: 'community', path: `/app/community/p/${post}` };
  const company = uuid(p.company_id);
  if ((kind === 'company_review' || kind === 'company_job') && company) {
    return { door: 'community', path: `/app/community/companies/${company}?tab=${kind === 'company_job' ? 'hiring' : 'reviews'}` };
  }
  const actor = uuid(p.actor_id);
  if (kind === 'person_follow' && actor) return { door: 'feed', path: `/app/u/${actor}` };
  return { browser: `/app/inbox?item=${encodeURIComponent(id)}` };
}

export interface RawItem {
  id: string;
  kind: string;
  status: string;
  payload?: P;
  created_at: string;
}

export function lite(it: RawItem): InboxLite {
  const p = it.payload ?? {};
  return { id: it.id, kind: it.kind, status: it.status, title: titleOf(it.kind, p), text: textOf(p), createdAt: it.created_at };
}
