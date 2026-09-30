/** The address of a secretary's share card.
 *
 *  A scraper caches the image by URL and never looks again, so a card that changed behind
 *  an unchanged URL is a card nobody sees again. Everything drawn on it goes into the
 *  token, and the URL moves when any of it does. The person page and the secretary page
 *  share this so one secretary has one card wherever it is shared from.
 */
const CARD_REV = "2";

export function cardToken(parts: (string | null | undefined)[]): string {
  // djb2, base36. Short enough to read in a log line, stable across renders.
  let h = 5381;
  for (const ch of [CARD_REV, ...parts].join("|")) h = ((h << 5) + h + ch.charCodeAt(0)) | 0;
  return (h >>> 0).toString(36);
}

export interface CardFace {
  name?: string | null; owner_display_name?: string | null; role_line?: string | null;
  avatar_url?: string | null; cover_url?: string | null; theme?: { accent?: string } | null;
}

/** In the path, not a query: scrapers are unreliable about query strings on og:image. */
export function cardUrl(code: string, a: CardFace): string {
  return `/api/public/links/${code}/og-${cardToken([a.name, a.owner_display_name, a.role_line, a.avatar_url, a.cover_url, a.theme?.accent])}.png`;
}
