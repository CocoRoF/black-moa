/**
 * 본창의 틀 (plan/62 §3).
 *
 * 위의 제목 줄(36px)과 왼쪽의 아이콘 막대(48px)만 앱이 그린다. 가운데는 세 문의 웹 뷰가 덮는다 — 이 화면의
 * 가운데가 보이는 것은 알림·설정을 열었을 때와 서버에 닿지 못했을 때뿐이다.
 *
 * 아이콘 막대의 위는 세 문(대화·소식·커뮤니티), 아래는 비서(아바타 켜고 끄기)·알림·설정·나.
 */
import { useEffect, useState, type ReactNode } from 'react';
import { Bell, ChevronLeft, ExternalLink, MessageCircle, Newspaper, RotateCw, Settings as Gear, Users, WifiOff } from 'lucide-react';
import type { Door, Pane, ShellState } from '@shared/contract';
import { api } from './bridge';
import { Face, Kbd, cn, prettyKeys } from './ui';
import { Alerts } from './Alerts';
import { SettingsPane } from './Settings';
import mark from './img/mark.png';

const DOORS: { id: Door; label: string; icon: ReactNode }[] = [
  { id: 'chat', label: '비서와 대화', icon: <MessageCircle className="h-[21px] w-[21px]" strokeWidth={1.8} /> },
  { id: 'feed', label: '소식', icon: <Newspaper className="h-[21px] w-[21px]" strokeWidth={1.8} /> },
  { id: 'community', label: '커뮤니티', icon: <Users className="h-[21px] w-[21px]" strokeWidth={1.8} /> },
];

const TITLES: Record<Pane, string> = { chat: '비서와 대화', feed: '소식', community: '커뮤니티', alerts: '알림', settings: '설정' };

export function ShellWindow() {
  const [s, setS] = useState<ShellState | null>(null);
  const [quickKeys, setQuickKeys] = useState('');
  useEffect(() => {
    void api().shell.state().then(setS);
    return api().shell.onState(setS);
  }, []);
  useEffect(() => {
    void api().shell.settings().then((x) => setQuickKeys(x.shortcuts.quick));
  }, [s?.pane]);
  if (!s) return <div className="h-full bg-bg" />;

  const barOn = s.signedIn || s.restoring;
  const door = s.pane === 'chat' || s.pane === 'feed' || s.pane === 'community';
  return (
    <div className="flex h-full flex-col bg-bg">
      <TitleBar s={s} door={door} quickKeys={quickKeys} />
      <div className="flex min-h-0 flex-1">
        {barOn ? <ActivityBar s={s} /> : null}
        <main className="relative min-w-0 flex-1">
          {s.pane === 'alerts' ? <Alerts s={s} /> : null}
          {s.pane === 'settings' ? <SettingsPane s={s} /> : null}
          {door && s.offline ? <Offline /> : null}
        </main>
      </div>
    </div>
  );
}

function TitleBar({ s, door, quickKeys }: { s: ShellState; door: boolean; quickKeys: string }) {
  const mac = s.platform === 'darwin';
  const agent = s.agent;
  return (
    <div className="h-9 shrink-0 border-b border-border bg-card">
    <header
      className="drag relative flex h-[35px] items-center gap-1"
      // 윈도·리눅스: 운영체제의 창 단추가 오른쪽 위를 덮는다. 그 폭만큼 비운다(env 가 없으면 창 전체).
      style={{ paddingLeft: mac ? 78 : 10, width: 'env(titlebar-area-width, 100%)' }}
    >
      <img src={mark} alt="" draggable={false} className="h-[18px] w-auto shrink-0" />
      <span className="ml-1.5 shrink-0 text-[13px] font-semibold">{s.signedIn || s.restoring ? TITLES[s.pane] : 'Memora'}</span>
      {door && s.signedIn ? (
        <div className="no-drag ml-1 flex items-center">
          <IconBtn label="뒤로" disabled={!s.canBack} onClick={() => void api().shell.back()}>
            <ChevronLeft className="h-4 w-4" />
          </IconBtn>
          <IconBtn label="새로고침" onClick={() => void api().shell.reload()}>
            <RotateCw className={cn('h-[14px] w-[14px]', s.loading && 'spin')} />
          </IconBtn>
        </div>
      ) : null}
      <div className="min-w-0 flex-1" />
      {/* 가운데: 어디서든 부르는 빠른 대화의 입구(Dex 의 명령 칸 자리). */}
      {s.signedIn && agent ? (
        <button
          type="button"
          onClick={() => void api().shell.openQuick()}
          className="no-drag absolute left-1/2 top-1/2 flex h-[25px] w-[min(420px,40%)] -translate-x-1/2 -translate-y-1/2 items-center gap-2 rounded-md border border-border bg-bg px-2 text-left text-[12px] text-muted-fg hover:border-accent/40 hover:text-fg"
        >
          <Face src={agent.avatarUrl} name={agent.name} size={16} />
          <span className="min-w-0 flex-1 truncate">{agent.name}에게 물어보기</span>
          {quickKeys ? <Kbd>{prettyKeys(quickKeys, s.platform)}</Kbd> : null}
        </button>
      ) : null}
      {door && s.signedIn ? (
        <div className="no-drag mr-1 flex items-center">
          <IconBtn label="브라우저에서 열기" onClick={() => void api().shell.openInBrowser()}>
            <ExternalLink className="h-[14px] w-[14px]" />
          </IconBtn>
        </div>
      ) : null}
    </header>
    </div>
  );
}

