export function fmtNumber(n: number | null | undefined, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return "–";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
export function fmtCredits(n: number | null | undefined) {
  if (n === null || n === undefined) return "–";
  const abs = Math.abs(n);
  return n.toLocaleString(undefined, { maximumFractionDigits: abs < 10 ? 2 : abs < 1000 ? 1 : 0 });
}
export function fmtBytes(b: number | null | undefined) {
  if (!b) return "0 B";
  const u = ["B", "KB", "MB", "GB"]; let i = 0; let v = b;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}
export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { dateStyle: "medium" }) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return d.toLocaleString(undefined, opts);
}
export function fmtDateTime(iso: string | null | undefined) {
  return fmtDate(iso, { dateStyle: "medium", timeStyle: "short" });
}
export function fmtTime(iso: string | null | undefined) {
  return fmtDate(iso, { timeStyle: "short" });
}
export function fmtRelative(iso: string | null | undefined, locale: "ko" | "en" = "ko") {
  if (!iso) return "–";
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return "–";
  const diff = (d - Date.now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), "day");
  return fmtDate(iso);
}
export function fmtMs(ms: number | null | undefined) {
  if (ms === null || ms === undefined) return "–";
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}
export function fmtPct(n: number) { return `${Math.round(n * 100)}%`; }

/** The API masks a secret as `****…****abcd` — for a 100-character key that is 96 asterisks,
 *  which fills a row and says nothing. Only the tail identifies the key. */
export function fmtSecretTail(masked: string | null | undefined) {
  const tail = (masked ?? "").replace(/^\*+/, "");
  return tail ? `…${tail}` : "";
}
