from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from memora.db.session import session_scope
from memora.models import Job
from memora.services import jobs as J


@pytest.mark.asyncio
async def test_active_job_dedupe_is_database_atomic(app):
    key = f"test-dedupe:{uuid.uuid4()}"

    async def enqueue_once() -> bool:
        async with session_scope() as db:
            job = await J.enqueue(db, "test.atomic", {"value": 1}, dedupe_key=key)
            return job is not None

    # Separate transactions intentionally race the same partial unique index.
    created = await asyncio.gather(*(enqueue_once() for _ in range(8)))
    assert sum(created) == 1

    async with session_scope() as db:
        active = await db.scalar(
            select(func.count()).select_from(Job).where(
                Job.dedupe_key == key,
                Job.status.in_(("queued", "running")),
            )
        )
        assert active == 1

        job = (
            await db.execute(select(Job).where(Job.dedupe_key == key, Job.status.in_(("queued", "running"))))
        ).scalars().one()
        await J.finish(db, job)

    # Finished jobs leave the partial unique index, so a later schedule period
    # may enqueue the same logical key again.
    async with session_scope() as db:
        assert await J.enqueue(db, "test.atomic", {"value": 2}, dedupe_key=key) is not None


async def test_one_slow_kind_cannot_take_the_whole_queue(client):
    """A per-kind ceiling in the claimer (plan/39).

    Forty-six distillations, each holding an external CLI that can stop answering, took
    every worker slot for twenty minutes: no indexing, no notifications, no credit sweeps.
    The claim now skips the kinds a worker already has its fill of.
    """
    from memora.db.session import session_scope
    from memora.services import jobs as J

    async with session_scope() as db:
        for _ in range(3):
            await J.enqueue(db, "memory.distill", {"turn_id": "x"})
        await J.enqueue(db, "knowledge.index", {"document_id": "y"})

    async with session_scope() as db:
        first = await J.claim(db, "w-test")
        assert first is not None

    # with that kind at its ceiling, the claim reaches past it
    async with session_scope() as db:
        nxt = await J.claim(db, "w-test", exclude=["memory.distill"])
        assert nxt is not None and nxt.kind != "memory.distill", "the queue is still blocked behind one kind"

    async with session_scope() as db:
        from sqlalchemy import text
        await db.execute(text("UPDATE jobs SET status='dead' WHERE kind IN ('memory.distill','knowledge.index') AND status IN ('queued','running')"))
