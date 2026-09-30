import type { Metadata, Viewport } from "next";
import { notFound } from "next/navigation";
import { cardUrl } from "@/lib/ogcard";
import { PublicChat, type PublicLinkPayload } from "@/components/public/PublicChat";

const INTERNAL = () => process.env.INTERNAL_API_URL ?? "http://127.0.0.1:8123";
// Under its own prefix a code cannot collide with a page, so the list of words it was
// forbidden to be is gone. The shape check stays: it keeps a malformed path from becoming
// a backend request.
const CODE = /^[a-z0-9][a-z0-9-]{1,31}$/i;

async function fetchLink(code: string): Promise<PublicLinkPayload | null | "error"> {
  if (!CODE.test(code)) return null;
  try {
    const r = await fetch(`${INTERNAL()}/api/public/links/${encodeURIComponent(code)}`, { cache: "no-store", headers: { Accept: "application/json" } });
    if (r.status === 404) return null;
    if (!r.ok) return "error";
    return (await r.json()) as PublicLinkPayload;
  } catch {
    return "error";
  }
}


type Params = { params: Promise<{ code: string }>; searchParams?: Promise<Record<string, string | string[] | undefined>> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { code } = await params;
  const data = await fetchLink(code);
  if (!data || data === "error") return { title: "MFSG", robots: { index: false } };
  const title = `${data.agent.name} · ${data.agent.owner_display_name}의 비서`;
  const a = data.agent;
  // In the path, not a query: scrapers are unreliable about query strings on og:image.
  const card = cardUrl(code, a);
  // Absolute, or a crawler is handed http://localhost:3000/… and shows an empty card.
  const site = process.env.PUBLIC_URL || process.env.MEMORA_PUBLIC_URL || process.env.NEXT_PUBLIC_URL;
  const base = site ? new URL(site) : undefined;
  return {
    ...(base ? { metadataBase: base } : {}),
    title: { absolute: title },
    description: data.agent.role_line || data.agent.greeting?.slice(0, 120) || title,
    manifest: `/api/public/links/${code}/manifest.webmanifest`,
    appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: data.agent.name },
    openGraph: { title, description: data.agent.role_line || undefined, type: "website",
                 // Canonical per secretary: a scraper that keys its cache on og:url must
                 // key it on *this* secretary, not on the domain they share.
                 url: `/secretary/${code}`,
                 images: [{ url: card, width: 1200, height: 630, type: "image/png", alt: title }] },
    twitter: { card: "summary_large_image", title, images: [card] },
    // The product mark, not the secretary's face: the tab should read as this service.
    icons: { icon: [{ url: "/favicon.ico", sizes: "any" }, { url: "/icon.png", type: "image/png" }], apple: "/icons/apple-touch-icon.png" },
    other: { "mobile-web-app-capable": "yes" },
  };
}

export async function generateViewport({ params }: Params): Promise<Viewport> {
  const { code } = await params;
  const data = await fetchLink(code);
  const accent = data && data !== "error" ? data.agent.theme?.accent ?? "#1a5fe0" : "#1a5fe0";
  return { width: "device-width", initialScale: 1, viewportFit: "cover", interactiveWidget: "resizes-content", themeColor: accent };
}

export default async function Page({ params, searchParams }: Params) {
  const { code } = await params;
  const data = await fetchLink(code);
  if (data === null) notFound();
  // Read on the server: deciding this in the browser makes the first render differ from
  // the HTML it hydrates, and React throws the page away and redraws it (#418).
  const sp = searchParams ? await searchParams : {};
  const embed = sp.embed === "1";
  // 링크 설정의 미리보기(plan/71): 고른 모양으로, 예시 대화만.
  const preview = sp.preview === "stage" || sp.preview === "chat" ? sp.preview : null;
  return <PublicChat code={code} initial={data === "error" ? null : data} embed={embed} preview={preview} />;
}
