"""공개 범위의 정본 (plan/48 §2).

이 서비스에는 세 당사자가 있다.

    [사용자 정보]  ──전부──▶  [비서]  ──공개 범위만큼──▶  [외부인]

**비서는 주인의 원장을 전부 본다.** `private` 이 막는 것은 *밖으로 나가는 것*이지
*비서가 아는 것*이 아니다. 그래서 주인의 턴은 범위를 따지지 않고, 범위는 외부인이
듣는 자리에서만 걸린다.

범위는 셋뿐이고, 원천이 무엇이든 같은 말을 쓴다. 프로필은 `known`, 피드는 `friends`,
지식과 인맥은 두 단계뿐이던 것을 여기 하나로 모은다. 어휘가 갈라지면 "인맥에게만"
이라고 정한 것이 어떤 원천에서는 지켜지고 어떤 원천에서는 조용히 비공개가 된다.
"""
from __future__ import annotations

from typing import Any

#: 무엇이 어디까지 나가는가. 화면 말로는 [모두 공개] · [내 인맥에게만] · [비공개].
LEVELS: tuple[str, ...] = ("public", "known", "private")

#: 지금 듣는 사람이 주인에게서 얼마나 가까운가.
VIEWERS: tuple[str, ...] = ("owner", "known", "stranger")

#: 옛 이름들. 데이터는 그대로 두고 읽을 때만 옮긴다.
#:
#: `friends` 는 피드가 쓰던 이름이고 `known` 과 같은 뜻이다. `on_request` 는 두 단계
#: 시절의 값으로, 그때도 방문자 프롬프트에 들어가지 않았으므로 `private` 이 맞다.
ALIASES: dict[str, str] = {"friends": "known", "on_request": "private"}


def normalize(value: Any) -> str:
    """무엇이 들어와도 셋 중 하나로. 모르는 값은 **가장 좁은 쪽**으로 접는다.

    모르는 값을 `public` 으로 접으면 오타 하나가 공개로 이어진다. 반대 방향의 실수는
    "왜 안 보이지" 로 끝나고, 이쪽 실수는 되돌릴 수 없다.
    """
    if value in LEVELS:
        return str(value)
    return ALIASES.get(str(value), "private")


def normalize_viewer(value: Any) -> str:
    """모르는 값이면 **가장 먼 쪽**으로. 같은 이유다."""
    return str(value) if value in VIEWERS else "stranger"


def visible_to(level: Any, viewer: Any) -> bool:
    """`level` 인 것을 `viewer` 에게 보여도 되는가.

    주인은 제 것을 전부 본다. 모두에게 공개한 것은 누구에게나 간다. 그 사이가
    이 서비스가 중간 단계를 두는 이유다: 인맥에게는 남보다 더 말해도 된다.
    """
    v = normalize_viewer(viewer)
    if v == "owner":
        return True
    lv = normalize(level)
    if lv == "public":
        return True
    return lv == "known" and v == "known"


def readable_levels(viewer: Any) -> tuple[str, ...]:
    """이 사람에게 보여도 되는 범위들. 목록 조회를 걸 때 쓴다."""
    v = normalize_viewer(viewer)
    if v == "owner":
        return LEVELS
    if v == "known":
        return ("public", "known")
    return ("public",)


def sql_in_clause(viewer: Any, column: str) -> str:
    """날 SQL 에 끼우는 조건. 주인이면 아예 조건을 달지 않는다.

    값은 직접 넣지 않고 리터럴로 적는다. `viewer` 는 서버가 잰 것이지 사용자가
    보낸 것이 아니고, 넣는 값도 이 모듈이 아는 세 단어뿐이다. 그래도 문자열을
    조립해 SQL 에 넣는 자리이므로 **여기 말고 다른 곳에서는 만들지 않는다.**
    """
    levels = readable_levels(viewer)
    if set(levels) == set(LEVELS):
        return ""
    quoted = ", ".join(f"'{lv}'" for lv in levels)
    return f" AND {column} IN ({quoted})"
