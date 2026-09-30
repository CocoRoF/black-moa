/**
 * 알림 — 최근 인박스 몇 개를 훑어보는 자리.
 *
 * 처리하는 곳은 웹의 인박스다. 여기서는 무엇이 왔는지 보고, 누르면 그것이 있는 곳으로 간다: 세 문 안에 그
 * 자리가 있으면 그 문으로(커뮤니티 글, 사람의 페이지), 아니면 브라우저의 인박스로.
 */
import { useCallback, useEffect, useState } from 'react';
import { Inbox } from 'lucide-react';
import type { InboxLite, ShellState } from '@shared/contract';
import { api } from './bridge';
import { ago, cn } from './ui';

export function Alerts({ s }: { s: ShellState }) {
  const [items, setItems] = useState<InboxLite[] | null>(null);
  const [err, setErr] = useState('');
  const load = useCallback(() => {
    api()
      .shell.inbox()
      .then((x) => {
        setItems(x);
        setErr('');
      })
      .catch((e: Error) => setErr(e.message));
  }, []);
  // 열 때, 그리고 새 알림이 올 때마다 다시 받는다.
  useEffect(load, [load, s.unread.inbox]);

  return (
    <div className="scroll h-full">
      <div className="mx-auto w-full max-w-[640px] px-5 py-5">
        <div className="mb-3 flex items-center gap-2">
          <h1 className="text-[15px] font-semibold">알림</h1>
          {s.unread.inbox ? <span className="rounded-full bg-accent-soft px-1.5 text-[11px] font-medium tabular-nums text-accent">{s.unread.inbox}</span> : null}
          <div className="flex-1" />
          <button type="button" onClick={() => void api().shell.openWeb('/app/inbox')} className="text-[12px] text-accent hover:underline">
            인박스에서 처리하기
          </button>
        </div>
        {err ? <p className="rounded-xl border border-border bg-card px-4 py-6 text-center text-[13px] text-muted-fg">{err}</p> : null}
        {!err && items === null ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-[58px] animate-pulse rounded-xl bg-muted" />
            ))}
          </div>
        ) : null}
        {!err && items && items.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-xl border border-border bg-card px-4 py-10 text-center">
            <Inbox className="h-6 w-6 text-muted-fg" strokeWidth={1.6} />
            <p className="text-[13px] font-medium">아직 온 알림이 없어요</p>
            <p className="text-[12px] text-muted-fg">방문자의 메시지, 댓글, 연결 소식이 여기 모여요.</p>
          </div>
        ) : null}
        {items && items.length ? (
          <ul className="overflow-hidden rounded-xl border border-border bg-card">
            {items.map((it, i) => (
              <li key={it.id} className={cn(i > 0 && 'border-t border-border')}>
                <button
                  type="button"
                  onClick={() => {
                    setItems((xs) => xs?.map((x) => (x.id === it.id ? { ...x, status: 'read' } : x)) ?? xs);
                    void api().shell.openInbox(it.id);
                  }}
                  className="flex w-full gap-2.5 px-3.5 py-2.5 text-left hover:bg-muted/60"
                >
                  <span className={cn('mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full', it.status === 'new' ? 'bg-accent' : 'bg-transparent')} />
                  <span className="min-w-0 flex-1">
                    <span className={cn('block truncate text-[13px]', it.status === 'new' ? 'font-semibold' : 'font-medium')}>{it.title}</span>
                    {it.text ? <span className="mt-0.5 block truncate text-[12px] text-muted-fg">{it.text}</span> : null}
                    <span className="mt-0.5 block text-[11px] text-muted-fg">{ago(it.createdAt)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
