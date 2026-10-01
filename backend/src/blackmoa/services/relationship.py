"""Relationship engine (plan/37): how far a person and a secretary have come, what that means
for the secretary's behaviour this turn, and the messages the secretary sends first.

Nothing here is a feeling the product manufactures. The stage is arithmetic over real
conversations; the block it puts in the prompt tells the model how a long-standing pair
behaves differently from two people who met yesterday; the proactive messages are the
secretary doing its job unasked, within a daily cap the owner controls.
"""
from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.logging import get_logger
from blackmoa.models import (
    Agent,
    AgentPersonaVersion,
    AgentRelationship,
    Conversation,
    Fact,
    InboxItem,
    Message,
    User,
)
from blackmoa.pipeline.personas import compile_persona, relationship_params

log = get_logger("blackmoa.relationship")

STAGES = ("new", "familiar", "trusted", "companion")
STAGE_LABELS = {"ko": {"new": "처음", "familiar": "익숙", "trusted": "신뢰", "companion": "동반"},
                "en": {"new": "New", "familiar": "Familiar", "trusted": "Trusted", "companion": "Companion"}}
# (active_days, turns, facts, posts) a pair needs for each stage.
#
# 네 번째가 결이다 (plan/45 §5). 이야기만으로는 [신뢰] 까지다. 마지막 한 칸은 이 사람이
# 자기 이야기를 남긴 적이 있어야 열린다. 한 갈래에서만 온 기억은 아직 그 사람을 아는
# 것이 아니다.
THRESHOLDS = {"familiar": (3, 10, 0, 0), "trusted": (10, 40, 10, 0), "companion": (30, 150, 30, 10)}

# ── 호감도 (plan/45 §4) ───────────────────────────────────────────────────────
#
# 자격은 쌓인 것이고 호감도는 지금이다. 실제 단계는 둘 중 낮은 쪽이라, 오래 쌓은 사이도
# 오래 비면 내려가고, 대신 돌아오는 길이 짧다(자격은 그대로니까).
AFFINITY_BANDS = ((75, "companion"), (50, "trusted"), (25, "familiar"), (0, "new"))
#: 그날 이야기했으면 — 그날 첫 대화가 끝나는 순간에 (plan/61).
AFFINITY_TALK = 8.0
#: 활발한 날: 그날 대화가 이만큼에 닿으면 한 번 더. 몰아서 하는 대화로 금방 차지 않게 하루 한 번.
AFFINITY_LIVELY_TURNS, AFFINITY_LIVELY = 10, 4.0
#: 기억이 하나 늘 때마다. 하루에 이만큼까지.
AFFINITY_PER_FACT, AFFINITY_FACT_CAP = 2.0, 6.0
#: 이틀까지는 아무 일도 없다. 주말도 있고 출장도 있다.
AFFINITY_GRACE_DAYS = 2
#: 사흘째부터. 날마다 가팔라지고, 하루에 이보다 더 잃지는 않는다.
AFFINITY_DECAY_BASE, AFFINITY_DECAY_GROWTH, AFFINITY_DECAY_CAP = 6.0, 1.45, 30.0
#: 먼저 건넨 말에 답이 없으면 (plan/61). 답하지 않은 한 줄기에 기한마다 한 번씩 — 그 사이 더 건넨 말은
#: 새 줄기를 만들지 않는다(하루 세 번까지 건네므로 말마다 깎으면 하루에 −45 가 된다). 알리지 않는다.
AFFINITY_IGNORED = ((timedelta(hours=24), 15.0, "ignored"), (timedelta(hours=48), 25.0, "ignored_2d"))
#: 호감도가 생긴 날(0061). 재계산은 이날부터 다시 센다.
AFFINITY_EPOCH = date(2026, 9, 21)
#: 그날까지 쌓은 자격의 단계로 시작한다 — 0061 이 했던 그대로.
AFFINITY_SEED = {"companion": 100.0, "trusted": 74.0, "familiar": 49.0, "new": 24.0}
AFFINITY_LOG_MAX = 120
#: 워커가 멈춰 있었어도 이만큼까지는 하루씩 정산한다.
AFFINITY_CATCHUP_DAYS = 90
ANNIVERSARIES = (7, 30, 100, 365)
#: 지어지는 말의 종류. 규칙이 고르고(plan/54), 종류마다 프롬프트 규칙이 다르다.
PROACTIVE_KINDS = ("followup", "morning", "checkin", "anniversary", "nudge")
PROACTIVE_TITLES = {"followup": {"ko": "이어서", "en": "Following up"}, "morning": {"ko": "아침 인사", "en": "Morning note"},
                    "checkin": {"ko": "안부", "en": "Checking in"}, "anniversary": {"ko": "함께한 날", "en": "A day to remember"},
                    "nudge": {"ko": "잠깐", "en": "A quick word"}}
# The secretary speaks first only when the owner has not been talking to it for this long
# (plan/37 §4, owner's rule): a message in the middle of a conversation is an interruption.
QUIET_MINUTES = 15
# How long after a conversation a follow-up still makes sense.
FOLLOWUP_WINDOW = timedelta(hours=8)
NOTHING = "NOTHING"
MOODS = ("", "focused", "cheerful", "calm", "curious", "tired", "concerned")


def _tz(owner: User) -> ZoneInfo:
    try:
        return ZoneInfo(owner.timezone or "Asia/Seoul")
    except Exception:
        return ZoneInfo("Asia/Seoul")


def _locale(owner: User) -> str:
    return "en" if (owner.locale or "ko").startswith("en") else "ko"


# ── state ──────────────────────────────────────────────────────────────────────

async def get(db: AsyncSession, user_id: uuid.UUID, agent_id: uuid.UUID) -> AgentRelationship | None:
    return (await db.execute(select(AgentRelationship).where(AgentRelationship.user_id == user_id,
                                                            AgentRelationship.agent_id == agent_id))).scalars().first()


async def get_or_create(db: AsyncSession, user_id: uuid.UUID, agent_id: uuid.UUID) -> AgentRelationship:
    rel = await get(db, user_id, agent_id)
    if rel is None:
        rel = AgentRelationship(user_id=user_id, agent_id=agent_id)
        db.add(rel)
        await db.flush()
    return rel


def thresholds(pace: str = "normal") -> dict[str, tuple[int, int, int, int]]:
    """문지방. 관계가 자라는 빠르기는 아무도 못 바꾼다 (plan/45 §0)."""
    return dict(THRESHOLDS)


def _reached(rel: AgentRelationship, th: tuple[int, int, int, int]) -> bool:
    return (rel.active_days >= th[0] and rel.turns >= th[1]
            and rel.facts_remembered >= th[2] and (rel.posts_written or 0) >= th[3])


def earned_stage(rel: AgentRelationship) -> str:
    """쌓은 것이 허락하는 단계. 누적이라 내려가지 않는다."""
    th = thresholds()
    stage = "new"
    for s in ("familiar", "trusted", "companion"):
        if _reached(rel, th[s]):
            stage = s
        else:
            break
    return stage


def warmth_stage(rel: AgentRelationship) -> str:
    """지금의 온도가 허락하는 단계."""
    a = max(0.0, min(100.0, float(rel.affinity or 0.0)))
    for floor, name in AFFINITY_BANDS:
        if a >= floor:
            return name
    return "new"


def computed_stage(rel: AgentRelationship, pace: str = "normal") -> str:
    """실제 단계는 둘 중 **낮은 쪽**이다. 쌓았어도 지금 비어 있으면 그만큼 멀다."""
    return STAGES[min(STAGES.index(earned_stage(rel)), STAGES.index(warmth_stage(rel)))]


def decay_for(idle_days: int) -> float:
    """며칠 비었을 때 그날 잃는 양. 사흘째부터 날마다 가팔라진다."""
    if idle_days <= AFFINITY_GRACE_DAYS:
        return 0.0
    n = idle_days - AFFINITY_GRACE_DAYS - 1
    return round(min(AFFINITY_DECAY_CAP, AFFINITY_DECAY_BASE * (AFFINITY_DECAY_GROWTH ** n)), 2)


