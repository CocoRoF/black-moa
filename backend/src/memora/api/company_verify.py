"""Proving where you work (plan/40 §10): the card on 내 정보."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from memora.core.deps import DB, CurrentUser
from memora.services.companies import switch as CO
from memora.services.companies import verification as V
from memora.services.mailer import send_mail

# 기업 기능이 꺼져 있으면 회사 인증도 없다 (plan/71).
router = APIRouter(prefix="/api/users/me/company", tags=["company-verify"], dependencies=[Depends(CO.gate)])


@router.get("")
async def my_company(user: CurrentUser, db: DB):
    return await V.status(db, user)


class StartIn(BaseModel):
    email: str = Field(max_length=190)


@router.post("/start")
async def start(body: StartIn, user: CurrentUser, db: DB):
    """Send the code now, on this request: the person is watching, and if the mail server
    refuses us they should hear it here rather than wait for a code that is not coming."""
    row, code, known = await V.start(db, user, body.email)
    await db.commit()
    from memora.services.emails import company_verification
    subject, text, html = company_verification(code=code, name=user.nickname or user.display_name or "", minutes=V.CODE_TTL_MIN)
    await send_mail(db, to=body.email.strip().lower(), subject=subject, text=text, html=html)
    from memora.services.companies.reviews import cards
    return {"state": "code_sent", "domain": row.domain, "email_masked": row.email_masked,
            "expires_at": row.code_expires_at.isoformat(), "candidates": await cards(db, known, user)}


class ConfirmIn(BaseModel):
    code: str | None = Field(default=None, max_length=12)
    company_id: uuid.UUID | None = None


@router.post("/confirm")
async def confirm(body: ConfirmIn, user: CurrentUser, db: DB):
    out = await V.confirm(db, user, code=body.code, company_id=body.company_id)
    await db.commit()
    return out


@router.delete("")
async def remove(user: CurrentUser, db: DB):
    await V.remove(db, user)
    await db.commit()
    return {"ok": True}
