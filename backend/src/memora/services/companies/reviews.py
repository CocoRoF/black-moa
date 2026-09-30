"""Company reviews, follows, views — and everything derived from them (plan/40).

The directory (plan/33) knows what the exchange and the regulator say about a company.
This module holds what *people* say: a review with five ratings, pros and cons, and
optionally pay, an interview and benefits. One table; the 연봉·면접·복지 tabs are filters
over it. Every number the screens show — a company's rating, its axes, recommendation
rates, salary medians, popularity — is written onto the companies row by `recompute`, so
reading a dashboard never aggregates reviews on the way.

Counters follow the community's rule (plan/29 §2): one statement, never read-modify-write.
"""
from __future__ import annotations

import math
import re
import statistics
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import cast, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.errors import Forbidden, NotFound, ValidationFailed
from memora.data.jobs_taxonomy import INDUSTRY_INDEX, JOB_INDEX, JOB_NAME, JOB_PARENT
from memora.models import (
    CommunityJob,
    CommunityPost,
    CommunityReaction,
    Company,
    CompanyFollow,
    CompanyReview,
    CompanyView,
    User,
)
from memora.services import community as C
from memora.services import profile as PF
from memora.services.companies import questions as Q
from memora.services.companies.query import expand_industry, match_by_name, substantive

# ── vocabulary ──────────────────────────────────────────────────────
#: The five things a review rates, in the order the statistics panel draws them.
AXES = ("pay", "balance", "culture", "promotion", "management")
AXIS_COLUMN = {"pay": "rating_pay", "balance": "rating_balance", "culture": "rating_culture",
               "promotion": "rating_promotion", "management": "rating_management"}

#: What a company can be known for. Tags are codes; the screen has the words.
TAG_CODES = ("pay", "balance", "culture", "promotion", "management", "recommended", "growing", "hiring")

#: Benefits a reviewer can tick. Codes are stable; labels live in the locale files.
BENEFITS: list[dict[str, str]] = [
    {"code": "bonus", "group": "pay"}, {"code": "stock", "group": "pay"},
    {"code": "retire", "group": "pay"}, {"code": "overtime", "group": "pay"},
    {"code": "flex", "group": "time"}, {"code": "remote", "group": "time"},
    {"code": "vacation", "group": "time"}, {"code": "sabbatical", "group": "time"},
    {"code": "parental", "group": "time"},
    {"code": "meal", "group": "life"}, {"code": "transport", "group": "life"},
    {"code": "phone", "group": "life"}, {"code": "housing", "group": "life"},
    {"code": "family", "group": "life"}, {"code": "tuition", "group": "life"},
    {"code": "education", "group": "growth"}, {"code": "conference", "group": "growth"},
    {"code": "language", "group": "growth"},
    {"code": "checkup", "group": "health"}, {"code": "insurance", "group": "health"},
    {"code": "gym", "group": "health"}, {"code": "snack", "group": "health"},
    {"code": "club", "group": "culture"}, {"code": "gift", "group": "culture"},
    {"code": "anniversary", "group": "culture"},
]
BENEFIT_CODES = {b["code"] for b in BENEFITS}

#: What a review's text talks about. Derived once, when it is saved, so "companies people
#: talk about pay at" is an index lookup and not a regex over every review.
TOPIC_WORDS: dict[str, re.Pattern[str]] = {
    "salary": re.compile(r"연봉|급여|월급|보상|성과급|인센티브|페이|임금|연봉협상|salary|pay\b", re.I),
    "welfare": re.compile(r"복지|복리|식대|간식|휴가|연차|재택|유연근무|benefit", re.I),
    "balance": re.compile(r"워라밸|야근|칼퇴|퇴근|주말|업무\s?강도|balance", re.I),
    "promotion": re.compile(r"승진|진급|승급|커리어|promotion", re.I),
    "culture": re.compile(r"분위기|문화|수평|꼰대|동료|팀워크|culture", re.I),
    "management": re.compile(r"경영진|대표|임원|리더십|사장|CEO|management", re.I),
    "growth": re.compile(r"성장|비전|미래|전망|매출|growth", re.I),
}

EMPLOYMENTS = ("current", "former")
GROWTHS = ("up", "flat", "down")
INTERVIEW_RESULTS = ("pass", "fail", "pending")
MIN_TEXT = 10
MAX_TEXT = 3000
REVIEWS_PER_HOUR = 5
#: Every job code, family or title, that a review may carry.
_JOB_CODES = set(JOB_NAME)


def _family(code: str) -> str:
    return JOB_PARENT.get(code, code) if code else ""


def _year_now() -> int:
    return datetime.now(UTC).year


# ── validation ──────────────────────────────────────────────────────
def _int_in(v: Any, lo: int, hi: int, field: str) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValidationFailed(f"{field} must be a number", code="review_invalid", detail={"field": field}) from None
    if not lo <= n <= hi:
        raise ValidationFailed(f"{field} out of range", code="review_invalid", detail={"field": field})
    return n


def _text(v: Any, field: str, *, required: bool, limit: int = MAX_TEXT) -> str:
    s = (v or "").strip() if isinstance(v, str) else ""
    if required and len(s) < MIN_TEXT:
        raise ValidationFailed(f"{field} too short", code="review_too_short", detail={"field": field, "min": MIN_TEXT})
    return s[:limit]


