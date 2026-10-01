"""Credit ledger, atomic per-turn reservations and usage accounting."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.errors import PaymentRequired, RateLimited
from blackmoa.models import (
    CreditBalance,
    CreditLedger,
    CreditReservation,
    ModelCatalog,
    UsageDaily,
    UsageEvent,
    User,
)

Q4 = Decimal("0.0001")
MIN_TURN_HOLD = Decimal("0.1000")


def q(x) -> Decimal:
    return Decimal(str(x or 0)).quantize(Q4, rounding=ROUND_HALF_UP)


async def usage_day(db: AsyncSession, owner_id: uuid.UUID, *, now: datetime | None = None) -> date:
    """Return the accounting day in the owner's configured IANA timezone."""
    timezone = await db.scalar(select(User.timezone).where(User.id == owner_id))
    try:
        zone = ZoneInfo(timezone or "UTC")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(zone).date()


async def balance(db: AsyncSession, owner_id: uuid.UUID) -> Decimal:
    row = await db.get(CreditBalance, owner_id)
    return q(row.balance) if row else Decimal("0")


async def balance_state(db: AsyncSession, owner_id: uuid.UUID) -> tuple[Decimal, Decimal, Decimal]:
    row = await db.get(CreditBalance, owner_id)
    if row is None:
        return Decimal("0"), Decimal("0"), Decimal("0")
    total = q(row.balance)
    reserved = max(Decimal("0"), q(row.reserved))
    return total, reserved, max(Decimal("0"), q(total - reserved))


async def available_balance(db: AsyncSession, owner_id: uuid.UUID) -> Decimal:
    return (await balance_state(db, owner_id))[2]


async def _lock_balance(db: AsyncSession, owner_id: uuid.UUID) -> CreditBalance:
    row = (await db.execute(select(CreditBalance).where(CreditBalance.owner_id == owner_id).with_for_update())).scalars().first()
    if row is None:
        row = CreditBalance(owner_id=owner_id, balance=Decimal("0"), reserved=Decimal("0"), updated_at=datetime.now(UTC))
        db.add(row)
        await db.flush()
        row = (await db.execute(select(CreditBalance).where(CreditBalance.owner_id == owner_id).with_for_update())).scalars().first()
    return row


async def _lock_day(db: AsyncSession, owner_id: uuid.UUID, day: date) -> UsageDaily:
    row = (await db.execute(select(UsageDaily).where(UsageDaily.owner_id == owner_id, UsageDaily.day == day).with_for_update())).scalars().first()
    if row is None:
        row = UsageDaily(owner_id=owner_id, day=day, credits=0, turns=0, visitor_turns=0,
                         reserved_credits=0, reserved_turns=0, reserved_visitor_turns=0)
        db.add(row)
        await db.flush()
    return row


async def apply(db: AsyncSession, owner_id: uuid.UUID, delta, kind: str, *, ref_type: str | None = None,
                ref_id: str | None = None, note: str | None = None, created_by: uuid.UUID | None = None,
                allow_reserved: bool = False) -> Decimal:
    """Apply a ledger delta without stealing credits already held by active turns.

    ``allow_reserved=True`` is for debits that record work that already happened
    (STT/TTS/embedding/summary usage, monthly rollover expiry). Those must never
    be refused: the cost is already incurred and the ledger has to stay equal to
    the usage it accounts for. Discretionary debits (admin adjustments) keep the
    guard so they cannot spend an in-flight turn's hold.
    """
    d = q(delta)
    row = await _lock_balance(db, owner_id)
    current = q(row.balance)
    reserved = max(Decimal("0"), q(row.reserved))
    new_balance = q(current + d)
    if d < 0 and new_balance < reserved and not allow_reserved:
        raise PaymentRequired("credits are reserved by active turns", code="credits_reserved",
                              detail={"balance": float(current), "reserved": float(reserved), "requested": float(-d)})
    row.balance = new_balance
    row.updated_at = datetime.now(UTC)
    db.add(CreditLedger(owner_id=owner_id, delta=d, balance_after=new_balance, kind=kind, ref_type=ref_type,
                        ref_id=ref_id, note=note, created_by=created_by, created_at=datetime.now(UTC)))
    return new_balance


