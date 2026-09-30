/** The password rule, in one place.
 *
 *  The server enforces exactly this (`_validate_password`): at least eight characters, and
 *  at least two of upper / lower / digit / symbol. The checklist a person reads while
 *  typing is generated from the same definition — a guide the backend does not check is a
 *  lie with extra steps, and one stricter than the backend refuses passwords the server
 *  would have taken.
 */
export const PASSWORD_MIN = 8;
export const CLASSES_REQUIRED = 2;
/** Mirrors the server's list. Kept in step with `_validate_password`: without it the
 *  checklist would go all-green on "password" and the server would still refuse it —
 *  a rejection with no visible reason, which is the failure this component exists to
 *  prevent. */
const COMMON = new Set(["password", "12345678", "qwerty123", "11111111", "abcdefgh", "iloveyou"]);

export type PasswordClass = "upper" | "lower" | "digit" | "symbol";

export interface PasswordVerdict {
  longEnough: boolean;
  classes: { key: PasswordClass; ok: boolean }[];
  classesMet: number;
  notCommon: boolean;
  ok: boolean;
}

export function checkPassword(pw: string): PasswordVerdict {
  const classes: { key: PasswordClass; ok: boolean }[] = [
    { key: "upper", ok: /[A-Z]/.test(pw) },
    { key: "lower", ok: /[a-z]/.test(pw) },
    { key: "digit", ok: /[0-9]/.test(pw) },
    { key: "symbol", ok: /[^A-Za-z0-9]/.test(pw) },
  ];
  const classesMet = classes.filter((c) => c.ok).length;
  const longEnough = pw.length >= PASSWORD_MIN;
  const notCommon = !COMMON.has(pw.toLowerCase());
  return { longEnough, classes, classesMet, notCommon,
           ok: longEnough && classesMet >= CLASSES_REQUIRED && notCommon };
}
