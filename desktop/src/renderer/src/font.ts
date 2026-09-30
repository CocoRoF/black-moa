/**
 * 글꼴은 앱에 함께 싣는다. 서버에 못 닿을 때도 틀은 메모라의 글씨(Pretendard)로 말해야 한다.
 */
import url from 'pretendard/dist/web/variable/woff2/PretendardVariable.woff2?url';

try {
  const face = new FontFace('Pretendard Variable', `url(${url}) format('woff2-variations')`, { weight: '45 920', display: 'swap' });
  document.fonts.add(face);
  void face.load().catch(() => {});
} catch {
  /* 글꼴이 없어도 시스템 글꼴로 그린다 */
}
