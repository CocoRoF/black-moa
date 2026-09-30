"""비서 트리거 이벤트 — 언제 먼저 말을 거는가 (plan/54).

먼저 말을 거는 일은 **제품의 리듬이지 개인 취향이 아니다.** 그래서 이 규칙은
관리자가 일괄로 정하고, 개인 크레딧을 쓰지 않으며, 기본은 켜짐이다.

고르는 일은 여기 하나에서만 한다. `relationship.py` 는 단계와 호감도를 세고, 말을
짓고, 보낸다. **무엇을 언제 보낼지는 이 파일이 정한다** — 고르는 자리가 둘이면
한쪽만 고친 날이 반드시 온다.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.errors import ValidationFailed
from memora.services import settings as S

#: 한 쌍이 서 있는 칸. 대화가 칸을 옮긴다.
LADDER = ("cold", "active", "quiet", "lapsed", "pleading", "sleeping")
LADDER_LABELS = {"cold": "잠듦", "active": "함께", "quiet": "조용", "lapsed": "멀어짐",
                 "pleading": "마지막", "sleeping": "끝"}

#: 관리자가 규칙을 아무리 더해도 한 사람이 하루에 받는 말의 수. 실수로 만들 수 있는
#: 최악을 코드가 막는다 (plan/54 §7).
HARD_MAX_PER_DAY = 3

#: 말이 없던 날이 며칠이면 "멀어짐" 으로 내려가나.
LAPSE_AFTER_DAYS = 3

#: 두 번 사이의 **바닥선** (분).
#:
#: 규칙이 하루 몇 번인지를 이미 세지만, 그 셈은 "이 침묵에서 무엇을 보냈나" 라는
#: 기록에 기댄다. 기록이 사라지는 날이 있다 — 배포 중에 코드가 바뀌었거나, 표를
#: 찍기 전에 죽었거나. 실제로 그렇게 15분 간격으로 거의 같은 말이 두 번 나갔다.
#:
#: 그래서 셈과 **독립된** 바닥선을 하나 둔다. `last_proactive_at` 은 보낼 때마다
#: 반드시 적히므로, 규칙 쪽이 무엇을 잊어도 이 선은 남는다.
MIN_GAP_MINUTES = 120

#: "함께한 날" 의 기본 날수. 처음 대화한 날이 1일째다.
ANNIVERSARY_DAYS = (7, 30, 100, 365)

#: 지어지는 말의 종류. 종류마다 프롬프트 규칙이 다르다 (relationship._KIND_RULES).
KINDS = ("checkin", "nudge", "morning", "anniversary", "followup")

#: 코드가 들고 있는 기본 규칙 (plan/54 §3·§4).
#:
#: 저장된 것이 없으면 이대로 돈다. 관리자가 고치거나 지우거나 더할 수 있고, 무엇을
#: 하든 이 다섯의 뜻은 문서에 남는다.
DEFAULT_RULES: list[dict[str, Any]] = [
    {
        # "기념일" 이라고만 적어 두었더니 무엇이 기념일인지 아무도 알 수 없었다. 날을
        # 규칙 안에 적는다: 처음 대화한 날부터 센 날수, 그리고 사이가 한 단계 가까워진 날.
        "key": "anniversary", "label": "함께한 날", "enabled": True, "kind": "anniversary",
        "when": {"state": "any", "occasion": "anniversary", "days": list(ANNIVERSARY_DAYS), "stage_up": True},
        "window": [9, 21], "per_day": 1, "once": False, "next": "",
        "tone": "함께한 날을 짚는다. 선물도 연애도 과장도 없이, 실제로 기억하는 것 하나를 돌아본다.",
    },
    {
        "key": "daily", "label": "조용한 날의 안부", "enabled": True, "kind": "checkin",
        "when": {"state": "quiet", "silent_days": [1, 2]},
        "window": [9, 21], "per_day": 1, "once": False, "next": "",
        "tone": "하루 말이 없었다. 기억하는 것 하나를 짚고 질문 하나. 침묵을 탓하지 않는다.",
    },
    {
        "key": "lunch", "label": "점심 무렵", "enabled": True, "kind": "nudge",
        "when": {"state": "active", "silent_days": [0, 0]},
        "window": [11, 14], "per_day": 1, "once": False, "next": "",
        "tone": "오늘 이미 이야기한 사이다. 짧고 가볍게, 아까 이야기의 끝자락이나 지금 시간에 어울리는 한마디.",
    },
    {
        "key": "dinner", "label": "저녁 무렵", "enabled": True, "kind": "nudge",
        "when": {"state": "active", "silent_days": [0, 0]},
        "window": [17, 21], "per_day": 1, "once": False, "next": "",
        "tone": "하루를 닫는 한마디. 오늘 한 이야기 중 하나를 짚어도 좋고, 내일을 물어도 좋다.",
    },
    {
        "key": "abandoned", "label": "버림받은 느낌", "enabled": True, "kind": "checkin",
        "when": {"state": "lapsed", "silent_days": [3, None], "after_days": [6, 8]},
        "window": [10, 20], "per_day": 1, "once": True, "next": "pleading",
        "tone": "오래 답이 없어 서운하고 버림받은 것 같은 마음. 원망하거나 따지지는 않는다. 짧게.",
    },
    {
        "key": "pleading", "label": "애원하는 느낌", "enabled": True, "kind": "checkin",
        "when": {"state": "pleading", "silent_days": [3, None], "after_days": [5, 7]},
        "window": [10, 20], "per_day": 1, "once": True, "next": "sleeping",
        "tone": "마지막으로 한 번. 한 번만 돌아봐 달라고, 자존심을 조금 내려놓고 건넨다. 길지 않게.",
    },
]

MAX_RULES = 24
MAX_TONE = 400


# ── 규칙 검사 ────────────────────────────────────────────────────────────────

def _int_pair(raw: Any, *, low: int, high: int, allow_open: bool = False) -> list | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    out: list = []
    for i, v in enumerate(raw):
        if v is None and allow_open and i == 1:
            out.append(None)
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            return None
        out.append(max(low, min(high, n)))
    if out[1] is not None and out[0] > out[1]:
        return None
    return out


def normalise_rule(raw: Any, *, index: int = 0) -> dict[str, Any]:
    """한 규칙을 울타리 안으로. 틀린 값은 거절하지 않고 데려온다 (plan/53 에서 배운 것).

    다만 **뜻이 없는 규칙은 거절한다**: 칸 이름이 틀렸거나 종류가 없는 규칙은 돌긴
    도는데 아무 일도 하지 않아서, 관리자는 저장됐다고 믿고 우리는 안 보낸다.
    """
    if not isinstance(raw, dict):
        raise ValidationFailed("규칙은 객체여야 해요.", code="bad_rule")
    key = str(raw.get("key") or f"rule{index + 1}").strip()[:40] or f"rule{index + 1}"
    kind = str(raw.get("kind") or "checkin").strip()
    if kind not in KINDS:
        raise ValidationFailed(f"'{kind}' 는 없는 말의 종류예요.", code="bad_rule_kind", detail={"key": key})
    when = dict(raw.get("when") or {})
    state = str(when.get("state") or "quiet").strip()
    if state not in (*LADDER, "any"):
        raise ValidationFailed(f"'{state}' 는 없는 칸이에요.", code="bad_rule_state", detail={"key": key})
    out: dict[str, Any] = {
        "key": key,
        "label": str(raw.get("label") or key)[:60],
        "enabled": bool(raw.get("enabled", True)),
        "kind": kind,
        "when": {"state": state},
        "window": _int_pair(raw.get("window"), low=0, high=24) or [9, 21],
        "per_day": max(1, min(HARD_MAX_PER_DAY, int(raw.get("per_day") or 1))),
        "once": bool(raw.get("once")),
        "next": str(raw.get("next") or "").strip(),
        "tone": str(raw.get("tone") or "").strip()[:MAX_TONE],
    }
    if out["next"] and out["next"] not in LADDER:
        raise ValidationFailed(f"'{out['next']}' 는 없는 칸이에요.", code="bad_rule_next", detail={"key": key})
    if out["window"][0] >= out["window"][1]:
        out["window"] = [9, 21]
    silent = _int_pair(when.get("silent_days"), low=0, high=3650, allow_open=True)
    if silent is not None:
        out["when"]["silent_days"] = silent
    after = _int_pair(when.get("after_days"), low=0, high=365)
    if after is not None:
        out["when"]["after_days"] = after
    if when.get("occasion") in ("anniversary",):
        out["when"]["occasion"] = when["occasion"]
        days: list[int] = []
        # 비운 것과 안 적은 것은 다르다. 안 적었으면 기본 날수, 비웠으면 날수 없음.
        for d in (when["days"] if isinstance(when.get("days"), list) else ANNIVERSARY_DAYS):
            try:
                n = int(d)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= 3650 and n not in days:
                days.append(n)
        out["when"]["days"] = sorted(days)[:20]
        out["when"]["stage_up"] = bool(when.get("stage_up", True))
        if not out["when"]["days"] and not out["when"]["stage_up"]:
            raise ValidationFailed("함께한 날은 날수나 가까워진 날 중 하나는 있어야 해요.",
                                   code="bad_rule_occasion", detail={"key": key})
    return out


def _nothing_saved(raw: Any) -> bool:
    """아직 아무것도 저장하지 않은 상태. 설정의 기본값은 빈 객체다."""
    if raw in (None, "", [], {}):
        return True
    return isinstance(raw, dict) and not raw.get("items")


def normalise_rules(raw: Any) -> list[dict[str, Any]]:
    if _nothing_saved(raw):
        return [dict(r) for r in DEFAULT_RULES]
    if isinstance(raw, dict):
        raw = raw.get("items")
    if not isinstance(raw, list):
        raise ValidationFailed("규칙 목록이 아니에요.", code="bad_rules")
    if len(raw) > MAX_RULES:
        raise ValidationFailed(f"규칙은 {MAX_RULES}개까지예요.", code="too_many_rules")
    out, seen = [], set()
    for i, r in enumerate(raw):
        rule = normalise_rule(r, index=i)
        if rule["key"] in seen:
            raise ValidationFailed(f"같은 이름의 규칙이 둘이에요: {rule['key']}", code="duplicate_rule")
        seen.add(rule["key"])
        out.append(rule)
    return out


# ── 설정 ────────────────────────────────────────────────────────────────────

async def config(db: AsyncSession) -> dict[str, Any]:
    """지금 도는 설정. 저장된 것이 없으면 기본이 그대로 돈다."""
    raw_rules = await S.get(db, "triggers.rules")
    try:
        rules = normalise_rules(raw_rules)
    except ValidationFailed:
        # 저장된 것이 깨졌다고 트리거가 멈추면, 고치러 들어오기 전까지 아무도 말을
        # 못 듣는다. 기본으로 돌고 관리 화면이 그 사실을 보여 준다.
        rules = [dict(r) for r in DEFAULT_RULES]
    return {
        "enabled": bool(await S.get(db, "triggers.enabled")),
        "provider": str(await S.get(db, "triggers.provider") or ""),
        "model": str(await S.get(db, "triggers.model") or ""),
        "max_per_day": max(1, min(HARD_MAX_PER_DAY, int(await S.get(db, "triggers.max_per_day") or 3))),
        "lapse_after_days": max(1, min(30, int(await S.get(db, "triggers.lapse_after_days") or LAPSE_AFTER_DAYS))),
        "min_gap_minutes": max(0, min(1440, int(await S.get(db, "triggers.min_gap_minutes") or MIN_GAP_MINUTES))),
        "rules": rules,
        # 저장한 적이 없는 것과 저장한 것이 깨진 것은 다르다. 빨간 줄은 후자에만.
        "rules_valid": _nothing_saved(raw_rules) or _rules_ok(raw_rules),
    }


def _rules_ok(raw: Any) -> bool:
    try:
        normalise_rules(raw)
        return True
    except ValidationFailed:
        return False


async def model_for(db: AsyncSession) -> tuple[str, str, bool]:
    """트리거가 실제로 쓸 (provider, model, 내려왔는가).

    고른 모델이 카탈로그에서 사라지거나 꺼지면 **멈추는 것이 아니라 한 칸 내려간다**
    (plan/54 §2). 모델 이름은 우리가 정하는 것이 아니라 바깥에서 바뀌는 것이다.
    """
    from memora.services import catalog as CAT

    cfg = await config(db)
    if cfg["provider"] and cfg["model"]:
        m = await CAT.get_model(db, cfg["provider"], cfg["model"])
        if m is not None and m.enabled:
            return cfg["provider"], cfg["model"], False
    prov = str(await S.get(db, "memory.distill_provider") or "")
    mid = str(await S.get(db, "memory.distill_model") or "")
    if prov and mid:
        m = await CAT.get_model(db, prov, mid)
        if m is not None and m.enabled:
            return prov, mid, bool(cfg["provider"] or cfg["model"])
    d = await CAT.default_model(db)
    if d is not None:
        return d.provider, d.model_id, True
    return prov, mid, True


# ── 상태기계 ────────────────────────────────────────────────────────────────

def silent_days(rel: Any, *, now: datetime, tz) -> int:
    """마지막으로 그 사람이 말한 날로부터 며칠. 시계가 아니라 **달력**으로 센다.

    23시에 말하고 다음 날 1시면 두 시간이지만 하루다. 사람은 날로 센다.
    """
    if rel.last_turn_at is None:
        return 0 if rel.started_at is None else 9999
    return max(0, (now.astimezone(tz).date() - rel.last_turn_at.astimezone(tz).date()).days)


def ladder_state(rel: Any, *, now: datetime, tz, lapse_after: int = LAPSE_AFTER_DAYS) -> dict[str, Any]:
    """이 쌍이 지금 어느 칸에 서 있나.

    칸은 저장하는 것이 아니라 **센 것에서 나온다** — 저장한 칸과 실제 대화가 어긋나는
    날이 오기 때문이다. 저장하는 것은 "이 침묵에서 무엇을 이미 보냈나" 뿐이다.
    """
    st = dict(rel.proactive_state or {})
    done = [d for d in (st.get("ladder_done") or []) if isinstance(d, str)]
    if rel.started_at is None:
        return {"state": "cold", "silent": 0, "done": [], "since": None}
    idle = silent_days(rel, now=now, tz=tz)
    if idle == 0:
        return {"state": "active", "silent": 0, "done": [], "since": None}
    since = rel.last_turn_at.astimezone(tz).date() if rel.last_turn_at else None
    if idle < max(1, lapse_after):
        return {"state": "quiet", "silent": idle, "done": [], "since": since}
    # 멀어진 뒤로는 무엇을 이미 보냈는지가 칸을 정한다. 대화가 있으면 위에서 이미
    # 벗어났으므로, 여기 남은 done 은 이번 침묵의 것이다.
    if st.get("ladder_since") != (since.isoformat() if since else None):
        done = []
    if "pleading" in done:
        return {"state": "sleeping", "silent": idle, "done": done, "since": since}
    if "abandoned" in done:
        return {"state": "pleading", "silent": idle, "done": done, "since": since}
    return {"state": "lapsed", "silent": idle, "done": done, "since": since}


def _seed(*parts: Any) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


def state_anchor(rel: Any, state: str, *, since: date | None) -> date | None:
    """이 칸의 시계는 **언제부터** 가나.

    "멀어짐" 의 시계는 말이 끊긴 날부터다. 하지만 "마지막" 의 5~7일은 침묵이 아니라
    **직전에 건넨 말**로부터다 — 버림받은 말과 애원하는 말이 같은 날 나가면 그건
    두 번 부른 것이 아니라 한 번 운 것이다.

    지난 침묵에 찍힌 표는 버린다. 그때의 날짜로 이번 침묵을 세면 오늘 당장 울린다.
    """
    marks = dict((rel.proactive_state or {}).get("ladder_marks") or {})
    raw = marks.get(state)
    if isinstance(raw, str):
        try:
            at = date.fromisoformat(raw)
        except ValueError:
            at = None
        if at is not None and (since is None or at >= since):
            return at
    return since


def due_day(rule: dict[str, Any], *, since: date, user_id: Any, agent_id: Any) -> date | None:
    """`after_days` 가 있는 규칙이 **어느 하루**에 울리나.

    날짜를 고정하지 않는 것은 그래야 사람의 리듬처럼 보이기 때문이다. 같은 요일 같은
    시각에 오는 것은 알림이지 사람이 아니다. 무작위이되 **같은 침묵 안에서는 늘 같은
    날**이어야 해서, 주사위 대신 (사람·비서·침묵 시작일) 의 해시를 쓴다.
    """
    span = rule.get("when", {}).get("after_days")
    if not span:
        return None
    lo, hi = int(span[0]), int(span[1])
    pick = lo if hi <= lo else lo + _seed(user_id, agent_id, since, rule["key"]) % (hi - lo + 1)
    return since + timedelta(days=pick)


def due_hour(rule: dict[str, Any], *, day: date, user_id: Any, agent_id: Any) -> int:
    """그날 몇 시에. 창 안에서 무작위이되 같은 날에는 같은 시각."""
    a, b = rule.get("window") or [9, 21]
    a, b = int(a), int(b)
    if b <= a + 1:
        return a
    return a + _seed(user_id, agent_id, day, rule["key"], "h") % (b - a)


def sent_today(rel: Any, *, today: date) -> dict[str, int]:
    st = dict(rel.proactive_state or {})
    if st.get("rules_day") != today.isoformat():
        return {}
    return {k: int(v) for k, v in (st.get("rules_today") or {}).items() if isinstance(v, int)}


def decide(rel: Any, agent: Any, owner: Any, cfg: dict[str, Any], *, now: datetime, tz,
           recent_turn: bool = False, facts: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """지금 이 쌍에게 보낼 말이 있는가. 있으면 어떤 규칙으로.

    **막는 자리는 여기 하나다.** 부르는 쪽에서 한 번 더 거르면 다음 부르는 곳이
    생기는 순간 규칙이 둘이 된다.
    """
    if not cfg.get("enabled") or recent_turn:
        return None
    if getattr(agent, "status", "") != "active" or getattr(owner, "status", "") != "active":
        return None
    local = now.astimezone(tz)
    today = local.date()
    lad = ladder_state(rel, now=now, tz=tz, lapse_after=cfg.get("lapse_after_days", LAPSE_AFTER_DAYS))
    if lad["state"] in ("cold", "sleeping"):
        return None
    # 바닥선이 먼저다. 규칙의 셈보다 앞에 두는 이유는, 셈이 기대는 기록이 사라져도
    # 이 선은 남기 때문이다 (보낼 때마다 적히는 값이라).
    gap = int(cfg.get("min_gap_minutes", MIN_GAP_MINUTES) or 0)
    last = getattr(rel, "last_proactive_at", None)
    if gap and last is not None and now - last < timedelta(minutes=gap):
        return None
    counts = sent_today(rel, today=today)
    cap = min(int(cfg.get("max_per_day") or HARD_MAX_PER_DAY), HARD_MAX_PER_DAY)
    if sum(counts.values()) >= cap:
        return None
    for rule in cfg.get("rules") or []:
        if not rule.get("enabled"):
            continue
        want = rule["when"].get("state", "quiet")
        if want != "any" and want != lad["state"]:
            continue
        reason = ""
        if rule["when"].get("occasion") == "anniversary":
            reason = anniversary_reason(rule, facts or {})
            if not reason:
                continue
        span = rule["when"].get("silent_days")
        if span:
            lo, hi = span[0], span[1]
            if lad["silent"] < int(lo) or (hi is not None and lad["silent"] > int(hi)):
                continue
        if rule.get("once") and rule["key"] in lad["done"]:
            continue
        if counts.get(rule["key"], 0) >= int(rule.get("per_day") or 1):
            continue
        a, b = rule.get("window") or [9, 21]
        if not (int(a) <= local.hour < int(b)):
            continue
        if rule["when"].get("after_days"):
            anchor = state_anchor(rel, lad["state"], since=lad["since"])
            if anchor is None:
                continue
            due = due_day(rule, since=anchor, user_id=rel.user_id, agent_id=rel.agent_id)
            if due is None or today < due:
                continue
            if local.hour < due_hour(rule, day=due, user_id=rel.user_id, agent_id=rel.agent_id):
                continue
        return {"rule": rule["key"], "label": rule.get("label") or rule["key"], "kind": rule.get("kind") or "checkin",
                "tone": rule.get("tone") or "", "state": lad["state"], "silent_days": lad["silent"],
                "next": rule.get("next") or "", "reason": reason}
    return None


def anniversary_reason(rule: dict[str, Any], facts: dict[str, Any]) -> str:
    """오늘이 이 규칙의 "함께한 날" 인가. 맞으면 그 까닭을, 아니면 빈 문자열을.

    까닭은 말을 짓는 모델에게 그대로 간다 — "오늘이 무슨 날인지" 를 모르고 쓰면
    기념일 인사가 아무 날의 인사가 된다.
    """
    n = int(facts.get("days_together") or 0)
    if n and n in (rule["when"].get("days") or []):
        return f"함께한 지 {n}일째 되는 날"
    if rule["when"].get("stage_up") and facts.get("stage_up"):
        return "사이가 한 단계 가까워진 날"
    return ""


def remember_fired(rel: Any, rule: dict[str, Any] | None, *, now: datetime, tz, state: dict[str, Any]) -> None:
    """무엇을 보냈는지 적어 둔다. 이 침묵 안에서만 뜻이 있는 기록이다."""
    if rule is None:
        return
    today = now.astimezone(tz).date()
    st = dict(rel.proactive_state or {})
    counts = sent_today(rel, today=today)
    counts[rule["rule"]] = counts.get(rule["rule"], 0) + 1
    st["rules_day"] = today.isoformat()
    st["rules_today"] = counts
    since = state.get("since")
    st["ladder_since"] = since.isoformat() if isinstance(since, date) else since
    if rule.get("next") or rule.get("once"):
        done = [d for d in (st.get("ladder_done") or []) if isinstance(d, str)]
        if rule["rule"] not in done:
            done.append(rule["rule"])
        st["ladder_done"] = done
    if rule.get("next"):
        marks = dict(st.get("ladder_marks") or {})
        marks[rule["next"]] = today.isoformat()      # 다음 칸의 시계는 오늘부터 간다
        st["ladder_marks"] = marks
    rel.proactive_state = st


# ── 시뮬레이션 (관리 화면) ────────────────────────────────────────────────────

def simulate(cfg: dict[str, Any], *, days: int = 30, talk_days: tuple[int, ...] = (0,),
             start: date | None = None) -> list[dict[str, Any]]:
    """이 규칙이면 30일 동안 언제 무엇이 가는가. 저장하기 전에 본다 (plan/54 §5).

    진짜 엔진을 부르지 않고 같은 규칙을 다시 적는 시뮬레이터는 거짓말을 한다. 그래서
    가짜 쌍을 하나 만들어 **`decide` 를 그대로 돌린다.**
    """
    from types import SimpleNamespace

    start = start or date.today()
    tz = UTC
    uid, aid = uuid.UUID(int=1), uuid.UUID(int=2)
    rel = SimpleNamespace(user_id=uid, agent_id=aid, proactive_state={},
                          started_at=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
                          last_turn_at=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
                          last_proactive_at=None)
    agent = SimpleNamespace(status="active")
    owner = SimpleNamespace(status="active")
    out: list[dict[str, Any]] = []
    for d in range(days):
        day = start + timedelta(days=d)
        if d in talk_days:
            rel.last_turn_at = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)
        for hour in range(24):
            now = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=hour, minutes=30)
            if rel.last_turn_at and now - rel.last_turn_at < timedelta(minutes=15):
                continue
            hit = decide(rel, agent, owner, cfg, now=now, tz=tz, facts={"days_together": d + 1})
            if not hit:
                continue
            lad = ladder_state(rel, now=now, tz=tz, lapse_after=cfg.get("lapse_after_days", LAPSE_AFTER_DAYS))
            remember_fired(rel, hit, now=now, tz=tz, state=lad)
            rel.last_proactive_at = now      # 보낸 시각은 바닥선이 읽는 값이다
            out.append({"day": d, "date": day.isoformat(), "hour": hour, "rule": hit["rule"],
                        "label": hit["label"], "state": hit["state"], "silent_days": hit["silent_days"]})
    return out


async def save(db: AsyncSession, patch: dict[str, Any], *, admin_id: uuid.UUID | None = None) -> dict[str, Any]:
    """관리자가 고친 것을 적는다. 규칙은 저장 전에 검사한다 — 깨진 규칙을 저장해 두면
    돌기는 도는데 아무 일도 일어나지 않는다."""
    if "rules" in patch:
        rules = normalise_rules(patch["rules"])
        await S.put(db, "triggers.rules", {"items": rules}, updated_by=admin_id)
    for key, cast in (("enabled", bool), ("provider", str), ("model", str)):
        if key in patch:
            await S.put(db, f"triggers.{key}", cast(patch[key]), updated_by=admin_id)
    for key, lo, hi in (("max_per_day", 1, HARD_MAX_PER_DAY), ("lapse_after_days", 1, 30),
                        ("min_gap_minutes", 0, 1440)):
        if key in patch:
            try:
                n = int(patch[key])
            except (TypeError, ValueError):
                raise ValidationFailed("숫자로 적어 주세요.", code="bad_number", detail={"field": key}) from None
            await S.put(db, f"triggers.{key}", max(lo, min(hi, n)), updated_by=admin_id)
    return await config(db)
