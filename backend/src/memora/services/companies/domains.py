"""Which email domain belongs to which company (plan/40 §10).

Three answers, in order of trust. The exchange lists a homepage for most listed companies,
and a company's mail almost always lives at the same registrable domain as its website —
so `samsung.com` is known before anyone types it. An administrator can add or remove one.
And a member who proved a mailbox at a domain nobody has mapped can say which company it
is; that becomes a claim, confirmed by an administrator or by enough members saying the
same thing.

A domain is always the *registrable* one: `sec.samsung.com` and `www.samsung.com` are both
`samsung.com`, and `mail.abc.co.kr` is `abc.co.kr`, not `co.kr`.
"""
from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.logging import get_logger
from memora.models import Company, CompanyDomain

log = get_logger("memora.companies.domains")

#: Mailboxes anyone can open. A verification from one of these proves nothing about an
#: employer. kakao.com is on the list on purpose: it is a public mail service, and Kakao's
#: own staff write from kakaocorp.com.
FREE_MAIL = frozenset({
    "gmail.com", "googlemail.com", "naver.com", "daum.net", "hanmail.net", "kakao.com", "nate.com",
    "outlook.com", "outlook.kr", "hotmail.com", "hotmail.co.kr", "live.com", "live.co.kr", "msn.com",
    "yahoo.com", "yahoo.co.kr", "ymail.com", "icloud.com", "me.com", "mac.com", "protonmail.com", "proton.me",
    "aol.com", "gmx.com", "gmx.net", "zoho.com", "mail.com", "qq.com", "163.com", "126.com", "yandex.com",
    "tistory.com", "empal.com", "dreamwiz.com", "korea.com", "paran.com", "lycos.co.kr", "chol.com", "hanafos.com",
    "freechal.com", "netian.com", "hitel.net", "unitel.co.kr", "nownuri.net", "duck.com", "fastmail.com", "hey.com",
})

#: Hosting and platform domains a homepage can live on without being the company's own.
PLATFORMS = frozenset({
    "cafe24.com", "imweb.me", "wixsite.com", "wix.com", "modoo.at", "creatorlink.net", "notion.site", "github.io",
    "blogspot.com", "wordpress.com", "weebly.com", "squarespace.com", "godaddysites.com", "sixshop.com",
    "blog.me", "linkedin.com", "facebook.com", "instagram.com", "youtube.com", "kakaocdn.net",
})

#: Second-level suffixes under country codes, so `abc.co.kr` keeps three labels.
SECOND_LEVEL: dict[str, frozenset[str]] = {
    "kr": frozenset({"co", "ne", "or", "re", "pe", "go", "mil", "ac", "hs", "ms", "es", "sc", "kg",
                     "seoul", "busan", "daegu", "incheon", "gwangju", "daejeon", "ulsan", "sejong", "gyeonggi", "gangwon",
                     "chungbuk", "chungnam", "jeonbuk", "jeonnam", "gyeongbuk", "gyeongnam", "jeju"}),
    "jp": frozenset({"co", "ne", "or", "ac", "go", "ad", "ed", "gr", "lg"}),
    "uk": frozenset({"co", "org", "ac", "gov", "ltd", "plc", "me", "net", "sch"}),
    "au": frozenset({"com", "net", "org", "edu", "gov", "asn", "id"}),
    "cn": frozenset({"com", "net", "org", "gov", "edu", "ac"}),
    "tw": frozenset({"com", "net", "org", "edu", "gov", "idv"}),
    "hk": frozenset({"com", "net", "org", "edu", "gov"}),
    "sg": frozenset({"com", "net", "org", "edu", "gov", "per"}),
    "in": frozenset({"co", "net", "org", "firm", "gen", "ind", "ac", "edu", "gov"}),
    "nz": frozenset({"co", "net", "org", "ac", "govt"}),
    "br": frozenset({"com", "net", "org", "gov", "edu"}),
    "mx": frozenset({"com", "net", "org", "gob", "edu"}),
    "vn": frozenset({"com", "net", "org", "edu", "gov"}),
    "id": frozenset({"co", "net", "or", "ac", "go", "web", "my"}),
    "my": frozenset({"com", "net", "org", "edu", "gov"}),
    "th": frozenset({"co", "in", "or", "ac", "go", "net"}),
    "ph": frozenset({"com", "net", "org", "edu", "gov"}),
    "za": frozenset({"co", "net", "org", "ac", "gov", "web"}),
    "il": frozenset({"co", "org", "ac", "gov", "net"}),
    "tr": frozenset({"com", "net", "org", "edu", "gov"}),
}

_EMAIL = re.compile(r"^[^@\s]{1,120}@([^@\s]{1,190})$")
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def registrable(host: str) -> str | None:
    """The part of a host that somebody registered: `sec.samsung.com` → `samsung.com`,
    `mail.abc.co.kr` → `abc.co.kr`. None for anything that is not a name."""
    h = (host or "").strip().lower().rstrip(".")
    if h.startswith("[") or re.fullmatch(r"[\d.]+", h):
        return None
    labels = h.split(".")
    if len(labels) < 2 or not all(_LABEL.match(x) for x in labels):
        return None
    tld = labels[-1]
    if tld in SECOND_LEVEL and len(labels) >= 3 and labels[-2] in SECOND_LEVEL[tld]:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def email_domain(email: str) -> str | None:
    """The registrable domain of an address, or None when it is not an address."""
    m = _EMAIL.match((email or "").strip().lower())
    return registrable(m.group(1)) if m else None


