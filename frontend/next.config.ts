import type { NextConfig } from "next";

const INTERNAL = process.env.INTERNAL_API_URL ?? "http://127.0.0.1:8123";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  devIndicators: false,
  images: { unoptimized: true },
  async headers() {
    // Private surfaces must never be indexed or embedded, even if robots.txt is ignored.
    const privateHeaders = [
      { key: "X-Robots-Tag", value: "noindex, nofollow, noarchive" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "same-origin" },
    ];
    return [
      { source: "/admin/:path*", headers: privateHeaders },
      { source: "/app/:path*", headers: privateHeaders },
      { source: "/admin", headers: privateHeaders },
      { source: "/app", headers: privateHeaders },
    ];
  },
  async redirects() {
    // One address per person. /p/... is only the inside of the rewrite below, so anyone who
    // arrives at it (an old link, a copied URL) is sent to the @ address that person shares.
    return [
      { source: "/p/:handle", destination: "/@:handle", permanent: true },
      { source: "/p/:handle/:slug", destination: "/@:handle/:slug", permanent: true },
    ];
  },
  async rewrites() {
    // A person's address keeps its @ in the URL bar. Next will not route a segment that
    // starts with @ into a dynamic segment — that prefix is its parallel-route convention —
    // so the address is rewritten onto a plain path here (plan/41 §2). Production too.
    const person = [{ source: "/@:handle", destination: "/p/:handle" },
                    { source: "/@:handle/:slug", destination: "/p/:handle/:slug" }];
    // Dev only: same-origin /api → backend. In production nginx routes /api to the backend.
    if (process.env.NODE_ENV === "production" && !process.env.PROXY_API_IN_PROD) return person;
    return [
      ...person,
      { source: "/api/:path*", destination: `${INTERNAL}/api/:path*` },
      { source: "/health", destination: `${INTERNAL}/health` },
      { source: "/health/:path*", destination: `${INTERNAL}/health/:path*` },
      { source: "/static/:path*", destination: `${INTERNAL}/static/:path*` },
    ];
  },
};

export default nextConfig;
