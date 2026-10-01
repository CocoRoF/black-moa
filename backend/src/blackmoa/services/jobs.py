"""PG-backed job queue (SKIP LOCKED). Producers call ``enqueue``; the worker polls."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.models import Job

_ACTIVE_DEDUPE_PREDICATE = "dedupe_key IS NOT NULL AND status IN ('queued', 'running')"


#: How far into the queue the fair ranking looks. Bounded so the claim costs the same
#: whether ten jobs are waiting or ten thousand.
HEAD = 500

#: How far back "recently served" looks. Long enough that a burst is spread out, short
#: enough that an owner who stopped hours ago is not still paying for it.
FAIR_WINDOW_MIN = 60


async def enqueue(
    db: AsyncSession,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    delay_s: float = 0,
    priority: int = 5,
    dedupe_key: str | None = None,
    max_attempts: int = 5,
    owner_id: uuid.UUID | str | None = None,
) -> Job | None:
    payload = payload or {}
    # Most payloads already say whose work this is; the ones that identify a document or a
    # turn instead pass it explicitly. Without an owner the job joins the service's own
    # share of the queue rather than silently jumping the round-robin.
    owner = owner_id if owner_id is not None else payload.get("owner_id")
    values = {
        "kind": kind,
        "owner_id": uuid.UUID(str(owner)) if owner else None,
        "payload": payload,
        "run_at": datetime.now(UTC) + timedelta(seconds=delay_s),
        "priority": priority,
        "dedupe_key": dedupe_key,
        "max_attempts": max_attempts,
        "created_at": datetime.now(UTC),
    }
    if dedupe_key:
        # The partial unique index is the authority. This remains correct when
        # multiple API/worker/scheduler processes enqueue the same key at once;
        # no application-level read-before-insert race remains.
        stmt = (
            pg_insert(Job)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[Job.dedupe_key],
                index_where=text(_ACTIVE_DEDUPE_PREDICATE),
            )
            .returning(Job.id)
        )
        row = (await db.execute(stmt)).first()
        if row is None:
            return None
        return await db.get(Job, row[0])

    job = Job(**values)
    db.add(job)
    return job


async def claim(db: AsyncSession, worker_id: str, kinds: list[str] | None = None,
                exclude: list[str] | None = None, exclude_prefixes: list[str] | None = None) -> Job | None:
    """Take the next job this worker is allowed to run.

    Two fairnesses, and they are different: ``exclude`` stops one *kind* taking every slot,
    while the round-robin below stops one *owner* taking every turn.

    ``exclude`` is how one slow kind stops being able to take the whole queue: the caller
    passes the kinds it already has as many of as it will run, and the claim skips them.
    Without it, forty-six distillations — each holding an external CLI that can stop
    answering — occupied every slot and nothing else ran for twenty minutes: no indexing,
    no notifications, no credit sweeps.
    """
    kind_clause = "AND kind = ANY(:kinds)" if kinds else ""
    skip_clause = "AND NOT (kind = ANY(:exclude))" if exclude else ""
    # A class can be named before its handlers exist — the places-map crawlers are
    # ``crawl.*`` — so a ceiling has to be expressible as a prefix, not just a list.
    prefix_clause = "AND NOT (kind LIKE ANY(:exclude_prefixes))" if exclude_prefixes else ""
    # Round-robin across owners, not first-come.
    #
    # The owner served longest ago goes next. Ranking each owner's waiting jobs instead —
    # everybody's first before anybody's second — looks like round-robin and is not: the
    # ranks are recomputed over what is still queued, so the owner with five hundred jobs
    # always has another rank-one job, and it is always older than anyone else's. They win
    # every round and the person behind them still waits for the whole import.
    #
    # Who went last is already recorded, in `locked_at` on the jobs themselves, so no state
    # has to be kept anywhere: an owner just served has a recent one, an owner who has been
    # waiting has none, and none sorts first.
    #
    # `AND status='queued'` is what makes this safe without FOR UPDATE (which PostgreSQL
    # will not allow beside a window function or an outer join like this): two workers that
    # pick the same job both try to take it, exactly one updates a row, and the loser claims
    # nothing and asks again.
    sql = text(f"""
        WITH head AS (
            SELECT id, owner_id, priority, run_at FROM jobs
            WHERE status='queued' AND run_at <= now() {kind_clause} {skip_clause} {prefix_clause}
            ORDER BY priority ASC, run_at ASC LIMIT :head
        ),
        served AS (
            SELECT owner_id, max(locked_at) AS at FROM jobs
            WHERE locked_at > now() - make_interval(mins => :window_min)
            GROUP BY owner_id
        )
        UPDATE jobs SET status='running', locked_by=:w, locked_at=now(), attempts=attempts+1
        WHERE id = (
            SELECT h.id FROM head h
            LEFT JOIN served s ON s.owner_id IS NOT DISTINCT FROM h.owner_id
            ORDER BY coalesce(s.at, to_timestamp(0)) ASC, h.priority ASC, h.run_at ASC
            LIMIT 1
        ) AND status='queued'
        RETURNING id
    """)
    params: dict[str, Any] = {"w": worker_id, "head": HEAD, "window_min": FAIR_WINDOW_MIN}
    if kinds:
        params["kinds"] = kinds
    if exclude:
        params["exclude"] = exclude
    if exclude_prefixes:
        params["exclude_prefixes"] = [f"{p}%" for p in exclude_prefixes]
    row = (await db.execute(sql, params)).first()
    if not row:
        return None
    return await db.get(Job, row[0])


async def last_enqueued_at(db: AsyncSession, kind: str) -> datetime | None:
    """When a job of this kind was last created, whatever became of it. The scheduler
    seeds its clocks from this so a restart does not fire every interval at once."""
    return (await db.execute(text("SELECT max(created_at) FROM jobs WHERE kind = :k"), {"k": kind})).scalar_one_or_none()


async def requeue_stale(db: AsyncSession, *, minutes: int = 20) -> int:
    """Jobs left in 'running' by a crashed worker go back to the queue (they count as an attempt)."""
    r = await db.execute(text("""
        UPDATE jobs SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END,
            locked_by = NULL, locked_at = NULL, last_error = coalesce(last_error, 'requeued: worker lost'),
            finished_at = CASE WHEN attempts >= max_attempts THEN now() ELSE finished_at END
        WHERE status = 'running' AND locked_at < now() - make_interval(mins => :m)
    """), {"m": minutes})
    return int(r.rowcount or 0)


async def finish(db: AsyncSession, job: Job, *, result: dict | None = None) -> None:
    job.status = "done"
    job.finished_at = datetime.now(UTC)
    job.result = result


async def fail(db: AsyncSession, job: Job, error: str) -> None:
    job.last_error = error[:4000]
    if job.attempts >= job.max_attempts:
        job.status = "dead"
        job.finished_at = datetime.now(UTC)
    else:
        job.status = "queued"
        job.run_at = datetime.now(UTC) + timedelta(seconds=min(600, 5 * (2 ** job.attempts)))
    job.locked_by = None
    job.locked_at = None
