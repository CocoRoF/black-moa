/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { BRAND } from "@/lib/brand";
import { cn } from "@/lib/utils";

/** Two renderings of the same art, swapped by CSS rather than by JavaScript.
 *
 *  Picking the source in JS means the first paint shows whichever theme the server
 *  guessed, then corrects itself — a visible flash on every load. Both are in the markup
 *  and the stylesheet decides, so the right one is there before the page paints. The
 *  hidden one is `loading="lazy"` and never fetched by a browser that will not show it. */
function ThemedArt({ light, dark, alt, height, width, className }: {
  light: string; dark: string; alt: string; height?: number; width?: number; className?: string;
}) {
  const common = cn("block select-none", className);
  const box = height ? { height } : { width, maxWidth: "100%" };
  return (
    <>
      <img src={light} alt={alt} className={cn(common, "dark:hidden", height ? "w-auto" : "h-auto")} style={box} draggable={false} />
      <img src={dark} alt="" aria-hidden loading="lazy" className={cn(common, "hidden dark:block", height ? "w-auto" : "h-auto")} style={box} draggable={false} />
    </>
  );
}

/** Header logo: the black-moa logo itself. `size` = image height in px.
 *  (The full lockup shrinks the wordmark to an illegible smudge at header size, so headers
 *  carry the wordmark alone; use `LogoMark` when the square mark is wanted instead.) */
export function Logo({ href = "/", size = 32, label, className }: { href?: string | null; size?: number; label?: string; className?: string }) {
  const img = <ThemedArt light={BRAND.wordmark} dark={BRAND.wordmarkDark} alt={label ?? BRAND.name} height={size} className={className} />;
  if (!href) return img;
  return <Link href={href} aria-label={label ?? BRAND.name} className="inline-flex items-center rounded-lg focus-visible:outline-2 focus-visible:outline-ring">{img}</Link>;
}

/** Compact mark only (collapsed sidebar, tab bars). `size` = badge diameter. */
export function LogoMark({ size = 32, className, href, muted }: { size?: number; className?: string; href?: string; muted?: boolean }) {
  const el = (
    <span className={cn("inline-flex shrink-0 items-center justify-center transition-[filter,opacity]", muted && "grayscale opacity-60", className)} style={{ width: size, height: size }} aria-hidden={href ? undefined : true}>
      {/* No disc behind it. The mark is a finished logo with its own silhouette; a tinted
          circle was there for the character illustration this replaced, and around the M
          it reads as a second, wrong shape. */}
      <img src={BRAND.characterIcon} alt="" width={247} height={195} className="block h-auto w-full" draggable={false} />
    </span>
  );
  if (!href) return el;
  return <Link href={href} aria-label={BRAND.name} className="inline-flex rounded-full focus-visible:outline-2 focus-visible:outline-ring">{el}</Link>;
}

/** Wordmark only ("black-moa"). `size` = height in px. */
export function Wordmark({ size = 20, className }: { size?: number; className?: string }) {
  return <ThemedArt light={BRAND.wordmark} dark={BRAND.wordmarkDark} alt={BRAND.name} height={size} className={className} />;
}

/** The black-moa mark alone (transparent PNG). `size` = height in px. */
export function Mascot({ size = 96, className, alt = "" }: { size?: number; className?: string; alt?: string }) {
  return <img src={BRAND.character} alt={alt} width={110} height={195} className={cn("block w-auto select-none", className)} style={{ height: size }} draggable={false} />;
}

/** Full logo (mascot + wordmark, tall composition) for hero surfaces. `width` = px. */
export function LogoFull({ width = 320, className, alt = BRAND.name }: { width?: number; className?: string; alt?: string }) {
  return <ThemedArt light={BRAND.logoFull} dark={BRAND.logoFullDark} alt={alt} width={width} className={className} />;
}

/** Soft brand glow used behind hero/auth/empty visuals.
 *  `fixed` anchors it to the viewport instead of the nearest positioned ancestor —
 *  inside a narrow column (the auth card) an absolute glow gets clipped to that
 *  column and reads as a hard-edged rectangle behind the card. */
export function BrandGlow({ className, fixed }: { className?: string; fixed?: boolean }) {
  return (
    <div aria-hidden className={cn("pointer-events-none inset-0 -z-10 overflow-hidden", fixed ? "fixed" : "absolute", className)}>
      <div className="absolute left-1/2 top-[-28%] h-[720px] w-[1100px] -translate-x-1/2 rounded-full opacity-60 blur-[110px]" style={{ background: "radial-gradient(closest-side, color-mix(in oklab, var(--brand-sky) 34%, transparent), transparent 72%)" }} />
      <div className="absolute left-[-12%] top-[18%] h-[460px] w-[460px] rounded-full opacity-45 blur-[110px]" style={{ background: "radial-gradient(closest-side, color-mix(in oklab, var(--accent) 28%, transparent), transparent 72%)" }} />
      <div className="absolute right-[-10%] bottom-[-15%] h-[520px] w-[520px] rounded-full opacity-40 blur-[110px]" style={{ background: "radial-gradient(closest-side, color-mix(in oklab, #7dd3fc 40%, transparent), transparent 72%)" }} />
    </div>
  );
}
