"""Publishing and adding up what each process can only see about itself (plan/32 §6).

An allocation that cannot be observed is an allocation nobody knows is holding. Thread
pools, connection lanes and in-flight requests are in-memory, so the console saw only the
process that happened to serve the request — and never the worker, whose pools and lanes
appeared on no screen at all. Each process publishes a snapshot; the console sums them.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.config import get_settings
from blackmoa.core.logging import get_logger
from blackmoa.models import ProcessStat

log = get_logger("blackmoa.procstats")

#: A snapshot older than this is a process that has stopped publishing — shown as stale
#: rather than added in, because summing a dead process's numbers overstates capacity.
FRESH_S = 90


def snapshot(role: str) -> dict[str, Any]:
    """What this process knows that no other process can ask it."""
    from blackmoa.core import pools
    from blackmoa.core import traffic as TF
    from blackmoa.core.database import manager as dbm
    from blackmoa.core.watchdog import loop_lag

    out: dict[str, Any] = {"pools": pools.stats(), "db": dbm.stats(), "loop_lag_s": round(loop_lag(), 3)}
    if role == "api":
        from blackmoa.pipeline.runtime import runtimes

        out["sessions"] = runtimes.count()
        out["in_flight"] = len(TF.in_flight())
        out.update({k: v for k, v in TF.counters().items() if k in ("served", "buffered", "dropped")})
    else:
        from blackmoa.worker.__main__ import CLASS_LIMITS, CONCURRENCY, RESERVED

        out["worker"] = {"concurrency": CONCURRENCY, "class_limits": CLASS_LIMITS, "reserved": RESERVED}
    return out


async def publish(db: AsyncSession, role: str) -> None:
    """Write this process's snapshot. Never allowed to be why anything fails."""
    s = get_settings()
    key = f"{role}:{s.worker_id}"
    try:
        row = {"key": key, "role": role, "at": datetime.now(UTC), "snapshot": snapshot(role)}
        await db.execute(insert(ProcessStat).values(**row).on_conflict_do_update(
            index_elements=["key"], set_={"at": row["at"], "snapshot": row["snapshot"]}))
    except Exception as e:  # noqa: BLE001
        log.warning("could not publish process stats", err=str(e)[:200])


async def fleet(db: AsyncSession) -> dict[str, Any]:
    """Every process's snapshot, and the totals across the ones still publishing."""
    rows = (await db.execute(select(ProcessStat).order_by(ProcessStat.key))).scalars().all()
    now = datetime.now(UTC)
    procs: list[dict[str, Any]] = []
    pools_total: dict[str, dict[str, int]] = {}
    db_total = {"capacity": 0, "checked_out": 0}
    for r in rows:
        age = (now - r.at).total_seconds()
        fresh = age < FRESH_S
        procs.append({"key": r.key, "role": r.role, "age_s": round(age, 1), "fresh": fresh, **(r.snapshot or {})})
        if not fresh:
            continue
        for name, p in (r.snapshot or {}).get("pools", {}).items():
            agg = pools_total.setdefault(name, {"size": 0, "in_flight": 0, "queued": 0})
            for k in agg:
                agg[k] += int(p.get(k) or 0)
        d = (r.snapshot or {}).get("db") or {}
        db_total["capacity"] += int(d.get("capacity") or 0)
        db_total["checked_out"] += int(d.get("checked_out") or 0)
    stale = [p["key"] for p in procs if not p["fresh"]]
    return {"processes": procs, "pools": pools_total, "db": db_total,
            "fresh": sum(1 for p in procs if p["fresh"]), "stale": stale}


async def sweep(db: AsyncSession, keep_hours: int = 24) -> int:
    """Rows for processes that are never coming back (a renamed container, a scaled-down
    replica) should not sit on the screen for ever."""
    from sqlalchemy import delete

    r = await db.execute(delete(ProcessStat).where(ProcessStat.at < datetime.now(UTC) - timedelta(hours=keep_hours)))
    return int(r.rowcount or 0)
