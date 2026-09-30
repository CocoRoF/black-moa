import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cardUrl } from "@/lib/ogcard";
import { PersonPage, type PersonPayload } from "@/components/public/PersonPage";

/** A person's own page (plan/41 §2, §3).
 *
 *  The address people see is `/@handle`. It does not live here because Next will not route
 *  a URL segment that starts with `@` into a dynamic segment — that prefix is its parallel
 *  route convention — so next.config rewrites `/@handle` onto this path. The `@` is what
 *  makes the address safe at the root: no page of ours can ever be named that.
 */
const INTERNAL = () => process.env.INTERNAL_API_URL ?? "http://127.0.0.1:8123";
const HANDLE = /^[a-z0-9][a-z0-9-]{1,31}$/i;

async function fetchPerson(handle: string): Promise<PersonPayload | null> {
  if (!HANDLE.test(handle)) return null;
  try {
    const r = await fetch(`${INTERNAL()}/api/public/people/${encodeURIComponent(handle)}`,
                          { cache: "no-store", headers: { Accept: "application/json" } });
    if (!r.ok) return null;
    return (await r.json()) as PersonPayload;
  } catch {
    return null;
  }
}

type Params = { params: Promise<{ handle: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { handle } = await params;
  const data = await fetchPerson(handle);
  if (!data) return { robots: { index: false } };
  const f = data.fields ?? {};
  const line = [f.title, f.company].filter(Boolean).join(" \u00b7 ");
  const site = process.env.PUBLIC_URL || process.env.MEMORA_PUBLIC_URL || process.env.NEXT_PUBLIC_URL;
  const title = `${data.display_name} (@${data.handle})`;
  const s = data.secretary;
  // Repeating the name in the line under it tells a reader nothing. When the person has
  // not written a bio, the card says what the page is for, which is true of every page.
  const desc = f.bio?.slice(0, 160) || line
    || (s?.name ? `${s.name}에게 물어보세요. ${data.display_name}님 대신 답해요.` : title);
  // The same card the secretary's own link shows: one face per secretary, wherever the
  // address was shared from. Without it a person's page wears the product's generic face.
  const card = s?.code
    ? cardUrl(s.code, { name: s.name, owner_display_name: data.display_name, role_line: s.role_line,
                        avatar_url: s.avatar_url, cover_url: s.cover_url, theme: s.theme })
    : undefined;
  return {
    ...(site ? { metadataBase: new URL(site) } : {}),
    title: { absolute: title },
    description: desc,
    alternates: { canonical: `/@${data.handle}` },
    // Readable by anyone with the address either way. This is only about being listed.
    ...(data.indexable === false ? { robots: { index: false, follow: true } } : {}),
    openGraph: { title, description: desc, type: "profile", url: `/@${data.handle}`,
                 ...(card ? { images: [{ url: card, width: 1200, height: 630, type: "image/png", alt: title }] } : {}) },
    // Set explicitly, or the root layout's product card is what a share shows instead of
    // the person whose address was shared.
    twitter: { card: "summary_large_image", title, description: desc, ...(card ? { images: [card] } : {}) },
  };
}

export default async function Page({ params }: Params) {
  const { handle } = await params;
  const data = await fetchPerson(handle);
  if (!data) notFound();
  return <PersonPage data={data} />;
}
