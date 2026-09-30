/**
 * 공개 범위의 정본 (plan/48 §2). 서버의 `core/visibility.py` 와 한 쌍이다.
 *
 *     [내 정보]  ──전부──▶  [비서]  ──공개 범위만큼──▶  [외부인]
 *
 * 비서는 내 정보를 전부 본다. 범위가 막는 것은 **밖으로 나가는 것**이지 비서가
 * 아는 것이 아니다. 그래서 화면 문구도 "비서에게 숨김" 이 아니라 "누구까지 보나"
 * 로 적는다.
 *
 * 원천마다 다른 말을 쓰면(프로필은 known, 피드는 friends, 지식은 두 단계뿐) 주인이
 * "인맥에게만" 이라고 정한 것이 어떤 곳에서는 지켜지고 어떤 곳에서는 조용히
 * 비공개가 된다. 그래서 말은 여기 하나로 모은다.
 */
import type { Locale } from "./i18n";

/** 무엇이 어디까지 나가는가. */
export const LEVELS = ["public", "known", "private"] as const;
export type Level = (typeof LEVELS)[number];

/** 지금 듣는 사람이 나에게서 얼마나 가까운가. */
export const VIEWERS = ["owner", "known", "stranger"] as const;
export type Viewer = (typeof VIEWERS)[number];

/** 옛 이름. 데이터는 그대로 두고 읽을 때만 옮긴다. */
const ALIASES: Record<string, Level> = { friends: "known", on_request: "private" };

/** 무엇이 들어와도 셋 중 하나로. 모르는 값은 가장 좁은 쪽으로 접는다. */
export function normalize(value: unknown): Level {
  const v = String(value ?? "");
  if ((LEVELS as readonly string[]).includes(v)) return v as Level;
  return ALIASES[v] ?? "private";
}

/** 화면에 적는 말. 서버 값과 일대일이다. */
export function levelLabel(level: unknown, locale: Locale = "ko"): string {
  const l = normalize(level);
  if (locale === "en") return { public: "Everyone", known: "My connections", private: "Only me" }[l];
  return { public: "모두 공개", known: "내 인맥에게만", private: "비공개" }[l];
}

/** 한 줄 설명. 무엇이 달라지는지 결과만 말한다. */
export function levelHint(level: unknown, locale: Locale = "ko"): string {
  const l = normalize(level);
  if (locale === "en") {
    return { public: "Anyone can see this, including people who are not signed in.",
             known: "Only people you are connected to can see this.",
             private: "Nobody but you. Your secretary still knows it." }[l];
  }
  return { public: "로그인하지 않은 사람도 볼 수 있어요.",
           known: "서로 인맥을 맺은 사람만 볼 수 있어요.",
           private: "나만 볼 수 있어요. 내 비서는 그래도 알고 있어요." }[l];
}

/** 고르는 자리에 쓰는 세 칸. 늘 같은 차례로 선다(넓은 것부터 좁은 것으로). */
export function levelOptions(locale: Locale = "ko"): { value: Level; label: string }[] {
  return LEVELS.map((l) => ({ value: l, label: levelLabel(l, locale) }));
}

/** 이 범위의 것을 저 사람에게 보여도 되나. 서버의 같은 이름과 같은 규칙이다. */
export function visibleTo(level: unknown, viewer: Viewer): boolean {
  if (viewer === "owner") return true;
  const l = normalize(level);
  if (l === "public") return true;
  return l === "known" && viewer === "known";
}
