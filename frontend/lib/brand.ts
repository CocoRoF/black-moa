/** Bumped whenever the artwork changes.
 *
 *  The assets are served with a seven-day max-age at the edge, so a new logo under an old
 *  path stays invisible for a week — which is exactly what happened on the Memora rename.
 *  The version rides on the URL so a change ships the moment it deploys. */
export const BRAND_REV = "3";
const v = (path: string) => `${path}?v=${BRAND_REV}`;

/** Static brand constants. Runtime service_name from /api/public/branding may override text labels. */
export const BRAND = {
  name: "Memora",
  tagline_ko: "당신의 진짜 비서를 만들어보세요",
  tagline_en: "Build your real secretary",
  // Sampled from the mark itself: the M runs blue on the left to purple on the right.
  accent: "#1a5fe0",
  accentDark: "#5b8dff",
  sky: "#006efd",
  violet: "#ba49f8",
  ogImage: v("/brand/og-default.png"),
  logoFull: v("/brand/logo-full-trim.png"),
  lockup: v("/brand/logo-lockup.png"),
  tagline_ko_lines: ["당신의 진짜 비서를", "만들어보세요"],
  tagline_en_lines: ["Build your real", "secretary"],
  wordmark: v("/brand/wordmark-trim.png"),
  // The wordmark's ink is near-black, so dark mode needs its own artwork rather than a
  // filter — the gradient "o" has to survive. Both are cut to the same ink height, so
  // swapping them does not resize the logo.
  wordmarkDark: v("/brand/wordmark-trim-dark.png"),
  logoFullDark: v("/brand/logo-full-trim-dark.png"),
  lockupDark: v("/brand/logo-lockup-dark.png"),
  character: v("/brand/character-trim.png"),
  characterIcon: v("/brand/character-icon-trim.png"),
} as const;