def normalise(data: dict[str, Any]) -> dict[str, Any]:
    """The reviewer's form, checked. Raises `review_invalid` naming the field.

    Two shapes are accepted. The current form sends `answers` (plan/40 §8) and every
    score is derived from them. A form without answers is the older one — five stars and
    three switches — and is still honoured, so nothing already written becomes invalid.
    """
    year = _int_in(data.get("work_year") or _year_now(), 1990, _year_now(), "work_year")
    out: dict[str, Any] = {
        "employment": data.get("employment") if data.get("employment") in EMPLOYMENTS else "current",
        "job_code": (data.get("job_code") or "") if (data.get("job_code") or "") in _JOB_CODES | {""} else "",
        "work_year": year,
        "title": _text(data.get("title"), "title", required=False, limit=120),
        "pros": _text(data.get("pros"), "pros", required=True),
        "cons": _text(data.get("cons"), "cons", required=True),
        "advice": _text(data.get("advice"), "advice", required=False),
        "salary": None, "experience_years": None, "interview": {}, "benefits": [], "answers": {},
    }
    if data.get("answers") is not None:
        answers, missing = Q.clean(data.get("answers"))
        if missing:
            raise ValidationFailed("answer the required questions", code="review_unanswered", detail={"questions": missing})
        scores = Q.area_scores(answers)
        for axis, col in AXIS_COLUMN.items():
            # An area with nothing scored yet takes the neutral middle; the required
            # question in each area makes that a corner case, not the norm.
            out[col] = float(scores.get(axis) or 3.0)
        out["rating"] = float(Q.overall(answers) or 3.0)
        d = Q.derived(answers)
        out["recommend"] = bool(d["recommend"]) if d["recommend"] is not None else out["rating"] >= 3.5
        out["ceo_approval"] = d["ceo_approval"]
        out["growth"] = d["growth"] if d["growth"] in GROWTHS else "flat"
        out["answers"] = answers
    else:
        out["rating"] = float(_int_in(data.get("rating"), 1, 5, "rating"))
        out["recommend"] = bool(data.get("recommend", True))
        out["ceo_approval"] = None if data.get("ceo_approval") is None else bool(data.get("ceo_approval"))
        out["growth"] = data.get("growth") if data.get("growth") in GROWTHS else "flat"
        for axis, col in AXIS_COLUMN.items():
            out[col] = float(_int_in(data.get(col, data.get(axis)), 1, 5, col))
    if not out["title"]:
        out["title"] = out["pros"][:60]
    if data.get("salary") not in (None, "", 0, "0"):
        out["salary"] = _int_in(data.get("salary"), 100, 1_000_000, "salary")
    if data.get("experience_years") not in (None, ""):
        out["experience_years"] = _int_in(data.get("experience_years"), 0, 50, "experience_years")
    iv = data.get("interview") or {}
    if isinstance(iv, dict):
        clean: dict[str, Any] = {}
        if iv.get("difficulty") not in (None, "", 0, "0"):
            clean["difficulty"] = _int_in(iv.get("difficulty"), 1, 5, "interview.difficulty")
        if iv.get("result") in INTERVIEW_RESULTS:
            clean["result"] = iv["result"]
        for k in ("questions", "process"):
            s = _text(iv.get(k), f"interview.{k}", required=False, limit=2000)
            if s:
                clean[k] = s
        out["interview"] = clean
    raw = data.get("benefits") or []
    if isinstance(raw, list):
        out["benefits"] = [b for b in dict.fromkeys(str(x) for x in raw) if b in BENEFIT_CODES][:len(BENEFITS)]
    blob = " ".join((out["title"], out["pros"], out["cons"], out["advice"]))
    topics = [k for k, rx in TOPIC_WORDS.items() if rx.search(blob)]
    if out["salary"] is not None and "salary" not in topics:
        topics.insert(0, "salary")
    out["topics"] = topics
    return out


# ── writing ─────────────────────────────────────────────────────────
async def submit(db: AsyncSession, *, company: Company, user: User, data: dict[str, Any]) -> CompanyReview:
    """Create the reviewer's review of this company, or replace it if they already have one."""
    await C.require_write_access(db, user)
    clean = normalise(data)
    existing = (await db.execute(select(CompanyReview).where(CompanyReview.company_id == company.id,
                                                             CompanyReview.author_id == user.id))).scalar_one_or_none()
    if existing is not None and existing.status == "hidden":
        raise Forbidden("this review was hidden by a moderator", code="review_hidden")
    # A deleted row that comes back is a new review to everyone but the database: it
    # counts against the hourly guard and it is news to followers. An edit is neither.
    fresh = existing is None or existing.status == "deleted"
    if fresh:
        await C._rate_guard(db, user.id, CompanyReview, REVIEWS_PER_HOUR, "reviews")
    from memora.services.companies import verification as VF
    clean["verified"] = await VF.verified_for(db, user.id, company.id)
    if existing is None:
        existing = CompanyReview(company_id=company.id, author_id=user.id, **clean)
        db.add(existing)
    else:
        for k, v in clean.items():
            setattr(existing, k, v)
        existing.status = "published"
        existing.version = (existing.version or 1) + 1
        existing.updated_at = datetime.now(UTC)
        if fresh:
            existing.created_at = datetime.now(UTC)
    await db.flush()
    if fresh:
        await notify_followers(db, company, kind="company_review", exclude=user.id,
                               payload={"review_id": str(existing.id), "title": clean["title"], "rating": clean["rating"],
                                        "excerpt": clean["pros"][:160]})
    await db.flush()
    await recompute(db, company.id)
    return existing


MAX_FOLLOWER_NOTICES = 500


async def notify_followers(db: AsyncSession, company: Company, *, kind: str, payload: dict[str, Any],
                           exclude: uuid.UUID | None = None) -> int:
    """Tell the people who follow this company (plan/40 §7). Bounded, so a company with a
    crowd behind it cannot turn one review into a minute of inserts."""
    from memora.services import inbox as I
    from memora.services.companies import switch as CO

    # 기업 기능이 꺼져 있으면 관심 기업 소식도 없다 (plan/71).
    if not await CO.enabled(db):
        return 0
    rows = (await db.execute(select(CompanyFollow.user_id).where(CompanyFollow.company_id == company.id)
                             .order_by(CompanyFollow.created_at.desc()).limit(MAX_FOLLOWER_NOTICES))).all()
    n = 0
    for (uid,) in rows:
        if uid == exclude:
            continue
        await I.create(db, owner_id=uid, agent_id=None, kind=kind,
                       payload={"company_id": str(company.id), "company_name": company.name, **payload})
        n += 1
    return n


