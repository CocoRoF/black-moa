import { BRAND_REV } from "@/lib/brand";
import { NextResponse } from "next/server";

export const dynamic = "force-static";

export function GET() {
  return NextResponse.json({
    name: "black-moa, 나만의 AI 비서", short_name: "black-moa", description: "당신의 진짜 비서를 만들어보세요", id: "/app", start_url: "/app", scope: "/", display: "standalone",
    orientation: "portrait", background_color: "#f7f7f9", theme_color: "#1a5fe0", lang: "ko",
    icons: [
      { src: `/icons/icon-192.png?v=${BRAND_REV}`, sizes: "192x192", type: "image/png", purpose: "any" },
      { src: `/icons/icon-512.png?v=${BRAND_REV}`, sizes: "512x512", type: "image/png", purpose: "any" },
      { src: `/icons/icon-512-maskable.png?v=${BRAND_REV}`, sizes: "512x512", type: "image/png", purpose: "maskable" },
      { src: `/icons/apple-touch-icon.png?v=${BRAND_REV}`, sizes: "180x180", type: "image/png", purpose: "any" },
    ],
  }, { headers: { "Content-Type": "application/manifest+json", "Cache-Control": "public, max-age=3600" } });
}