def llm_credits(cat: ModelCatalog | None, input_tokens: int, output_tokens: int, cache_read: int = 0,
                cache_write: int = 0) -> Decimal:
    if cat is None:
        return Decimal("0")
    c = (Decimal(input_tokens + cache_write) / 1000 * Decimal(str(cat.credit_per_1k_input))
         + Decimal(output_tokens) / 1000 * Decimal(str(cat.credit_per_1k_output))
         + Decimal(cache_read) / 1000 * Decimal(str(cat.credit_per_1k_cache_read)))
    if (input_tokens + output_tokens) > 0 and c < Decimal("0.1"):
        c = Decimal("0.1")
    return q(c)


async def precheck(db: AsyncSession, owner_id: uuid.UUID, *, daily_cap: int | None = None) -> Decimal:
    """Advisory check for non-turn callers. Turns use ``reserve_turn`` atomically."""
    _, _, available = await balance_state(db, owner_id)
    if available <= 0:
        raise PaymentRequired("credits exhausted", detail={"balance": float(available)})
    if daily_cap:
        today = (await db.execute(select(UsageDaily).where(UsageDaily.owner_id == owner_id,
                                                           UsageDaily.day == await usage_day(db, owner_id)))).scalars().first()
        used = q(today.credits) + q(today.reserved_credits) if today else Decimal("0")
        if used >= q(daily_cap):
            raise PaymentRequired("daily credit cap reached", code="daily_cap_reached",
                                  detail={"cap": daily_cap, "used": float(used)})
    return available


async def day_start(db: AsyncSession, owner_id: uuid.UUID, *, now: datetime | None = None) -> datetime:
    """Midnight of the owner's accounting day, as an instant — the boundary a per-agent
    daily cap is measured from, so "today" means the same thing it does everywhere else."""
    timezone = await db.scalar(select(User.timezone).where(User.id == owner_id))
    try:
        zone = ZoneInfo(timezone or "UTC")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    instant = (now or datetime.now(UTC)).astimezone(zone)
    return instant.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


async def agent_spend(db: AsyncSession, agent_id: uuid.UUID, since: datetime) -> Decimal:
    """What one secretary has spent since an instant, from the usage ledger.

    Advisory, unlike the balance: a secretary's own caps are its owner's guard rails, and
    the account can never be overspent because the balance reservation below is what
    actually holds money. Two turns racing at the very edge of a cap is a rounding error,
    not an overdraft.
    """
    total = await db.scalar(select(func.coalesce(func.sum(UsageEvent.credits), 0)).where(
        UsageEvent.agent_id == agent_id, UsageEvent.created_at >= since))
    return q(total or 0)


async def reserve_turn(db: AsyncSession, *, owner_id: uuid.UUID, turn_id: uuid.UUID, turn_cap,
                       daily_cap: int | None, audience: str, visitor_turn_cap: int | None = None,
                       agent_id: uuid.UUID | None = None, monthly_cap: int | None = None) -> CreditReservation:
    """Atomically hold the maximum amount a turn may spend.

    Lock order is always CreditBalance -> UsageDaily -> CreditReservation. The
    balance row serializes all spending/reservations for one owner, so concurrent
    requests cannot overcommit the account or daily/visitor quotas.
    """
    existing = await db.get(CreditReservation, turn_id)
    if existing is not None:
        return existing
    bal = await _lock_balance(db, owner_id)
    today = await usage_day(db, owner_id)
    day = await _lock_day(db, owner_id, today)
    available = max(Decimal("0"), q(bal.balance) - q(bal.reserved))
    if available < MIN_TURN_HOLD:
        raise PaymentRequired("credits exhausted", detail={"balance": float(available)})

    cap = max(Decimal("0"), q(turn_cap))
    if cap < MIN_TURN_HOLD:
        raise PaymentRequired("turn credit cap is too small", code="turn_cap_too_small")
    hold = min(cap, available)
    # The caps below belong to the secretary, not to the account (plan/34), so they are
    # measured from what this agent has spent rather than from the owner's day row.
    if agent_id is not None and daily_cap:
        used = await agent_spend(db, agent_id, await day_start(db, owner_id))
        remaining = max(Decimal("0"), q(daily_cap) - used)
        if remaining < MIN_TURN_HOLD:
            raise PaymentRequired("daily credit cap reached", code="daily_cap_reached",
                                  detail={"cap": daily_cap, "used": float(used)})
        hold = min(hold, remaining)
    if agent_id is not None and monthly_cap:
        used = await agent_spend(db, agent_id, datetime.now(UTC) - timedelta(days=30))
        remaining = max(Decimal("0"), q(monthly_cap) - used)
        if remaining < MIN_TURN_HOLD:
            raise PaymentRequired("monthly credit cap reached", code="monthly_cap_reached",
                                  detail={"cap": monthly_cap, "used": float(used)})
        hold = min(hold, remaining)
    if audience == "visitor" and visitor_turn_cap is not None:
        consumed = int(day.visitor_turns or 0) + int(day.reserved_visitor_turns or 0)
        if consumed >= int(visitor_turn_cap):
            raise RateLimited("visitor turn cap", code="visitor_daily_cap")
    if hold < MIN_TURN_HOLD:
        raise PaymentRequired("credits exhausted", detail={"balance": float(available)})

    bal.reserved = q(bal.reserved) + hold
    bal.updated_at = datetime.now(UTC)
    day.reserved_credits = q(day.reserved_credits) + hold
    day.reserved_turns = int(day.reserved_turns or 0) + 1
    if audience == "visitor":
        day.reserved_visitor_turns = int(day.reserved_visitor_turns or 0) + 1
    res = CreditReservation(turn_id=turn_id, owner_id=owner_id, amount=hold, actual_credits=0, charged_credits=0,
                            day=today, audience=audience, status="held", created_at=datetime.now(UTC))
    db.add(res)
    await db.flush()
    return res