def score(rel: AgentRelationship, pace: str = "normal") -> float:
    d, t, f, p = thresholds()["companion"]
    parts = [min(1.0, rel.active_days / d) * 0.35, min(1.0, rel.turns / t) * 0.35,
             min(1.0, rel.facts_remembered / max(1, f)) * 0.2, min(1.0, (rel.posts_written or 0) / max(1, p)) * 0.1]
    return round(min(1.0, sum(parts)), 4)


def progress(rel: AgentRelationship, pace: str = "normal") -> dict[str, Any] | None:
    """다음 단계까지 무엇이 모자란지. 쌓는 쪽만 센다: 온도는 오늘 하면 오늘 오른다."""
    i = STAGES.index(earned_stage(rel))
    if i >= len(STAGES) - 1:
        return None
    nxt = STAGES[i + 1]
    d, t, f, p = thresholds()[nxt]
    posts = rel.posts_written or 0
    ratios = [min(1.0, rel.active_days / d), min(1.0, rel.turns / t),
              1.0 if f == 0 else min(1.0, rel.facts_remembered / f), 1.0 if p == 0 else min(1.0, posts / p)]
    return {"stage": nxt, "ratio": round(min(ratios), 3),
            "needs": {"days": max(0, d - rel.active_days), "turns": max(0, t - rel.turns),
                      "facts": max(0, f - rel.facts_remembered), "posts": max(0, p - posts)},
            "targets": {"days": d, "turns": t, "facts": f, "posts": p}}


def days_together(rel: AgentRelationship, now: datetime | None = None) -> int:
    if not rel.started_at:
        return 0
    now = now or datetime.now(UTC)
    return max(1, (now.date() - rel.started_at.astimezone(UTC).date()).days + 1)


async def count_facts(db: AsyncSession, user_id: uuid.UUID, agent_id: uuid.UUID) -> int:
    """**이 비서가** 주인에 대해 알게 된 사실의 수.

    읽기와 세기가 같은 규칙을 쓴다: 프롬프트에 들어가는 사실도 이 비서의 것뿐이다
    (`_facts_block`). 사이(관계)는 이 비서와 나 사이의 것이므로, 다른 비서가 알게 된
    것으로 단계가 오르면 그건 남의 공을 가져오는 것이다 (plan/49).
    """
    return int((await db.execute(select(func.count(Fact.id)).where(
        Fact.owner_id == user_id, Fact.status == "active", Fact.visibility != "visitor_private",
        (Fact.agent_id == agent_id) | (Fact.agent_id.is_(None))))).scalar_one())


def _add_milestone(rel: AgentRelationship, key: str, at: datetime, **extra) -> bool:
    ms = list(rel.milestones or [])
    if any(m.get("key") == key for m in ms):
        return False
    ms.append({"key": key, "at": at.isoformat(), **extra})
    rel.milestones = ms[-60:]
    return True


def refresh_stage(rel: AgentRelationship, agent: Agent, now: datetime | None = None) -> list[str]:
    """단계·진행도·이정표를 다시 센다. 새로 생긴 이정표를 돌려준다.

    **단계는 내려갈 수 있다** (plan/45 §4). 쌓은 것은 그대로지만 오래 비면 지금의 사이는
    그만큼 멀다. 올라간 것만 소식으로 전한다: 멀어진 것은 알림이 아니라 상태다.
    이정표는 한 번 찍히면 지우지 않는다. 그건 역사이지 상태가 아니다.
    """
    now = now or datetime.now(UTC)
    new_keys: list[str] = []
    cur = rel.stage if rel.stage in STAGES else "new"
    comp = computed_stage(rel)
    if comp != cur:
        rel.stage, rel.stage_changed_at = comp, now
        if STAGES.index(comp) > STAGES.index(cur) and _add_milestone(rel, f"stage_{comp}", now):
            new_keys.append(f"stage_{comp}")
    rel.score = score(rel)
    days = days_together(rel, now)
    for n in ANNIVERSARIES:
        # An anniversary that passed before the engine existed is recorded on its real date
        # and not announced: only today's counts as news.
        if days >= n and _add_milestone(rel, f"days_{n}", now if days == n else (rel.started_at + timedelta(days=n - 1))) and days == n:
            new_keys.append(f"days_{n}")
    if rel.facts_remembered >= 1 and _add_milestone(rel, "first_memory", now):
        new_keys.append("first_memory")
    return new_keys


async def count_posts(db: AsyncSession, owner_id: uuid.UUID) -> int:
    from blackmoa.models import BlogPost

    return int((await db.execute(select(func.count(BlogPost.id)).where(
        BlogPost.owner_id == owner_id, BlogPost.status == "published"))).scalar_one())


async def posted_days(db: AsyncSession, owner_id: uuid.UUID, start: date, end: date, tz: ZoneInfo) -> set[date]:
    """이 사람이 무언가를 남긴 날들 (plan/45 §4).

    바빠서 이야기할 틈이 없는 날에도 사진 한 장과 한 줄이면 방치가 아니다. 회복은 아니고
    그날 식지 않을 뿐이다.
    """
    from blackmoa.models import BlogPost

    if end < start:
        return set()
    lo = datetime.combine(start, time.min, tzinfo=tz).astimezone(UTC)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    rows = (await db.execute(select(BlogPost.created_at).where(
        BlogPost.owner_id == owner_id, BlogPost.created_at >= lo, BlogPost.created_at < hi))).scalars().all()
    return {r.astimezone(tz).date() for r in rows if r}


# ── 호감도 엔진 (plan/61) ──────────────────────────────────────────────────────
#
# 실시간(대화 · 15분 작업 · 먼저 건넨 말)과 재계산이 **같은 함수**를 쓴다. 규칙이 두 벌이면 한쪽만 고친
# 날이 반드시 온다.
#
#   advance      지금까지 끝난 날의 정산과 무응답 기한을 시간 순서대로
#   credit_turn  대화 한 번: 그날 첫 대화 +8, 열 번째 +4, 기다리던 말에 답함
#   credit_facts 기억이 늘어난 만큼(하루 최대)
#   note_proactive  먼저 건넨 말 — 답을 기다리기 시작
#
# 예전의 결함: 하루 한 번 정산에 오르는 것과 내리는 것을 함께 넣었더니, 15분 작업이 자정 직후 그날을 먼저
# 정산해 버려 낮의 대화가 한 번도 오르지 못했다. 이제 오르는 것은 그 순간에, 내리는 것은 그날이 끝난 뒤에.

def _st(rel: AgentRelationship) -> dict[str, Any]:
    return dict(rel.affinity_state or {})


def _bump(rel: AgentRelationship, delta: float, why: str, at: datetime) -> float:
    before = float(rel.affinity or 0.0)
    after = round(max(0.0, min(100.0, before + delta)), 2)
    rel.affinity = after
    log = list(rel.affinity_log or [])
    log.append({"at": at.astimezone(UTC).isoformat(timespec="seconds"), "d": round(after - before, 2), "why": why, "v": after})
    rel.affinity_log = log[-AFFINITY_LOG_MAX:]
    return after - before


def _today(st: dict[str, Any], day: date) -> dict[str, Any]:
    if st.get("day") != day.isoformat():
        st.update({"day": day.isoformat(), "turns": 0, "talked": False, "lively": False, "facts": 0.0})
    return st


def _last_talk(rel: AgentRelationship, st: dict[str, Any], d: date, tz: ZoneInfo) -> date | None:
    """d 이전(포함)의 마지막 대화한 날. 최근 대화한 날 목록이 정본이고, 없으면 기록된 마지막 날."""
    days = [x for x in (date.fromisoformat(v) for v in st.get("talk_days") or []) if x <= d]
    if days:
        return max(days)
    if rel.last_active_day and rel.last_active_day <= d:
        return rel.last_active_day
    if rel.started_at:
        return rel.started_at.astimezone(tz).date()
    return None


