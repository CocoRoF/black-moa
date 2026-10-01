"""Reading the traffic record.

The dashboard's questions, each answered by one query over ``api_requests``: how much is
being served, how fast, what is failing, what is slow, who is calling, and which calls held
the process. Aggregation happens in Postgres — sending a hundred thousand rows to the
browser to be counted there is how a monitoring page becomes the reason for an outage.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core import traffic as T
from blackmoa.core.logging import get_logger

log = get_logger("blackmoa.traffic.store")

#: Rows older than this are dropped by the retention sweep. Long enough for "what happened
#: last night", short enough that the table stays a working set rather than an archive.
KEEP_DAYS = 7


async def flush(db: AsyncSession, limit: int = 500) -> int:
    """Write buffered rows. Called by the worker/housekeeping, never by a request."""
    rows = T.take_batch(limit)
    if not rows:
        return 0
    now = datetime.now(UTC)
    await db.execute(text("""
        INSERT INTO api_requests (id, at, route, method, lane, status, ms, ttfb_ms, lag_ms, owner_id, agent_id, ip, ua, bytes_out, error)
        VALUES (:id, :at, :route, :method, :lane, :status, :ms, :ttfb_ms, :lag_ms, :owner_id, :agent_id, :ip, :ua, :bytes_out, :error)
    """), [{**r, "at": now, "id": r["id"] if isinstance(r["id"], uuid.UUID) else uuid.uuid4()} for r in rows])
    return len(rows)


async def sweep(db: AsyncSession) -> int:
    r = await db.execute(text("DELETE FROM api_requests WHERE at < now() - make_interval(days => :d)"), {"d": KEEP_DAYS})
    return int(r.rowcount or 0)


def _window(minutes: int) -> dict[str, Any]:
    return {"since": datetime.now(UTC) - timedelta(minutes=minutes)}


async def summary(db: AsyncSession, minutes: int = 60) -> dict[str, Any]:
    """Totals, latency percentiles and error rate for the window, overall and per lane.

    Percentiles are taken over ``ttfb_ms`` — how long the API took to start answering.
    Taking them over total duration lets one notification stream left open all afternoon
    decide the p99, which is how a monitoring page starts lying.
    """
    p = _window(minutes)
    overall = (await db.execute(text("""
        SELECT count(*) AS n,
               coalesce(avg(ms), 0) AS avg_ms,
               coalesce(percentile_disc(0.5) WITHIN GROUP (ORDER BY ttfb_ms), 0) AS p50,
               coalesce(percentile_disc(0.95) WITHIN GROUP (ORDER BY ttfb_ms), 0) AS p95,
               coalesce(percentile_disc(0.99) WITHIN GROUP (ORDER BY ttfb_ms), 0) AS p99,
               coalesce(max(ttfb_ms), 0) AS max_ms,
               coalesce(max(ms), 0) AS longest_ms,
               count(*) FILTER (WHERE status >= 500) AS errors,
               count(*) FILTER (WHERE status = 429) AS throttled,
               count(*) FILTER (WHERE ttfb_ms > 10000) AS slow,
               coalesce(sum(lag_ms), 0) AS lag_ms
        FROM api_requests WHERE at >= :since
    """), p)).mappings().one()
    lanes = (await db.execute(text("""
        SELECT lane, count(*) AS n, coalesce(avg(ttfb_ms), 0) AS avg_ms,
               coalesce(percentile_disc(0.95) WITHIN GROUP (ORDER BY ttfb_ms), 0) AS p95,
               count(*) FILTER (WHERE status >= 500) AS errors,
               coalesce(max(ms), 0) AS max_ms
        FROM api_requests WHERE at >= :since GROUP BY lane ORDER BY n DESC
    """), p)).mappings().all()
    return {"window_minutes": minutes,
            "overall": {k: (float(v) if k not in ("n", "errors", "throttled", "slow") else int(v)) for k, v in overall.items()},
            "lanes": [{"lane": r["lane"], "n": int(r["n"]), "avg_ms": float(r["avg_ms"]), "p95_ms": float(r["p95"]),
                       "errors": int(r["errors"]), "max_ms": float(r["max_ms"])} for r in lanes]}


async def series(db: AsyncSession, minutes: int = 60, buckets: int = 60) -> list[dict[str, Any]]:
    """Requests, latency and errors over time — the shape of the window."""
    width = max(1, minutes // max(1, buckets))
    rows = (await db.execute(text("""
        SELECT to_timestamp(floor(extract(epoch FROM at) / (:w * 60)) * (:w * 60)) AS bucket,
               count(*) AS n, coalesce(avg(ttfb_ms), 0) AS avg_ms,
               coalesce(percentile_disc(0.95) WITHIN GROUP (ORDER BY ttfb_ms), 0) AS p95,
               count(*) FILTER (WHERE status >= 500) AS errors
        FROM api_requests WHERE at >= :since GROUP BY 1 ORDER BY 1
    """), {**_window(minutes), "w": width})).mappings().all()
    return [{"at": r["bucket"].isoformat(), "n": int(r["n"]), "avg_ms": float(r["avg_ms"]),
             "p95_ms": float(r["p95"]), "errors": int(r["errors"])} for r in rows]


async def endpoints(db: AsyncSession, minutes: int = 60, limit: int = 20, order: str = "total_ms") -> list[dict[str, Any]]:
    """Where the service time goes.

    Ordered by total time by default, because the endpoint that costs the most is rarely
    the slowest one — it is the one called ten thousand times.

    Every column is time-to-first-byte, for the same reason the caller list is: totalling
    the whole life of a response puts the notification stream at the top of every ordering
    forever (fifteen open tabs read as eleven minutes of work) and buries the endpoint
    actually spending the machine. How long a request *held* a slot is a different question,
    answered by the live list and the anomaly list.
    """
    col = {"total_ms": "sum(ttfb_ms)", "p95": "percentile_disc(0.95) WITHIN GROUP (ORDER BY ttfb_ms)",
           "calls": "count(*)", "errors": "count(*) FILTER (WHERE status >= 500)"}.get(order, "sum(ttfb_ms)")
    rows = (await db.execute(text(f"""
        SELECT route, method, lane, count(*) AS n, coalesce(avg(ttfb_ms), 0) AS avg_ms,
               coalesce(percentile_disc(0.95) WITHIN GROUP (ORDER BY ttfb_ms), 0) AS p95,
               coalesce(max(ttfb_ms), 0) AS max_ms, coalesce(sum(ttfb_ms), 0) AS total_ms,
               count(*) FILTER (WHERE status >= 500) AS errors,
               count(*) FILTER (WHERE status = 429) AS throttled
        FROM api_requests WHERE at >= :since
        GROUP BY route, method, lane ORDER BY {col} DESC NULLS LAST LIMIT :lim
    """), {**_window(minutes), "lim": limit})).mappings().all()
    return [{"route": r["route"], "method": r["method"], "lane": r["lane"], "n": int(r["n"]),
             "avg_ms": float(r["avg_ms"]), "p95_ms": float(r["p95"]), "max_ms": float(r["max_ms"]),
             "total_ms": float(r["total_ms"]), "errors": int(r["errors"]), "throttled": int(r["throttled"])} for r in rows]


async def anomalies(db: AsyncSession, minutes: int = 180, limit: int = 30) -> list[dict[str, Any]]:
    """Calls worth a person's attention.

    Four different things, so four conditions: slow to answer at all (ttfb), stalled the
    event loop while it ran (lag), failed, or was a conversation that held a slot for over
    two minutes. Duration alone is deliberately not one of them — a notification stream is
    legitimately open for as long as its browser tab, and ranking by duration would bury
    every real finding under those. Severity is stated in milliseconds so the ordering is
    one idea rather than four.
    """
    rows = (await db.execute(text("""
        SELECT at, route, method, lane, status, ms, ttfb_ms, lag_ms, owner_id, ip, error,
               GREATEST(ttfb_ms, lag_ms * 4, CASE WHEN lane = 'chat' THEN ms ELSE 0 END) AS severity
        FROM api_requests
        WHERE at >= :since
          AND (ttfb_ms > 10000 OR lag_ms > 1000 OR status >= 500 OR (lane = 'chat' AND ms > 120000))
        ORDER BY severity DESC LIMIT :lim
    """), {**_window(minutes), "lim": limit})).mappings().all()
    return [{"at": r["at"].isoformat(), "route": r["route"], "method": r["method"], "lane": r["lane"],
             "status": int(r["status"]), "ms": float(r["ms"]), "ttfb_ms": float(r["ttfb_ms"]),
             "lag_ms": float(r["lag_ms"]), "owner_id": str(r["owner_id"]) if r["owner_id"] else None,
             "ip": r["ip"], "error": r["error"]} for r in rows]


async def callers(db: AsyncSession, minutes: int = 60, limit: int = 15) -> list[dict[str, Any]]:
    """Who is calling. An owner or an address at the top of this list with a thousand
    requests is either a runaway client or something worse; either way it has a name — and
    a name is the point, so the account's address is joined in rather than leaving an
    operator to look up a truncated id."""
    rows = (await db.execute(text("""
        SELECT r.owner_id, coalesce(u.email, '') AS email, coalesce(u.display_name, '') AS name,
               r.ip, count(*) AS n,
               -- time actually spent answering them. A stream held open by a browser tab
               -- costs a connection, not service, so ranking by duration would put
               -- whoever leaves a tab open at the top of the list.
               coalesce(sum(r.ttfb_ms), 0) AS total_ms,
               count(*) FILTER (WHERE r.status >= 500) AS errors,
               count(*) FILTER (WHERE r.status = 429) AS throttled
        FROM api_requests r LEFT JOIN users u ON u.id = r.owner_id
        WHERE r.at >= :since GROUP BY r.owner_id, u.email, u.display_name, r.ip
        ORDER BY n DESC LIMIT :lim
    """), {**_window(minutes), "lim": limit})).mappings().all()
    return [{"owner_id": str(r["owner_id"]) if r["owner_id"] else None, "email": r["email"] or None,
             "name": r["name"] or None, "ip": r["ip"], "n": int(r["n"]), "total_ms": float(r["total_ms"]),
             "errors": int(r["errors"]), "throttled": int(r["throttled"])} for r in rows]
