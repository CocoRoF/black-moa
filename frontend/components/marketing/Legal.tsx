/**
 * 이용약관·개인정보 처리방침 (plan/73).
 *
 * 서버에서 그린다 — 검색엔진과 스크립트를 끈 브라우저에도 전문이 보여야 하는 문서다. 본문은 서버가 준
 * 마크다운(관리자가 넣은 것 또는 기본 문서에 운영자 정보를 채운 것)이다. 시행일을 맨 위에 둔다.
 */
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";

export type LegalKind = "terms" | "privacy";

export interface LegalPayload {
  terms: string;
  privacy: string;
  version: string;
  effective_date: string;
  service: string;
  operator: Record<string, string>;
}

const INTERNAL = () => process.env.INTERNAL_API_URL ?? "http://127.0.0.1:8123";

export async function fetchLegal(): Promise<LegalPayload | null> {
  try {
    const r = await fetch(`${INTERNAL()}/api/public/legal`, { cache: "no-store", headers: { Accept: "application/json" } });
    if (!r.ok) return null;
    return (await r.json()) as LegalPayload;
  } catch {
    return null;
  }
}

const TITLE: Record<LegalKind, string> = { terms: "이용약관", privacy: "개인정보 처리방침" };

export function LegalDoc({ kind, data }: { kind: LegalKind; data: LegalPayload | null }) {
  const md = data?.[kind] ?? "";
  const other: LegalKind = kind === "terms" ? "privacy" : "terms";
  return (
    <article className="mx-auto max-w-3xl px-4 py-10 sm:py-14">
      <header className="border-b border-border pb-6">
        <p className="text-sm font-medium text-accent">{data?.service ?? "Memora"}</p>
        <h1 className="mt-1 text-[28px] font-bold tracking-tight">{TITLE[kind]}</h1>
        {data ? <p className="mt-2 text-sm text-muted-fg">시행일 {data.effective_date}</p> : null}
        <p className="mt-3 text-sm">
          <Link href={`/${other}`} className="text-muted-fg underline underline-offset-2 hover:text-fg">{TITLE[other]} 보기</Link>
        </p>
      </header>
      {!md ? (
        <p className="mt-8 text-muted-fg">문서를 불러오지 못했어요. 잠시 후 다시 열어 주세요.</p>
      ) : (
        <div className="legal-doc mt-8">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}
              components={{
                table: ({ children }) => <div className="legal-table"><table>{children}</table></div>,
                a: ({ href, children }) => {
                  const external = !!href && /^https?:/.test(href);
                  return <a href={href} {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{children}</a>;
                },
              }}>
              {md}
            </ReactMarkdown>
        </div>
      )}
    </article>
  );
}
