/**
 * 비서에게 묻기 — 아바타가 쓴다(빠른 대화에서 한 말도 아바타가 받는다, plan/69).
 *
 * 말은 **그 비서의 가장 최근 대화에 그대로 쌓인다.** 앱에만 남는 대화를 따로 두면 접속기가 아니다.
 * 본창의 대화 문을 열면 방금 한 말과 답이 거기 있다(웹이 다시 보일 때 기록을 새로 받는다).
 *
 * 답은 메인에서 흐른다(stream.ts). 창을 닫아도 끊기지 않고, 다시 열면 받던 답이 그대로 보인다.
 */
import { randomUUID } from 'node:crypto';
import type { Answer, TurnEvent } from '@shared/contract';
import * as auth from './auth';
import * as strm from './stream';
import { ApiError, toError } from './api';
import * as voice from './voice';

/** 그 비서의 가장 최근 대화. 없으면 하나 연다. */
export async function conversationFor(agentId: string): Promise<string> {
  // 웹이 여는 것과 같은 대화: 주인과 비서의 대화 가운데 가장 최근 것(plan/69). 거르지 않으면 방문자·비서끼리의
  // 대화에 주인의 말을 넣을 수 있었다.
  const r = await auth.call<{ items?: { id: string }[] }>('GET', `/api/agents/${agentId}/conversations?audience=owner`);
  const found = r?.items?.[0]?.id;
  if (found) return found;
  const made = await auth.call<{ id: string }>('POST', `/api/agents/${agentId}/conversations`, { title: '' });
  return made.id;
}

/** 이벤트 하나를 받아 답을 한 걸음 옮긴다. 순수 함수라 시험할 수 있다. */
export function step(a: Answer, ev: TurnEvent): Answer {
  const d = (ev.data ?? {}) as Record<string, unknown>;
  switch (ev.type) {
    case 'text.delta':
      return { ...a, text: a.text + (typeof d.text === 'string' ? d.text : ''), status: '' };
    case 'thinking.status':
      return a.text ? a : { ...a, status: d.active ? '생각하는 중' : a.status };
    case 'thinking.delta':
      return a.text ? a : { ...a, status: '생각하는 중' };
    case 'tool.start': {
      // 서버가 사람 말로 된 이름을 준다. 도구의 속 이름(영문)은 보여 주지 않는다.
      const label = String(d.label || '').trim();
      return { ...a, status: /[가-힣]/.test(label) ? label : '확인하는 중' };
    }
    case 'tool.end':
      return a;
    case 'turn.complete':
      return { ...a, text: typeof d.answer === 'string' && d.answer ? d.answer : a.text, status: '', done: true };
    case 'turn.error':
      return { ...a, status: '', done: true, error: typeof d.message === 'string' && /[가-힣]/.test(d.message) ? d.message : '답을 받지 못했어요.' };
    case 'turn.cancelled':
      return { ...a, status: '', done: true };
    default:
      return a;
  }
}

/** 묻는 곳 하나. 답 하나를 들고, 바뀔 때마다 알린다. */
export class Asker {
  private answer: Answer | null = null;
  private runId: string | null = null;
  private listeners = new Set<(a: Answer | null) => void>();

  current(): Answer | null {
    return this.answer;
  }

