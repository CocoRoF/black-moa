"use client";
import { memo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import { Check, Copy } from "@/components/icons";
import { copyText, cn } from "@/lib/utils";

const schema = {
  ...defaultSchema,
  attributes: { ...defaultSchema.attributes, code: [...(defaultSchema.attributes?.code ?? []), ["className", /^language-./]], a: [...(defaultSchema.attributes?.a ?? []), "target", "rel"] },
};

function Pre({ children }: { children?: ReactNode }) {
  const [ok, setOk] = useState(false);
  const getText = (n: unknown): string => {
    if (typeof n === "string") return n;
    if (Array.isArray(n)) return n.map(getText).join("");
    if (n && typeof n === "object" && "props" in n) return getText((n as { props: { children?: unknown } }).props.children);
    return "";
  };
  return (
    <div className="relative group">
      <pre>{children}</pre>
      <button type="button" aria-label="copy code" onClick={async () => { if (await copyText(getText(children))) { setOk(true); setTimeout(() => setOk(false), 1500); } }}
        className="absolute right-2 top-2 rounded-md bg-white/10 p-1.5 text-white/80 opacity-80 hover:bg-white/20 group-hover:opacity-100 min-h-0">
        {ok ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

function MarkdownInner({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("prose-chat", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeSanitize, schema]]}
        components={{
          a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer nofollow">{children}</a>,
          pre: ({ children }) => <Pre>{children}</Pre>,
        }}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
export default memo(MarkdownInner);
