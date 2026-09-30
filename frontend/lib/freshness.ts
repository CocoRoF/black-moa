"use client";
/** 열려 있는 탭이 옛 번들을 물고 있는지 본다.
 *
 *  배포는 새 번들을 올릴 뿐이고, 그 순간 열려 있던 탭은 옛 코드를 계속 돌린다.
 *  고쳐 놓은 버그를 그 탭만 계속 겪고, 쓰는 사람은 그것을 알 길이 없다.
 *
 *  강제로 새로고침하지 않는다. 쓰다 만 글이 사라지는 것이 낡은 화면보다 나쁘다.
 *  한 줄로 알리고, 누르면 그때 새로고침한다. */
const URL_ = "/build-id";
const EVERY = 5 * 60 * 1000;

let first = "";
let last = 0;
let told = false;

async function read(): Promise<string> {
  const r = await fetch(URL_, { cache: "no-store" });
  if (!r.ok) throw new Error(String(r.status));
  return (await r.text()).trim().slice(0, 100);
}

/** 한 번 확인한다. 바뀌었으면 `onStale` 을 **한 번만** 부른다. */
export async function checkFreshness(onStale: () => void, force = false) {
  if (told) return;
  const now = Date.now();
  if (!force && now - last < EVERY) return;
  last = now;
  try {
    const id = await read();
    if (!id) return;
    if (!first) { first = id; return; }
    if (id !== first) { told = true; onStale(); }
  } catch { /* 못 물어봤으면 다음 기회에 */ }
}

/** 탭이 다시 보일 때와 스트림이 다시 붙을 때 확인한다. 둘 다 배포 직후에 일어난다. */
export function watchFreshness(onStale: () => void): () => void {
  void checkFreshness(onStale, true);
  const onVisible = () => { if (document.visibilityState === "visible") void checkFreshness(onStale); };
  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("focus", onVisible);
  return () => {
    document.removeEventListener("visibilitychange", onVisible);
    window.removeEventListener("focus", onVisible);
  };
}