def _settle_day(rel: AgentRelationship, st: dict[str, Any], d: date, tz: ZoneInfo, posted: set[date]) -> None:
    """끝난 하루 d 를 정산한다: 말 없이 사흘째 이후면 식는다. 그날 대화했거나 글을 남겼으면 없다."""
    talked = d.isoformat() in (st.get("talk_days") or []) or rel.last_active_day == d
    if talked or d in posted:
        return
    last = _last_talk(rel, st, d, tz)
    silence = (d - last).days if last else AFFINITY_GRACE_DAYS + 1
    loss = decay_for(silence)
    if loss:
        at = datetime.combine(d + timedelta(days=1), time.min, tzinfo=tz)
        _bump(rel, -loss, f"quiet_{silence}", at)


def _check_ignored(rel: AgentRelationship, st: dict[str, Any], now: datetime) -> None:
    aw = st.get("awaiting")
    if not aw:
        return
    since = datetime.fromisoformat(aw["since"])
    steps = int(aw.get("steps") or 0)
    for i, (after, loss, why) in enumerate(AFFINITY_IGNORED):
        if steps <= i and now >= since + after:
            _bump(rel, -loss, why, since + after)
            steps = i + 1
    st["awaiting"] = {**aw, "steps": steps}


def advance(rel: AgentRelationship, now: datetime, tz: ZoneInfo, posted: set[date] | None = None) -> None:
    """지금까지 일어났어야 할 일을 **시간 순서대로**: 끝난 날마다의 정산, 답을 기다리는 말의 기한.

    워커가 며칠 멈춰 있었어도 그 날들을 하루씩 센다(최근 대화한 날 목록으로 각 날의 침묵 길이를 안다).
    """
    posted = posted or set()
    st = _st(rel)
    today = now.astimezone(tz).date()
    if rel.affinity_day is None:
        start = rel.started_at.astimezone(tz).date() if rel.started_at else today
        rel.affinity_day = start - timedelta(days=1)
    first = max(rel.affinity_day + timedelta(days=1), today - timedelta(days=AFFINITY_CATCHUP_DAYS))
    points: list[tuple[datetime, str, Any]] = []
    d = first
    while d < today:
        points.append((datetime.combine(d + timedelta(days=1), time.min, tzinfo=tz), "day", d))
        d += timedelta(days=1)
    aw = st.get("awaiting")
    if aw:
        since = datetime.fromisoformat(aw["since"])
        for i, (after, _loss, _why) in enumerate(AFFINITY_IGNORED):
            if int(aw.get("steps") or 0) <= i and since + after <= now:
                points.append((since + after, "ignored", i))
    for at, what, arg in sorted(points, key=lambda p: (p[0], p[1])):
        if what == "day":
            _settle_day(rel, st, arg, tz, posted)
            rel.affinity_day = arg
        else:
            _check_ignored(rel, st, at)
    if rel.affinity_day < today - timedelta(days=1):
        rel.affinity_day = today - timedelta(days=1)
    rel.affinity_state = st


def credit_turn(rel: AgentRelationship, at: datetime, tz: ZoneInfo) -> None:
    """대화 한 번이 끝났다. ``advance`` 뒤에 부른다."""
    st = _st(rel)
    day = at.astimezone(tz).date()
    _today(st, day)
    st["turns"] = int(st.get("turns") or 0) + 1
    if not st.get("talked"):
        _bump(rel, AFFINITY_TALK, "talk", at)
        st["talked"] = True
        st["talk_days"] = sorted({*(st.get("talk_days") or []), day.isoformat()})[-30:]
    if st["turns"] >= AFFINITY_LIVELY_TURNS and not st.get("lively"):
        _bump(rel, AFFINITY_LIVELY, "lively", at)
        st["lively"] = True
    # 기다리던 말에 답했다 — 그 줄기는 여기서 끝난다.
    st.pop("awaiting", None)
    rel.affinity_state = st


def credit_facts(rel: AgentRelationship, at: datetime, tz: ZoneInfo, facts_now: int) -> None:
    """기억이 늘어난 만큼(하루 최대). 줄었으면 기준만 낮춘다 — 지운 기억을 다시 쳐 주지 않는다."""
    gained = int(facts_now) - int(rel.affinity_facts or 0)
    if gained > 0:
        st = _today(_st(rel), at.astimezone(tz).date())
        room = max(0.0, AFFINITY_FACT_CAP - float(st.get("facts") or 0.0))
        pts = min(room, gained * AFFINITY_PER_FACT)
        if pts > 0:
            _bump(rel, pts, "memory", at)
            st["facts"] = float(st.get("facts") or 0.0) + pts
        rel.affinity_state = st
    rel.affinity_facts = int(facts_now)


def note_proactive(rel: AgentRelationship, at: datetime) -> None:
    """먼저 건넨 말 — 답을 기다리기 시작한다. 이미 기다리는 중이면 처음 말부터 센다."""
    st = _st(rel)
    if not st.get("awaiting"):
        st["awaiting"] = {"since": at.astimezone(UTC).isoformat(timespec="seconds"), "steps": 0}
    rel.affinity_state = st


async def _posted_since_settled(db: AsyncSession, rel: AgentRelationship, owner: User, now: datetime, tz: ZoneInfo) -> set[date]:
    today = now.astimezone(tz).date()
    first = (rel.affinity_day + timedelta(days=1)) if rel.affinity_day else today - timedelta(days=1)
    if first >= today:
        return set()
    return await posted_days(db, owner.id, max(first, today - timedelta(days=AFFINITY_CATCHUP_DAYS)), today - timedelta(days=1), tz)


async def settle(db: AsyncSession, *, owner: User, agent: Agent, rel: AgentRelationship, now: datetime | None = None) -> float:
    """15분 작업의 몫: 끝난 날들 · 무응답 기한 · 늘어난 기억. 호감도가 얼마나 움직였는지 돌려준다."""
    now = now or datetime.now(UTC)
    tz = _tz(owner)
    before = float(rel.affinity or 0.0)
    advance(rel, now, tz, await _posted_since_settled(db, rel, owner, now, tz))
    with contextlib.suppress(Exception):
        rel.facts_remembered = await count_facts(db, owner.id, agent.id)
    credit_facts(rel, now, tz, rel.facts_remembered or 0)
    with contextlib.suppress(Exception):
        rel.posts_written = await count_posts(db, owner.id)
    refresh_stage(rel, agent, now)
    return round(float(rel.affinity or 0.0) - before, 2)


async def record_turn(db: AsyncSession, *, owner: User, agent: Agent, at: datetime | None = None) -> tuple[AgentRelationship, list[str]]:
    """One completed owner turn: counters, streak, remembered facts, affinity, stage."""
    at = at or datetime.now(UTC)
    tz = _tz(owner)
    rel = await get_or_create(db, owner.id, agent.id)
    today = at.astimezone(tz).date()
    if rel.started_at is None:
        rel.started_at = at
    # 먼저 지나간 것을 센다(끝난 날·무응답 기한) — 오늘의 대화가 어제의 침묵을 지우지 않게.
    with contextlib.suppress(Exception):
        advance(rel, at, tz, await _posted_since_settled(db, rel, owner, at, tz))
    rel.last_turn_at = at
    rel.turns = (rel.turns or 0) + 1
    if rel.last_active_day != today:
        rel.streak_days = (rel.streak_days or 0) + 1 if rel.last_active_day == today - timedelta(days=1) else 1
        rel.active_days = (rel.active_days or 0) + 1
        rel.last_active_day = today
    # 오늘 이야기했으면 그 자리에서 오른다 (plan/61).
    credit_turn(rel, at, tz)
    with contextlib.suppress(Exception):
        rel.facts_remembered = await count_facts(db, owner.id, agent.id)
    credit_facts(rel, at, tz, rel.facts_remembered or 0)
    with contextlib.suppress(Exception):
        rel.posts_written = await count_posts(db, owner.id)
    return rel, refresh_stage(rel, agent, at)


