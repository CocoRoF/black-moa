/**
 * 아바타 공간 (plan/46 §4, plan/63, plan/66).
 *
 * 비서가 올린 사진이 **그대로** 데스크톱 위에 선다(XGen Dex 의 사진 아바타처럼). 투명한 그림은 바탕 없이,
 * 흰 바탕의 그림은 바탕을 걷어 사람만(character.ts), 사진 배경이면 둥근 카드로. 입모양을 흉내 내지 않는다 —
 * 숨(천천히 떠오름)·소리(말할 때 빛)·고개(소리 크기만큼 끄덕임)로 산다. 말은 사진 위의 말풍선으로, 한 글자씩.
 *
 * 잠김(기본): 이 창은 클릭을 뒤로 흘려보낸다. 단추는 사진 아래에 붙은 컨트롤 창(Chip.tsx)에 있고, 마우스가
 * 사진·말풍선 위에 올 때만 나온다 — 그 자리(`data-hit`)를 메인에 알린다.
 * 풀림: 점선 틀의 손잡이로 창 크기를, 아래 막대의 손잡이로 자리를 바꾼다. 사진 위에서 휠을 굴리면 커서를
 * 향해 확대·축소, 끌면 사진이 옮겨진다. 두 번 누르면 처음 모양으로. 사진의 모양은 사진마다 기억한다.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Eye, EyeOff, RotateCcw, X } from 'lucide-react';
import { IDLE_STATUS, type AvatarStatus, type AvatarSubject, type PictureView, type ResizeEdge, type SayState } from '@shared/contract';
import { DEFAULT_VIEW, RESERVE, isDefault, layout, panBy, wheelNotches, zoomAt } from '@shared/picture';
import { api } from './bridge';
import { prepare, type Prepared } from './character';
import { useRecorder } from './useRecorder';
import { useVoice } from './useVoice';
import { Actions, GripIcon, IconButton, LockButton, startWindowDrag } from './avatar-actions';
import { cn } from './ui';
import mark from './img/mark.png';

/** 말풍선이 한 글자씩 나오는 빠르기(ms/글자). 밀린 글이 많으면 따라잡도록 빨라진다. */
const CHAR_MS = 32;
/** 다 나온 말풍선이 머무는 시간: 읽을 만큼(길이에 따라), 먼저 건넨 말은 더 오래. */
const lingerFor = (text: string, proactive: boolean) => (proactive ? 60_000 : 6_000 + Math.min(14_000, text.length * 50));
/** 먼저 건넨 말에 [답하기] 가 머무는 시간. */
const PROACTIVE_MS = 10 * 60_000;

