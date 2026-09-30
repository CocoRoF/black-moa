/**
 * 빠른 대화의 답을 읽기 좋게. 웹의 마크다운만큼은 아니고, 답에 흔히 나오는 것만: 문단, 목록, 굵게, 코드,
 * 링크, 머리말. HTML 은 받지 않는다(글자로 보인다) — 서버가 준 글을 그대로 DOM 에 넣지 않기 위해서다.
 */
import type { ReactNode } from 'react';

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  // 코드 → 링크 → 굵게 순서로 한 번에 가른다.
  const re = /(`[^`\n]+`)|(\[[^\]\n]+\]\((https?:\/\/[^)\s]+)\))|(\*\*[^*\n]+\*\*)|(https?:\/\/[^\s)]+)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const k = `${key}-${i++}`;
    if (m[1]) out.push(<code key={k}>{m[1].slice(1, -1)}</code>);
    else if (m[2]) {
      const label = m[2].slice(1, m[2].indexOf(']('));
      out.push(
        <a key={k} href={m[3]} target="_blank" rel="noreferrer">
          {label}
        </a>,
      );
    } else if (m[4]) out.push(<strong key={k}>{m[4].slice(2, -2)}</strong>);
    else if (m[5]) {
      out.push(
        <a key={k} href={m[5]} target="_blank" rel="noreferrer">
          {m[5]}
        </a>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  let i = 0;
  let n = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++]);
      i++;
      blocks.push(
        <pre key={n++}>
          <code>{body.join('\n')}</code>
        </pre>,
      );
      continue;
    }
    if (/^\s*[-*•]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*•]\s+/, ''));
      blocks.push(
        <ul key={n++}>
          {items.map((t, j) => (
            <li key={j}>{inline(t, `u${n}-${j}`)}</li>
          ))}
        </ul>,
      );
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+[.)]\s+/, ''));
      blocks.push(
        <ol key={n++}>
          {items.map((t, j) => (
            <li key={j}>{inline(t, `o${n}-${j}`)}</li>
          ))}
        </ol>,
      );
      continue;
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push(<h3 key={n++}>{inline(h[2], `h${n}`)}</h3>);
      i++;
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^```|^\s*[-*•]\s+|^\s*\d+[.)]\s+|^#{1,3}\s/.test(lines[i])) para.push(lines[i++]);
    blocks.push(
      <p key={n++}>
        {para.map((t, j) => (
          <span key={j}>
            {j > 0 ? <br /> : null}
            {inline(t, `p${n}-${j}`)}
          </span>
        ))}
      </p>,
    );
  }
  return <div className="md">{blocks}</div>;
}