# ── 재계산 (plan/61) ──────────────────────────────────────────────────────────

async def recompute(db: AsyncSession, rel: AgentRelationship, *, epoch: date = AFFINITY_EPOCH,
                    now: datetime | None = None) -> dict[str, Any]:
    """실제 기록으로 호감도를 처음부터 다시 센다 — 실시간과 **같은 엔진**으로.

    기록: 주인이 건 대화 턴(끝난 것, 심부름 아님), 비서가 먼저 건넨 말, 기억(사실), 남긴 글.
    시작값은 ``epoch`` 전까지 쌓은 자격의 단계(0061 이 했던 그대로). 그 뒤에 시작한 쌍은 0.
    바꾸지 않고 결과만 돌려준다 — 적용은 부르는 쪽이 한다(``apply_recompute``).
    """
    from blackmoa.models import Turn

    now = now or datetime.now(UTC)
    owner = await db.get(User, rel.user_id)
    agent = await db.get(Agent, rel.agent_id)
    tz = _tz(owner)
    started = rel.started_at.astimezone(tz).date() if rel.started_at else now.astimezone(tz).date()
    begin = max(epoch, started)
    begin_at = datetime.combine(begin, time.min, tzinfo=tz)

    turns = [t for (t,) in (await db.execute(select(Turn.started_at).where(
        Turn.owner_id == rel.user_id, Turn.agent_id == rel.agent_id, Turn.audience == "owner",
        Turn.status == "completed", Turn.simulated.is_(False)).order_by(Turn.started_at))).all()]
    facts = [f for (f,) in (await db.execute(select(Fact.created_at).where(
        Fact.owner_id == rel.user_id, Fact.status == "active", Fact.visibility != "visitor_private",
        (Fact.agent_id == rel.agent_id) | (Fact.agent_id.is_(None))).order_by(Fact.created_at))).all() if f]
    proactive = [m.created_at for m in (await db.execute(select(Message).join(Conversation, Conversation.id == Message.conversation_id).where(
        Conversation.owner_id == rel.user_id, Conversation.agent_id == rel.agent_id, Conversation.audience == "owner",
        Message.role == "assistant", Message.created_at >= begin_at))).scalars().all()
        if any((c or {}).get("card_type") == "proactive" for c in (m.cards or []))]
    posted = await posted_days(db, rel.user_id, begin, now.astimezone(tz).date(), tz)

    before = [t for t in turns if t < begin_at]
    talk_before = sorted({t.astimezone(tz).date() for t in before})
    facts_before = sum(1 for f in facts if f < begin_at)
    if started < epoch:
        from blackmoa.models import BlogPost
        posts_before = int((await db.execute(select(func.count(BlogPost.id)).where(
            BlogPost.owner_id == rel.user_id, BlogPost.status == "published", BlogPost.created_at < begin_at))).scalar_one())
        seed_stage = earned_stage(AgentRelationship(active_days=len(talk_before), turns=len(before),
                                                    facts_remembered=facts_before, posts_written=posts_before))
        seed = AFFINITY_SEED[seed_stage]
    else:
        seed_stage, seed = "new", 0.0
    sim = AgentRelationship(affinity=seed, affinity_day=begin - timedelta(days=1), affinity_facts=facts_before,
                            affinity_state={"talk_days": [d.isoformat() for d in talk_before[-30:]]}, affinity_log=[],
                            last_active_day=talk_before[-1] if talk_before else None, started_at=rel.started_at)
    events: list[tuple[datetime, int, str]] = [(t, 1, "turn") for t in turns if t >= begin_at]
    events += [(m, 0, "proactive") for m in proactive]
    events += [(f, 2, "fact") for f in facts if f >= begin_at]
    count = facts_before
    for at, _order, what in sorted(events):
        advance(sim, at, tz, posted)
        if what == "turn":
            sim.last_active_day = at.astimezone(tz).date()
            credit_turn(sim, at, tz)
        elif what == "proactive":
            note_proactive(sim, at)
        else:
            count += 1
            credit_facts(sim, at, tz, count)
    advance(sim, now, tz, posted)
    return {"agent": agent.name if agent else "", "owner": owner.email if owner else "", "seed_stage": seed_stage, "seed": seed,
            "before": round(float(rel.affinity or 0.0), 2), "after": round(float(sim.affinity or 0.0), 2),
            "affinity_day": sim.affinity_day, "affinity_facts": sim.affinity_facts,
            "state": sim.affinity_state, "log": list(sim.affinity_log or [])}


async def apply_recompute(db: AsyncSession, rel: AgentRelationship, result: dict[str, Any]) -> list[str]:
    """재계산 결과를 적용하고 단계를 다시 센다. 올라간 단계도 알리지 않는다(재계산은 소식이 아니다)."""
    rel.affinity = result["after"]
    rel.affinity_day = result["affinity_day"]
    rel.affinity_facts = result["affinity_facts"]
    rel.affinity_state = result["state"]
    rel.affinity_log = [*result["log"], {"at": datetime.now(UTC).isoformat(timespec="seconds"), "d": 0.0,
                                         "why": "recomputed", "v": result["after"]}][-AFFINITY_LOG_MAX:]
    agent = await db.get(Agent, rel.agent_id)
    return refresh_stage(rel, agent) if agent else []


# ── the block the model reads every owner turn ─────────────────────────────────

_STAGE_GUIDE = {
    "new": "Recently met: attentive, a little reserved; learn what to call them and how they like things, write it down.",
    "familiar": "You know each other's rhythm: refer to what you remember in passing; light teasing only if the persona allows.",
    "trusted": "They rely on you: be candid, flag risks before being asked, follow up on what matters to them.",
    "companion": "A long-standing pair: shorthand and anticipation are expected; you are still their secretary.",
}



def prompt_block(rel: AgentRelationship | None, agent: Agent, owner: User, *, opened_with: str | None = None) -> str:
    """The relationship note of the owner prompt: state only, a few lines, refreshed every turn.
    The boundaries that never change live in the base rules, where they are cached."""
    now = datetime.now(UTC)
    lines = ["# Relationship"]
    if rel is None or not rel.started_at:
        lines.append("First conversation with the owner. " + _STAGE_GUIDE["new"])
    else:
        stage = rel.stage if rel.stage in STAGES else "new"
        days = days_together(rel, now)
        idle = (now - rel.last_turn_at).days if rel.last_turn_at else 0
        lines.append(f"Day {days} with {owner.display_name}, {rel.turns} exchanges over {rel.active_days} days"
                     + (f", {rel.streak_days} in a row" if rel.streak_days >= 2 else "") + f". Stage: {stage}. " + _STAGE_GUIDE[stage])
        if idle >= 3:
            lines.append(f"{idle} days since you last talked — notice it warmly if it fits, never as a complaint.")
        recent = [m for m in (rel.milestones or []) if m.get("at") and (now - datetime.fromisoformat(m["at"])).days <= 3]
        if recent:
            lines.append("Recent: " + ", ".join(m["key"].replace("_", " ") for m in recent[-3:]) + ".")
        mood = rel.mood or {}
        if mood.get("state") and (not mood.get("expires_at") or datetime.fromisoformat(mood["expires_at"]) > now):
            lines.append(f"Your state today: {mood['state']}" + (f" ({mood.get('reason')})" if mood.get("reason") else "") + " — let it colour the tone, do not narrate it.")
    if opened_with:
        lines.append(f"You wrote first earlier, unprompted, and they are answering it now: \"{opened_with[:400]}\"")
    # 온도는 수가 아니라 말투로 온다 (plan/45 §4). 수를 읽어 주면 그건 게임이 된다.
    if rel is not None and rel.started_at:
        warm = warmth_stage(rel)
        earned = earned_stage(rel)
        if STAGES.index(warm) < STAGES.index(earned):
            lines.append("It has been a while since you two talked. You still know them, but keep a"
                         " little distance for now and let it close as you speak. Never mention the gap,"
                         " never sulk, never ask why they were away.")
    return "\n".join(lines)