async def remove(db: AsyncSession, *, review: CompanyReview, user: User) -> None:
    if review.author_id != user.id and user.role != "admin":
        raise Forbidden("not your review", code="not_owner")
    review.status = "deleted"
    await db.flush()
    await recompute(db, review.company_id)


async def set_status(db: AsyncSession, review_id: uuid.UUID, status: str) -> None:
    """Moderation. `hidden` keeps the row so the author can be told; `published` restores."""
    r = await db.get(CompanyReview, review_id)
    if r is None:
        raise NotFound("review not found", code="review_not_found")
    r.status = status
    await db.flush()
    await recompute(db, r.company_id)


async def toggle_helpful(db: AsyncSession, *, review: CompanyReview, user: User) -> tuple[bool, int]:
    """Same shape as a post like (plan/29): the unique row decides, never a prior read."""
    if review.author_id == user.id:
        raise Forbidden("you cannot vote on your own review", code="own_review")
    res = await db.execute(pg_insert(CommunityReaction.__table__)
                           .values(id=uuid.uuid4(), target_type="review", target_id=review.id,
                                   user_id=user.id, kind="helpful")
                           .on_conflict_do_nothing(constraint="uq_community_reaction"))
    if res.rowcount:
        await db.execute(update(CompanyReview).where(CompanyReview.id == review.id)
                         .values(helpful_count=CompanyReview.helpful_count + 1))
        await db.refresh(review)
        return True, review.helpful_count
    await db.execute(delete(CommunityReaction).where(CommunityReaction.target_type == "review",
                                                     CommunityReaction.target_id == review.id,
                                                     CommunityReaction.user_id == user.id,
                                                     CommunityReaction.kind == "helpful"))
    await db.execute(update(CompanyReview).where(CompanyReview.id == review.id)
                     .values(helpful_count=func.greatest(CompanyReview.helpful_count - 1, 0)))
    await db.refresh(review)
    return False, review.helpful_count


async def toggle_follow(db: AsyncSession, *, company: Company, user: User) -> tuple[bool, int]:
    res = await db.execute(pg_insert(CompanyFollow.__table__)
                           .values(id=uuid.uuid4(), company_id=company.id, user_id=user.id)
                           .on_conflict_do_nothing(constraint="uq_company_follow"))
    if res.rowcount:
        await db.execute(update(Company).where(Company.id == company.id)
                         .values(follow_count=Company.follow_count + 1, popularity=Company.popularity + 2.0))
        await db.refresh(company)
        return True, company.follow_count
    await db.execute(delete(CompanyFollow).where(CompanyFollow.company_id == company.id,
                                                 CompanyFollow.user_id == user.id))
    await db.execute(update(Company).where(Company.id == company.id)
                     .values(follow_count=func.greatest(Company.follow_count - 1, 0),
                             popularity=func.greatest(Company.popularity - 2.0, 0)))
    await db.refresh(company)
    return False, company.follow_count


async def register_view(db: AsyncSession, company_id: uuid.UUID, viewer_key: str) -> None:
    """A reader counts once a day. Popularity gets a small nudge at once so the dashboard
    moves between the worker's ranking passes; the pass sets the exact value."""
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    res = await db.execute(pg_insert(CompanyView.__table__)
                           .values(id=uuid.uuid4(), company_id=company_id, viewer_key=viewer_key, day=day)
                           .on_conflict_do_nothing(constraint="uq_company_view"))
    if res.rowcount:
        await db.execute(update(Company).where(Company.id == company_id)
                         .values(view_count=Company.view_count + 1, views_7d=Company.views_7d + 1,
                                 popularity=Company.popularity + 0.3))


# ── the numbers ─────────────────────────────────────────────────────
def _avg(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 2) if xs else 0.0


def _pct(hits: int, n: int) -> int | None:
    return round(100 * hits / n) if n else None


def _salary_summary(vals: list[int]) -> dict[str, Any] | None:
    if not vals:
        return None
    vals = sorted(vals)
    return {"n": len(vals), "median": int(statistics.median(vals)), "min": vals[0], "max": vals[-1],
            "avg": int(sum(vals) / len(vals))}


def _tags(n: int, axes: dict[str, float], recommend: int | None, growth: int | None, open_jobs: int) -> list[str]:
    tags: list[str] = []
    if n >= 2:
        # Best axes first, so the card leads with what the company is actually known for.
        for axis, v in sorted(axes.items(), key=lambda kv: -kv[1]):
            if v >= 3.8 and len(tags) < 3:
                tags.append(axis)
        if recommend is not None and recommend >= 70:
            tags.append("recommended")
        if growth is not None and growth >= 60:
            tags.append("growing")
    if open_jobs > 0:
        tags.append("hiring")
    return tags[:4]


def popularity_score(*, market: str, views_7d: int, follow_count: int, review_count: int,
                     open_jobs: int, employees: int | None, homepage: str) -> float:
    """What "popular" means, in one place. Also written as SQL in `rank_all`; keep both."""
    tier = {"유가": 1.0, "코스닥": 0.6, "코넥스": 0.3}.get(market, 0.0)
    return round(math.log1p(views_7d) * 3 + follow_count * 2 + review_count * 4 + open_jobs * 1.5
                 + tier + (0.2 if homepage else 0) + math.log1p(employees or 0) / 4, 3)


