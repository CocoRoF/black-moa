"use client";
import dynamic from "next/dynamic";

const Inner = dynamic(() => import("./MarkdownInner"), { ssr: false, loading: () => null });

export function Markdown({ text, className }: { text: string; className?: string }) {
  if (!text) return null;
  return <Inner text={text} className={className} />;
}