def _release_counters(bal: CreditBalance, day: UsageDaily, res: CreditReservation) -> None:
    amount = q(res.amount)
    bal.reserved = max(Decimal("0"), q(bal.reserved) - amount)
    bal.updated_at = datetime.now(UTC)
    day.reserved_credits = max(Decimal("0"), q(day.reserved_credits) - amount)
    day.reserved_turns = max(0, int(day.reserved_turns or 0) - 1)
    if res.audience == "visitor":
        day.reserved_visitor_turns = max(0, int(day.reserved_visitor_turns or 0) - 1)


async def release_turn(db: AsyncSession, turn_id: uuid.UUID) -> Decimal:
    """Release an unused hold. Idempotent."""
    res0 = await db.get(CreditReservation, turn_id)
    if res0 is None:
        return Decimal("0")
    bal = await _lock_balance(db, res0.owner_id)
    res = (await db.execute(select(CreditReservation).where(CreditReservation.turn_id == turn_id).with_for_update())).scalars().first()
    if res is None:
        return max(Decimal("0"), q(bal.balance) - q(bal.reserved))
    if res.status != "held":
        return max(Decimal("0"), q(bal.balance) - q(bal.reserved))
    day = await _lock_day(db, res.owner_id, res.day)
    _release_counters(bal, day, res)
    res.status = "released"
    res.settled_at = datetime.now(UTC)
    return max(Decimal("0"), q(bal.balance) - q(bal.reserved))


