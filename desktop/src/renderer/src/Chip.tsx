/**
 * 잠긴 아바타의 컨트롤 창 (plan/66).
 *
 * 잠긴 아바타 창은 클릭을 뒤로 흘려보내므로 자기 단추를 담을 수 없다. 단추는 사진 아래에 붙어 다니는 이
 * 작은 창에 산다. 마우스가 아바타 위에 있을 때만 나온다(메인이 커서를 보고 알린다). 단추가 아닌 곳을 잡고 끌면 아바타가 따라 움직인다 — 자리를 옮기려고 잠금을 풀었다 다시
 * 잠글 까닭이 없다.
 *
 * 창은 내용에 꼭 맞춘다(메인에게 크기를 알린다). 작으면 단추가 잘리고, 크면 남는 투명한 자리가 데스크톱
 * 클릭을 먹는다.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { IDLE_STATUS, type AvatarStatus } from '@shared/contract';
import { api } from './bridge';
import { Actions, LockButton, startWindowDrag } from './avatar-actions';
import { cn } from './ui';

export function ChipWindow() {
  const [s, setS] = useState<AvatarStatus>(IDLE_STATUS);
  const [shown, setShown] = useState(false);
  useEffect(() => api().chip.onReveal(setShown), []);
  const bar = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void api().chip.status().then(setS);
    return api().chip.onStatus(setS);
  }, []);

  useLayoutEffect(() => {
    const report = () => {
      const r = bar.current?.getBoundingClientRect();
      if (r && r.width > 0 && r.height > 0) api().chip.reportSize(Math.ceil(r.width) + 2, Math.ceil(r.height) + 2);
    };
    report();
    // 배율이 바뀌어도 크기 소식은 오지 않는다. 가끔 다시 잰다.
    const t = setInterval(report, 1500);
    window.addEventListener('resize', report);
    return () => {
      clearInterval(t);
      window.removeEventListener('resize', report);
    };
  }, [s]);

  const chip = api().chip;
  return (
    <div
      // 나오고 숨는 것은 메인이 이 창을 띄우고 내리는 것으로 한다(plan/70) — 페이지는 늘 보이는 모양으로 그려 둔다.
      // 가려졌다고 여겨져 다시 그리지 못해도 뜨는 순간 이 모양이 보인다. 나올 때만 살짝 떠오른다.
      className={cn('grid h-screen w-screen place-items-center', shown && 'fade-up')}
      data-shown={shown ? '1' : '0'}
      onMouseEnter={() => chip.reportHover(true)}
      onMouseLeave={() => chip.reportHover(false)}
    >
      <div
        ref={bar}
        className="ov-bar"
        // 그림자는 두지 않는다 — 창이 알약에 꼭 맞아 그림자가 네모나게 잘려 보인다.
        style={{ width: 'max-content', flexWrap: 'nowrap', boxShadow: 'none' }}
        title="끌어서 옮기기"
        onMouseDown={(e) => startWindowDrag(e, chip.moveBy, chip.commitBounds)}
      >
        <Actions
          s={s}
          on={{
            mic: () => chip.command('mic'),
            speak: () => chip.command('toggle-speak'),
            write: () => (s.proactive ? chip.command('reply') : void chip.openQuick()),
            chat: () => void chip.openChat(),
            stop: () => chip.command('stop'),
            capture: () => chip.command('capture'),
          }}
        />
        <span className="ov-divider" />
        <LockButton locked onClick={() => chip.unlock()} />
      </div>
    </div>
  );
}