def is_free(domain: str) -> bool:
    return (domain or "").lower() in FREE_MAIL


def homepage_domain(url: str) -> str | None:
    """A company's own domain from the homepage the exchange lists — or None when the
    site sits on a platform or a public host, which says nothing about its mail."""
    u = (url or "").strip()
    if not u:
        return None
    if "://" not in u:
        u = "http://" + u
    try:
        host = (urlparse(u).hostname or "").lower()
    except ValueError:
        return None
    d = registrable(host)
    if not d or d in FREE_MAIL or d in PLATFORMS:
        return None
    return d


def mask_email(email: str) -> str:
    local, _, host = (email or "").strip().lower().partition("@")
    if not local or not host:
        return ""
    return f"{local[0]}{'*' * max(2, min(6, len(local) - 1))}@{host}"


# ── the table ───────────────────────────────────────────────────────
async def sync_from_homepages(db: AsyncSession) -> int:
    """Every listed company's homepage domain, as a confirmed mapping. Idempotent; run by
    the worker's ranking pass so a homepage corrected in the console reaches this table."""
    rows = (await db.execute(select(Company.id, Company.homepage)
                             .where(Company.homepage != "", Company.hidden.is_(False)))).all()
    values = []
    for cid, homepage in rows:
        d = homepage_domain(homepage)
        if d:
            values.append({"id": uuid.uuid4(), "domain": d, "company_id": cid, "source": "homepage", "status": "confirmed"})
    inserted = 0
    for i in range(0, len(values), 500):
        res = await db.execute(pg_insert(CompanyDomain.__table__).values(values[i:i + 500])
                               .on_conflict_do_nothing(constraint="uq_company_domain"))
        inserted += int(res.rowcount or 0)
    if inserted:
        log.info("company domains synced from homepages", inserted=inserted, of=len(values))
    return inserted


async def companies_at(db: AsyncSession, domain: str, *, confirmed_only: bool = True) -> list[Company]:
    """The companies known at this domain, best-known first."""
    stmt = (select(Company).join(CompanyDomain, CompanyDomain.company_id == Company.id)
            .where(CompanyDomain.domain == domain, Company.hidden.is_(False)))
    if confirmed_only:
        stmt = stmt.where(CompanyDomain.status == "confirmed")
    stmt = stmt.order_by(Company.market.desc(), Company.review_count.desc(), Company.name).limit(20)
    return list((await db.execute(stmt)).scalars().all())


async def mapping(db: AsyncSession, domain: str, company_id: uuid.UUID) -> CompanyDomain | None:
    return (await db.execute(select(CompanyDomain).where(CompanyDomain.domain == domain,
                                                         CompanyDomain.company_id == company_id))).scalar_one_or_none()


async def add(db: AsyncSession, *, company_id: uuid.UUID, domain: str, source: str, status: str) -> CompanyDomain:
    """Create the mapping, or upgrade the existing one: a claim that an administrator
    confirms becomes confirmed; a confirmed row is never demoted here."""
    row = await mapping(db, domain, company_id)
    if row is None:
        row = CompanyDomain(domain=domain, company_id=company_id, source=source, status=status)
        db.add(row)
        await db.flush()
        return row
    if status == "confirmed" and row.status != "confirmed":
        row.status, row.source = "confirmed", source
    return row


#: How many verified members must say "this domain is this company" before it counts
#: without an administrator.
CLAIMS_TO_CONFIRM = 3


async def note_claim(db: AsyncSession, *, company_id: uuid.UUID, domain: str) -> CompanyDomain:
    """A verified member says the domain belongs to this company. Enough of them agreeing
    confirms it; one alone is a proposal an administrator will see."""
    row = await add(db, company_id=company_id, domain=domain, source="claim", status="pending")
    if row.status == "pending":
        await db.execute(update(CompanyDomain).where(CompanyDomain.id == row.id).values(claims=CompanyDomain.claims + 1))
        await db.refresh(row)
        if row.claims >= CLAIMS_TO_CONFIRM:
            row.status = "confirmed"
    return row


async def remove(db: AsyncSession, domain_id: uuid.UUID) -> None:
    row = await db.get(CompanyDomain, domain_id)
    if row is not None:
        await db.delete(row)


async def for_company(db: AsyncSession, company_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (await db.execute(select(CompanyDomain).where(CompanyDomain.company_id == company_id)
                             .order_by(CompanyDomain.status, CompanyDomain.domain))).scalars().all()
    return [out(r) for r in rows]


async def pending_claims(db: AsyncSession, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = (await db.execute(select(CompanyDomain, Company).join(Company, Company.id == CompanyDomain.company_id)
                             .where(CompanyDomain.status == "pending")
                             .order_by(CompanyDomain.claims.desc(), CompanyDomain.created_at.asc()).limit(limit))).all()
    return [{**out(d), "company_name": c.name, "market": c.market, "industry_text": c.industry_text} for d, c in rows]


async def decide(db: AsyncSession, domain_id: uuid.UUID, *, approve: bool) -> None:
    row = await db.get(CompanyDomain, domain_id)
    if row is None:
        return
    if approve:
        row.status, row.source = "confirmed", "admin"
    else:
        await db.delete(row)


async def confirmed_count(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(CompanyDomain)
                                 .where(CompanyDomain.status == "confirmed"))).scalar_one() or 0)


def out(r: CompanyDomain) -> dict[str, Any]:
    return {"id": str(r.id), "domain": r.domain, "company_id": str(r.company_id), "source": r.source,
            "status": r.status, "claims": r.claims, "created_at": r.created_at.isoformat() if r.created_at else None}
