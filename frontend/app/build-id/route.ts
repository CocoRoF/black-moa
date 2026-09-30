/** 이 화면이 지금 서 있는 건물의 번호.
 *
 *  배포는 새 번들을 올리지만, 열려 있던 탭은 옛 번들을 그대로 물고 돈다. 그 탭은
 *  고쳐 놓은 버그를 계속 겪는다 — 실제로 하루 종일 401 을 만들던 탭이 그랬다.
 *  화면은 처음 본 값을 기억해 두었다가 이 값이 달라지면 새로고침을 권한다.
 *
 *  빌드마다 달라지고 배포하지 않으면 그대로인 값이어야 하므로 Next 의 빌드 id 를
 *  쓴다. 백엔드의 재시작 같은 것으로는 바뀌지 않는다. */
import { readFile } from "node:fs/promises";

export const dynamic = "force-dynamic";

let cached = "";

export async function GET() {
  if (!cached) {
    try {
      cached = (await readFile(".next/BUILD_ID", "utf8")).trim();
    } catch {
      cached = "dev";
    }
  }
  return new Response(cached, {
    headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
  });
}
