import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PostPage, type PostPayload } from "@/components/public/PostPage";

/** One post on somebody's own page (plan/41 §4). Reached as `/@handle/{slug}`; see the
 *  rewrite in next.config for why the address does not live at that path. */
const INTERNAL = () => process.env.INTERNAL_API_URL ?? "http://127.0.0.1:8123";
const HANDLE = /^[a-z0-9][a-z0-9-]{1,31}$/i;

/** A slug can reach this page already percent-encoded — a Korean title makes a Korean
 *  address — and encoding it a second time asks the backend for a post that does not
 *  exist. Decoding first is safe either way: a decoded slug decodes to itself. */
function once(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

async function fetchPost(handle: string, slug: string): Promise<PostPayload | null> {
  if (!HANDLE.test(handle) || !slug) return null;
  try {
    const r = await fetch(`${INTERNAL()}/api/public/people/${encodeURIComponent(handle)}/posts/${encodeURIComponent(once(slug))}`,
                          { cache: "no-store", headers: { Accept: "application/json" } });
    if (!r.ok) return null;
    return (await r.json()) as PostPayload;
  } catch {
    return null;
  }
}

type Params = { params: Promise<{ handle: string; slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { handle, slug } = await params;
  const data = await fetchPost(handle, slug);
  if (!data) return { robots: { index: false } };
  const site = process.env.PUBLIC_URL || process.env.BLACKMOA_PUBLIC_URL || process.env.NEXT_PUBLIC_URL;
  const url = `/@${data.handle}/${data.post.slug}`;
  const title = `${data.post.title} · ${data.display_name}`;
  return {
    ...(site ? { metadataBase: new URL(site) } : {}),
    title: { absolute: title },
    description: data.post.excerpt,
    alternates: { canonical: url },
    ...(data.indexable === false ? { robots: { index: false, follow: true } } : {}),
    openGraph: { title: data.post.title, description: data.post.excerpt, type: "article", url,
                 authors: [data.display_name],
                 ...(data.post.published_at ? { publishedTime: data.post.published_at } : {}) },
    // Without this the root layout's product card is what a shared post shows.
    twitter: { card: "summary_large_image", title: data.post.title, description: data.post.excerpt },
  };
}

export default async function Page({ params }: Params) {
  const { handle, slug } = await params;
  const data = await fetchPost(handle, slug);
  if (!data) notFound();
  return <PostPage data={data} />;
}
