/**
 * 아바타의 단추들 (plan/66).
 *
 * 두 곳에서 쓴다: 잠겼을 때는 컨트롤 창(chip.html)에서, 풀었을 때는 아바타 창 바닥의 막대에서. 같은 것을
 * 쓰는 까닭은 둘이 갈리면 "잠갔을 때만 없는 단추" 가 생기고, 사용자는 그것이 뜻한 것인지 고장인지 알 수
 * 없어서다(Dex 의 ActionBar 와 같은 원칙).
 */
import type { ReactNode } from 'react';
import { Lock, LockOpen, MessageCircle, Mic, PenLine, ScanEye, Square, Volume2, VolumeX } from 'lucide-react';
import type { AvatarStatus } from '@shared/contract';
import { cn } from './ui';

export interface ActionHandlers {
  mic(): void;
  speak(): void;
  /** 글로 묻기. 비서가 먼저 말을 걸었으면 [답하기]. */
  write(): void;
  chat(): void;
  stop(): void;
  /** 화면 보여주기(plan/70): 찍어서 빠른 대화에 붙여 연다. */
  capture(): void;
}

export function Actions({ s, on }: { s: AvatarStatus; on: ActionHandlers }) {
  return (
    <>
      {/* 관리자가 음성을 끄면 그 단추는 없다(plan/67). 듣는 중이면 끌 수는 있어야 한다. */}
      {s.stt || s.recording ? (
        <IconButton label={s.recording ? '말을 마쳤어요' : '말하기'} className={s.recording ? 'rec' : undefined} onClick={on.mic}>
          <Mic size={15} />
        </IconButton>
      ) : null}
      {s.tts ? (
        <IconButton label={s.speak ? '소리 끄기' : '소리 켜기'} className={s.speak ? 'on' : undefined} onClick={on.speak}>
          {s.speak ? <Volume2 size={15} /> : <VolumeX size={15} />}
        </IconButton>
      ) : null}
      {s.proactive ? (
        <button type="button" className="ov-reply" title="답하기" aria-label="답하기" onClick={on.write}>
          <PenLine size={13} />
          답하기
        </button>
      ) : (
        <IconButton label="글로 묻기" onClick={on.write}>
          <PenLine size={15} />
        </IconButton>
      )}
      {s.capture ? (
        <IconButton label="화면 보여주기" onClick={on.capture}>
          <ScanEye size={15} />
        </IconButton>
      ) : null}
      <IconButton label="대화 전체 보기" onClick={on.chat}>
        <MessageCircle size={15} />
      </IconButton>
      {s.busy || s.speaking ? (
        <IconButton label="그만" onClick={on.stop}>
          <Square size={12} fill="currentColor" />
        </IconButton>
      ) : null}
    </>
  );
}

export function LockButton({ locked, onClick }: { locked: boolean; onClick: () => void }) {
  return (
    <IconButton label={locked ? '잠금 풀기' : '잠그기'} onClick={onClick}>
      {locked ? <Lock size={15} /> : <LockOpen size={15} />}
    </IconButton>
  );
}

export function IconButton({ label, onClick, className, children }: { label: string; onClick: () => void; className?: string; children: ReactNode }) {
  return (
    <button type="button" title={label} aria-label={label} onClick={onClick} className={cn('ov-icon-btn', className)}>
      {children}
    </button>
  );
}

export function GripIcon() {
  return (
    <svg width="12" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      {[6, 12, 18].map((cy) => (
        <g key={cy}>
          <circle cx="9" cy={cy} r="1.7" />
          <circle cx="15" cy={cy} r="1.7" />
        </g>
      ))}
    </svg>
  );
}

/**
 * 누른 채 끌면 창이 따라온다(끝나면 자리를 적는다). 단추를 누른 것은 끌기가 아니다.
 * 한 프레임에 한 번만 보낸다 — 마우스는 1초에 수백 번 움직인다.
 */
export function startWindowDrag(e: React.MouseEvent, moveBy: (dx: number, dy: number) => void, commit: () => void): void {
  if (e.button !== 0 || (e.target as HTMLElement).closest('button')) return;
  e.preventDefault();
  let dx = 0;
  let dy = 0;
  let raf = 0;
  const flush = () => {
    raf = 0;
    if (dx || dy) moveBy(dx, dy);
    dx = 0;
    dy = 0;
  };
  const move = (ev: MouseEvent) => {
    dx += ev.movementX;
    dy += ev.movementY;
    if (!raf) raf = requestAnimationFrame(flush);
  };
  const up = () => {
    window.removeEventListener('mousemove', move);
    window.removeEventListener('mouseup', up);
    if (raf) cancelAnimationFrame(raf);
    flush();
    commit();
  };
  window.addEventListener('mousemove', move);
  window.addEventListener('mouseup', up);
}