async def settle_turn(db: AsyncSession, *, owner_id: uuid.UUID, agent_id: uuid.UUID, turn_id: uuid.UUID,
                      provider: str, model_id: str, input_tokens: int, output_tokens: int, cache_read: int,
                      cache_write: int, cost_usd: float, credits, audience: str) -> tuple[Decimal, Decimal]:
    """Settle actual LLM usage against its hold, never exceeding the reservation.

    Returns ``(available_balance_after, charged_credits)``.

    Overage policy (plan/15 §4 vs plan/19 turn lifecycle): when the provider
    reports more than the hold, the excess is **not** charged. ``charged`` is
    capped at the hold, and the full provider figure is preserved on
    ``CreditReservation.actual_credits`` so the gap stays auditable (the runner
    also logs it at ERROR). The same capped number is written to both the
    ``usage_events`` row and the ``credit_ledger`` row, so
    ``sum(usage_events.credits) == -sum(credit_ledger.delta)`` always holds and
    the balance can never be driven negative by one runaway turn.
    """
    existing = (await db.execute(select(CreditLedger).where(CreditLedger.kind == "turn", CreditLedger.ref_type == "turn",
                                                              CreditLedger.ref_id == str(turn_id)))).scalars().first()
    if existing:
        _, _, available = await balance_state(db, owner_id)
        return available, q(-existing.delta)

    res0 = await db.get(CreditReservation, turn_id)
    if res0 is None:
        # Compatibility for administrative/tests/legacy callers. New turn paths
        # always create a reservation before the provider is invoked.
        res0 = await reserve_turn(db, owner_id=owner_id, turn_id=turn_id, turn_cap=max(MIN_TURN_HOLD, q(credits)),
                                  daily_cap=None, audience=audience, visitor_turn_cap=None)
    bal = await _lock_balance(db, owner_id)
    res = (await db.execute(select(CreditReservation).where(CreditReservation.turn_id == turn_id).with_for_update())).scalars().first()
    if res is None:
        raise RuntimeError("credit reservation disappeared")
    if res.status != "held":
        _, _, available = await balance_state(db, owner_id)
        return available, q(res.charged_credits)
    day = await _lock_day(db, owner_id, res.day)
    actual = max(Decimal("0"), q(credits))
    charged = min(actual, q(res.amount))
    _release_counters(bal, day, res)
    new_balance = q(bal.balance) - charged
    if new_balance < 0:  # invariant guard; reservation should make this impossible
        charged = max(Decimal("0"), q(bal.balance))
        new_balance = q(bal.balance) - charged
    bal.balance = new_balance
    bal.updated_at = datetime.now(UTC)
    res.actual_credits = actual
    res.charged_credits = charged
    res.status = "settled"
    res.settled_at = datetime.now(UTC)

    if charged > 0:
        db.add(UsageEvent(owner_id=owner_id, agent_id=agent_id, turn_id=turn_id, kind="llm", provider=provider,
                          model_id=model_id, input_tokens=input_tokens, output_tokens=output_tokens,
                          cache_read_tokens=cache_read, cost_usd=cost_usd, credits=charged, created_at=datetime.now(UTC)))
        db.add(CreditLedger(owner_id=owner_id, delta=-charged, balance_after=new_balance, kind="turn", ref_type="turn",
                            ref_id=str(turn_id), created_at=datetime.now(UTC)))
    day.credits = q(day.credits) + charged
    day.turns = int(day.turns or 0) + 1
    if audience == "visitor":
        day.visitor_turns = int(day.visitor_turns or 0) + 1
    return max(Decimal("0"), new_balance - q(bal.reserved)), charged


async def charge_turn(db: AsyncSession, *, owner_id: uuid.UUID, agent_id: uuid.UUID, turn_id: uuid.UUID,
                      provider: str, model_id: str, input_tokens: int, output_tokens: int, cache_read: int,
                      cache_write: int, cost_usd: float, credits, audience: str) -> Decimal:
    """Backward-compatible direct settlement; normal turn execution uses reserve+settle."""
    available, _ = await settle_turn(db, owner_id=owner_id, agent_id=agent_id, turn_id=turn_id, provider=provider,
                                     model_id=model_id, input_tokens=input_tokens, output_tokens=output_tokens,
                                     cache_read=cache_read, cache_write=cache_write, cost_usd=cost_usd,
                                     credits=credits, audience=audience)
    return available


async def recover_orphaned_turns(db: AsyncSession) -> int:
    """Release holds left by an API process crash and mark orphaned turns failed."""
    from blackmoa.models import Turn

    rows = (await db.execute(select(Turn).where(Turn.status.in_(("pending", "running"))).with_for_update())).scalars().all()
    now = datetime.now(UTC)
    for turn in rows:
        turn.status = "failed"
        turn.error_code = "server_restarted"
        turn.error_message = "turn interrupted by server restart"
        turn.ended_at = now
        await release_turn(db, turn.id)

    # Also heal a hold whose turn row was deleted/corrupted or had already moved
    # to a terminal state before a previous process died.
    held = (await db.execute(select(CreditReservation.turn_id).where(CreditReservation.status == "held"))).scalars().all()
    for turn_id in held:
        turn = await db.get(Turn, turn_id)
        if turn is None or turn.status not in ("pending", "running"):
            await release_turn(db, turn_id)
    return len(rows)


def ledger_kind_for_usage(usage_kind: str) -> str:
    return "turn" if usage_kind in ("llm", "turn") else "usage"