async def opened_with(db: AsyncSession, conversation_id: uuid.UUID) -> str | None:
    """The proactive message the owner is replying to, if the last thing in the conversation
    before their message was one. The session runtime keeps history in memory, so a message
    the worker wrote while it was alive would otherwise be invisible to the model."""
    rows = (await db.execute(select(Message).where(Message.conversation_id == conversation_id)
                             .order_by(Message.created_at.desc()).limit(2))).scalars().all()
    for m in rows:
        if m.role == "user":
            continue
        if m.role == "assistant" and any((c or {}).get("card_type") == "proactive" for c in (m.cards or [])):
            return m.content
        return None
    return None


# ── read models ────────────────────────────────────────────────────────────────

def rel_out(rel: AgentRelationship | None, agent: Agent, locale: str = "ko",
            triggers: dict[str, Any] | None = None) -> dict[str, Any]:
    """[우리 사이] 화면이 읽는 것.

    먼저 말 거는 일의 설정은 **관리자의 것**이라 여기서는 지금 값을 보여 주기만 한다
    (plan/54 §1). 개인이 고치는 칸은 없다.
    """
    params = relationship_params(agent.persona)
    tr = triggers or {}
    now = datetime.now(UTC)
    if rel is None:
        rel = AgentRelationship(user_id=agent.owner_id, agent_id=agent.id, stage="new", score=0.0, turns=0, active_days=0,
                                streak_days=0, facts_remembered=0, milestones=[], mood={}, proactive_count=0)
    stage = rel.stage if rel.stage in STAGES else "new"
    mood = dict(rel.mood or {})
    if mood.get("expires_at") and datetime.fromisoformat(mood["expires_at"]) <= now:
        mood = {}
    return {"agent_id": str(agent.id), "stage": stage, "stage_label": STAGE_LABELS.get(locale, STAGE_LABELS["ko"])[stage],
            "stage_index": STAGES.index(stage), "stages": list(STAGES), "score": rel.score or 0.0,
            "started_at": rel.started_at.isoformat() if rel.started_at else None,
            "last_turn_at": rel.last_turn_at.isoformat() if rel.last_turn_at else None,
            "days_together": days_together(rel, now), "turns": rel.turns or 0, "active_days": rel.active_days or 0,
            "streak_days": rel.streak_days or 0, "facts_remembered": rel.facts_remembered or 0,
            "stage_changed_at": rel.stage_changed_at.isoformat() if rel.stage_changed_at else None,
            "milestones": list(reversed(rel.milestones or [])), "mood": mood, "moods": list(MOODS),
            "progress": progress(rel), "params": params,
            # 쌓은 것과 지금. 둘 중 낮은 쪽이 단계다 (plan/45 §4).
            "affinity": round(float(rel.affinity or 0.0), 1),
            "earned_stage": earned_stage(rel), "warmth_stage": warmth_stage(rel),
            "posts_written": rel.posts_written or 0,
            #: 마지막 대화로부터 며칠. 사흘째부터 식기 시작한다.
            "idle_days": (now.date() - rel.last_active_day).days if rel.last_active_day else None,
            "grace_days": AFFINITY_GRACE_DAYS,
            "proactive": {"enabled": bool(tr.get("enabled", True)), "max_per_day": int(tr.get("max_per_day") or 3),
                          "managed": True,
                          "last_at": rel.last_proactive_at.isoformat() if rel.last_proactive_at else None,
                          "last_kind": rel.last_proactive_kind or "",
                          "sent_today": rel.proactive_count if rel.proactive_day == now.astimezone(UTC).date() else 0,
                          "quiet_minutes": QUIET_MINUTES,
                          "quiet_until": (rel.last_turn_at + timedelta(minutes=QUIET_MINUTES)).isoformat()
                          if rel.last_turn_at and now - rel.last_turn_at < timedelta(minutes=QUIET_MINUTES) else None}}


async def journal(db: AsyncSession, *, owner: User, agent: Agent, limit: int = 60) -> list[dict[str, Any]]:
    """Facts, notes and milestones as one timeline, newest first."""
    from blackmoa.memory.facade import note_store

    entries: list[dict[str, Any]] = []
    facts = (await db.execute(select(Fact).where(Fact.owner_id == owner.id, Fact.status == "active", Fact.visibility != "visitor_private",
                                                 (Fact.agent_id == agent.id) | (Fact.agent_id.is_(None)))
                              .order_by(Fact.created_at.desc()).limit(limit))).scalars().all()
    for f in facts:
        entries.append({"type": "fact", "id": str(f.id), "at": (f.created_at or f.updated_at).isoformat(), "subject": f.subject,
                        "predicate": f.predicate, "object": f.object, "kind": f.kind, "visibility": f.visibility})
    with contextlib.suppress(Exception):
        for n in note_store(agent.id, "owner").list(limit=limit):
            at = n.updated or n.created or ""
            entries.append({"type": "note", "id": n.id, "namespace": "owner", "at": at, "title": n.title, "body": n.body[:400],
                            "category": n.category, "pinned": n.pinned, "importance": n.importance})
    # 내가 적어 둔 것도 우리 사이의 일이다 (plan/45 §7). 글을 백 편 써도 여기 한 줄도
    # 남지 않으면, 한 일이 어디로 갔는지 알 길이 없다.
    from blackmoa.models import BlogPost

    posts = (await db.execute(select(BlogPost).where(
        BlogPost.owner_id == owner.id, BlogPost.status == "published")
        .order_by(BlogPost.published_at.desc().nullslast()).limit(limit))).scalars().all()
    rel = await get(db, owner.id, agent.id)
    seen = {str(x) for x in ((rel.glanced if rel else []) or [])}
    for post in posts:
        at = (post.published_at or post.created_at)
        entries.append({"type": "post", "id": str(post.id), "at": at.isoformat() if at else "",
                        "title": post.title, "body": (post.body or "")[:400],
                        "visibility": post.visibility, "images": len(post.images or []),
                        "read": str(post.id) in seen})
    for m in (rel.milestones if rel else []) or []:
        entries.append({"type": "milestone", "id": m["key"], "at": m["at"], "key": m["key"]})

    def _key(e: dict[str, Any]) -> str:
        return str(e.get("at") or "")
    entries.sort(key=_key, reverse=True)
    return entries[:limit]


async def brief_for_user(db: AsyncSession, user_id: uuid.UUID, locale: str = "ko") -> list[dict[str, Any]]:
    agents = (await db.execute(select(Agent).where(Agent.owner_id == user_id, Agent.status != "archived"))).scalars().all()
    rels = {r.agent_id: r for r in (await db.execute(select(AgentRelationship).where(AgentRelationship.user_id == user_id))).scalars().all()}
    out = []
    for a in agents:
        o = rel_out(rels.get(a.id), a, locale)
        o["agent_name"] = a.name
        out.append(o)
    return out


