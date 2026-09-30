/**
 * 빠른 대화 (plan/62 §3, plan/69).
 *
 * 어디서든 뜨는 입력 줄 하나. 보내면 줄은 닫히고, 답은 **아바타의 말풍선**으로 나온다(Geny·Dex 와 같다). 이 창이
 * 또 하나의 채팅창이 되면 곁의 비서와 대화가 두 군데로 갈라진다. 아바타가 꺼져 있으면 앱이 띄운다.
 *
 * 비서를 고르면 아바타의 비서도 그 비서가 된다. 아바타가 답하는 중이면 [그만] 으로 멈출 수 있다.
 *
 * 화면 보여주기(plan/70): 설정에서 켜 두면 [화면 보여주기] 로 지금 화면을 한 장 찍어 이 물음에 붙인다. 붙은 화면은
 * 작게 보이고, 떼거나 그대로 보낸다. 글 없이 보내면 "이 화면 좀 봐 줘" 로 묻는다.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ArrowUp, Check, ChevronDown, CornerDownLeft, Loader2, Mic, ScanEye, Square, X } from 'lucide-react';
import type { AgentLite, Answer, ShotPreview } from '@shared/contract';
import { api } from './bridge';
import { useRecorder } from './useRecorder';
import { Face, Kbd, cn, useVoiceAvailability } from './ui';

export function QuickWindow() {
  const [agents, setAgents] = useState<AgentLite[]>([]);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [picking, setPicking] = useState(false);
  const [sending, setSending] = useState(false);
  const [note, setNote] = useState('');
  const [captureOn, setCaptureOn] = useState(false);
  const [shot, setShot] = useState<ShotPreview | null>(null);
  const [shooting, setShooting] = useState(false);
  // 관리자가 끈 음성은 단추도 없다(plan/67).
  const voice = useVoiceAvailability();
  const input = useRef<HTMLTextAreaElement>(null);
  const root = useRef<HTMLDivElement>(null);

  const loadAgents = useCallback(() => {
    void api()
      .quick.agents()
      .then((r) => {
        setAgents(r.agents);
        setAgentId(r.agentId);
        setCaptureOn(r.capture);
        setShot(r.shot);
      });
  }, []);

  // 창이 다시 보일 때마다: 비서 목록을 새로 받고 입력칸에 초점.
  useEffect(() => {
    loadAgents();
    const off = api().quick.onShown(() => {
      loadAgents();
      setPicking(false);
      setNote('');
      setSending(false);
      requestAnimationFrame(() => {
        input.current?.focus();
        input.current?.select();
      });
    });
    return off;
  }, [loadAgents]);

  useEffect(() => api().quick.onAnswer(setAnswer), []);
  useEffect(() => api().quick.onShot(setShot), []);

  const takeShot = async () => {
    if (shooting) return;
    setNote('');
    setShooting(true);
    try {
      setShot(await api().quick.capture());
    } catch (e) {
      setNote(e instanceof Error ? e.message : '화면을 찍지 못했어요.');
    } finally {
      setShooting(false);
      requestAnimationFrame(() => input.current?.focus());
    }
  };

  // 내용이 자란 만큼 창도 자란다(여러 줄·비서 고르기·알림).
  useLayoutEffect(() => {
    const el = root.current;
    if (!el) return;
    const ro = new ResizeObserver(() => void api().quick.resize(Math.ceil(el.getBoundingClientRect().height)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 입력칸은 네 줄까지 자란다.
  useLayoutEffect(() => {
    const t = input.current;
    if (!t) return;
    t.style.height = 'auto';
    t.style.height = `${Math.min(t.scrollHeight, 96)}px`;
  }, [text]);

  const agent = agents.find((a) => a.id === agentId) ?? agents[0] ?? null;
  const busy = !!answer && !answer.done;

  const send = useCallback(
    async (q: string) => {
      const said = q.trim();
      // 화면이 붙어 있으면 글 없이도 보낼 수 있다(메인이 "이 화면 좀 봐 줘" 로 묻는다).
      if ((!said && !shot) || !agent || sending) return;
      setNote('');
      setSending(true);
      try {
        // 흐르기 시작하면 메인이 이 줄을 닫는다. 답은 아바타가 한다.
        await api().quick.ask(agent.id, said);
        setText('');
      } catch (e) {
        setNote(e instanceof Error ? e.message : '말을 전하지 못했어요.');
      } finally {
        setSending(false);
      }
    },
    [agent, sending, shot],
  );

  const recorder = useRecorder(async (audioBuf, mime) => {
    if (!agent) return;
    setNote('');
    try {
      const r = await api().quick.transcribe(agent.id, audioBuf, mime);
      if (r.text.trim()) await send(r.text);
    } catch (e) {
      setNote(e instanceof Error ? e.message : '말을 알아듣지 못했어요.');
    }
  });

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(text);
    }
  };

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.isComposing) return;
      e.preventDefault();
      if (picking) setPicking(false);
      else void api().quick.hide();
    };
    window.addEventListener('keydown', onEsc);
    return () => window.removeEventListener('keydown', onEsc);
  }, [picking]);

  return (
    <div ref={root} className="flex flex-col overflow-hidden rounded-[inherit] border border-border bg-card">
      {/* 입력 줄 */}
      <div className="drag flex items-start gap-2 px-3 py-3">
        <button
          type="button"
          onClick={() => agents.length > 1 && setPicking((x) => !x)}
          title={agent ? `${agent.name}에게 묻기` : undefined}
          className={cn('no-drag mt-[3px] flex shrink-0 items-center gap-0.5 rounded-full', agents.length > 1 && 'hover:opacity-80')}
        >
          <Face src={agent?.avatarUrl} name={agent?.name} size={28} />
          {agents.length > 1 ? <ChevronDown className="h-3.5 w-3.5 text-muted-fg" /> : null}
        </button>
        <textarea
          ref={input}
          rows={1}
          value={text}
          autoFocus
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          placeholder={!agent ? '비서를 먼저 만들어 주세요' : shot ? '이 화면에 대해 물어보세요' : `${agent.name}에게 물어보세요`}
          disabled={!agent}
          className="no-drag selectable mt-[5px] min-h-[24px] flex-1 resize-none bg-transparent text-[15px] leading-6 outline-none placeholder:text-muted-fg"
        />
        {captureOn ? (
          <button
            type="button"
            onClick={() => void takeShot()}
            disabled={!agent || shooting}
            title="화면 보여주기"
            className={cn('no-drag inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg', shot ? 'text-accent' : 'text-muted-fg hover:bg-muted hover:text-fg')}
          >
            {shooting ? <Loader2 className="spin h-4 w-4" /> : <ScanEye className="h-4 w-4" />}
          </button>
        ) : null}
        {voice.stt || recorder.recording ? (
          <button
            type="button"
            onClick={() => void recorder.toggle()}
            disabled={!agent}
            title={recorder.recording ? '말을 마쳤어요' : '말로 묻기'}
            className={cn(
              'no-drag inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
              recorder.recording ? 'bg-danger text-white' : 'text-muted-fg hover:bg-muted hover:text-fg',
            )}
          >
            <Mic className="h-4 w-4" />
          </button>
        ) : null}
        {busy && !text.trim() && !sending ? (
          <button
            type="button"
            onClick={() => void api().quick.stop()}
            title="그만"
            className="no-drag inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-fg hover:opacity-80"
          >
            <Square className="h-3.5 w-3.5" fill="currentColor" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => void send(text)}
            disabled={(!text.trim() && !shot) || !agent || sending}
            title="보내기"
            className="no-drag inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-fg disabled:opacity-30"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* 붙인 화면 — 무엇이 나갈지 보고 보낸다 */}
      {shot ? (
        <div className="fade-up flex items-center gap-3 border-t border-border px-3 py-2">
          <img src={shot.preview} alt="붙인 화면" className="h-14 rounded-md border border-border object-cover" style={{ aspectRatio: `${shot.width} / ${shot.height}` }} />
          <div className="min-w-0 flex-1 text-[12px] text-muted-fg">
            <p className="text-fg">지금 화면을 함께 보내요</p>
            <p>보내기를 눌러야 나가요.</p>
          </div>
          <button
            type="button"
            onClick={() => {
              setShot(null);
              void api().quick.dropShot();
            }}
            title="화면 떼기"
            className="no-drag inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-fg hover:bg-muted hover:text-fg"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : null}

      {/* 비서 고르기 — 아바타의 비서도 함께 바뀐다 */}
      {picking ? (
        <ul className="fade-up border-t border-border px-2 py-1.5">
          {agents.map((a) => (
            <li key={a.id}>
              <button
                type="button"
                onClick={() => {
                  setAgentId(a.id);
                  setPicking(false);
                  void api().quick.pick(a.id);
                  input.current?.focus();
                }}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] hover:bg-muted"
              >
                <Face src={a.avatarUrl} name={a.name} size={22} />
                <span className="flex-1 truncate">{a.name}</span>
                {a.id === agent?.id ? <Check className="h-4 w-4 text-accent" /> : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {note || recorder.error ? (
        <p className="border-t border-border px-4 py-2 text-[12px] text-danger">{note || recorder.error}</p>
      ) : (
        <div className="flex items-center gap-1 border-t border-border px-4 py-1.5 text-[11px] text-muted-fg">
          <span className="flex-1 truncate">{sending ? '보내는 중이에요' : busy ? '아바타가 답하고 있어요' : '답은 아바타가 말해 줘요'}</span>
          <Kbd>
            <CornerDownLeft className="inline h-2.5 w-2.5" />
          </Kbd>
          보내기 <Kbd>Esc</Kbd> 닫기
        </div>
      )}
    </div>
  );
}
