import type { MetadataRoute } from "next";

/** Every public address a search engine may list (plan/41 §2).
 *
 *  The pages are readable by anyone with the address whatever this file says; being listed
 *  is the part each person agrees to, so only people who left [검색 결과에 보이기] on are
 *  here, with the posts they published publicly.
 */
const INTERNAL = () => process.env.INTERNAL_API_URL ?? "http://127.0.0.1:8123";

interface Person { handle: string; updated_at: string; posts: { slug: string; updated_at: string }[] }

// Built when asked, not when the image is built: the public address is a runtime setting,
// and a sitemap prerendered without it is an empty one that ships with every deploy.
export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const site = (process.env.PUBLIC_URL || process.env.MEMORA_PUBLIC_URL || process.env.NEXT_PUBLIC_URL || "").replace(/\/$/, "");
  if (!site) return [];
  const entries: MetadataRoute.Sitemap = [
    { url: `${site}/`, changeFrequency: "weekly", priority: 1 },
  ];
  try {
    const r = await fetch(`${INTERNAL()}/api/public/sitemap`, { next: { revalidate: 3600 }, headers: { Accept: "application/json" } });
    if (!r.ok) return entries;
    const { people } = (await r.json()) as { people: Person[] };
    for (const p of people ?? []) {
      entries.push({ url: `${site}/@${p.handle}`, lastModified: new Date(p.updated_at), changeFrequency: "weekly", priority: 0.8 });
      for (const post of p.posts ?? []) {
        entries.push({ url: `${site}/@${p.handle}/${encodeURIComponent(post.slug)}`, lastModified: new Date(post.updated_at),
                       changeFrequency: "monthly", priority: 0.6 });
      }
    }
  } catch {
    // A sitemap that cannot be built is not a reason to serve an error to a crawler.
  }
  return entries;
}