def set_mood(rel: AgentRelationship, state: str, reason: str = "", hours: int = 24) -> None:
    if not state:
        rel.mood = {}
        return
    now = datetime.now(UTC)
    rel.mood = {"state": state[:24], "reason": (reason or "")[:120], "set_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=max(1, min(168, hours)))).isoformat()}


# ── proactive messages ─────────────────────────────────────────────────────────

async def recent_owner_turn(db: AsyncSession, owner_id: uuid.UUID, agent_id: uuid.UUID, *, minutes: int = QUIET_MINUTES) -> datetime | None:
    """When the owner last spoke to this secretary inside the quiet window, from the turns
    table — the ground truth, including a turn that is running right now."""
    from blackmoa.models import Turn
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    return (await db.execute(select(func.max(Turn.started_at)).where(Turn.owner_id == owner_id, Turn.agent_id == agent_id,
                                                                    Turn.audience == "owner", Turn.started_at >= since))).scalar()


async def recently_active_pairs(db: AsyncSession, *, minutes: int = QUIET_MINUTES) -> set[tuple[uuid.UUID, uuid.UUID]]:
    from blackmoa.models import Turn
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    rows = (await db.execute(select(Turn.owner_id, Turn.agent_id).where(Turn.audience == "owner", Turn.started_at >= since).distinct())).all()
    return {(r[0], r[1]) for r in rows}


# 무엇을 언제 보낼지 고르는 일은 `services/triggers.py` 하나에서만 한다 (plan/54 §6).
# 예전에는 이 자리에 같은 판단이 한 벌 더 있었다 — 고르는 자리가 둘이면 한쪽만 고친
# 날이 반드시 온다.


#: 한 번에 들춰 보는 글 수. 둘이면 이야깃거리는 되고 잡담은 안 된다.
GLANCE_N = 2
#: 기억해 두는 "이미 본 글" 의 길이. 이보다 오래된 것은 다시 봐도 새롭다.
GLANCE_MEMORY = 40


async def glance(db: AsyncSession, rel: AgentRelationship, owner: User, *, limit: int = GLANCE_N) -> list[Any]:
    """비서가 주인이 적어 둔 것을 들춰 본다 (plan/45 §3).

    통로는 늘 열려 있지만 **반드시 쓰는 것은 아니다.** 계기가 왔을 때 몇 편을 집어 보고,
    거기서 할 말을 찾으면 쓰고 못 찾으면 그냥 지나간다. 확정된 파이프라인이 아니라
    우연이라, 몰아서 쓴다고 몰아서 읽히지 않는다.

    고르는 무게: 최근일수록, 아직 안 본 것일수록. 가끔은 오래된 것도 집는다. 그래야
    "작년 이맘때" 같은 말이 나온다.
    """
    import random

    from blackmoa.models import BlogPost

    seen = {str(x) for x in (rel.glanced or [])}
    rows = list((await db.execute(select(BlogPost).where(
        BlogPost.owner_id == owner.id, BlogPost.status == "published", BlogPost.body != "")
        .order_by(BlogPost.published_at.desc().nullslast()).limit(60))).scalars().all())
    if not rows:
        return []
    now = datetime.now(UTC)

    def weight(i: int, post: Any) -> float:
        fresh = 1.0 / (1 + i * 0.25)                       # 목록에서 위에 있을수록
        unseen = 3.0 if str(post.id) not in seen else 0.6  # 아직 안 본 것이 훨씬 자주
        said = min(1.5, 0.5 + len(post.body or "") / 400)  # 적힌 말이 있을수록
        days = (now - post.published_at).days if post.published_at else 0
        old = 1.4 if days > 180 else 1.0                   # 가끔은 오래된 것도
        return fresh * unseen * said * old

    picked: list[Any] = []
    pool = list(enumerate(rows))
    for _ in range(min(limit, len(pool))):
        ws = [weight(i, p) for i, p in pool]
        total = sum(ws)
        if total <= 0:
            break
        r = random.random() * total
        for k, w in enumerate(ws):
            r -= w
            if r <= 0:
                picked.append(pool.pop(k)[1])
                break
    return picked


def remember_glance(rel: AgentRelationship, posts: list[Any]) -> None:
    seen = [x for x in (rel.glanced or []) if x not in {str(p.id) for p in posts}]
    rel.glanced = (seen + [str(p.id) for p in posts])[-GLANCE_MEMORY:]


async def _context_for(db: AsyncSession, rel: AgentRelationship, agent: Agent, owner: User) -> str:
    from blackmoa.memory.facade import note_store

    tz = _tz(owner)
    now = datetime.now(UTC)
    local = now.astimezone(tz)
    lines = [f"Now: {local.strftime('%Y-%m-%d %A %H:%M')} ({owner.timezone or 'Asia/Seoul'})",
             f"Days together: {days_together(rel, now)}; stage: {rel.stage}; exchanges: {rel.turns}; "
             f"days since last conversation: {(now - rel.last_turn_at).days if rel.last_turn_at else 'n/a'}"]
    facts = (await db.execute(select(Fact).where(Fact.owner_id == owner.id, Fact.status == "active", Fact.visibility != "visitor_private",
                                                 (Fact.agent_id == agent.id) | (Fact.agent_id.is_(None)))
                              .order_by(Fact.created_at.desc()).limit(14))).scalars().all()
    if facts:
        lines.append("Things you remember about the owner (newest first):")
        lines += [f"  - [{f.kind}] {f.subject} / {f.predicate} / {f.object[:120]}" for f in facts]
    with contextlib.suppress(Exception):
        notes = note_store(agent.id, "owner").list(limit=3)
        if notes:
            lines.append("Recent notes you wrote:")
            lines += [f"  - {n.title}: {n.body[:200].replace(chr(10), ' ')}" for n in notes]
    conv = (await db.execute(select(Conversation).where(Conversation.owner_id == owner.id, Conversation.agent_id == agent.id,
                                                        Conversation.audience == "owner", Conversation.simulated.is_(False))
                             .order_by(Conversation.last_message_at.desc().nullslast()).limit(1))).scalars().first()
    if conv is not None:
        msgs = (await db.execute(select(Message).where(Message.conversation_id == conv.id, Message.role.in_(("user", "assistant")))
                                 .order_by(Message.created_at.desc()).limit(4))).scalars().all()
        if msgs:
            lines.append("How the last conversation ended:")
            lines += [f"  {'owner' if m.role == 'user' else 'you'}: {(m.content or '')[:200].replace(chr(10), ' ')}" for m in reversed(msgs)]
    # 스케줄은 주인의 원장이다 — 비서의 [캘린더] 스위치 없이 늘 본다 (plan/56). black-moa 일정 + Google.
    with contextlib.suppress(Exception):
        from blackmoa.services import schedule as SCH
        evs = await SCH.events_between(db, owner, now, now + timedelta(hours=24), limit=6)
        if evs:
            lines.append("Owner's schedule, next 24h:")
            lines += [f"  - {'all day' if e.get('all_day') else (e.get('start') or '')[11:16]} {e.get('title', '')}" for e in evs]
    # 주인이 적어 둔 것 몇 편. 읽되 반드시 쓰지는 않는다 (plan/45 §3).
    with contextlib.suppress(Exception):
        looked = await glance(db, rel, owner)
        if looked:
            lines.append("Things they wrote lately (you may or may not bring one up; if you do, say"
                         " you read it, and never quote anything they marked for you alone to a third party):")
            for post in looked:
                when = post.published_at.astimezone(tz).strftime("%m/%d") if post.published_at else "?"
                lines += [f"  - [{when}] {(post.body or '')[:300].replace(chr(10), ' ')}"]
            remember_glance(rel, looked)
    new_inbox = int((await db.execute(select(func.count(InboxItem.id)).where(InboxItem.owner_id == owner.id, InboxItem.agent_id == agent.id,
                                                                             InboxItem.status == "new"))).scalar_one())
    if new_inbox:
        lines.append(f"Inbox items waiting for the owner: {new_inbox}")
    return "\n".join(lines)


_KIND_RULES = {
    "followup": ("A conversation with the owner ended a little while ago (see how it ended in the context). If something "
                 "was left open — a task you offered to do, a question they had, a plan they mentioned, something they were "
                 "worried about — pick it up in one or two sentences, in your own voice. If nothing in the context is worth "
                 "following up on, answer with exactly the single word NOTHING and nothing else."),
    "morning": ("A morning note. Greet briefly, mention at most two concrete things from the context (today's events, "
                "inbox items waiting, something left open last time), and end with one light question or offer. "
                "Three to six short sentences; a list only if there are three or more events."),
    "checkin": ("You have not talked for a while. One warm line that shows you remember something specific from the "
                "context, then one question. Two or three sentences. Never mention the silence as a complaint."),
    "nudge": ("You already spoke with the owner today. Send one short, light line — pick up the thread of what you talked "
              "about, or say something that fits this hour. One or two sentences. Never ask them to reply, never mention "
              "that you are checking in."),
    "anniversary": ("Today is a day worth marking (see the context: days together or a new stage). Look back briefly at "
                    "something you actually remember, say what you value about working together — in character. "
                    "Two to four sentences. No gifts, no romance, no drama."),
}


async def compose_proactive(db: AsyncSession, rel: AgentRelationship, agent: Agent, owner: User, kind: str,
                            *, tone: str = "", occasion: str = "") -> tuple[str, dict[str, Any], dict[str, str]]:
    """먼저 건넬 말을 짓는다.

    **비서의 모델이 아니라 트리거 모델로 돈다** (plan/54 §2). 비서가 sonnet 이어도
    먼저 건네는 한 문장에 큰 모델이 필요하지 않고, 이 일은 모든 사람에게 매일 일어난다.
    고른 모델이 사라지면 멈추지 않고 한 칸 내려간다.
    """
    from blackmoa.providers.llm.simple import complete
    from blackmoa.services import triggers as TR

    locale = _locale(owner)
    persona = compile_persona(agent.persona or {}, agent_name=agent.name, owner_name=owner.display_name,
                              role_line=agent.role_line or "", language=agent.language or "auto")
    system = "\n\n".join([
        persona, prompt_block(rel, agent, owner),
        "# Task\nYou are about to send the owner a message FIRST — they did not write to you. "
        f"Write only the message body, as {agent.name}, in {'English' if locale == 'en' else 'Korean'} unless the persona fixes another language.\n"
        + _KIND_RULES.get(kind, _KIND_RULES["checkin"]) + "\n"
        "Rules: never invent events, names or facts that are not in the context; if the context is thin, keep it short and "
        "general; no markdown headings; no sign-off with your name; emoji only if the persona allows.",
    ])
    if tone.strip():
        # 규칙이 정한 말의 온도. 이것이 규칙의 핵심이라 프롬프트의 마지막에 선다.
        system += "\n\n## The feeling this message carries\n" + tone.strip()[:400]
    ctx = await _context_for(db, rel, agent, owner)
    if occasion:
        # 오늘이 무슨 날인지 모르고 쓰면 기념일 인사가 아무 날의 인사가 된다.
        ctx += f"\nToday is: {occasion}"
    elif kind == "anniversary":
        ctx += f"\nOccasion: {'day ' + str(days_together(rel)) if days_together(rel) in ANNIVERSARIES else 'a new stage: ' + rel.stage}"
    if (agent.custom_instructions or "").strip():
        system += "\n\n## The owner's own words\n" + agent.custom_instructions.strip()[:2000]
    provider, model, fell_back = await TR.model_for(db)
    ran = {"provider": provider, "model": model, "fell_back": fell_back}
    try:
        text, usage = await complete(db, provider=provider, model=model, system=system, user_text=ctx, max_tokens=500,
                                     timeout_s=120, lane="interactive")
    except Exception as e:  # noqa: BLE001
        log.warning("proactive: trigger model failed, falling back to the secretary's own", err=str(e)[:160])
        text, usage = await complete(db, provider=agent.provider, model=agent.model_id,
                                     system=system, user_text=ctx, max_tokens=500, timeout_s=120, lane="interactive")
        ran = {"provider": agent.provider, "model": agent.model_id, "fell_back": True}
    text = (text or "").strip().strip('"')
    if text.upper().rstrip(".") == NOTHING or (kind == "followup" and NOTHING in text[:12].upper()):
        text = ""
    return text, usage or {}, ran


async def deliver_proactive(db: AsyncSession, rel: AgentRelationship, agent: Agent, owner: User, kind: str, text: str,
                            *, rule: str = "") -> Message:
    from blackmoa.services import conversations as CV
    from blackmoa.services import notifications as NT

    now = datetime.now(UTC)
    conv = (await db.execute(select(Conversation).where(Conversation.owner_id == owner.id, Conversation.agent_id == agent.id,
                                                        Conversation.audience == "owner", Conversation.simulated.is_(False),
                                                        Conversation.status != "deleted")
                             .order_by(Conversation.last_message_at.desc().nullslast()).limit(1))).scalars().first()
    if conv is None or not conv.last_message_at or now - conv.last_message_at > timedelta(days=7):
        conv = await CV.create(db, owner_id=owner.id, agent_id=agent.id, audience="owner",
                               title=PROACTIVE_TITLES.get(kind, PROACTIVE_TITLES["checkin"])[_locale(owner)])
    msg = await CV.add_message(db, conv, role="assistant", content=text,
                               # 어떤 규칙이 울렸는지 메시지에 남긴다. 관리 화면의 발송 기록이
                               # "누가 언제 무엇을 받았나" 를 여기서 읽는다 (plan/54 §5).
                               cards=[{"card_type": "proactive", "payload": {"kind": kind, "rule": rule, "at": now.isoformat()}}])
    conv.unread_owner = True
    today = now.astimezone(_tz(owner)).date()
    same_day = rel.proactive_day == today
    rel.proactive_count = (rel.proactive_count or 0) + 1 if same_day else 1
    rel.proactive_day = today
    rel.last_proactive_at, rel.last_proactive_kind = now, kind
    # 답을 기다리기 시작한다. 하루 동안 답이 없으면 식는다 — 알리지는 않는다 (plan/61).
    note_proactive(rel, now)
    prev = list((rel.proactive_state or {}).get("kinds_today") or []) if same_day else []
    rel.proactive_state = {**(rel.proactive_state or {}), "kinds_today": prev + [kind]}
    _add_milestone(rel, "first_proactive", now)
    with contextlib.suppress(Exception):
        await NT.evaluate(db, owner_id=owner.id, event="secretary_message",
                          payload={"text": text, "agent_name": agent.name, "conversation_id": str(conv.id), "agent_id": str(agent.id), "kind": kind},
                          agent_id=agent.id)
    return msg


async def run_proactive(db: AsyncSession, *, agent_id: uuid.UUID, user_id: uuid.UUID, kind: str | None = None, force: bool = False,
                        rule: str = "", tone: str = "") -> dict[str, Any]:
    """먼저 건네는 말 하나를 실제로 짓고 보낸다.

    **개인의 크레딧은 쓰지 않는다** (plan/54 §1). 내가 부르지 않은 말에 내 잔액이
    줄면 그 기능을 끄는 것이 합리적인 선택이 되고, 잔액이 0인 사람 — 가장 오래
    안 온 사람 — 에게 가장 말을 안 걸게 된다. 쓴 토큰과 달러는 그대로 남겨 운영자가
    보지만, 사용자의 원장에서는 한 푼도 나가지 않는다.
    """
    from blackmoa.services import credits as CR
    from blackmoa.services import triggers as TR

    agent = await db.get(Agent, agent_id)
    owner = await db.get(User, user_id)
    if agent is None or owner is None:
        return {"skipped": "orphan"}
    rel = await get_or_create(db, user_id, agent_id)
    if rel.started_at is None and not force:
        return {"skipped": "never_talked"}
    if rel.started_at is None:
        rel.started_at = datetime.now(UTC)
    recent = await recent_owner_turn(db, owner.id, agent.id)
    if recent is not None:
        # The owner's rule, applied at send time too: a job queued fifteen quiet minutes ago
        # does not fire into a conversation that has since started.
        return {"skipped": "owner_talking", "quiet_until": (recent + timedelta(minutes=QUIET_MINUTES)).isoformat()}
    cfg = await TR.config(db)
    now = datetime.now(UTC)
    tz = _tz(owner)
    # **보낼 때 다시 고른다.** 15분 전에 큐에 들어간 판단을 그대로 쓰면, 그 사이에
    # 바뀐 것(대화·상한·관리자의 설정)을 무시하게 된다. 작업이 들고 온 종류는
    # 중복 방지와 기록을 위한 이름일 뿐이다.
    #
    # 고른 결과를 `decided` 로 들고 있어야 보낸 뒤에 사다리에 표를 찍을 수 있다.
    # 표가 안 찍히면 [버림받은 느낌]이 날마다 다시 나간다 — 한 번만 보내기로 한
    # 말이 매일 오는 것이 이 기능에서 가장 나쁜 고장이다.
    decided = TR.decide(rel, agent, owner, cfg, now=now, tz=tz, facts=_facts(rel, owner, now))
    occasion = ""
    if decided is not None:
        kind, rule, tone = decided["kind"], decided["rule"], decided["tone"]
        occasion = decided.get("reason") or ""
    elif not force:
        return {"skipped": "nothing_to_say"}
    kind = kind if kind in PROACTIVE_KINDS else ("morning" if now.astimezone(tz).hour < 12 else "checkin")
    text, usage, ran = await compose_proactive(db, rel, agent, owner, kind, tone=tone, occasion=occasion)
    if kind == "followup":
        rel.proactive_state = {**(rel.proactive_state or {}), "followup_for": rel.last_turn_at.isoformat() if rel.last_turn_at else None}
        if not text and force:
            # Asked for a word and there was nothing to follow up on: say something anyway.
            kind = "morning" if now.astimezone(tz).hour < 12 else "checkin"
            text, usage, ran = await compose_proactive(db, rel, agent, owner, kind, tone=tone, occasion=occasion)
        elif not text:
            return {"skipped": "nothing_to_follow_up"}
    if not text:
        return {"skipped": "empty"}
    # 무엇을 태웠는지는 남긴다. 크레딧은 0 — 청구되지 않은 일이 기록에서 사라지면
    # 운영자는 이 기능의 값을 영영 모른다.
    with contextlib.suppress(Exception):
        from blackmoa.services import catalog as CAT
        cat = await CAT.get_model(db, ran["provider"], ran["model"])
        await CR.record_house_usage(db, owner_id=owner.id, agent_id=agent.id, kind="trigger",
                                    provider=ran["provider"], model_id=ran["model"], usage=usage, catalog=cat,
                                    note=f"trigger:{rule or kind}")
    msg = await deliver_proactive(db, rel, agent, owner, kind, text, rule=rule)
    if decided is not None:
        TR.remember_fired(rel, decided, now=now, tz=tz,
                          state=TR.ladder_state(rel, now=now, tz=tz, lapse_after=cfg["lapse_after_days"]))
    return {"sent": kind, "rule": rule, "model": f"{ran['provider']}/{ran['model']}", "fell_back": ran["fell_back"],
            "message_id": str(msg.id), "conversation_id": str(msg.conversation_id)}


def _facts(rel: AgentRelationship, owner: User, now: datetime) -> dict[str, Any]:
    """오늘에 대한 사실. 어느 날이 "함께한 날" 인지는 규칙이 정한다 (plan/54)."""
    today = now.astimezone(_tz(owner)).date()
    stage_up = rel.stage_changed_at is not None and rel.stage != "new" \
        and rel.stage_changed_at.astimezone(_tz(owner)).date() == today
    return {"days_together": days_together(rel, now), "stage_up": stage_up}


async def tick(db: AsyncSession) -> dict[str, Any]:
    """Every few minutes: find the pairs whose secretary has something to say and queue one job each."""
    from blackmoa.services import jobs as J

    rows = (await db.execute(select(AgentRelationship, Agent, User).join(Agent, Agent.id == AgentRelationship.agent_id)
                             .join(User, User.id == AgentRelationship.user_id)
                             .where(Agent.status == "active", User.status == "active", AgentRelationship.started_at.isnot(None)))).all()
    from blackmoa.services import triggers as TR

    cfg = await TR.config(db)
    queued = 0
    now = datetime.now(UTC)
    talking = await recently_active_pairs(db)
    cooled = 0
    for rel, agent, owner in rows:
        # 호감도는 달력도 센다 — 대화가 없어도 날은 가고, 답을 기다리는 말의 기한도 온다 (plan/61).
        # 단계와 기념일도 여기서 달력을 따라 움직인다.
        try:
            if await settle(db, owner=owner, agent=agent, rel=rel, now=now) < 0:
                cooled += 1
        except Exception as e:  # noqa: BLE001 — 한 쌍의 고장이 나머지를 막지 않게
            log.warning("affinity settle failed", agent=str(agent.id), err=str(e)[:160])
            refresh_stage(rel, agent, now)
        # 무엇을 언제 보낼지는 규칙이 정한다 (plan/54). 여기서 한 번 더 거르지 않는다.
        hit = TR.decide(rel, agent, owner, cfg, now=now, tz=_tz(owner),
                        recent_turn=(owner.id, agent.id) in talking, facts=_facts(rel, owner, now))
        if not hit:
            continue
        day = now.astimezone(_tz(owner)).date().isoformat()
        await J.enqueue(db, "relationship.proactive",
                        {"agent_id": str(agent.id), "user_id": str(owner.id), "kind": hit["kind"],
                         "rule": hit["rule"], "tone": hit["tone"]},
                        dedupe_key=f"proactive:{agent.id}:{day}:{hit['rule']}", priority=6, owner_id=owner.id)
        queued += 1
    return {"pairs": len(rows), "queued": queued, "cooled": cooled}


# ── persona versions ───────────────────────────────────────────────────────────

VERSIONED = ("name", "role_line", "persona", "custom_instructions", "greeting", "language", "suggested_questions")


def persona_snapshot(agent: Agent) -> dict[str, Any]:
    return {k: getattr(agent, k) for k in VERSIONED}


async def snapshot(db: AsyncSession, agent: Agent, *, label: str = "", force: bool = False) -> AgentPersonaVersion | None:
    """Keep this version of who the secretary is, unless it is identical to the last one kept."""
    snap = persona_snapshot(agent)
    last = (await db.execute(select(AgentPersonaVersion).where(AgentPersonaVersion.agent_id == agent.id)
                             .order_by(AgentPersonaVersion.created_at.desc()).limit(1))).scalars().first()
    if last is not None and last.snapshot == snap and not force:
        return None
    v = AgentPersonaVersion(agent_id=agent.id, owner_id=agent.owner_id, label=label[:80], snapshot=snap, created_at=datetime.now(UTC))
    db.add(v)
    await db.flush()
    old = (await db.execute(select(AgentPersonaVersion).where(AgentPersonaVersion.agent_id == agent.id)
                            .order_by(AgentPersonaVersion.created_at.desc()).offset(30))).scalars().all()
    for o in old:
        await db.delete(o)
    return v


async def list_versions(db: AsyncSession, agent_id: uuid.UUID) -> list[AgentPersonaVersion]:
    return list((await db.execute(select(AgentPersonaVersion).where(AgentPersonaVersion.agent_id == agent_id)
                                  .order_by(AgentPersonaVersion.created_at.desc()).limit(30))).scalars().all())


def version_out(v: AgentPersonaVersion) -> dict[str, Any]:
    s = v.snapshot or {}
    p = s.get("persona") or {}
    return {"id": str(v.id), "label": v.label, "created_at": v.created_at.isoformat(), "snapshot": s,
            "summary": {"name": s.get("name"), "preset": p.get("preset"), "role_line": s.get("role_line"),
                        "custom_len": len(s.get("custom_instructions") or "")}}
