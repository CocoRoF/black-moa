"""Postgres LISTEN/NOTIFY, end to end.

The live notification stream is the only reason this module exists: the pod that files an
inbox item is rarely the pod holding that user's open SSE stream, so the fan-out goes
through the database. That makes it exactly the kind of code that can be broken for months
without a single test noticing — the endpoint still returns 200 and still sends keepalives,
and the badge still moves on the next poll, so nothing looks wrong from outside.

It *was* broken: the listener asked the pool proxy for a `get_raw_connection` it does not
have, failed on every attempt, and reconnected every three seconds forever while leaking
the checkout it had just taken. This test is the smallest thing that would have said so.
"""
from __future__ import annotations

import asyncio
import uuid

from blackmoa.core import bus
from blackmoa.db.session import session_scope


async def test_a_published_event_reaches_a_subscriber_through_postgres(app):
    owner = uuid.uuid4()
    bus.start()   # idempotent; the app's lifespan has usually started it already
    async with bus.subscribe(owner) as q:
        msg = None
        # The listener attaches asynchronously, and pg_notify only fires at commit, so
        # publish until one lands rather than sleeping a guessed amount and hoping.
        for _ in range(50):
            async with session_scope() as db:
                await bus.publish(db, owner_id=owner, kind="inbox", data={"id": str(owner)})
            try:
                msg = await asyncio.wait_for(q.get(), timeout=0.2)
                break
            except TimeoutError:
                continue
    assert msg is not None, "nothing was delivered: the listener never attached"
    assert msg["kind"] == "inbox" and msg["data"]["id"] == str(owner)


async def test_an_event_is_delivered_only_to_its_own_owner(app):
    """Payloads are addressed. A fan-out that reached every open stream would leak one
    account's activity to another's browser."""
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    bus.start()
    async with bus.subscribe(mine) as mine_q, bus.subscribe(theirs) as their_q:
        got = None
        for _ in range(50):
            async with session_scope() as db:
                await bus.publish(db, owner_id=mine, kind="inbox", data={"id": "x"})
            try:
                got = await asyncio.wait_for(mine_q.get(), timeout=0.2)
                break
            except TimeoutError:
                continue
        assert got is not None
        assert their_q.empty(), "another account's stream must not see this"
