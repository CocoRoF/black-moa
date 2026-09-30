/**
 * 이 서비스에서 음성을 쓰는가 (plan/67).
 *
 * 관리자가 받아쓰기(STT)·읽어 주기(TTS)를 끄면 앱도 마이크·소리 단추와 그 설정을 감춘다. 값은 서버가
 * 로그인 없이 알려 주는 `/api/auth/status` 의 `voice` 에서 온다(웹과 같은 곳). 계정을 새로 읽을 때마다
 * 함께 묻고, 요청이 "꺼졌어요" 로 돌아오면 그 자리에서 감춘다 — 다음 확인을 기다리며 죽은 단추를 두지 않는다.
 *
 * 앱의 창(틀·아바타·컨트롤·빠른 대화)에 모두 알린다. 세 문의 웹은 스스로 안다. 틀의 상태(state)에는 controller 가
 * 옮겨 적는다 — 여기서 state 를 부르면 대화 모듈(chat)을 검사할 때 Electron 앱이 있어야 한다.
 */
import { BrowserWindow } from 'electron';
import { CH, VOICE_UNKNOWN, type VoiceAvailability } from '@shared/contract';
import { parseJson, sendOnce } from './api';

let now: VoiceAvailability = VOICE_UNKNOWN;
const listeners = new Set<(v: VoiceAvailability) => void>();

export const get = (): VoiceAvailability => now;

export function onChange(fn: (v: VoiceAvailability) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function set(patch: Partial<VoiceAvailability>): void {
  const next = { ...now, ...patch };
  if (next.stt === now.stt && next.tts === now.tts) return;
  now = next;
  for (const w of BrowserWindow.getAllWindows()) if (!w.isDestroyed()) w.webContents.send(CH.voice, now);
  for (const fn of listeners) fn(now);
}

export async function refresh(): Promise<void> {
  try {
    const r = await sendOnce('/api/auth/status');
    if (r.status !== 200) return;
    const v = parseJson<{ voice?: Partial<VoiceAvailability> }>(r)?.voice;
    // 음성을 알리기 전의 서버(옛 판)라면 예전처럼 켜 둔다.
    set({ stt: v ? v.stt === true : true, tts: v ? v.tts === true : true });
  } catch {
    /* 서버에 닿지 않으면 지금 아는 대로 */
  }
}

/** 요청이 "꺼졌어요" 로 돌아왔다. */
export function noteRefusal(code: string | undefined): void {
  if (code === 'stt_disabled') set({ stt: false });
  if (code === 'tts_disabled') set({ tts: false });
}
