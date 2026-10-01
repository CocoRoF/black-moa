from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from blackmoa.core.deps import DB, CurrentUser
from blackmoa.models import CreditLedger, UsageDaily, UsageEvent
from blackmoa.services import credits as CR
from blackmoa.services import jobs as J
from blackmoa.services import plans as P
from blackmoa.services import settings as S

router = APIRouter(prefix="/api", tags=["credits"])


@router.get("/credits/balance")
async def balance(user: CurrentUser, db: DB):
    plan = await P.plan_for_user(db, user)
    total, reserved, available = await CR.balance_state(db, user.id)
    anchor = user.plan_cycle_anchor
    cycle_end = None
    if anchor:
        days = (datetime.now(UTC) - anchor).days
        cycle_end = (anchor + timedelta(days=30 * (days // 30 + 1))).isoformat()
    low = float(available) <= plan.monthly_credits * float(await S.get(db, "credits.low_watermark_ratio"))
    return {"balance": float(total), "reserved": float(reserved), "available": float(available),
            "plan": {"code": plan.code, "name": plan.name, "monthly_credits": plan.monthly_credits, "max_agents": plan.max_agents,
                     "max_share_links": plan.max_share_links, "max_storage_mb": plan.max_storage_mb,
                     "features": plan.features},
            "cycle_ends_at": cycle_end, "low": low, "stripe_enabled": bool(await S.get(db, "stripe.secret_key"))}


@router.get("/credits/ledger")
async def ledger(user: CurrentUser, db: DB, limit: int = 100):
    rows = (await db.execute(select(CreditLedger).where(CreditLedger.owner_id == user.id).order_by(CreditLedger.created_at.desc()).limit(min(limit, 500)))).scalars().all()
    return {"items": [{"id": str(r.id), "delta": float(r.delta), "balance_after": float(r.balance_after), "kind": r.kind, "ref_type": r.ref_type,
                       "ref_id": r.ref_id, "note": r.note, "created_at": r.created_at.isoformat()} for r in rows]}


@router.get("/credits/usage")
async def usage(user: CurrentUser, db: DB, days: int = 30):
    since_day = await CR.usage_day(db, user.id) - timedelta(days=min(days, 365))
    try:
        owner_zone = ZoneInfo(user.timezone or "UTC")
    except ZoneInfoNotFoundError:
        owner_zone = ZoneInfo("UTC")
    since_utc = datetime.combine(since_day, time.min, tzinfo=owner_zone).astimezone(UTC)
    daily = (await db.execute(select(UsageDaily).where(UsageDaily.owner_id == user.id, UsageDaily.day >= since_day).order_by(UsageDaily.day))).scalars().all()
    by_model = (await db.execute(select(UsageEvent.provider, UsageEvent.model_id, func.sum(UsageEvent.credits), func.count())
                                 .where(UsageEvent.owner_id == user.id, UsageEvent.created_at >= since_utc).group_by(UsageEvent.provider, UsageEvent.model_id))).all()
    return {"daily": [{"day": d.day.isoformat(), "credits": float(d.credits), "turns": d.turns, "visitor_turns": d.visitor_turns,
                       "reserved_credits": float(d.reserved_credits or 0)} for d in daily],
            "by_model": [{"provider": p, "model_id": m, "credits": float(c or 0), "count": n} for p, m, c, n in by_model]}


@router.post("/credits/topup-request")
async def topup_request(user: CurrentUser, db: DB):
    await J.enqueue(db, "admin.notify", {"subject": "[black-moa] 크레딧 충전 요청", "text": f"{user.email} ({user.display_name}) 님이 충전을 요청했어요."}, priority=2)
    await db.commit()
    return {"ok": True}


class CheckoutIn(BaseModel):
    package: str


@router.post("/billing/checkout")
async def checkout(body: CheckoutIn, user: CurrentUser, db: DB):
    from blackmoa.services.billing import create_checkout

    return {"url": await create_checkout(db, user, body.package)}


@router.post("/billing/webhook")
async def webhook(request, db: DB):  # type: ignore[no-untyped-def]
    from fastapi import Request

    from blackmoa.services.billing import handle_webhook

    assert isinstance(request, Request)
    body = await request.body()
    await handle_webhook(db, body, request.headers.get("stripe-signature", ""))
    await db.commit()
    return {"ok": True}
