"use client";
import Link from "next/link";
import Image from "next/image";
import { ArrowLeft } from "@/components/icons";
import { LocaleProvider, useT } from "@/lib/i18n";
import { useBrowserLocale } from "@/lib/hooks";
import { Wordmark } from "@/components/brand/Logo";
import type { BlogPost } from "@/lib/api";

export interface PostPayload { handle: string; display_name: string; avatar_url: string | null; indexable?: boolean; post: BlogPost }

/** The date, drawn the same way on the server and in the browser.
 *
 *  `toLocaleString` does not agree with itself across the two: the server has no browser
 *  locale or timezone, so a published date rendered that way arrives as one string and
 *  hydrates as another, and React throws the page away and redraws it. The published day
 *  is a fact, not a moment, so it is written out plainly.
 */
function dateLabel(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getUTCFullYear()}. ${d.getUTCMonth() + 1}. ${d.getUTCDate()}.`;
}

/** One post, read by anybody the author let in (plan/41 §4). */
export function PostPage({ data }: { data: PostPayload }) {
  const locale = useBrowserLocale();
  return <LocaleProvider locale={locale}><Inner data={data} /></LocaleProvider>;
}

function Inner({ data }: { data: PostPayload }) {
  const t = useT();
  const p = data.post;
  return (
    <div className="min-h-dvh bg-bg">
      <header className="border-b border-border">
        <div className="mx-auto flex w-full max-w-[720px] items-center justify-between px-5 py-3">
          <Link href={`/@${data.handle}`} className="flex items-center gap-2 text-sm font-medium hover:opacity-80">
            <ArrowLeft className="h-4 w-4" />
            {data.avatar_url ? <Image src={data.avatar_url} alt="" width={24} height={24} unoptimized className="h-6 w-6 rounded-full object-cover" /> : null}
            {data.display_name}
          </Link>
          <Link href="/" aria-label="Memora"><Wordmark size={16} /></Link>
        </div>
      </header>
      <article className="mx-auto w-full max-w-[720px] px-5 py-10">
        {p.kind === "note" ? null : <h1 className="text-[28px] font-semibold leading-tight tracking-tight">{p.title}</h1>}
        <p className={p.kind === "note" ? "text-sm text-muted-fg" : "mt-2 text-sm text-muted-fg"}>
          {p.published_at ? <time dateTime={p.published_at}>{dateLabel(p.published_at)}</time> : null}
          {p.visibility === "friends" ? ` · ${t("blog.vis_friends")}` : ""}
        </p>
        {p.images?.length ? (
          <div className="mt-6 space-y-3">
            {p.images.map((u) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={u} src={u} alt="" className="w-full rounded-2xl bg-muted" />
            ))}
          </div>
        ) : null}
        {/* Plain text, deliberately: what the author typed, with their line breaks kept. */}
        {p.body ? <div className="mt-7 whitespace-pre-wrap text-[17px] leading-[1.8]">{p.body}</div> : null}
      </article>
      <footer className="mx-auto w-full max-w-[720px] px-5 pb-16">
        <Link href={`/@${data.handle}`} className="inline-flex items-center gap-2 rounded-xl border border-border px-4 py-2.5 text-sm hover:border-accent hover:text-accent">
          <ArrowLeft className="h-4 w-4" />{t("blog.back_to_person", { name: data.display_name })}
        </Link>
      </footer>
    </div>
  );
}
