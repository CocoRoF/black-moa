/** One place the verification code is normalised.
 *
 *  A code reaches this field by paste far more often than by typing: from the mail body,
 *  from a notification, sometimes with the label still attached. `maxLength` alone does the
 *  wrong thing with any of that — it keeps the first six characters, so a pasted
 *  "인증 코드: 022139" becomes "인증 코드:" and a spaced code becomes three digits.
 */
export const CODE_LENGTH = 6;

export const normalizeCode = (raw: string) => raw.replace(/\D+/g, "").slice(0, CODE_LENGTH);
