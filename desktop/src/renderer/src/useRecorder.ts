/**
 * 마이크로 말하고 글로 받기.
 *
 * 녹음은 렌더러에서만 할 수 있다(메인에는 마이크가 없다). 바이트가 다 모이면
 * 메인으로 넘기고, 서버로 나가는 것은 거기서 한다.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export interface Recorder {
  recording: boolean;
  error: string;
  toggle(): Promise<void>;
}

export function useRecorder(onDone: (audio: ArrayBuffer, mime: string) => Promise<void> | void): Recorder {
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState('');
  const rec = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);

  // 창이 사라질 때 마이크를 놓아 주지 않으면 표시등이 계속 켜져 있다.
  useEffect(
    () => () => {
      if (rec.current?.state === 'recording') rec.current.stop();
      stream.current?.getTracks().forEach((t) => t.stop());
    },
    [],
  );

  const toggle = useCallback(async () => {
    if (rec.current?.state === 'recording') {
      rec.current.stop();
      return;
    }
    setError('');
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.current = s;
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
      const r = new MediaRecorder(s, { mimeType: mime });
      const parts: Blob[] = [];
      r.ondataavailable = (e) => e.data.size && parts.push(e.data);
      r.onstop = async () => {
        setRecording(false);
        s.getTracks().forEach((t) => t.stop());
        stream.current = null;
        rec.current = null;
        const blob = new Blob(parts, { type: mime });
        // 버튼을 잘못 눌러 생긴 빈 녹음으로 크레딧을 쓰지 않는다.
        if (blob.size < 1200) return;
        await onDone(await blob.arrayBuffer(), mime);
      };
      rec.current = r;
      r.start();
      setRecording(true);
    } catch {
      setError('마이크를 쓸 수 없어요. 시스템 설정에서 이 앱의 마이크 권한을 확인해 주세요.');
      setRecording(false);
    }
  }, [onDone]);

  return { recording, error, toggle };
}
