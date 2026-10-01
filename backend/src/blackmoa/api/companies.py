"""Companies as readers use them (plan/33 §5, plan/40).

The dashboard, search, a company's page, and what people say about it. Everything here
reads our own database — the directory is collected on a schedule, never on request —
and the numbers a page shows were written when a review was saved, not summed here.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from blackmoa.api.community import _job_out, _read_budget, _write_budget
from blackmoa.core.deps import DB, CurrentUser
from blackmoa.core.errors import NotFound, ValidationFailed
from blackmoa.data.jobs_taxonomy import JOB_FAMILIES, JOB_NAME
from blackmoa.models import Company, CompanyReview
from blackmoa.services import community as C
from blackmoa.services.companies import questions as Q
from blackmoa.services.companies import reviews as RV
from blackmoa.services.companies import switch as CO
from blackmoa.services.companies.query import SORTS, search, suggest

# 관리자가 기업 기능을 끄면 기업 페이지 전체가 닫힌다 (plan/71).
router = APIRouter(prefix="/api/community/companies", tags=["companies"], dependencies=[Depends(CO.gate)])


async def _company(db, company_id: uuid.UUID) -> Company:
    c = await db.get(Company, company_id)
    if c is None or c.hidden:
        raise NotFound("company not found", code="company_not_found")
    return c


async def _review(db, review_id: uuid.UUID) -> CompanyReview:
    r = await db.get(CompanyReview, review_id)
    if r is None or r.status == "deleted":
        raise NotFound("review not found", code="review_not_found")
    return r


# ── lists (static paths first: they must not be read as a company id) ─────────────
@router.get("")
async def company_list(user: CurrentUser, db: DB, q: str = "", region: str = "", industry: str = "",
                       market: str = "", sort: str = "popular", page: int = 1):
    """The directory, as readers see it: hidden companies out, and only companies we can
    say something about (plan/33 §5)."""
    _read_budget(user)
    found = await search(db, q=q, region=region, industry=industry, market=market, page=max(1, page),
                         size=24, include_hidden=False, sort=sort if sort in SORTS else "popular")
    mine = await RV.followed_ids(db, user.id, [uuid.UUID(it["id"]) for it in found["items"]])
    for it in found["items"]:
        it["following"] = uuid.UUID(it["id"]) in mine
    return found


@router.get("/home")
async def company_home(user: CurrentUser, db: DB):
    """The first screen: who is popular, where pay is talked about, what touches the
    reader's own job — and only then a search box (plan/40 §1)."""
    _read_budget(user)
    return await RV.home(db, user)


@router.get("/search")
async def company_search_all(user: CurrentUser, db: DB, q: str = ""):
    _read_budget(user)
    return await RV.search_all(db, q=q, user=user)


@router.get("/suggest")
async def company_suggest(user: CurrentUser, db: DB, q: str = ""):
    """Name completion for the posting form, so a posting can be linked to a real company
    instead of being one more spelling of its name."""
    _read_budget(user)
    return {"items": await suggest(db, q)}


@router.get("/meta")
async def company_meta(user: CurrentUser):
    """The vocabulary a review form needs. Shipped whole, like the job taxonomy."""
    return {"axes": list(RV.AXES), "benefits": RV.BENEFITS, "tags": list(RV.TAG_CODES),
            "employments": list(RV.EMPLOYMENTS), "growths": list(RV.GROWTHS),
            "interview_results": list(RV.INTERVIEW_RESULTS), "min_text": RV.MIN_TEXT,
            "year_now": RV._year_now(), "sorts": list(SORTS), "job_families": JOB_FAMILIES,
            "questions": Q.spec(), "areas": list(Q.AREAS), "fact_questions": list(Q.FACT_QUESTIONS)}


@router.get("/compare")
async def company_compare(user: CurrentUser, db: DB, ids: str = ""):
    """Side by side, up to four (plan/40 §7). Unknown or hidden ids are simply absent."""
    _read_budget(user)
    parsed: list[uuid.UUID] = []
    for raw in ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed.append(uuid.UUID(raw))
        except ValueError:
            raise ValidationFailed("bad id", code="bad_id") from None
    return {"items": await RV.compare(db, ids=parsed, user=user), "max": RV.MAX_COMPARE}


@router.get("/reviews/mine")
async def my_reviews(user: CurrentUser, db: DB):
    from sqlalchemy import select

    _read_budget(user)
    rows = (await db.execute(
        select(CompanyReview, Company).join(Company, Company.id == CompanyReview.company_id)
        .where(CompanyReview.author_id == user.id, CompanyReview.status != "deleted")
        .order_by(CompanyReview.updated_at.desc()).limit(100))).all()
    return {"items": [RV.review_out(r, mine=True, helpful=False, company=c) for r, c in rows]}


# ── one review ──────────────────────────────────────────────────────
@router.delete("/reviews/{review_id}")
async def delete_review(review_id: uuid.UUID, user: CurrentUser, db: DB):
    _write_budget(user)
    r = await _review(db, review_id)
    await RV.remove(db, review=r, user=user)
    await db.commit()
    return {"ok": True}


@router.post("/reviews/{review_id}/helpful")
async def helpful(review_id: uuid.UUID, user: CurrentUser, db: DB):
    _write_budget(user)
    r = await _review(db, review_id)
    if r.status != "published":
        raise NotFound("review not found", code="review_not_found")
    on, n = await RV.toggle_helpful(db, review=r, user=user)
    await db.commit()
    return {"helpful": on, "helpful_count": n}


