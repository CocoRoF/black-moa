/**
 * 앱의 설정 (plan/62 §6). 이 컴퓨터에서의 일만 여기서 정한다 — 비서·계정의 설정은 웹에 있다.
 */
import { useEffect, useState, type ReactNode } from 'react';
import type { Settings, ShellState, Shortcuts } from '@shared/contract';
import { api } from './bridge';
import { RefreshCw } from 'lucide-react';
import { Face, Kbd, Switch, cn, prettyKeys } from './ui';

export function SettingsPane({ s }: { s: ShellState }) {
  const [v, setV] = useState<Settings | null>(null);
  useEffect(() => {
    void api().shell.settings().then(setV);
  }, []);
  if (!v) return null;
  const set = (patch: Partial<Settings>) => {
    setV({ ...v, ...patch, notify: { ...v.notify, ...(patch.notify ?? {}) }, shortcuts: { ...v.shortcuts, ...(patch.shortcuts ?? {}) } });
    void api().shell.setSettings(patch).then(setV);
  };

  return (
    <div className="scroll h-full">
      <div className="mx-auto w-full max-w-[640px] space-y-4 px-5 py-5">
        <h1 className="text-[15px] font-semibold">설정</h1>

        <Section title="일반">
          <Row label="컴퓨터를 켜면 시작" hint="트레이에서 조용히 기다려요.">
            <Switch label="컴퓨터를 켜면 시작" on={s.autostart} onChange={(on) => void api().shell.setAutostart(on)} />
          </Row>
          <Row label="시작할 때 아바타 띄우기" hint="앱이 켜지면 비서가 화면 구석에 함께 떠요.">
            <Switch label="시작할 때 아바타 띄우기" on={v.avatarOnStart} onChange={(on) => set({ avatarOnStart: on })} />
          </Row>
          <Row label="화면 테마">
            <Segmented
              value={v.theme}
              options={[
                ['system', '시스템'],
                ['light', '밝게'],
                ['dark', '어둡게'],
              ]}
              onChange={(t) => set({ theme: t as Settings['theme'] })}
            />
          </Row>
        </Section>

        <Section title="비서">
          <Row label="곁에 둘 비서" hint="아바타와 빠른 대화가 이 비서를 불러요.">
            <div className="flex flex-wrap justify-end gap-1.5">
              {s.agents.map((a) => {
                const on = (v.agentId ?? s.agent?.id) === a.id;
                return (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => set({ agentId: a.id })}
                    className={cn(
                      'inline-flex items-center gap-1.5 rounded-full border py-1 pl-1 pr-2.5 text-[12px]',
                      on ? 'border-accent bg-accent-soft font-medium text-accent' : 'border-border hover:bg-muted',
                    )}
                  >
                    <Face src={a.avatarUrl} name={a.name} size={20} />
                    {a.name}
                  </button>
                );
              })}
              {!s.agents.length ? <span className="text-[12px] text-muted-fg">아직 비서가 없어요</span> : null}
            </div>
          </Row>
          {s.voice.tts ? (
            <Row label="답을 소리로 듣기" hint="아바타가 답을 비서의 목소리로 읽어 줘요.">
              <Switch label="답을 소리로 듣기" on={v.speak} onChange={(on) => set({ speak: on })} />
            </Row>
          ) : null}
        </Section>

        <Section title="화면">
          <Row
            label="화면 보여주기"
            hint="켜면 아바타와 빠른 대화에 [화면 보여주기] 가 생겨요. 누를 때만 지금 화면을 한 장 찍고, 보내기를 눌러야 물음과 함께 비서에게 가요."
          >
            <Switch label="화면 보여주기" on={v.capture} onChange={(on) => set({ capture: on })} />
          </Row>
        </Section>

        <Section title="알림">
          <Row label="비서가 먼저 건넨 말" hint="비서가 말을 걸면 바로 알려 드려요.">
            <Switch label="비서가 먼저 건넨 말" on={v.notify.proactive} onChange={(on) => set({ notify: { ...v.notify, proactive: on } })} />
          </Row>
          <Row label="인박스" hint="방문자의 메시지, 댓글, 연결 소식이에요.">
            <Switch label="인박스" on={v.notify.inbox} onChange={(on) => set({ notify: { ...v.notify, inbox: on } })} />
          </Row>
          <Row label="메시지" hint="다른 사람이 보낸 메시지예요.">
            <Switch label="메시지" on={v.notify.messages} onChange={(on) => set({ notify: { ...v.notify, messages: on } })} />
          </Row>
        </Section>

        <Section title="단축키">
          {(
            [
              ['quick', '빠른 대화', '어디서든 비서에게 한 마디 물어요.'],
              ['avatar', '아바타 띄우기·내리기', ''],
              ['main', '본창 열기·숨기기', ''],
              ...(v.capture ? ([['capture', '화면 보여주고 묻기', '지금 화면을 찍어 빠른 대화에 붙여요.']] as [keyof Shortcuts, string, string][]) : []),
            ] as [keyof Shortcuts, string, string][]
          ).map(([k, label, hint]) => (
            <Row key={k} label={label} hint={s.shortcutErrors.includes(k) ? '다른 프로그램이 이 조합을 쓰고 있어요. 다른 조합을 골라 주세요.' : hint} warn={s.shortcutErrors.includes(k)}>
              <KeyField value={v.shortcuts[k]} platform={s.platform} onChange={(accel) => set({ shortcuts: { ...v.shortcuts, [k]: accel } })} />
            </Row>
          ))}
        </Section>

        <Section title="계정">
          {s.me ? (
            <div className="flex items-center gap-2.5 px-4 py-3">
              <Face src={s.me.avatarUrl} name={s.me.name} size={32} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium">{s.me.name}</p>
                <p className="truncate text-[12px] text-muted-fg">{s.me.email}</p>
              </div>
              <button type="button" onClick={() => void api().shell.signOut()} className="rounded-lg border border-border px-3 py-1.5 text-[12px] hover:bg-muted">
                로그아웃
              </button>
            </div>
          ) : null}
          <Row label="웹에서 전체 기능" hint="비서 관리, 내 정보, 스케줄 같은 나머지는 웹에서 해요.">
            <button type="button" onClick={() => void api().shell.openWeb('/app')} className="rounded-lg border border-border px-3 py-1.5 text-[12px] hover:bg-muted">
              열기
            </button>
          </Row>
        </Section>

        <Section title="정보">
          <UpdateRow s={s} />
        </Section>
      </div>
    </div>
  );
}