function useWindowSize() {
  const [s, set] = useState({ w: window.innerWidth, h: window.innerHeight });
  useEffect(() => {
    const f = () => set({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener('resize', f);
    return () => window.removeEventListener('resize', f);
  }, []);
  return s;
}

export function AvatarWindow() {
  const [who, setWho] = useState<AvatarSubject>({ agentId: null, name: '', avatarUrl: null, imageUrl: null });
  const [figure, setFigure] = useState<Prepared | null>(null);
  const [loading, setLoading] = useState(true);
  const [said, setSaid] = useState('');
  const [done, setDone] = useState(true);
  const [revealed, setRevealed] = useState(true);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [proactive, setProactive] = useState(false);
  const [firstWord, setFirstWord] = useState(false);
  const [bubble, setBubble] = useState(false);
  const [level, setLevel] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const [locked, setLocked] = useState(true);
  const [inset, setInset] = useState(0);
  const [status, setStatus] = useState<AvatarStatus>(IDLE_STATUS);
  const [view, setView] = useState<PictureView>(DEFAULT_VIEW);
  const [panning, setPanning] = useState(false);
  const [dockH, setDockH] = useState(44);
  const { w: W, h: H } = useWindowSize();
  const spoken = useRef('');
  const dirty = useRef(false);
  const stage = useRef<HTMLDivElement>(null);
  const dock = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void api().avatar.subject().then(setWho);
    return api().avatar.onSubject(setWho);
  }, []);
  useEffect(() => {
    void api().avatar.locked().then(setLocked);
    return api().avatar.onLocked(setLocked);
  }, []);
  useEffect(() => api().avatar.onChipInset(setInset), []);
  useEffect(() => {
    void api().avatar.status().then(setStatus);
    return api().avatar.onStatus(setStatus);
  }, []);

  // 그림을 받아 와 세울 준비를 한다(투명 확인 → 필요하면 바탕 걷기).
  useEffect(() => {
    let alive = true;
    let made: string | null = null;
    setLoading(true);
    void (async () => {
      const bytes = who.imageUrl ? await api().avatar.image(who.imageUrl).catch(() => null) : null;
      const p = bytes ? await prepare(bytes) : null;
      if (!alive) {
        if (p) URL.revokeObjectURL(p.url);
        return;
      }
      made = p?.url ?? null;
      setFigure(p);
      setLoading(false);
    })();
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [who.imageUrl]);

  // 이 사진을 놓아 두었던 모양. (저장보다 먼저 선언한다 — 사진이 바뀌는 순간 앞 사진의 모양을 새 사진에 적지 않게.)
  useEffect(() => {
    dirty.current = false;
    setView(DEFAULT_VIEW);
    if (!who.imageUrl) return;
    let alive = true;
    void api()
      .avatar.view(who.imageUrl)
      .then((v) => {
        if (alive && !dirty.current && v) setView(v);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [who.imageUrl]);

  useEffect(() => {
    const url = who.imageUrl;
    if (!dirty.current || !url) return;
    const t = setTimeout(() => {
      dirty.current = false;
      void api().avatar.saveView(url, isDefault(view) ? null : view);
    }, 600);
    return () => clearTimeout(t);
  }, [view, who.imageUrl]);

  const voice = useVoice(setLevel, () => setSpeaking(false));

  // 소리를 끄면 읽던 것도 멈춘다.
  useEffect(() => {
    if (!status.speak) {
      voice.stop();
      setSpeaking(false);
    }
  }, [status.speak, voice]);

  // 답이 다 끝난 뒤에 소리로 읽는다. 조각마다 읽으면 문장이 토막 나고 요청도 그만큼 나가 크레딧이 센다.
  // 물음은 여기서도, 빠른 대화에서도 온다(plan/69) — 무엇을 하는 중인지는 흐르는 답이 말해 준다.
  const [working, setWorking] = useState('');
  useEffect(() => {
    const apply = ({ text, done: finished, error, proactive: first, status: now }: SayState) => {
      setSaid(text);
      setDone(finished);
      setBubble(true);
      setFirstWord(!!first);
      setWorking(finished ? '' : (now ?? ''));
      if (first) {
        setProactive(true);
        setNote('');
      } else {
        setBusy(!finished);
        if (!finished && !text) {
          // 새 물음이 시작됐다(빠른 대화에서 물었을 수도 있다). 지난 오류·먼저 건넨 말의 표시는 걷는다.
          setNote('');
          setProactive(false);
          spoken.current = '';
        }
      }
      if (!finished) return;
      setBusy(false);
      if (error) {
        setNote(error);
        return;
      }
      const full = text.trim();
      if (!full || full === spoken.current) return;
      spoken.current = full;
      void (async () => {
        if (!(await api().avatar.speaks().catch(() => false))) return;
        setSpeaking(true);
        try {
          await voice.play(await api().avatar.speak(full.slice(0, 700)));
        } catch {
          // 소리가 안 나와도 글은 이미 떠 있다. 조용히 넘어간다.
          setSpeaking(false);
        }
      })();
    };
    // 창이 뜨기 전부터 흐르던 답(빠른 대화에서 물어 막 열렸을 때)을 먼저 받는다.
    void api()
      .avatar.lastSay()
      .then((s) => s && apply(s))
      .catch(() => {});
    return api().avatar.onSay(apply);
  }, [voice]);

  const ask = useCallback(async (text: string) => {
    setNote('');
    setSaid('');
    setDone(false);
    setProactive(false);
    setFirstWord(false);
    setBubble(true);
    spoken.current = '';
    setBusy(true);
    try {
      await api().avatar.ask(text);
    } catch (e) {
      setBusy(false);
      setDone(true);
      setNote(e instanceof Error ? e.message : '말을 전하지 못했어요.');
    }
  }, []);

  const recorder = useRecorder(async (audio, mime) => {
    setNote('');
    try {
      const r = await api().avatar.transcribe(audio, mime);
      if (r.text.trim()) await ask(r.text);
    } catch (e) {
      setBubble(true);
      setNote(e instanceof Error ? e.message : '말을 알아듣지 못했어요.');
    }
  });

  useEffect(() => {
    if (!recorder.error) return;
    setBubble(true);
    setNote(recorder.error);
  }, [recorder.error]);

  const stop = useCallback(() => {
    voice.stop();
    setSpeaking(false);
    void api().avatar.stop();
    setBusy(false);
  }, [voice]);

  const reply = useCallback(() => {
    setProactive(false);
    setBubble(false);
    void api().avatar.openQuick();
  }, []);

  const openChat = useCallback(() => {
    setProactive(false);
    void api().avatar.openChat();
  }, []);

  // 컨트롤 창의 단추. 녹음·재생·답은 이 창에 산다.
  const commands = useRef({ mic: () => {}, stop, reply });
  // 관리자가 받아쓰기를 껐으면 새로 듣지 않는다(듣던 것은 끌 수 있다).
  commands.current = { mic: () => (status.stt || recorder.recording ? void recorder.toggle() : undefined), stop, reply };
  useEffect(
    () =>
      api().avatar.onCommand((c) => {
        if (c === 'mic') commands.current.mic();
        else if (c === 'stop') commands.current.stop();
        else if (c === 'reply') commands.current.reply();
      }),
    [],
  );

  // 컨트롤이 그릴 수 있도록 지금 하는 일을 알린다.
  useEffect(() => {
    api().avatar.reportActivity({ recording: recorder.recording, busy, speaking, proactive });
  }, [recorder.recording, busy, speaking, proactive]);

  // 먼저 건넨 말에 끝내 답하지 않으면 [답하기] 는 거둔다.
  useEffect(() => {
    if (!proactive) return;
    const t = setTimeout(() => setProactive(false), PROACTIVE_MS);
    return () => clearTimeout(t);
  }, [proactive]);

  // 말풍선을 거둔다: 다 나오고, 읽을 만큼 머문 뒤에.
  useEffect(() => {
    if (!bubble || !done || !revealed || recorder.recording) return;
    const t = setTimeout(
      () => {
        setBubble(false);
        setNote('');
      },
      lingerFor(note || said, firstWord && !note),
    );
    return () => clearTimeout(t);
  }, [bubble, done, revealed, firstWord, said, note, recorder.recording]);

  // ── 사진 다루기(잠금을 풀었을 때만) ──
  const live = useRef({ locked, figure, W, H, hidden: status.hidden });
  live.current = { locked, figure, W, H, hidden: status.hidden };

  // 휠: 커서가 가리키는 곳을 붙잡은 채 확대·축소. React 의 onWheel 은 기본 동작을 막을 수 없어 직접 단다.
  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const { locked: l, figure: fig, W: w, H: h, hidden } = live.current;
      if (l || !fig || hidden) return;
      e.preventDefault();
      const notches = wheelNotches(e.deltaY);
      if (!notches) return;
      dirty.current = true;
      setView((v) => zoomAt(v, w, h, fig, e.clientX, e.clientY, notches));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  const panId = useRef<number | null>(null);
  const onPanStart = (e: React.PointerEvent) => {
    if (locked || e.button !== 0 || !figure || status.hidden) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    panId.current = e.pointerId;
    setPanning(true);
  };
  const onPanMove = (e: React.PointerEvent) => {
    if (panId.current !== e.pointerId || !figure) return;
    const dx = e.movementX;
    const dy = e.movementY;
    if (!dx && !dy) return;
    dirty.current = true;
    setView((v) => panBy(v, W, H, figure, dx, dy));
  };
  const onPanEnd = (e: React.PointerEvent) => {
    if (panId.current !== e.pointerId) return;
    panId.current = null;
    setPanning(false);
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };
  const resetView = () => {
    dirty.current = true;
    setView(DEFAULT_VIEW);
  };

  // 아바타인 곳(사진·표식·말풍선)을 메인에 알린다. 잠겼을 때 마우스가 여기 오면 컨트롤이 나온다.
  const lastHit = useRef('');
  const hitRef = useRef<{ x: number; y: number; width: number; height: number } | null>(null);
  useLayoutEffect(() => {
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    document.querySelectorAll('[data-hit]').forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return;
      x0 = Math.min(x0, r.left);
      y0 = Math.min(y0, r.top);
      x1 = Math.max(x1, r.right);
      y1 = Math.max(y1, r.bottom);
    });
    const area =
      x0 < x1 && y0 < y1
        ? { x: Math.max(0, Math.round(x0)), y: Math.max(0, Math.round(y0)), width: Math.round(Math.min(W, x1) - Math.max(0, x0)), height: Math.round(Math.min(H, y1) - Math.max(0, y0)) }
        : null;
    hitRef.current = area && area.width > 0 && area.height > 0 ? area : null;
    const key = JSON.stringify(area);
    if (key === lastHit.current) return;
    lastHit.current = key;
    api().avatar.reportHitArea(area && area.width > 0 && area.height > 0 ? area : null);
  });

  // 윈도·맥은 클릭이 통과하는 창에도 마우스 움직임을 넘겨준다. 사진·말풍선(또는 바닥 가운데의 컨트롤 자리) 위에서
  // 움직이면 메인에 알린다 — 커서 자리만 보는 길이 둘째 화면의 배율 때문에 어긋나도 컨트롤이 나오게(plan/70).
  useEffect(() => {
    let last = 0;
    const onMove = (e: MouseEvent) => {
      const a = hitRef.current;
      const slot = e.clientY > window.innerHeight - 60 && Math.abs(e.clientX - window.innerWidth / 2) < 140;
      const over = slot || !a || (e.clientX >= a.x - 4 && e.clientX <= a.x + a.width + 4 && e.clientY >= a.y - 4 && e.clientY <= a.y + a.height + 4);
      if (!over) return;
      const now = performance.now();
      if (now - last < 100) return;
      last = now;
      api().avatar.hoverPing();
    };
    window.addEventListener('mousemove', onMove);
    return () => window.removeEventListener('mousemove', onMove);
  }, []);

  // 풀었을 때 막대의 높이(좁은 창에서는 두 줄이 된다) — 말풍선을 그 위로.
  useLayoutEffect(() => {
    const h = dock.current?.offsetHeight;
    if (h && Math.abs(h - dockH) > 1) setDockH(h);
  });

  // 소리 크기만큼 고개가 끄덕이고 빛이 번진다.
  const nod = speaking ? Math.sin(Date.now() / 140) * level * 3 : 0;
  const glow = level > 0.02 ? ` drop-shadow(0 0 ${Math.round(4 + level * 12)}px rgba(91,141,255,${(0.25 + level * 0.4).toFixed(2)}))` : '';
  const L = figure ? layout(W, H, figure, view) : null;
  const hidden = status.hidden;
  const bubbleBottom = locked ? (inset ? inset + 4 : 12) : dockH + 16;
  const now: AvatarStatus = { ...status, recording: recorder.recording, busy, speaking, proactive };

  return (
    <div className={cn('ov-root', hidden && 'avatar-hidden')}>
      <div
        ref={stage}
        className={cn('ov-stage', !locked && 'unlocked', panning && 'panning')}
        onPointerDown={onPanStart}
        onPointerMove={onPanMove}
        onPointerUp={onPanEnd}
        onPointerCancel={onPanEnd}
        onDoubleClick={() => !locked && resetView()}
      >
        {hidden ? null : figure && L ? (
          <div data-hit className={cn('ov-figure', !figure.standing && 'card')} style={{ left: L.left, top: L.top, width: L.width, height: L.height }}>
            {/* 숨(천천히 떠오름)은 바깥에, 끄덕임은 안쪽에 — 한 요소에 둘 다 걸면 CSS 애니메이션이 끄덕임을 덮는다. */}
            <div className={cn('h-full w-full', !panning && 'breathe')}>
              <img
                src={figure.url}
                alt={who.name}
                draggable={false}
                style={{
                  transform: `translateY(${nod}px)`,
                  filter: figure.standing ? `drop-shadow(0 3px 8px rgba(0,0,0,0.24))${glow}` : undefined,
                  boxShadow: figure.standing
                    ? undefined
                    : `0 8px 20px rgba(0,0,0,0.3)${level > 0.02 ? `, 0 0 ${Math.round(6 + level * 14)}px rgba(91,141,255,0.5)` : ''}`,
                }}
              />
            </div>
          </div>
        ) : loading ? null : (
          // 그림이 없으면(아직 안 정했거나 받지 못했다) 블랙모아의 표식을 세운다.
          <img
            data-hit
            src={mark}
            alt={who.name}
            draggable={false}
            className="breathe pointer-events-none absolute left-1/2 object-contain drop-shadow-lg"
            style={{ width: Math.min(W * 0.5, H * 0.45), bottom: RESERVE + 8, marginLeft: -Math.min(W * 0.5, H * 0.45) / 2 }}
          />
        )}
      </div>

      {/* 마이크가 켜져 있다는 것은 언제나 보여야 한다. */}
      {recorder.recording ? (
        <span className="ov-pill">
          <span className="rec" />
          듣는 중
        </span>
      ) : null}

      {bubble && (said || note || busy) ? (
        <div className="ov-subtitle-wrap" style={{ bottom: bubbleBottom }}>
          <Subtitle text={note || said} error={!!note} streaming={!done && !note} thinking={busy && !said && !note} status={working} onRevealed={setRevealed} />
        </div>
      ) : null}

      {locked ? null : (
        <>
          <ResizeFrame />
          <div className="ov-dock">
            <div ref={dock} className="ov-bar" onMouseDown={(e) => startWindowDrag(e, api().avatar.moveBy, api().avatar.commitBounds)}>
              <span className="ov-grip" title="끌어서 옮기기">
                <GripIcon />
              </span>
              <Actions
                s={now}
                on={{
                  mic: () => void recorder.toggle(),
                  speak: () => void api().avatar.setSpeak(!status.speak),
                  write: () => (proactive ? reply() : void api().avatar.openQuick()),
                  chat: openChat,
                  stop,
                  capture: () => api().avatar.capture(),
                }}
              />
              <span className="ov-divider" />
              <IconButton label={hidden ? '사진 보이기' : '사진 숨기기'} onClick={() => void api().avatar.setHidden(!hidden)}>
                {hidden ? <EyeOff size={15} /> : <Eye size={15} />}
              </IconButton>
              <IconButton label="사진 처음 모양으로" onClick={resetView}>
                <RotateCcw size={14} />
              </IconButton>
              <LockButton locked={false} onClick={() => api().avatar.setLocked(true)} />
              <IconButton label="닫기" className="danger" onClick={() => void api().avatar.close()}>
                <X size={15} />
              </IconButton>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

const HANDLES: ResizeEdge[] = ['n', 's', 'w', 'e', 'nw', 'ne', 'sw', 'se'];

/** 풀었을 때의 점선 틀. 여덟 손잡이 중 하나를 끌면 창의 크기가 바뀐다. */
function ResizeFrame() {
  const start = (edge: ResizeEdge) => (e: React.PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture?.(e.pointerId);
    let dx = 0;
    let dy = 0;
    let raf = 0;
    const flush = () => {
      raf = 0;
      if (dx || dy) api().avatar.resizeBy(edge, dx, dy);
      dx = 0;
      dy = 0;
    };
    const move = (ev: PointerEvent) => {
      dx += ev.movementX;
      dy += ev.movementY;
      if (!raf) raf = requestAnimationFrame(flush);
    };
    const up = (ev: PointerEvent) => {
      el.releasePointerCapture?.(ev.pointerId);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (raf) cancelAnimationFrame(raf);
      flush();
      api().avatar.commitBounds();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return (
    <div className="ov-resize-frame">
      <div className="ov-resize-label">휠로 확대 · 끌어서 옮기기</div>
      {HANDLES.map((h) => (
        <div key={h} className={`ov-rh ${h}`} data-edge={h} onPointerDown={start(h)} />
      ))}
    </div>
  );
}

/** 한 글자씩 나오는 말풍선. 새 말이면(앞의 말을 이어 쓴 것이 아니면) 처음부터 다시. */
function Subtitle({
  text,
  error,
  streaming,
  thinking,
  status,
  onRevealed,
}: {
  text: string;
  error: boolean;
  streaming: boolean;
  thinking: boolean;
  /** 답이 오기 전에 하는 일(일정을 확인하는 중 …). */
  status?: string;
  onRevealed: (done: boolean) => void;
}) {
  const [shown, setShown] = useState(0);
  const [visible, setVisible] = useState(false);
  const shownRef = useRef(0);
  const prev = useRef('');
  const body = useRef<HTMLDivElement>(null);
  const full = useRef(text);
  full.current = text;

  // 다음 프레임에 보인다 — 처음부터 보이게 그리면 떠오르는 움직임이 없다.
  useEffect(() => {
    const r = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(r);
  }, []);

  useEffect(() => {
    if (!text.startsWith(prev.current)) {
      shownRef.current = 0;
      setShown(0);
    }
    prev.current = text;
  }, [text]);

  useEffect(() => {
    if (!text) return;
    let raf = 0;
    let last = 0;
    const tick = (ts: number) => {
      const dt = last ? Math.min(0.1, (ts - last) / 1000) : 0;
      last = ts;
      const target = full.current.length;
      let s = shownRef.current;
      if (s < target) {
        // 밀린 글이 많으면 빨라진다 — 답은 다 왔는데 말풍선만 한참 뒤처지지 않게.
        const backlog = target - s;
        const cps = (1000 / CHAR_MS) * (backlog > 160 ? 4 : backlog > 60 ? 2 : 1);
        s = Math.min(target, s + cps * dt);
        if (Math.floor(s) !== Math.floor(shownRef.current)) setShown(Math.floor(s));
        shownRef.current = s;
        raf = requestAnimationFrame(tick);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [text]);

  useEffect(() => {
    body.current?.scrollTo({ top: body.current.scrollHeight });
  }, [shown]);

  const caught = shown >= text.length;
  useEffect(() => onRevealed(caught), [caught, onRevealed]);

  return (
    <div ref={body} data-hit className={cn('ov-subtitle', visible && 'show', error && 'error')}>
      {thinking ? (
        <span className="inline-flex items-center gap-1 py-1">
          {[0, 1, 2].map((i) => (
            <span key={i} className="dot inline-block h-1.5 w-1.5 rounded-full bg-white/80" />
          ))}
          {status && status !== '생각하는 중' && status !== '보내는 중' ? <span className="ml-1.5 text-[12px] text-white/75">{status}</span> : null}
        </span>
      ) : (
        <span>
          {text.slice(0, shown)}
          {streaming || !caught ? <span className="cursor" /> : null}
        </span>
      )}
    </div>
  );
}