async def charge_usage(db: AsyncSession, *, owner_id: uuid.UUID, kind: str, credits, provider: str = "",
                       model_id: str = "", units: float = 0, agent_id: uuid.UUID | None = None,
                       note: str | None = None) -> Decimal:
    c = q(credits)
    if c <= 0:
        return await available_balance(db, owner_id)
    ev = UsageEvent(owner_id=owner_id, agent_id=agent_id, kind=kind, provider=provider, model_id=model_id,
                    units=units, credits=c, created_at=datetime.now(UTC))
    db.add(ev)
    await db.flush()
    await apply(db, owner_id, -c, ledger_kind_for_usage(kind), ref_type="usage", ref_id=str(ev.id), note=note or kind,
                allow_reserved=True)
    return await available_balance(db, owner_id)


async def record_house_usage(db: AsyncSession, *, owner_id: uuid.UUID, kind: str, provider: str, model_id: str,
                             usage: dict | None, catalog: ModelCatalog | None = None, agent_id: uuid.UUID | None = None,
                             note: str | None = None) -> UsageEvent | None:
    """집이 낸 일을 기록만 한다 (plan/54 §1).

    트리거처럼 **사용자가 부르지 않은 일**은 그 사람의 원장에서 나가면 안 된다. 그렇다고
    기록에서 지우면 운영자는 이 기능이 얼마를 쓰는지 영영 모른다. 그래서 토큰과 달러는
    그대로 적고 크레딧만 0으로 둔다 — 사용자의 화면에서 0은 정확히 "내 것이 나가지
    않았다" 는 뜻이다.
    """
    u = usage or {}
    ins, outs = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
    if not (ins or outs):
        return None
    _ = note
    # 값은 `units` 에 적는다: 크레딧으로 쟀다면 얼마였을까. `credits` 는 0 이어야 하고
    # (사용자가 낸 것이 없다), 그 둘이 한 행에 나란히 있어야 "집이 이만큼 냈다" 가 된다.
    worth = llm_credits(catalog, ins, outs) if catalog is not None else Decimal(0)
    ev = UsageEvent(owner_id=owner_id, agent_id=agent_id, kind=kind[:24], provider=provider[:32], model_id=model_id[:128],
                    input_tokens=ins, output_tokens=outs, units=worth, cost_usd=0, credits=0,
                    created_at=datetime.now(UTC))
    db.add(ev)
    await db.flush()
    return ev


RESERVATION_TTL_MINUTES = 120


async def expire_stale_reservations(db: AsyncSession, *, minutes: int = RESERVATION_TTL_MINUTES,
                                    limit: int = 500) -> int:
    """Release holds no live turn can still settle.

    A hard-killed API process (OOM, ``docker kill``) leaves ``held`` rows behind
    and permanently shrinks the owner's available balance until the next
    restart. The startup sweep only helps if the process actually comes back, so
    the worker runs this periodically as well. Bounded per pass and idempotent.
    """
    from blackmoa.models import Turn

    cutoff = datetime.now(UTC) - timedelta(minutes=max(1, minutes))
    turn_ids = (await db.execute(
        select(CreditReservation.turn_id)
        .where(CreditReservation.status == "held", CreditReservation.created_at < cutoff)
        .order_by(CreditReservation.created_at)
        .limit(max(1, limit))
    )).scalars().all()
    released = 0
    for turn_id in turn_ids:
        res = await db.get(CreditReservation, turn_id)
        if res is None or res.status != "held":
            continue
        turn = await db.get(Turn, turn_id)
        if turn is not None and turn.status in ("pending", "running"):
            turn.status = "failed"
            turn.error_code = "turn_abandoned"
            turn.error_message = "turn exceeded the maximum credit reservation lifetime"
            turn.ended_at = datetime.now(UTC)
        await release_turn(db, turn_id)
        released += 1
    return released


async def sweep_reservations(db: AsyncSession, *, days: int = 30) -> int:
    """Remove terminal reservation audit rows after their operational value expires."""
    r = await db.execute(text("""
        DELETE FROM credit_reservations
        WHERE status IN ('settled','released') AND settled_at < now() - make_interval(days => :d)
    """), {"d": days})
    return int(r.rowcount or 0)
