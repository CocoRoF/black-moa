import type { Metadata, Viewport } from "next";
import { BRAND, BRAND_REV } from "@/lib/brand";
// The library first: globals.css then overrides its trigger to match this app's inputs.
import "@cocorof/react-calendar/styles.css";
import "./globals.css";
import { Providers } from "./providers";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

const BASE = process.env.PUBLIC_URL || process.env.MEMORA_PUBLIC_URL || process.env.NEXT_PUBLIC_URL || "http://localhost:3000";
export const metadata: Metadata = {
  metadataBase: new URL(BASE),
  title: { default: "Memora, 나만의 AI 비서", template: "%s · Memora" },
  description: "당신의 진짜 비서를 만들어보세요. 나를 대신해 답하고, 메시지를 받고, 미팅을 잡아주는 AI 비서 Memora.",
  applicationName: "Memora",
  manifest: "/manifest.webmanifest",
  icons: { icon: [{ url: `/favicon.ico?v=${BRAND_REV}`, sizes: "any" }, { url: `/icon.png?v=${BRAND_REV}`, type: "image/png" }], apple: `/icons/apple-touch-icon.png?v=${BRAND_REV}` },
  appleWebApp: { capable: true, title: "Memora", statusBarStyle: "default" },
  openGraph: { type: "website", siteName: "Memora", title: "Memora, 나만의 AI 비서", description: "당신의 진짜 비서를 만들어보세요", images: [{ url: BRAND.ogImage, width: 1200, height: 630 }] },
  twitter: { card: "summary_large_image", title: "Memora, 나만의 AI 비서", images: [BRAND.ogImage] },
  formatDetection: { telephone: false },
};
export const viewport: Viewport = {
  width: "device-width", initialScale: 1, viewportFit: "cover", interactiveWidget: "resizes-content",
  themeColor: [{ media: "(prefers-color-scheme: light)", color: "#1a5fe0" }, { media: "(prefers-color-scheme: dark)", color: "#0d0f14" }],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <body className="min-h-dvh antialiased">
        {/* <head> 를 우리가 손으로 채우지 않는다.
            React 19 는 트리 안의 <script> 와 <link rel=stylesheet> 를 제 규칙대로 <head> 로
            끌어올린다. 우리가 <head> 안에 직접 적어 두면 서버가 보낸 차례와 클라이언트가
            그리는 차례가 어긋날 자리가 생기고, 차가운 적재 열 번에 한 번쯤 화면 전체가 한 번
            다시 그려진다(눈에 보이는 결과는 같지만 공짜는 아니다).

            테마 스크립트는 <body> 의 첫 줄이라 첫 그림 전에 실행되고, 글꼴은 `precedence` 로
            React 가 자리를 잡는다. 둘 다 다루는 주인이 하나가 된다. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        <link rel="stylesheet" precedence="default" crossOrigin="anonymous"
              href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
