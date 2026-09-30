import { useCallback, useEffect, useRef } from 'react';

/** mp3 를 틀고, 그 크기를 매 프레임 재어 알려 준다. 얼굴이 소리에 반응하는 근거. */
export function useVoice(onLevel: (v: number) => void, onEnd: () => void) {
  const ctx = useRef<AudioContext | null>(null);
  const src = useRef<AudioBufferSourceNode | null>(null);
  const frame = useRef(0);

  const stop = useCallback(() => {
    cancelAnimationFrame(frame.current);
    try {
      src.current?.stop();
    } catch {
      /* 이미 끝났을 수 있다 */
    }
    src.current = null;
    onLevel(0);
  }, [onLevel]);

  useEffect(() => () => stop(), [stop]);

  const play = useCallback(
    async (mp3: ArrayBuffer) => {
      stop();
      ctx.current ??= new AudioContext();
      const ac = ctx.current;
      if (ac.state === 'suspended') await ac.resume();
      const buf = await ac.decodeAudioData(mp3.slice(0));
      const node = ac.createBufferSource();
      node.buffer = buf;
      const analyser = ac.createAnalyser();
      analyser.fftSize = 256;
      node.connect(analyser);
      analyser.connect(ac.destination);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        // 128 이 무음이다. 평균 절댓값이 곧 소리의 크기.
        let sum = 0;
        for (const v of data) sum += Math.abs(v - 128);
        onLevel(Math.min(1, sum / data.length / 34));
        frame.current = requestAnimationFrame(tick);
      };
      node.onended = () => {
        cancelAnimationFrame(frame.current);
        onLevel(0);
        onEnd();
      };
      src.current = node;
      node.start();
      tick();
    },
    [onEnd, onLevel, stop],
  );

  return { play, stop };
}
