"""Reading the directory — the shape the admin console and the community both use."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.data.jobs_taxonomy import INDUSTRIES
from blackmoa.models import Company
from blackmoa.services.companies.merge import normalise_name


def substantive():
    """Companies we can say something about, as one expression both readers and the
    coverage count use.

    Written twice it drifted: the directory tested `stock_code IS NOT NULL`, which the
    regulator keeps for every company that ever listed, so 1,231 dissolved shells were
    shown to readers as a name and nothing else. `market` is what the exchange sets and
    what means currently traded.
    """
    return or_(Company.market != "", Company.industry_text != "",
               Company.address != "", Company.biz_no.is_not(None))


def expand_industry(code: str) -> list[str]:
    """A code, plus every code beneath it."""
    out = [code]
    for top in INDUSTRIES:
        if top["value"] == code:
            out += [c["value"] for c in top.get("children") or []]
            break
    return out


def out(c: Company, *, full: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": str(c.id), "name": c.name, "stock_code": c.stock_code, "market": c.market,
        "industry_text": c.industry_text, "industry_codes": list(c.industry_codes or []),
        "region_code": c.region_code, "region_text": c.region_text,
        "ceo": c.ceo, "homepage": c.homepage, "status": c.status,
        # What people say and do (plan/40) — the numbers a card shows.
        "rating": round(c.rating or 0, 1), "review_count": c.review_count, "follow_count": c.follow_count,
        "open_jobs": c.open_jobs, "tags": list(c.tags or []), "employees": c.employees,
        "listed_on": c.listed_on.isoformat() if c.listed_on else None,
    }
    if full:
        row |= {
            "corp_code": c.corp_code, "biz_no": c.biz_no, "product": c.product,
            "listed_on": c.listed_on.isoformat() if c.listed_on else None,
            "fiscal_month": c.fiscal_month, "address": c.address, "phone": c.phone,
            "founded_on": c.founded_on.isoformat() if c.founded_on else None,
            "employees": c.employees,
            # Which source last wrote, and what a person has corrected since — the two
            # questions anyone looking at a surprising value will ask.
            "sources": dict(c.sources or {}), "locked_fields": list(c.locked_fields or []),
            "hidden": c.hidden,
        }
    return row


#: How a list may be ordered. `name` is the console's (stable, alphabetical); `popular` is
#: the reader's default — what people look at, follow, review and are hired by (plan/40).
SORTS = ("name", "popular", "rating", "reviews", "follows")


async def search(db: AsyncSession, *, q: str = "", market: str = "", region: str = "",
                 industry: str = "", page: int = 1, size: int = 50,
                 include_hidden: bool = True, sort: str = "name") -> dict[str, Any]:
    where = []
    if not include_hidden:
        where.append(Company.hidden.is_(False))
        # The DART dictionary contributes about 115,000 companies of which most are, for a
        # reader, a name and nothing else. A directory has to be worth reading, so readers
        # see companies we can actually say something about; the console still sees every
        # row, because that is where you go to find out why one is empty.
        where.append(substantive())
    if q.strip():
        term = q.strip()
        # By name, by normalised name (so "(주)카카오" finds "카카오"), or by ticker.
        where.append(or_(Company.name.ilike(f"%{term}%"),
                         Company.name_norm.ilike(f"%{normalise_name(term)}%"),
                         Company.stock_code == term.zfill(6) if term.isdigit() else Company.stock_code == term))
    if market:
        where.append(Company.market == market)
    if region:
        where.append(Company.region_code == region)
    if industry:
        # A parent code matches its children: filtering by 제조·화학 must not miss a
        # semiconductor maker filed under `mfg.semi`. The codes are expanded from the
        # taxonomy rather than matched as a prefix, because JSONB containment is exact.
        where.append(or_(*[Company.industry_codes.contains([code]) for code in expand_industry(industry)]))
    stmt = select(Company)
    for w in where:
        stmt = stmt.where(w)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    order = {
        "popular": (Company.popularity.desc(), Company.review_count.desc(), Company.name),
        "rating": ((Company.review_count > 0).desc(), Company.rating.desc(), Company.review_count.desc(), Company.name),
        "reviews": (Company.review_count.desc(), Company.rating.desc(), Company.name),
        "follows": (Company.follow_count.desc(), Company.popularity.desc(), Company.name),
    }.get(sort, (Company.market.desc(), Company.name))
    if q.strip():
        # An exact name beats a longer name that merely contains the words: "카카오" must
        # list 카카오 before 카카오뱅크 whichever is more popular.
        exact = (Company.name_norm == normalise_name(q.strip())).desc()
        order = (exact, *order)
    rows = (await db.execute(
        stmt.order_by(*order).offset((page - 1) * size).limit(size)
    )).scalars().all()
    return {"items": [out(c) for c in rows], "total": int(total), "page": page, "size": size}


async def suggest(db: AsyncSession, q: str, limit: int = 8) -> list[dict[str, Any]]:
    """Name completion. Matches on the normalised name so a poster typing "카카오" is
    offered "(주)카카오" — the point is to link the posting, not to test their spelling."""
    term = (q or "").strip()
    if len(term) < 2:
        return []
    norm = normalise_name(term)
    rows = (await db.execute(
        select(Company).where(Company.hidden.is_(False))
        .where(or_(Company.name.ilike(f"%{term}%"), Company.name_norm.ilike(f"%{norm}%")))
        # Listed companies first: they are the ones a reader is most likely to mean, and
        # the only ones with enough detail to be worth linking.
        .order_by(Company.stock_code.is_(None), Company.name).limit(limit)
    )).scalars().all()
    return [{"id": str(c.id), "name": c.name, "stock_code": c.stock_code,
             "market": c.market, "industry_text": c.industry_text, "region_text": c.region_text}
            for c in rows]


async def match_by_name(db: AsyncSession, name: str) -> Company | None:
    """The company a poster's free text refers to, if it is unambiguous.

    Used when a posting is created without an explicit link. Exact on the normalised name
    only — a fuzzy guess here would attach a posting to the wrong employer, which is worse
    than leaving it unlinked.
    """
    norm = normalise_name(name)
    if not norm:
        return None
    rows = (await db.execute(
        select(Company).where(Company.name_norm == norm, Company.hidden.is_(False)).limit(2)
    )).scalars().all()
    return rows[0] if len(rows) == 1 else None