/**
 * 새 판(plan/65): [업데이트] 한 번이면 다운로드 센터에서 받아 설치하고 다시 켠다.
 * [업데이트 확인] 은 앱을 다시 켜지 않고 지금 새 판이 있는지 묻는다.
 */
function UpdateRow({ s }: { s: ShellState }) {
  const u = s.update;
  // "몇 분 전에 확인했어요" 가 멈춰 있지 않게 가끔 다시 그린다.
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30_000);
    return () => clearInterval(t);
  }, []);
  const pct = Math.round((u.progress || 0) * 100);
  const busy = u.phase === 'downloading' || u.phase === 'installing';
  const failed = u.phase === 'error' || !!u.checkError;
  const hint =
    u.phase === 'downloading'
      ? `새 버전(${u.latest})을 받는 중이에요. ${pct}%`
      : u.phase === 'installing'
        ? '설치하는 중이에요. 곧 다시 켜져요.'
        : u.checking
          ? '새 버전이 있는지 확인하고 있어요.'
          : u.checkError
            ? u.checkError
            : u.phase === 'error'
              ? u.error || '업데이트하지 못했어요.'
              : u.newer && u.latest
                ? `버전 ${s.version} · 새 버전(${u.latest})이 나왔어요.`
                : `버전 ${s.version}${u.latest ? ` · 최신이에요${u.checkedAt ? ` (${checkedWhen(u.checkedAt)})` : ''}` : ''}`;
  const canInstall = u.newer && u.installable && u.phase !== 'error';
  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium">black-moa</p>
          <p className={cn('mt-0.5 text-[12px]', failed ? 'text-danger' : 'text-muted-fg')}>{hint}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            disabled={busy || u.checking}
            onClick={() => void api().shell.checkUpdate()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[12px] hover:bg-muted disabled:opacity-60"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', u.checking && 'spin')} />
            {u.checking ? '확인 중' : '업데이트 확인'}
          </button>
          {canInstall ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void api().shell.update()}
              className="rounded-lg bg-accent px-3 py-1.5 text-[12px] font-medium text-accent-fg hover:opacity-90 disabled:opacity-60"
            >
              {busy ? '업데이트 중' : '업데이트'}
            </button>
          ) : (
            <button type="button" onClick={() => void api().shell.openDownloads()} className="rounded-lg border border-border px-3 py-1.5 text-[12px] hover:bg-muted">
              다운로드 센터
            </button>
          )}
        </div>
      </div>
      {u.phase === 'downloading' ? (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-accent transition-[width] duration-200" style={{ width: `${pct}%` }} />
        </div>
      ) : null}
    </div>
  );
}

