"""Proving where you work, with a work mailbox (plan/40 §10).

A code goes to the address; the address's domain says which companies it can be; the
member picks one of those, or proposes one when nobody has mapped the domain yet. The
profile then carries the company from the directory and the date it was proven, reviews
written by that member at that company are marked, and one mailbox can only ever prove
one account.

The address itself is not kept — its hash is, for the one-mailbox rule and for showing
the member which address they used, masked.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from memora.models import Company, CompanyVerification, User
from memora.services import profile as PF
from memora.services.companies import domains as D

CODE_TTL_MIN = 15
SENDS_PER_HOUR = 5
MAX_ATTEMPTS = 5


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def latest(db: AsyncSession, user_id: uuid.UUID, *, statuses: tuple[str, ...] = ("pending", "verified")) -> CompanyVerification | None:
    return (await db.execute(select(CompanyVerification).where(CompanyVerification.user_id == user_id,
                                                                CompanyVerification.status.in_(statuses))
                             .order_by(CompanyVerification.created_at.desc()))).scalars().first()


async def verified(db: AsyncSession, user_id: uuid.UUID) -> CompanyVerification | None:
    return await latest(db, user_id, statuses=("verified",))


async def verified_company_id(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    v = await verified(db, user_id)
    return v.company_id if v is not None else None


async def verified_for(db: AsyncSession, user_id: uuid.UUID, company_id: uuid.UUID) -> bool:
    """Whether this member has proven a mailbox at this company — a mapping the directory
    stands behind, not merely one they proposed."""
    v = await verified(db, user_id)
    if v is None or v.company_id != company_id:
        return False
    m = await D.mapping(db, v.domain, company_id)
    return m is not None and m.status == "confirmed"


async def start(db: AsyncSession, user: User, email: str) -> tuple[CompanyVerification, str, list[Company]]:
    """Issue a code for this address. Returns the row, the code (for the mail), and the
    companies already known at the address's domain."""
    email = (email or "").strip().lower()
    domain = D.email_domain(email)
    if not domain:
        raise ValidationFailed("not an email address", code="invalid_email")
    if D.is_free(domain):
        raise ValidationFailed("a personal mailbox proves nothing about an employer", code="free_mail",
                               detail={"domain": domain})
    since = datetime.now(UTC) - timedelta(hours=1)
    sent = (await db.execute(select(func.count()).select_from(CompanyVerification)
                             .where(CompanyVerification.user_id == user.id, CompanyVerification.created_at >= since))).scalar_one()
    if int(sent or 0) >= SENDS_PER_HOUR:
        raise Forbidden("too many codes in the last hour", code="verify_rate_limited")
    email_hash = _sha(email)
    taken = (await db.execute(select(CompanyVerification.user_id)
                              .where(CompanyVerification.email_hash == email_hash, CompanyVerification.status == "verified"))).first()
    if taken is not None and taken[0] != user.id:
        raise Conflict("this address already proves another account", code="company_email_taken")
    await db.execute(update(CompanyVerification).where(CompanyVerification.user_id == user.id, CompanyVerification.status == "pending")
                     .values(status="expired"))
    code = _code()
    row = CompanyVerification(user_id=user.id, domain=domain, email_masked=D.mask_email(email), email_hash=email_hash,
                              code_hash=_sha(f"{user.id}:{code}"),
                              code_expires_at=datetime.now(UTC) + timedelta(minutes=CODE_TTL_MIN))
    db.add(row)
    await db.flush()
    return row, code, await D.companies_at(db, domain)


async def confirm(db: AsyncSession, user: User, *, code: str | None, company_id: uuid.UUID | None) -> dict[str, Any]:
    """Check the code, then settle which company. Three outcomes short of done: the code
    is wrong (`bad_code`), the domain has several companies and none was picked
    (`need_choice`), or the domain has none (`need_company`)."""
    row = await latest(db, user.id, statuses=("pending",))
    if row is None:
        raise NotFound("no code was sent", code="no_pending_verification")
    if row.code_expires_at < datetime.now(UTC):
        row.status = "expired"
        raise ValidationFailed("the code has expired", code="code_expired")
    if row.code_verified_at is None:
        if not code:
            raise ValidationFailed("code required", code="bad_code")
        row.attempts += 1
        if row.attempts > MAX_ATTEMPTS:
            row.status = "expired"
            raise ValidationFailed("too many tries; ask for a new code", code="too_many_attempts")
        if not hmac.compare_digest(row.code_hash, _sha(f"{user.id}:{code.strip()}")):
            raise ValidationFailed("wrong code", code="bad_code", detail={"attempts_left": MAX_ATTEMPTS - row.attempts})
        row.code_verified_at = datetime.now(UTC)

    known = await D.companies_at(db, row.domain)
    company: Company | None = None
    if company_id is not None:
        company = await db.get(Company, company_id)
        if company is None or company.hidden:
            raise NotFound("company not found", code="company_not_found")
    elif len(known) == 1:
        company = known[0]
    if company is None:
        from memora.services.companies.reviews import cards
        return {"state": "choose" if known else "propose", "domain": row.domain, "email_masked": row.email_masked,
                "candidates": await cards(db, known, user)}

    proposal = company.id not in {c.id for c in known}
    if proposal:
        await D.note_claim(db, company_id=company.id, domain=row.domain)
    await db.execute(update(CompanyVerification)
                     .where(CompanyVerification.user_id == user.id, CompanyVerification.status == "verified")
                     .values(status="replaced"))
    row.status, row.company_id, row.verified_at = "verified", company.id, datetime.now(UTC)
    await PF.update(db, user.id, data={"company": company.name, "company_id": str(company.id),
                                       "company_verified_at": row.verified_at.isoformat(), "company_domain": row.domain}, trusted=True)
    await db.flush()
    return await status(db, user)


async def remove(db: AsyncSession, user: User) -> None:
    await db.execute(update(CompanyVerification)
                     .where(CompanyVerification.user_id == user.id, CompanyVerification.status.in_(("verified", "pending")))
                     .values(status="removed"))
    await PF.update(db, user.id, data={"company_id": None, "company_verified_at": None, "company_domain": None}, trusted=True)


async def status(db: AsyncSession, user: User) -> dict[str, Any]:
    """What the profile card shows: nothing yet, a code on its way, or a proven company."""
    from memora.services.companies.reviews import card

    prof = await PF.get(db, user.id)
    data = prof.data or {}
    out: dict[str, Any] = {"state": "none", "company_text": str(data.get("company") or "")}
    v = await verified(db, user.id)
    if v is not None:
        company = await db.get(Company, v.company_id) if v.company_id else None
        m = await D.mapping(db, v.domain, v.company_id) if v.company_id else None
        out.update({"state": "verified", "domain": v.domain, "email_masked": v.email_masked,
                    "verified_at": v.verified_at.isoformat() if v.verified_at else None,
                    "company": card(company) if company is not None and not company.hidden else None,
                    "mapping": m.status if m is not None else "pending"})
        return out
    p = await latest(db, user.id, statuses=("pending",))
    if p is not None and p.code_expires_at >= datetime.now(UTC):
        from memora.services.companies.reviews import cards
        # The companies known at the domain travel with every pending state, so a dialog
        # reopened mid-way can still say "4곳의 회사가 함께 써요" under the code box.
        known = await D.companies_at(db, p.domain)
        out.update({"state": "code_sent", "domain": p.domain, "email_masked": p.email_masked,
                    "expires_at": p.code_expires_at.isoformat(), "candidates": await cards(db, known, user)})
        if p.code_verified_at is not None:
            out["state"] = "choose" if known else "propose"
    return out
