/**
 * 틀·아바타·빠른 대화가 함께 쓰는 작은 조각들. 메모라 웹의 모양을 한 단계 작게.
 */
import { useEffect, useState, type ReactNode } from 'react';
import { VOICE_UNKNOWN, type VoiceAvailability } from '@shared/contract';
import { asset } from './asset';
import { api } from './bridge';

export const cn = (...xs: (string | false | null | undefined)[]): string => xs.filter(Boolean).join(' ');

/** 이 서비스에서 음성을 쓰는가(plan/67). 알기 전에는 감춘다. */
export function useVoiceAvailability(): VoiceAvailability {
  const [v, setV] = useState<VoiceAvailability>(VOICE_UNKNOWN);
  useEffect(() => {
    void api().voice().then(setV).catch(() => {});
    return api().onVoice(setV);
  }, []);
  return v;
}

/** 얼굴. 사진이 없으면 이름의 첫 글자. */
export function Face({ src, name, size = 24, ring }: { src?: string | null; name?: string; size?: number; ring?: boolean }) {
  const style = { width: size, height: size };
  if (src) {
    return (
      <img
        src={asset(src)}
        alt=""
        draggable={false}
        className={cn('shrink-0 rounded-full object-cover', ring && 'ring-2 ring-accent ring-offset-1 ring-offset-card')}
        style={style}
      />
    );
  }
  return (
    <span
      className={cn('inline-flex shrink-0 items-center justify-center rounded-full bg-accent-soft font-semibold text-accent', ring && 'ring-2 ring-accent')}
      style={{ ...style, fontSize: Math.max(10, size * 0.42) }}
    >
      {(name || '비').slice(0, 1)}
    </span>
  );
}

export function Switch({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={cn('relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-40', on ? 'bg-accent' : 'bg-border')}
    >
      <span className={cn('inline-block h-4 w-4 rounded-full bg-white shadow transition-transform', on ? 'translate-x-[18px]' : 'translate-x-0.5')} />
    </button>
  );
}

export function Dots() {
  return (
    <span className="inline-flex items-center gap-[3px]">
      {[0, 1, 2].map((i) => (
        <span key={i} className="dot inline-block h-1 w-1 rounded-full bg-current" />
      ))}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-border bg-card px-1 py-px font-sans text-[10.5px] leading-none text-muted-fg">{children}</kbd>;
}

/** 단축키를 사람이 읽는 모양으로. */
export function prettyKeys(accel: string, platform: string): string {
  if (!accel) return '';
  const mac = platform === 'darwin';
  return accel
    .split('+')
    .map((k) => {
      if (k === 'CommandOrControl' || k === 'CmdOrCtrl') return mac ? '⌘' : 'Ctrl';
      if (k === 'Command' || k === 'Cmd') return '⌘';
      if (k === 'Control' || k === 'Ctrl') return mac ? '⌃' : 'Ctrl';
      if (k === 'Alt' || k === 'Option') return mac ? '⌥' : 'Alt';
      if (k === 'Shift') return mac ? '⇧' : 'Shift';
      if (k === 'Super' || k === 'Meta') return mac ? '⌘' : 'Win';
      if (k === 'Space') return mac ? 'Space' : 'Space';
      return k;
    })
    .join(mac ? '' : '+');
}

/** "방금 · 5분 전 · 3시간 전 · 어제 · 9월 3일". */
export function ago(iso: string): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return '';
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return '방금';
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  if (s < 172800) return '어제';
  const d = new Date(t);
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}
