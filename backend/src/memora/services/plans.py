from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.models import Plan, User

# A plan says what an account is given and what it may hold — not how hard it may be
# worked. Credits and knowledge are the two things that cost us money; everything else
# a person should be free to arrange (plan/34).
DEFAULT_PLANS = [
    dict(code="free", name="Free", monthly_credits=1000, max_agents=1, max_share_links=2, max_storage_mb=1024,
         features={"web_search": False, "voice": True, "google": True}, is_default=True),
    dict(code="pro", name="Pro", monthly_credits=5000, max_agents=3, max_share_links=10, max_storage_mb=3072,
         features={"web_search": True, "voice": True, "google": True}, is_default=False),
]


async def ensure_default_plans(db: AsyncSession) -> None:
    existing = {p.code for p in (await db.execute(select(Plan))).scalars().all()}
    for p in DEFAULT_PLANS:
        if p["code"] not in existing:
            db.add(Plan(**p))


async def default_plan(db: AsyncSession) -> Plan:
    plan = (await db.execute(select(Plan).where(Plan.is_default.is_(True)))).scalars().first()
    if plan is None:
        await ensure_default_plans(db)
        await db.flush()
        plan = (await db.execute(select(Plan).where(Plan.is_default.is_(True)))).scalars().first()
    return plan


async def plan_for_user(db: AsyncSession, user: User) -> Plan:
    if user.plan_id:
        plan = await db.get(Plan, user.plan_id)
        if plan:
            return plan
    return await default_plan(db)


async def plan_by_id(db: AsyncSession, plan_id: uuid.UUID | None) -> Plan | None:
    return await db.get(Plan, plan_id) if plan_id else None
