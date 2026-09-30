import { notFound, permanentRedirect } from "next/navigation";

/** Where a shared secretary link used to live.
 *
 *  Links were served straight off the root, so every code was competing with the app's own
 *  pages for the same namespace. They live under /secretary now, and this keeps everything
 *  already shared, printed or pasted working. A person's page does not come through here:
 *  `/@handle` is rewritten to /p/[handle] in next.config (plan/41 §2).
 *
 *  The reserved list survives for one reason: a static route wins over this catch-all in
 *  Next's matcher, but a *missing* one would fall through, and redirecting /terms to a
 *  secretary page is worse than a 404.
 */
const RESERVED = new Set(["app", "admin", "api", "login", "signup", "health", "static", "_next", "c", "s",
                          "about", "terms", "privacy", "secretary", "favicon.ico", "manifest.webmanifest",
                          "robots.txt", "sitemap.xml", "icon.png", "icons", "brand", "p"]);
const CODE = /^[a-z0-9][a-z0-9-]{1,31}$/i;

export default async function LegacyLinkRedirect({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  if (RESERVED.has(code.toLowerCase()) || !CODE.test(code)) notFound();
  permanentRedirect(`/secretary/${encodeURIComponent(code)}`);
}