async def recompute(db: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    """Re-derive everything on the companies row from the published reviews.

    Done in Python over this one company's reviews rather than in SQL: a company has tens
    of reviews, occasionally thousands, and the by-year / by-job / benefits breakdowns are
    easier to read here than as six GROUP BYs. Bounded, so a pathological company cannot
    stall a request.
    """
    rows = list((await db.execute(
        select(CompanyReview).where(CompanyReview.company_id == company_id, CompanyReview.status == "published")
        .order_by(CompanyReview.created_at.desc()).limit(5000))).scalars().all())
    n = len(rows)
    axes = {axis: _avg([float(getattr(r, col)) for r in rows]) for axis, col in AXIS_COLUMN.items()}
    rating = _avg([r.rating for r in rows])
    recommend = _pct(sum(1 for r in rows if r.recommend), n)
    ceo_rows = [r for r in rows if r.ceo_approval is not None]
    ceo = _pct(sum(1 for r in ceo_rows if r.ceo_approval), len(ceo_rows))
    growth = _pct(sum(1 for r in rows if r.growth == "up"), n)

    by_year: dict[str, Any] = {}
    for r in rows:
        y = by_year.setdefault(str(r.work_year), {"n": 0, "sum": 0.0, "axes": {a: 0.0 for a in AXES}, "recommend": 0})
        y["n"] += 1
        y["sum"] += r.rating
        y["recommend"] += 1 if r.recommend else 0
        for axis, col in AXIS_COLUMN.items():
            y["axes"][axis] += float(getattr(r, col))
    for y in by_year.values():
        y["rating"] = round(y["sum"] / y["n"], 2)
        y["axes"] = {a: round(v / y["n"], 2) for a, v in y["axes"].items()}
        y["recommend"] = _pct(y["recommend"], y["n"])
        del y["sum"]

    by_job: dict[str, Any] = {}
    for r in rows:
        fam = _family(r.job_code)
        if not fam:
            continue
        j = by_job.setdefault(fam, {"n": 0, "sum": 0.0, "salaries": []})
        j["n"] += 1
        j["sum"] += r.rating
        if r.salary:
            j["salaries"].append(r.salary)
    for j in by_job.values():
        j["rating"] = round(j["sum"] / j["n"], 2)
        j["salary"] = _salary_summary(j["salaries"])
        del j["sum"], j["salaries"]

    salaries = [r.salary for r in rows if r.salary]
    salary = _salary_summary(salaries)
    if salary:
        # By experience band, which is what "is this fair for my years" actually asks.
        bands: dict[str, list[int]] = {}
        for r in rows:
            if r.salary and r.experience_years is not None:
                key = "0-2" if r.experience_years <= 2 else "3-5" if r.experience_years <= 5 else "6-9" if r.experience_years <= 9 else "10+"
                bands.setdefault(key, []).append(r.salary)
        salary["bands"] = {k: _salary_summary(v) for k, v in bands.items()}

    iv_rows = [r for r in rows if r.interview]
    difficulties = [int(r.interview["difficulty"]) for r in iv_rows if r.interview.get("difficulty")]
    results = [r.interview["result"] for r in iv_rows if r.interview.get("result")]
    interview = {"n": len(iv_rows), "difficulty": _avg([float(d) for d in difficulties]) if difficulties else None,
                 "pass_rate": _pct(sum(1 for x in results if x == "pass"), len(results))} if iv_rows else None

    benefit_counts: dict[str, int] = {}
    for r in rows:
        for b in r.benefits or []:
            benefit_counts[b] = benefit_counts.get(b, 0) + 1
    benefits = sorted(({"code": k, "n": v} for k, v in benefit_counts.items()), key=lambda x: (-x["n"], x["code"]))
    topic_counts: dict[str, int] = {}
    for r in rows:
        for tpc in r.topics or []:
            topic_counts[tpc] = topic_counts.get(tpc, 0) + 1
    employment = {"current": sum(1 for r in rows if r.employment == "current"),
                  "former": sum(1 for r in rows if r.employment == "former")}
    # How the overall scores spread — five stars down to one — for the distribution strip.
    dist = {str(k): 0 for k in range(5, 0, -1)}
    for r in rows:
        dist[str(max(1, min(5, int(round(r.rating)))))] += 1
    # What people actually answered, per question — the facts a page quotes (plan/40 §8).
    facts = Q.tally([r.answers or {} for r in rows])
    answered = sum(1 for r in rows if r.answers)
    verified_n = sum(1 for r in rows if r.verified)

    c = await db.get(Company, company_id)
    if c is None:
        return {}
    stats = {"n": n, "rating": rating, "axes": axes, "recommend": recommend, "ceo": ceo, "growth": growth,
             "by_year": by_year, "by_job": by_job, "salary": salary, "interview": interview,
             "benefits": benefits[:12], "topics": topic_counts, "employment": employment, "dist": dist,
             "facts": facts, "answered": answered, "verified_n": verified_n,
             "computed_at": datetime.now(UTC).isoformat()}
    c.stats = stats
    c.review_count = n
    c.rating = rating
    c.tags = _tags(n, axes, recommend, growth, c.open_jobs)
    c.popularity = popularity_score(market=c.market, views_7d=c.views_7d, follow_count=c.follow_count,
                                    review_count=n, open_jobs=c.open_jobs, employees=c.employees, homepage=c.homepage)
    await db.flush()
    return stats


async def rank_all(db: AsyncSession) -> dict[str, int]:
    """The worker's pass: views in the last week, open postings, and the popularity that
    follows from them — for every company, in four statements."""
    await db.execute(text("UPDATE companies SET views_7d = 0 WHERE views_7d <> 0"))
    await db.execute(text("""
        UPDATE companies c SET views_7d = v.n
        FROM (SELECT company_id, count(*) AS n FROM company_views
              WHERE created_at >= now() - interval '7 days' GROUP BY company_id) v
        WHERE c.id = v.company_id"""))
    await db.execute(text("UPDATE companies SET open_jobs = 0 WHERE open_jobs <> 0"))
    await db.execute(text("""
        UPDATE companies c SET open_jobs = j.n
        FROM (SELECT company_id, count(*) AS n FROM community_jobs
              WHERE status = 'open' AND company_id IS NOT NULL GROUP BY company_id) j
        WHERE c.id = j.company_id"""))
    res = await db.execute(text("""
        UPDATE companies SET popularity =
            ln(1 + views_7d) * 3 + follow_count * 2 + review_count * 4 + open_jobs * 1.5
            + CASE market WHEN '유가' THEN 1.0 WHEN '코스닥' THEN 0.6 WHEN '코넥스' THEN 0.3 ELSE 0 END
            + CASE WHEN homepage <> '' THEN 0.2 ELSE 0 END
            + ln(1 + COALESCE(employees, 0)) / 4.0
        WHERE hidden = false AND (market <> '' OR industry_text <> '' OR address <> '' OR biz_no IS NOT NULL)"""))
    # A "hiring" tag comes and goes with the postings, not with the next review.
    await db.execute(text("""
        UPDATE companies SET tags = (SELECT COALESCE(jsonb_agg(t), '[]'::jsonb) FROM jsonb_array_elements(tags) t WHERE t <> '"hiring"')
        WHERE tags @> '["hiring"]' AND open_jobs = 0"""))
    await db.execute(text("""
        UPDATE companies SET tags = tags || '["hiring"]'::jsonb
        WHERE open_jobs > 0 AND NOT (tags @> '["hiring"]') AND jsonb_array_length(tags) < 4"""))
    return {"ranked": res.rowcount or 0}


# ── reading ─────────────────────────────────────────────────────────
def card(c: Company, *, following: bool = False) -> dict[str, Any]:
    """What a search result or a shelf shows about a company."""
    st = c.stats or {}
    return {
        "id": str(c.id), "name": c.name, "stock_code": c.stock_code, "market": c.market,
        "industry_text": c.industry_text, "industry_codes": list(c.industry_codes or []),
        "region_code": c.region_code, "region_text": c.region_text, "ceo": c.ceo, "homepage": c.homepage,
        "status": c.status, "employees": c.employees,
        "listed_on": c.listed_on.isoformat() if c.listed_on else None,
        "founded_on": c.founded_on.isoformat() if c.founded_on else None,
        "rating": round(c.rating or 0, 1), "review_count": c.review_count, "follow_count": c.follow_count,
        "open_jobs": c.open_jobs, "tags": list(c.tags or []), "following": following,
        "recommend": st.get("recommend"), "salary_median": (st.get("salary") or {}).get("median"),
    }


async def followed_ids(db: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    rows = await db.execute(select(CompanyFollow.company_id).where(CompanyFollow.user_id == user_id,
                                                                    CompanyFollow.company_id.in_(ids)))
    return {r[0] for r in rows}


async def cards(db: AsyncSession, companies: list[Company], user: User | None) -> list[dict[str, Any]]:
    mine = await followed_ids(db, user.id, [c.id for c in companies]) if user else set()
    return [card(c, following=c.id in mine) for c in companies]


def _visible():
    return (Company.hidden.is_(False), substantive())


def review_out(r: CompanyReview, *, mine: bool, helpful: bool, company: Company | None = None) -> dict[str, Any]:
    """A review, without its author. The job family, status and year are the byline."""
    fam = _family(r.job_code)
    row: dict[str, Any] = {
        "id": str(r.id), "company_id": str(r.company_id), "status": r.status,
        "employment": r.employment, "job_code": r.job_code, "job_family": fam,
        "job_label": JOB_NAME.get(r.job_code, ""), "family_label": JOB_NAME.get(fam, ""),
        "work_year": r.work_year, "title": r.title, "pros": r.pros, "cons": r.cons, "advice": r.advice,
        "rating": r.rating,
        "axes": {axis: round(float(getattr(r, col)), 2) for axis, col in AXIS_COLUMN.items()},
        "recommend": r.recommend, "ceo_approval": r.ceo_approval, "growth": r.growth,
        "salary": r.salary, "experience_years": r.experience_years,
        "interview": dict(r.interview or {}), "benefits": list(r.benefits or []), "topics": list(r.topics or []),
        "answers": dict(r.answers or {}), "verified": bool(r.verified),
        "helpful_count": r.helpful_count, "helpful": helpful, "is_mine": mine,
        "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "version": r.version,
    }
    if company is not None:
        row["company"] = {"id": str(company.id), "name": company.name, "market": company.market,
                          "industry_text": company.industry_text, "region_text": company.region_text}
    return row


async def list_reviews(db: AsyncSession, *, company_id: uuid.UUID, user: User | None, year: int | None = None,
                       sort: str = "helpful", kind: str = "all", job: str = "", page: int = 1,
                       size: int = 10) -> dict[str, Any]:
    stmt = select(CompanyReview).where(CompanyReview.company_id == company_id, CompanyReview.status == "published")
    if year:
        stmt = stmt.where(CompanyReview.work_year == year)
    if kind == "salary":
        stmt = stmt.where(or_(CompanyReview.salary.is_not(None), CompanyReview.topics.contains(cast(["salary"], JSONB))))
    elif kind == "interview":
        stmt = stmt.where(CompanyReview.interview != cast({}, JSONB))
    elif kind == "benefits":
        stmt = stmt.where(func.jsonb_array_length(CompanyReview.benefits) > 0)
    if job:
        codes = JOB_INDEX.get(job) or [job]
        stmt = stmt.where(CompanyReview.job_code.in_(codes))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    order = {
        "new": (CompanyReview.created_at.desc(),),
        "high": (CompanyReview.rating.desc(), CompanyReview.created_at.desc()),
        "low": (CompanyReview.rating.asc(), CompanyReview.created_at.desc()),
    }.get(sort, (CompanyReview.helpful_count.desc(), CompanyReview.created_at.desc()))
    size = max(1, min(size, 50))
    rows = list((await db.execute(stmt.order_by(*order).offset((page - 1) * size).limit(size))).scalars().all())
    helpful = await C.liked_ids(db, target_type="review", ids=[r.id for r in rows], user_id=user.id if user else None) \
        if rows else set()
    return {"items": [review_out(r, mine=bool(user and r.author_id == user.id), helpful=r.id in helpful) for r in rows],
            "total": int(total), "page": page, "size": size}


async def my_review(db: AsyncSession, *, company_id: uuid.UUID, user: User) -> CompanyReview | None:
    r = (await db.execute(select(CompanyReview).where(CompanyReview.company_id == company_id,
                                                      CompanyReview.author_id == user.id))).scalar_one_or_none()
    return r if r is not None and r.status != "deleted" else None


async def detail(db: AsyncSession, *, company: Company, user: User) -> dict[str, Any]:
    """The company page's first request: the company, its numbers, and where the reader
    stands with it. Tabs fetch their own lists."""
    from memora.services.companies.query import out

    mine = await my_review(db, company_id=company.id, user=user)
    following = bool(await followed_ids(db, user.id, [company.id]))
    industry = (company.industry_codes or [None])[0]
    related: list[Company] = []
    if industry:
        related = list((await db.execute(
            select(Company).where(*_visible(), Company.id != company.id,
                                  Company.industry_codes.contains(cast([industry], JSONB)))
            .order_by(Company.popularity.desc(), Company.name).limit(6))).scalars().all())
    posts_n = (await db.execute(
        select(func.count()).select_from(CommunityPost)
        .where(CommunityPost.status == "published", CommunityPost.title.ilike(f"%{company.name}%")))).scalar_one() \
        if len(company.name) >= 2 else 0
    # The reader's own line of work, as seen at this company: the by-job slice of the
    # stats, when their profile names a job (plan/40 §7).
    prof = await PF.get(db, user.id)
    job_codes = [c for c in ((prof.data or {}).get("job_codes") or []) if isinstance(c, str)]
    fam = _family(job_codes[0]) if job_codes else ""
    my_job = None
    if fam:
        slice_ = ((company.stats or {}).get("by_job") or {}).get(fam)
        my_job = {"family": fam, "label": JOB_NAME.get(fam, fam), "stats": slice_}
    from memora.services.companies import verification as VF
    return {
        "company": {**out(company, full=True), **card(company, following=following)},
        "stats": company.stats or EMPTY_STATS,
        "my_verified": await VF.verified_for(db, user.id, company.id),
        "my_review": review_out(mine, mine=True, helpful=False) if mine else None,
        "following": following,
        "related": await cards(db, related, user),
        "posts_count": int(posts_n),
        "years": sorted(((company.stats or {}).get("by_year") or {}).keys(), reverse=True),
        "my_job": my_job,
    }


#: What a company with no reviews reports — every key a screen reads, so no reader has to
#: guess which ones exist before the first review.
EMPTY_STATS: dict[str, Any] = {"n": 0, "rating": 0.0, "axes": {}, "recommend": None, "ceo": None, "growth": None,
                               "by_year": {}, "by_job": {}, "salary": None, "interview": None, "benefits": [],
                               "topics": {}, "employment": {"current": 0, "former": 0}, "dist": {}, "facts": {}, "answered": 0, "verified_n": 0}

MAX_COMPARE = 4


async def compare(db: AsyncSession, *, ids: list[uuid.UUID], user: User) -> list[dict[str, Any]]:
    """Up to four companies side by side: the card plus the slice of stats a table shows.
    Order follows the ids the reader picked."""
    ids = list(dict.fromkeys(ids))[:MAX_COMPARE]
    if not ids:
        return []
    rows = {c.id: c for c in (await db.execute(select(Company).where(Company.id.in_(ids), Company.hidden.is_(False)))).scalars().all()}
    mine = await followed_ids(db, user.id, ids)
    out_: list[dict[str, Any]] = []
    for i in ids:
        c = rows.get(i)
        if c is None:
            continue
        st = c.stats or {}
        out_.append({**card(c, following=i in mine),
                     "stats": {"n": st.get("n", 0), "rating": st.get("rating", 0), "axes": st.get("axes") or {},
                               "recommend": st.get("recommend"), "ceo": st.get("ceo"), "growth": st.get("growth"),
                               "salary": st.get("salary"), "interview": st.get("interview"),
                               "benefits": [b["code"] for b in (st.get("benefits") or [])[:6]],
                               "employment": st.get("employment") or {}, "facts": st.get("facts") or {},
                               "answered": st.get("answered", 0)}})
    return out_


# ── the dashboard ───────────────────────────────────────────────────
def _best_snippet(r: CompanyReview) -> dict[str, Any]:
    return {"review_id": str(r.id), "title": r.title, "excerpt": (r.pros or "")[:120], "rating": r.rating,
            "family_label": JOB_NAME.get(_family(r.job_code), ""), "salary": r.salary}


async def salary_top(db: AsyncSession, user: User, *, limit: int = 3, days: int = 365) -> list[dict[str, Any]]:
    """Companies people talk about pay at. Reviews first; while there are too few of
    those, postings that state a salary keep the shelf from standing empty."""
    since = datetime.now(UTC) - timedelta(days=days)
    grouped = (await db.execute(
        select(CompanyReview.company_id, func.count().label("n"))
        .where(CompanyReview.status == "published", CompanyReview.created_at >= since,
               or_(CompanyReview.salary.is_not(None), CompanyReview.topics.contains(cast(["salary"], JSONB))))
        .group_by(CompanyReview.company_id).order_by(text("n DESC")).limit(limit))).all()
    items: list[dict[str, Any]] = []
    for cid, n in grouped:
        c = await db.get(Company, cid)
        if c is None or c.hidden:
            continue
        best = (await db.execute(
            select(CompanyReview).where(CompanyReview.company_id == cid, CompanyReview.status == "published",
                                        or_(CompanyReview.salary.is_not(None),
                                            CompanyReview.topics.contains(cast(["salary"], JSONB))))
            .order_by(CompanyReview.helpful_count.desc(), CompanyReview.created_at.desc()).limit(1))).scalar_one_or_none()
        items.append({"company": card(c), "mentions": int(n), "source": "reviews",
                      "snippet": _best_snippet(best) if best else None})
    if len(items) < limit:
        seen = {it["company"]["id"] for it in items}
        top = func.coalesce(CommunityJob.salary_max, CommunityJob.salary_min)
        jobs = (await db.execute(
            select(CommunityJob.company_id, func.max(top).label("top"), func.min(func.coalesce(CommunityJob.salary_min, CommunityJob.salary_max)).label("low"),
                   func.count().label("n"))
            .where(CommunityJob.status == "open", CommunityJob.company_id.is_not(None), top.is_not(None))
            .group_by(CommunityJob.company_id).order_by(text("top DESC")).limit(limit * 2))).all()
        for cid, hi, lo, n in jobs:
            if str(cid) in seen or len(items) >= limit:
                continue
            c = await db.get(Company, cid)
            if c is None or c.hidden:
                continue
            j = (await db.execute(select(CommunityJob).where(CommunityJob.company_id == cid, CommunityJob.status == "open")
                                  .order_by(top.desc()).limit(1))).scalar_one_or_none()
            items.append({"company": card(c), "mentions": int(n), "source": "jobs",
                          "snippet": {"title": j.title if j else "", "salary_min": lo, "salary_max": hi, "job_id": str(j.id) if j else None}})
    mine = await followed_ids(db, user.id, [uuid.UUID(it["company"]["id"]) for it in items])
    for it in items:
        it["company"]["following"] = uuid.UUID(it["company"]["id"]) in mine
    return items


async def for_me(db: AsyncSession, user: User, *, limit: int = 9) -> dict[str, Any]:
    """Companies that touch the reader's own line of work, each with the reason it is here:
    hiring for their job, reviewed by people in their job, or in their industry."""
    prof = await PF.get(db, user.id)
    data = prof.data or {}
    job_codes = [c for c in (data.get("job_codes") or []) if isinstance(c, str)]
    industry_codes = [c for c in (data.get("industry_codes") or []) if isinstance(c, str)]
    if not job_codes and not industry_codes:
        return {"needs_profile": True, "items": []}
    picked: dict[uuid.UUID, dict[str, Any]] = {}

    wanted: set[str] = set()
    for code in job_codes:
        wanted.update(JOB_INDEX.get(code) or [code])
    if wanted:
        hiring = (await db.execute(
            select(CommunityJob.company_id, func.count().label("n"))
            .where(CommunityJob.status == "open", CommunityJob.company_id.is_not(None),
                   or_(*[CommunityJob.job_codes.contains(cast([c], JSONB)) for c in sorted(wanted)]))
            .group_by(CommunityJob.company_id).order_by(text("n DESC")).limit(limit))).all()
        for cid, n in hiring:
            picked.setdefault(cid, {"why": "jobs", "n": int(n)})
        families = {_family(c) for c in job_codes if _family(c)}
        fam_codes: set[str] = set()
        for f in families:
            fam_codes.update(JOB_INDEX.get(f) or [f])
        if fam_codes and len(picked) < limit:
            reviewed = (await db.execute(
                select(CompanyReview.company_id, func.count().label("n"))
                .where(CompanyReview.status == "published", CompanyReview.job_code.in_(sorted(fam_codes)))
                .group_by(CompanyReview.company_id).order_by(text("n DESC")).limit(limit))).all()
            for cid, n in reviewed:
                picked.setdefault(cid, {"why": "reviews", "n": int(n)})
    if industry_codes and len(picked) < limit:
        codes: set[str] = set()
        for code in industry_codes:
            codes.update(INDUSTRY_INDEX.get(code) or expand_industry(code))
        rows = (await db.execute(
            select(Company.id).where(*_visible(), or_(*[Company.industry_codes.contains(cast([c], JSONB)) for c in sorted(codes)]))
            .order_by(Company.popularity.desc(), Company.review_count.desc(), Company.name).limit(limit * 2))).all()
        for (cid,) in rows:
            if len(picked) >= limit:
                break
            picked.setdefault(cid, {"why": "industry", "n": 0})
    ids = list(picked)[:limit]
    companies = {c.id: c for c in (await db.execute(select(Company).where(Company.id.in_(ids), Company.hidden.is_(False)))).scalars().all()} if ids else {}
    mine = await followed_ids(db, user.id, ids)
    items = [{**card(companies[i], following=i in mine), **picked[i]} for i in ids if i in companies]
    return {"needs_profile": False, "items": items,
            "job_labels": [JOB_NAME.get(c, c) for c in job_codes][:3]}


async def shelves(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    """Curated rows for the dashboard. Rated shelves need enough reviews to mean
    anything; until then the directory's own facts (hiring, newly listed, most viewed)
    fill the page so it never opens on nothing."""
    out: list[dict[str, Any]] = []
    for axis in ("promotion", "pay", "balance", "culture"):
        expr = cast(Company.stats["axes"][axis].astext, __import__("sqlalchemy").Float)
        rows = list((await db.execute(
            select(Company).where(*_visible(), Company.review_count >= 2, expr >= 3.5)
            .order_by(expr.desc(), Company.review_count.desc(), Company.name).limit(8))).scalars().all())
        if len(rows) >= 3:
            out.append({"key": axis, "items": await cards(db, rows, user)})
    hiring = list((await db.execute(
        select(Company).where(*_visible(), Company.open_jobs > 0)
        .order_by(Company.open_jobs.desc(), Company.popularity.desc(), Company.name).limit(8))).scalars().all())
    if len(hiring) >= 2:
        out.append({"key": "hiring", "items": await cards(db, hiring, user)})
    viewed = list((await db.execute(
        select(Company).where(*_visible(), Company.views_7d > 0)
        .order_by(Company.views_7d.desc(), Company.popularity.desc(), Company.name).limit(8))).scalars().all())
    if len(viewed) >= 3:
        out.append({"key": "viewed", "items": await cards(db, viewed, user)})
    listed = list((await db.execute(
        select(Company).where(*_visible(), Company.listed_on.is_not(None), Company.market != "")
        .order_by(Company.listed_on.desc(), Company.name).limit(8))).scalars().all())
    if len(listed) >= 3:
        out.append({"key": "new_listed", "items": await cards(db, listed, user)})
    return out


#: The question whose most common answer headlines each area on the dashboard — the
#: required one, so every reviewed company has it.
AREA_HEADLINE = {"pay": "pay_level", "balance": "hours", "culture": "comm", "promotion": "promo_speed", "management": "trust"}


def _top_option(counts: dict[str, int] | None) -> dict[str, Any] | None:
    if not counts:
        return None
    total = sum(counts.values())
    if not total:
        return None
    opt, n = max(counts.items(), key=lambda kv: kv[1])
    return {"option": opt, "n": n, "total": total, "pct": round(100 * n / total)}


async def area_top(db: AsyncSession, user: User, area: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """The companies people rate highest in one area — with that area's headline fact.

    Any company with a review qualifies; the count is shown, so a 5.0 from one person
    reads as what it is. Ranked by the area's score, then by how many said so.
    """
    from sqlalchemy import Float

    expr = cast(Company.stats["axes"][area].astext, Float)
    rows = list((await db.execute(
        select(Company).where(*_visible(), Company.review_count >= 1, Company.stats["axes"].has_key(area))
        .order_by(expr.desc(), Company.review_count.desc(), Company.name).limit(limit))).scalars().all())
    mine = await followed_ids(db, user.id, [c.id for c in rows])
    out_: list[dict[str, Any]] = []
    for c in rows:
        st = c.stats or {}
        q = AREA_HEADLINE[area]
        out_.append({**card(c, following=c.id in mine),
                     "score": round(float((st.get("axes") or {}).get(area) or 0), 1),
                     "fact": {"question": q, **top} if (top := _top_option((st.get("facts") or {}).get(q))) else None})
    return out_


async def home(db: AsyncSession, user: User) -> dict[str, Any]:
    popular = list((await db.execute(
        select(Company).where(*_visible()).order_by(Company.popularity.desc(), Company.review_count.desc(), Company.name)
        .limit(12))).scalars().all())
    recent = (await db.execute(
        select(CompanyReview, Company).join(Company, Company.id == CompanyReview.company_id)
        .where(CompanyReview.status == "published", Company.hidden.is_(False))
        .order_by(CompanyReview.created_at.desc()).limit(6))).all()
    following = list((await db.execute(
        select(Company).join(CompanyFollow, CompanyFollow.company_id == Company.id)
        .where(CompanyFollow.user_id == user.id, Company.hidden.is_(False))
        .order_by(CompanyFollow.created_at.desc()).limit(12))).scalars().all())
    prof = await PF.get(db, user.id)
    own_name = str((prof.data or {}).get("company") or "").strip()
    # A proven company beats a typed name (plan/40 §10).
    from memora.services.companies import verification as VF
    own_id = await VF.verified_company_id(db, user.id)
    own = await db.get(Company, own_id) if own_id else (await match_by_name(db, own_name) if own_name else None)
    if own is not None and own.hidden:
        own = None
    totals = (await db.execute(
        select(func.count(Company.id).filter(Company.hidden.is_(False)),
               func.coalesce(func.sum(Company.review_count), 0)).where(substantive()))).one()
    return {
        "popular": await cards(db, popular, user),
        # The five areas a review speaks about, each with its top companies (plan/40 §9).
        "areas": [{"key": area, "items": await area_top(db, user, area)} for area in AXES],
        "salary_top": await salary_top(db, user),
        "for_me": await for_me(db, user),
        "following": [card(c, following=True) for c in following],
        "my_company": {"name": own_name or (own.name if own else ""), "verified": bool(own_id), "company": (await cards(db, [own], user))[0] if own else None} if (own_name or own) else None,
        "shelves": await shelves(db, user),
        "recent_reviews": [review_out(r, mine=r.author_id == user.id, helpful=False, company=c) for r, c in recent],
        "totals": {"companies": int(totals[0]), "reviews": int(totals[1])},
    }


async def search_all(db: AsyncSession, *, q: str, user: User) -> dict[str, Any]:
    """One query, three answers: companies, postings, posts. What the 전체 tab shows."""
    from memora.services.companies.query import search

    q = (q or "").strip()
    found = await search(db, q=q, page=1, size=6, include_hidden=False, sort="popular")
    ids = [uuid.UUID(it["id"]) for it in found["items"]]
    companies = {c.id: c for c in (await db.execute(select(Company).where(Company.id.in_(ids)))).scalars().all()} if ids else {}
    company_cards = await cards(db, [companies[i] for i in ids if i in companies], user)
    jobs = await C.list_jobs(db, q=q, limit=6) if q else []
    posts, _ = await C.list_posts(db, board=None, q=q, limit=6) if q else ([], None)
    boards = {b.id: b for b in await C.boards(db)}
    return {
        "q": q,
        "companies": {"items": company_cards, "total": found["total"]},
        "jobs": [{"id": str(j.id), "title": j.title, "company": j.company, "company_id": str(j.company_id) if j.company_id else None,
                  "location": j.location, "employment_type": j.employment_type, "salary_min": j.salary_min,
                  "salary_max": j.salary_max, "created_at": j.created_at.isoformat()} for j in jobs],
        "posts": [{"id": str(p.id), "title": p.title, "excerpt": p.body[:140],
                   "board": boards[p.board_id].name if p.board_id in boards else "",
                   "like_count": p.like_count, "comment_count": p.comment_count,
                   "created_at": p.created_at.isoformat()} for p in posts],
    }


async def posts_about(db: AsyncSession, *, company: Company, limit: int = 20) -> list[CommunityPost]:
    """Community posts that name the company. The name is the only link there is — a
    post is not tagged with an employer — so this is a text search, on purpose narrow."""
    if len(company.name) < 2:
        return []
    rows, _ = await C.list_posts(db, board=None, q=company.name, limit=limit)
    return rows
