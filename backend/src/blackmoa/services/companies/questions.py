"""What a review asks about working life (plan/40 §8).

Not five star scales. A reviewer answers concrete questions in plain words — how many
hours a week, how often overtime, whether leave is taken without a glance, whether a
mistake can be said out loud, what a promotion is actually based on, whether they would
join again — and picks who the company suits. Each answer carries a score, so the five
areas still add up to the shape on the page and the number the directory sorts by, but a
reader gets facts ("주 45~52시간이 가장 많아요") and not a 3.4.

Codes are the contract: the screen has the words, the server has the arithmetic.
"""
from __future__ import annotations

from typing import Any

#: The five areas, in the order the page draws them. They keep the old axis codes so the
#: radar, the comparison table and every stored review line up.
AREAS = ("pay", "balance", "culture", "promotion", "management")

#: code → (area, required, [(option, score)]) — score on the 1..5 scale, None = not scored.
QUESTIONS: dict[str, dict[str, Any]] = {
    # 보상
    "pay_level": {"area": "pay", "required": True, "options": [("low", 1.5), ("avg", 3.0), ("high", 4.2), ("top", 5.0)]},
    "raise": {"area": "pay", "required": False, "options": [("none", 1.5), ("cpi", 3.0), ("perf", 4.5)]},
    "welfare": {"area": "pay", "required": False, "options": [("thin", 2.0), ("basic", 3.0), ("rich", 4.5)]},
    # 시간
    "hours": {"area": "balance", "required": True, "options": [("le40", 5.0), ("h40_45", 4.0), ("h45_52", 2.5), ("gt52", 1.0)]},
    "overtime": {"area": "balance", "required": False, "options": [("rare", 5.0), ("monthly", 4.0), ("weekly", 2.5), ("daily", 1.0)]},
    "vacation": {"area": "balance", "required": False, "options": [("free", 5.0), ("coord", 3.5), ("hard", 1.5)]},
    "flex": {"area": "balance", "required": False, "multi": True, "max": 2, "options": [("remote", None), ("flextime", None)]},
    # 사람
    "comm": {"area": "culture", "required": True, "options": [("flat", 5.0), ("mixed", 3.5), ("vertical", 1.5)]},
    "peers": {"area": "culture", "required": False, "options": [("learn", 5.0), ("ok", 3.5), ("weak", 2.0)]},
    "safety": {"area": "culture", "required": False, "options": [("yes", 5.0), ("depends", 3.0), ("no", 1.5)]},
    "social": {"area": "culture", "required": False, "options": [("light", 4.5), ("some", 3.5), ("heavy", 1.5)]},
    # 성장
    "promo_speed": {"area": "promotion", "required": True, "options": [("fast", 5.0), ("normal", 3.5), ("slow", 2.0), ("stuck", 1.0)]},
    "promo_basis": {"area": "promotion", "required": False, "options": [("perf", 5.0), ("tenure", 3.0), ("opaque", 1.0)]},
    "learning": {"area": "promotion", "required": False, "options": [("many", 5.0), ("some", 3.5), ("few", 1.5)]},
    "career_value": {"area": "promotion", "required": False, "options": [("big", 5.0), ("ok", 3.5), ("little", 1.5)]},
    # 경영·안정
    "trust": {"area": "management", "required": True, "options": [("trust", 5.0), ("neutral", 3.0), ("distrust", 1.0)]},
    "vision": {"area": "management", "required": False, "options": [("clear", 5.0), ("vague", 3.0), ("none", 1.0)]},
    "stability": {"area": "management", "required": False, "options": [("stable", 5.0), ("normal", 3.5), ("shaky", 1.0)]},
    "outlook": {"area": "management", "required": False, "options": [("up", 5.0), ("flat", 3.0), ("down", 1.0)]},
    # 총평 — the one number the directory sorts by comes from this, not from a star.
    "again": {"area": None, "required": True, "options": [("must", 5.0), ("probably", 4.0), ("unsure", 2.5), ("no", 1.0)]},
    # 이런 분께 — who it suits and who it does not. Tags, not scores.
    "fit": {"area": None, "required": False, "multi": True, "max": 3,
            "options": [("growth", None), ("stability", None), ("balance", None), ("pay", None), ("autonomy", None),
                        ("structure", None), ("junior", None), ("senior", None)]},
    "unfit": {"area": None, "required": False, "multi": True, "max": 2,
              "options": [("growth", None), ("stability", None), ("balance", None), ("pay", None), ("autonomy", None),
                          ("structure", None), ("junior", None), ("senior", None)]},
}

#: The facts the page and the comparison table quote, in this order.
FACT_QUESTIONS = ("hours", "overtime", "vacation", "comm", "safety", "promo_basis", "stability", "pay_level")

_SCORE = {q: dict(spec["options"]) for q, spec in QUESTIONS.items()}
_OPTIONS = {q: [o for o, _ in spec["options"]] for q, spec in QUESTIONS.items()}


def spec() -> list[dict[str, Any]]:
    """What the form is built from. Codes only — the words are the screen's."""
    return [{"code": q, "area": s["area"], "required": bool(s["required"]), "multi": bool(s.get("multi")),
             "max": s.get("max"), "options": _OPTIONS[q]} for q, s in QUESTIONS.items()]


def clean(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """(answers, missing required questions). Unknown questions and options are dropped —
    an old form must still save — but a required question left blank is the caller's."""
    answers: dict[str, Any] = {}
    raw = raw if isinstance(raw, dict) else {}
    for q, s in QUESTIONS.items():
        v = raw.get(q)
        if s.get("multi"):
            if isinstance(v, list):
                picked = [x for x in dict.fromkeys(str(x) for x in v) if x in _OPTIONS[q]][: int(s.get("max") or 9)]
                if picked:
                    answers[q] = picked
        elif isinstance(v, str) and v in _OPTIONS[q]:
            answers[q] = v
    missing = [q for q, s in QUESTIONS.items() if s["required"] and q not in answers]
    return answers, missing


def area_scores(answers: dict[str, Any]) -> dict[str, float | None]:
    """Each area is the mean of its answered, scored questions. None when nothing scored."""
    out: dict[str, float | None] = {}
    for area in AREAS:
        vals = [_SCORE[q][answers[q]] for q, s in QUESTIONS.items()
                if s["area"] == area and q in answers and not s.get("multi") and _SCORE[q].get(answers[q]) is not None]
        out[area] = round(sum(vals) / len(vals), 2) if vals else None
    return out


def overall(answers: dict[str, Any]) -> float | None:
    v = answers.get("again")
    return _SCORE["again"].get(v) if v else None


def derived(answers: dict[str, Any]) -> dict[str, Any]:
    """The old booleans, read off the new answers, so nothing downstream changes shape."""
    again = answers.get("again")
    trust = answers.get("trust")
    return {
        "recommend": again in ("must", "probably") if again else None,
        "ceo_approval": True if trust == "trust" else False if trust == "distrust" else None,
        "growth": answers.get("outlook") or None,
    }


def tally(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Option counts per question over many reviews' answers, for the facts a page quotes."""
    counts: dict[str, dict[str, int]] = {}
    for a in rows:
        for q, v in (a or {}).items():
            if q not in QUESTIONS:
                continue
            bucket = counts.setdefault(q, {})
            for opt in (v if isinstance(v, list) else [v]):
                bucket[opt] = bucket.get(opt, 0) + 1
    return counts
