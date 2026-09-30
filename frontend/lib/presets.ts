/** The photographs offered when a secretary is given a face.
 *
 *  Grouped the way somebody picking one thinks: 남자 한 줄, 여자 한 줄, 그리고 직접
 *  올리기. A flat row of six faces makes the reader sort them before choosing.
 *
 *  The `?v=` is load-bearing. These are static files behind Cloudflare, which serves them
 *  with a four-hour max-age we cannot purge from here — so re-cropping a preset changes the
 *  bytes while every browser that has seen it keeps showing the old ones. The path never
 *  changes (an `avatar_url` already stored keeps resolving); the query is what makes a
 *  browser go and fetch the new picture. Bump it whenever a preset image is regenerated.
 */
export const PRESET_REV = "3";

const at = (file: string) => `/presets/${file}?v=${PRESET_REV}`;

export interface PresetGroup {
  /** `onb.photo_male` / `onb.photo_female` 로 읽는다. */
  key: "male" | "female";
  /** 한 줄에 다섯. 그림체가 다른 것은 다른 줄에 둔다(사진은 윗줄, 도트 그림은 아랫줄). */
  rows: { key: string; src: string }[][];
}

export const AVATAR_GROUPS: PresetGroup[] = [
  {
    key: "male",
    rows: [[
      { key: "male", src: at("secretary-male.png") },
      { key: "male-pinstripe", src: at("secretary-male-pinstripe.png") },
      { key: "male-double", src: at("secretary-male-double.png") },
      { key: "male-grey", src: at("secretary-male-grey.png") },
      { key: "male-burgundy", src: at("secretary-male-burgundy.png") },
    ]],
  },
  {
    key: "female",
    rows: [[
      { key: "female", src: at("secretary-female.png") },
      { key: "female-bob", src: at("secretary-female-bob.png") },
      { key: "female-dark", src: at("secretary-female-dark.png") },
      { key: "female-ponytail", src: at("secretary-female-ponytail.png") },
      { key: "female-pixie", src: at("secretary-female-pixie.png") },
    ], [
      { key: "female-dot-cardigan", src: at("secretary-female-dot-cardigan.png") },
      { key: "female-dot-auburn", src: at("secretary-female-dot-auburn.png") },
      { key: "female-dot-shirt", src: at("secretary-female-dot-shirt.png") },
      { key: "female-dot-green", src: at("secretary-female-dot-green.png") },
      { key: "female-dot-navy", src: at("secretary-female-dot-navy.png") },
    ]],
  },
];

/** The one a new secretary starts with, so nobody is handed a grey circle. */
export const DEFAULT_AVATAR = AVATAR_GROUPS[0].rows[0][0].src;