  on(fn: (a: Answer | null) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private set(a: Answer | null): void {
    this.answer = a;
    for (const fn of this.listeners) fn(a);
  }

  async ask(agentId: string, text: string, uploadIds: string[] = []): Promise<void> {
    const q = text.trim();
    if (!q) return;
    // 앞 답은 이쪽에서만 놓는다. 서버에 "멈춰" 를 보내면 그 요청이 새 물음보다 늦게 닿아 새 답을 멈출 수 있다 —
    // 같은 대화에 새 물음이 들어가면 서버가 앞 답을 스스로 멈춘다.
    if (this.runId) strm.detach(this.runId);
    this.runId = null;
    const id = randomUUID();
    this.set({ id, agentId, conversationId: null, question: q, text: '', status: '보내는 중', done: false });
    let cid: string;
    try {
      cid = await conversationFor(agentId);
    } catch (e) {
      if (this.answer?.id === id) this.set({ ...this.answer, status: '', done: true, error: e instanceof Error ? e.message : '말을 전하지 못했어요.' });
      return;
    }
    if (this.answer?.id !== id) return; // 그사이 새로 물었다
    this.set({ ...this.answer, conversationId: cid, status: '생각하는 중' });
    const h = strm.run({
      agentId,
      conversationId: cid,
      text: q,
      uploadIds,
      onEvent: (ev) => {
        if (this.answer?.id === id) this.set(step(this.answer, ev));
      },
      onDone: (ok, error) => {
        if (this.runId === h.runId) this.runId = null;
        if (this.answer?.id !== id) return;
        if (!this.answer.done || (!ok && !this.answer.error)) {
          this.set({ ...this.answer, status: '', done: true, error: ok ? this.answer.error : error });
        }
      },
    });
    this.runId = h.runId;
  }

  stop(): void {
    if (this.runId) strm.cancel(this.runId);
    this.runId = null;
    if (this.answer && !this.answer.done) this.set({ ...this.answer, status: '', done: true });
  }

  clear(): void {
    this.stop();
    this.set(null);
  }
}

/** 곁의 비서(아바타). 빠른 대화의 말도 여기로 온다(plan/69). */
export const avatar = new Asker();

/** 관리자가 음성을 껐다는 답이면 앱도 그 단추를 바로 감춘다(plan/67). */
function refused(e: ApiError): ApiError {
  voice.noteRefusal(e.code);
  return e;
}

/** 녹음을 글로. 그 비서의 받아쓰기 설정(언어)을 서버가 쓴다. */
export async function transcribe(agentId: string, audio: ArrayBuffer, mime: string): Promise<{ text: string }> {
  const boundary = `----memora${Date.now().toString(16)}`;
  const head = Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.webm"\r\nContent-Type: ${mime}\r\n\r\n`,
  );
  const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
  const data = Buffer.concat([head, Buffer.from(audio), tail]);
  const r = await auth.authed('POST', `/api/agents/${agentId}/stt`, undefined, {
    data,
    contentType: `multipart/form-data; boundary=${boundary}`,
  });
  if (r.status >= 400) throw refused(toError(r));
  return JSON.parse(r.body.toString('utf8')) as { text: string };
}

/** 찍은 화면을 올린다(plan/70) — 물음에 붙일 첨부 번호. 대화의 다른 첨부와 같은 길(`/api/uploads`)이다. */
export async function uploadImage(jpeg: Buffer, filename = 'screen.jpg'): Promise<string> {
  const boundary = `----memora${Date.now().toString(16)}`;
  const parts = [
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="kind"\r\n\r\nattachment\r\n`),
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: image/jpeg\r\n\r\n`),
    jpeg,
    Buffer.from(`\r\n--${boundary}--\r\n`),
  ];
  const r = await auth.authed('POST', '/api/uploads', undefined, { data: Buffer.concat(parts), contentType: `multipart/form-data; boundary=${boundary}` });
  if (r.status >= 400) throw toError(r);
  return (JSON.parse(r.body.toString('utf8')) as { upload_id: string }).upload_id;
}

/** 글을 그 비서의 목소리로. mp3 바이트. */
export async function speak(agentId: string, text: string): Promise<ArrayBuffer> {
  const r = await auth.authed('POST', `/api/agents/${agentId}/tts`, { text: text.slice(0, 700) });
  if (r.status >= 400) throw refused(toError(r));
  // 구조화 복제로 넘어가도록 바이트만 넘긴다.
  return r.body.buffer.slice(r.body.byteOffset, r.body.byteOffset + r.body.byteLength) as ArrayBuffer;
}
