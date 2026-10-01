import Link from "next/link";
import { BrandGlow, Mascot } from "@/components/brand/Logo";

export default function NotFound() {
  return (
    <main className="relative min-h-dvh flex flex-col items-center justify-center gap-4 p-6 text-center overflow-hidden">
      <BrandGlow />
      <Mascot size={150} className="float-y" alt="black-moa" />
      <div className="text-5xl font-semibold tracking-tight">404</div>
      <p className="text-muted-fg">여기엔 아무것도 없어요. 링크가 바뀌었거나 사라졌을 수 있어요.<br /><span className="text-sm">Nothing here — the link may have moved or expired.</span></p>
      <Link href="/" className="rounded-xl bg-accent px-4 py-2.5 text-sm font-medium text-accent-fg shadow-lg shadow-sky-500/20">홈으로 · Home</Link>
    </main>
  );
}