function IconBtn({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-fg hover:bg-muted hover:text-fg disabled:opacity-35 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  );
}

function ActivityBar({ s }: { s: ShellState }) {
  const unread = s.unread.inbox;
  return (
    <nav className="flex w-12 shrink-0 flex-col items-center border-r border-border bg-card py-1.5" aria-label="Memora">
      {DOORS.map((d) => (
        <BarBtn key={d.id} label={d.label} active={s.pane === d.id} onClick={() => void api().shell.select(d.id)}>
          {d.icon}
        </BarBtn>
      ))}
      <div className="flex-1" />
      {s.agent ? (
        <BarBtn label={s.avatarOn ? `${s.agent.name} 내리기` : `${s.agent.name} 띄우기`} onClick={() => void api().shell.toggleAvatar()}>
          <span className="relative">
            <Face src={s.agent.avatarUrl} name={s.agent.name} size={24} />
            <span
              className={cn('absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-card', s.avatarOn ? 'bg-success' : 'bg-border')}
            />
          </span>
        </BarBtn>
      ) : null}
      <BarBtn label="알림" active={s.pane === 'alerts'} onClick={() => void api().shell.select('alerts')}>
        <span className="relative">
          <Bell className="h-[21px] w-[21px]" strokeWidth={1.8} />
          {unread ? (
            <span className="absolute -right-2 -top-1.5 min-w-[16px] rounded-full bg-accent px-1 text-center text-[9.5px] font-semibold leading-4 text-accent-fg">
              {unread > 99 ? '99+' : unread}
            </span>
          ) : null}
        </span>
      </BarBtn>
      <BarBtn label={s.update.newer ? '설정 · 새 버전이 있어요' : '설정'} active={s.pane === 'settings'} onClick={() => void api().shell.select('settings')}>
        <span className="relative">
          <Gear className="h-[21px] w-[21px]" strokeWidth={1.8} />
          {s.update.newer ? <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border border-card bg-accent" /> : null}
        </span>
      </BarBtn>
      {s.me ? (
        <BarBtn
          label={s.me.name}
          onClick={(e) => {
            const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
            void api().shell.accountMenu(r.right + 4, r.top);
          }}
        >
          <Face src={s.me.avatarUrl} name={s.me.name} size={24} />
        </BarBtn>
      ) : null}
    </nav>
  );
}

function BarBtn({
  label,
  active,
  onClick,
  children,
}: {
  label: string;
  active?: boolean;
  onClick: (e: React.MouseEvent) => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-current={active ? 'page' : undefined}
      onClick={onClick}
      className={cn('relative flex h-11 w-12 items-center justify-center transition-colors', active ? 'text-fg' : 'text-muted-fg hover:text-fg')}
    >
      {active ? <span className="active-bar absolute left-0 top-2 bottom-2 w-[2px] rounded-r" /> : null}
      {children}
    </button>
  );
}

function Offline() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
      <WifiOff className="mb-1 h-7 w-7 text-muted-fg" strokeWidth={1.6} />
      <p className="text-[15px] font-semibold">서버에 닿지 못했어요</p>
      <p className="text-[13px] text-muted-fg">인터넷 연결을 확인한 뒤 다시 시도해 주세요.</p>
      <button
        type="button"
        onClick={() => void api().shell.reload()}
        className="mt-3 rounded-lg bg-accent px-4 py-2 text-[13px] font-medium text-accent-fg hover:opacity-90"
      >
        다시 시도
      </button>
    </div>
  );
}
