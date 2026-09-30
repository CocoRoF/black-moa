"use client";
/** iOS-safe audio playback: decodeAudioData + AudioBufferSourceNode, gesture-driven resume. */
let ctx: AudioContext | null = null;
let current: AudioBufferSourceNode | null = null;
const queue: ArrayBuffer[] = [];
let playing = false;

export function getAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (!ctx) {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
  }
  return ctx;
}

/** Call from a user gesture (tap) to unlock audio on iOS. */
export async function unlockAudio() {
  const c = getAudioContext();
  if (!c) return;
  if (c.state === "suspended") { try { await c.resume(); } catch { /* ignore */ } }
  try {
    const b = c.createBuffer(1, 1, 22050);
    const s = c.createBufferSource(); s.buffer = b; s.connect(c.destination); s.start(0);
  } catch { /* ignore */ }
}

async function playNext() {
  const c = getAudioContext();
  if (!c || playing) return;
  const buf = queue.shift();
  if (!buf) return;
  playing = true;
  try {
    if (c.state === "suspended") await c.resume();
    const audio = await c.decodeAudioData(buf.slice(0));
    await new Promise<void>((resolve) => {
      const src = c.createBufferSource();
      src.buffer = audio; src.connect(c.destination);
      src.onended = () => resolve();
      current = src; src.start(0);
    });
  } catch { /* skip chunk */ }
  finally { playing = false; current = null; void playNext(); }
}

export function enqueueAudio(buf: ArrayBuffer) { queue.push(buf); void playNext(); }
export function stopAudio() { queue.length = 0; try { current?.stop(); } catch { /* ignore */ } current = null; playing = false; }
export function isAudioPlaying() { return playing || queue.length > 0; }

/** Split text into sentence-ish chunks for progressive TTS. */
export function splitSentences(text: string, max = 240): string[] {
  const clean = text.replace(/```[\s\S]*?```/g, " ").replace(/[*_`#>|]/g, "").replace(/\s+/g, " ").trim();
  if (!clean) return [];
  const parts = clean.split(/(?<=[.!?。！？]|다\.|요\.)\s+/);
  const out: string[] = [];
  let cur = "";
  for (const p of parts) {
    if ((cur + " " + p).trim().length > max && cur) { out.push(cur.trim()); cur = p; } else cur = (cur + " " + p).trim();
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

export function pickRecorderMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  for (const m of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4;codecs=mp4a.40.2", "audio/mp4", "audio/ogg;codecs=opus"]) {
    try { if (MediaRecorder.isTypeSupported(m)) return m; } catch { /* ignore */ }
  }
  return "";
}
