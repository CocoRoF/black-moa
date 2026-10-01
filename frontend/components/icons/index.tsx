/** The project's icons, in one place.
 *
 *  Every icon on a black-moa screen is a Lucide line icon — the rail, the buttons, the boards.
 *  Nothing imports `lucide-react` directly (ESLint enforces it); screens import from here,
 *  and the domain sets below are the only place a name from the database becomes a glyph.
 */
import type { LucideIcon, LucideProps } from "lucide-react";
import { Briefcase, FileText, Heart, Home, Megaphone, MessageCircle, PiggyBank, TrendingUp } from "lucide-react";

export * from "lucide-react";
export type Icon = LucideIcon;
export type IconProps = LucideProps;

// ── boards ───────────────────────────────────────────────────────────

/** A board names one of these; the name is what the admin picks and the database keeps. */
export const BOARD_ICONS: Record<string, Icon> = {
  briefcase: Briefcase,
  "trending-up": TrendingUp,
  "file-text": FileText,
  heart: Heart,
  "piggy-bank": PiggyBank,
  "message-circle": MessageCircle,
  megaphone: Megaphone,
  home: Home,
};
export const BOARD_GLYPHS = Object.keys(BOARD_ICONS);

export function BoardIcon({ name, className }: { name?: string | null; className?: string }) {
  const I = BOARD_ICONS[(name ?? "").trim()] ?? MessageCircle;
  return <I className={className ?? "h-4 w-4"} aria-hidden />;
}
