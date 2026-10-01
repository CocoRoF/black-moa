import type { MetadataRoute } from "next";

/** Written here rather than as a static file so it can name the sitemap, which only this
 *  deployment knows the address of. */
// Same reason as the sitemap it points at: the address is only known at runtime.
export const dynamic = "force-dynamic";

export default function robots(): MetadataRoute.Robots {
  const site = (process.env.PUBLIC_URL || process.env.BLACKMOA_PUBLIC_URL || process.env.NEXT_PUBLIC_URL || "").replace(/\/$/, "");
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/app", "/admin", "/api"] }],
    ...(site ? { sitemap: `${site}/sitemap.xml`, host: site } : {}),
  };
}