class ReportIn(BaseModel):
    reason: str = Field(max_length=40)
    detail: str = Field(default="", max_length=2000)


@router.post("/reviews/{review_id}/report", status_code=201)
async def report_review(review_id: uuid.UUID, body: ReportIn, user: CurrentUser, db: DB):
    _write_budget(user)
    r = await _review(db, review_id)
    await C.report(db, target_type="review", target_id=r.id, user=user, reason=body.reason, detail=body.detail)
    await db.commit()
    return {"ok": True}


# ── one company ─────────────────────────────────────────────────────
@router.get("/{company_id}")
async def company_detail(company_id: uuid.UUID, user: CurrentUser, db: DB):
    _read_budget(user)
    c = await _company(db, company_id)
    await RV.register_view(db, c.id, str(user.id))
    await db.commit()
    await db.refresh(c)
    return await RV.detail(db, company=c, user=user)


@router.post("/{company_id}/follow")
async def follow(company_id: uuid.UUID, user: CurrentUser, db: DB):
    _write_budget(user)
    c = await _company(db, company_id)
    on, n = await RV.toggle_follow(db, company=c, user=user)
    await db.commit()
    return {"following": on, "follow_count": n}


@router.get("/{company_id}/reviews")
async def reviews(company_id: uuid.UUID, user: CurrentUser, db: DB, year: int | None = None,
                  sort: str = "helpful", kind: str = "all", job: str = "", page: int = 1, size: int = 10):
    _read_budget(user)
    c = await _company(db, company_id)
    return await RV.list_reviews(db, company_id=c.id, user=user, year=year, sort=sort, kind=kind,
                                 job=job, page=max(1, page), size=size)


class InterviewIn(BaseModel):
    difficulty: int | None = None
    result: str | None = None
    questions: str | None = Field(default=None, max_length=2000)
    process: str | None = Field(default=None, max_length=2000)


class ReviewIn(BaseModel):
    employment: str | None = None
    job_code: str | None = None
    work_year: int | None = None
    title: str | None = Field(default=None, max_length=120)
    pros: str = Field(max_length=RV.MAX_TEXT)
    cons: str = Field(max_length=RV.MAX_TEXT)
    advice: str | None = Field(default=None, max_length=RV.MAX_TEXT)
    #: The current form: concrete answers (services.companies.questions). Scores derive.
    answers: dict[str, Any] | None = None
    #: The older form, still accepted when `answers` is absent.
    rating: int | None = None
    rating_pay: int | None = None
    rating_balance: int | None = None
    rating_culture: int | None = None
    rating_promotion: int | None = None
    rating_management: int | None = None
    recommend: bool = True
    ceo_approval: bool | None = None
    growth: str | None = None
    salary: int | None = None
    experience_years: int | None = None
    interview: InterviewIn | None = None
    benefits: list[str] | None = None


@router.post("/{company_id}/reviews", status_code=201)
async def write_review(company_id: uuid.UUID, body: ReviewIn, user: CurrentUser, db: DB):
    """Create the reader's review of this company, or replace the one they already
    wrote — one voice per person per company."""
    _write_budget(user)
    c = await _company(db, company_id)
    data: dict[str, Any] = body.model_dump(exclude_none=True)
    if body.ceo_approval is None:
        data["ceo_approval"] = None
    r = await RV.submit(db, company=c, user=user, data=data)
    await db.commit()
    await db.refresh(r)
    await db.refresh(c)
    return {"review": RV.review_out(r, mine=True, helpful=False), "stats": c.stats, "company": RV.card(c)}


@router.get("/{company_id}/jobs")
async def company_jobs(company_id: uuid.UUID, user: CurrentUser, db: DB):
    _read_budget(user)
    c = await _company(db, company_id)
    jobs = await C.list_jobs(db, company_id=c.id, limit=30)
    return {"items": [_job_out(j, mine=j.posted_by == user.id) for j in jobs]}


@router.get("/{company_id}/posts")
async def company_posts(company_id: uuid.UUID, user: CurrentUser, db: DB):
    """Community posts that name the company — the closest thing to a newsroom that does
    not involve reading someone else's site."""
    _read_budget(user)
    c = await _company(db, company_id)
    rows = await RV.posts_about(db, company=c)
    boards = {b.id: b for b in await C.boards(db)}
    return {"items": [{"id": str(p.id), "title": p.title, "excerpt": p.body[:160],
                       "board": boards[p.board_id].name if p.board_id in boards else "",
                       "like_count": p.like_count, "comment_count": p.comment_count, "view_count": p.view_count,
                       "created_at": p.created_at.isoformat()} for p in rows]}


@router.get("/{company_id}/salary")
async def company_salary(company_id: uuid.UUID, user: CurrentUser, db: DB):
    """What the pay tab shows: the summary from the stats blob plus the reviews that state
    a figure, so a reader can see the numbers behind the median."""
    _read_budget(user)
    c = await _company(db, company_id)
    st = c.stats or {}
    by_job = {k: v for k, v in (st.get("by_job") or {}).items() if v.get("salary")}
    listed = await RV.list_reviews(db, company_id=c.id, user=user, kind="salary", sort="new", size=50)
    return {"summary": st.get("salary"), "by_job": by_job, "job_labels": {k: JOB_NAME.get(k, k) for k in by_job},
            "reviews": listed["items"], "total": listed["total"]}


__all__ = ["router", "ValidationFailed"]