/** 마지막으로 확인한 때: 방금, 몇 분 전, 또는 시각. */
function checkedWhen(at: number): string {
  const min = Math.floor((Date.now() - at) / 60_000);
  if (min < 1) return '방금 확인했어요';
  if (min < 60) return `${min}분 전에 확인했어요`;
  const d = new Date(at);
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}에 확인했어요`;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="mb-1.5 px-1 text-[12px] font-medium text-muted-fg">{title}</h2>
      <div className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">{children}</div>
    </section>
  );
}

function Row({ label, hint, warn, children }: { label: string; hint?: string; warn?: boolean; children: ReactNode }) {
  return (
    <div className="flex items-center gap-4 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium">{label}</p>
        {hint ? <p className={cn('mt-0.5 text-[12px]', warn ? 'text-danger' : 'text-muted-fg')}>{hint}</p> : null}
      </div>
      {children}
    </div>
  );
}

function Segmented({ value, options, onChange }: { value: string; options: [string, string][]; onChange: (v: string) => void }) {
  return (
    <div className="inline-flex rounded-lg bg-muted p-0.5 text-[12px]">
      {options.map(([k, label]) => (
        <button
          key={k}
          type="button"
          onClick={() => onChange(k)}
          className={cn('rounded-md px-2.5 py-1', value === k ? 'bg-card font-medium shadow-sm' : 'text-muted-fg hover:text-fg')}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

const MOD_KEYS = new Set(['Control', 'Shift', 'Alt', 'Meta']);

/** 눌러서 정하는 단축키 칸. 수식키 없이 누른 것은 받지 않는다(타자를 가로챈다). */
export function toAccelerator(e: Pick<KeyboardEvent, 'key' | 'code' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey'>, mac: boolean): string | null {
  if (MOD_KEYS.has(e.key)) return null;
  const mods: string[] = [];
  if (mac ? e.metaKey : e.ctrlKey) mods.push('CommandOrControl');
  if (mac && e.ctrlKey) mods.push('Control');
  if (!mac && e.metaKey) mods.push('Super');
  if (e.altKey) mods.push('Alt');
  if (e.shiftKey) mods.push('Shift');
  if (!mods.length || (mods.length === 1 && mods[0] === 'Shift')) return null;
  let key = '';
  if (/^Key[A-Z]$/.test(e.code)) key = e.code.slice(3);
  else if (/^Digit[0-9]$/.test(e.code)) key = e.code.slice(5);
  else if (/^F([1-9]|1[0-9]|2[0-4])$/.test(e.code)) key = e.code;
  else if (e.code === 'Space') key = 'Space';
  else if (e.code === 'Enter') key = 'Enter';
  else if (e.code === 'Backquote') key = '`';
  else if (e.code === 'Slash') key = '/';
  else if (e.code === 'Period') key = '.';
  else if (e.code === 'Comma') key = ',';
  else if (e.code === 'Semicolon') key = ';';
  else return null;
  return [...mods, key].join('+');
}

function KeyField({ value, platform, onChange }: { value: string; platform: string; onChange: (accel: string) => void }) {
  const [listening, setListening] = useState(false);
  useEffect(() => {
    if (!listening) return;
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === 'Escape') return setListening(false);
      if ((e.key === 'Backspace' || e.key === 'Delete') && !e.ctrlKey && !e.metaKey && !e.altKey) {
        setListening(false);
        return onChange('');
      }
      const accel = toAccelerator(e, platform === 'darwin');
      if (!accel) return;
      setListening(false);
      onChange(accel);
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [listening, onChange, platform]);
  return (
    <button
      type="button"
      onClick={() => setListening((x) => !x)}
      onBlur={() => setListening(false)}
      className={cn(
        'min-w-[128px] rounded-lg border px-2.5 py-1.5 text-center text-[12px]',
        listening ? 'border-accent bg-accent-soft text-accent' : 'border-border hover:bg-muted',
      )}
    >
      {listening ? '조합을 누르세요' : value ? <Kbd>{prettyKeys(value, platform)}</Kbd> : <span className="text-muted-fg">쓰지 않음</span>}
    </button>
  );
}
