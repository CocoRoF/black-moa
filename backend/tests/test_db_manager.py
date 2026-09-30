"""The connection manager (plan/43).

One owner for the pool, no class of work able to take all of it, and — the part that has to
be true in every state — a process that survives the database going away and coming back.
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql import text

from tests.conftest import auth, signup

_async = pytest.mark.asyncio


@_async
async def test_everything_shares_one_manager():
    """The premise. Two engines would make every number below a lie."""
    import pathlib

    from memora.core.database import manager
    from memora.db.session import engine

    assert engine is manager.engine

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "memora"
    built = [
        f"{f.relative_to(root)}:{i}"
        for f in root.rglob("*.py")
        if f.name != "database.py"
        for i, line in enumerate(f.read_text().splitlines(), 1)
        if "create_async_engine(" in line
    ]
    assert not built, "a second engine outside the manager: " + ", ".join(built)


@_async
async def test_one_lane_cannot_take_the_whole_pool():
    """Chat must not be able to starve community, an import must not starve chat."""
    from memora.core.database import LaneBusy, manager

    _, ceiling = manager._gate.limits("chat", manager.capacity())
    held: list = []
    try:
        for _ in range(ceiling):
            cm = manager.session("chat", commit=False)
            await cm.__aenter__()
            held.append(cm)
        assert manager.stats()["lanes"]["chat"]["in_use"] == ceiling

        # chat is full: it waits, and is turned away rather than hanging for ever
        import memora.core.database as D

        original, D.LANE_WAIT_S = D.LANE_WAIT_S, 0.2
        try:
            with pytest.raises(LaneBusy):
                async with manager.session("chat"):
                    pass
        finally:
            D.LANE_WAIT_S = original

        # …and another class of work is completely unaffected
        async with manager.session("community", commit=False) as db:
            assert (await db.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        for cm in reversed(held):
            await cm.__aexit__(None, None, None)
    assert manager.stats()["lanes"]["chat"]["in_use"] == 0


@_async
async def test_it_survives_every_connection_being_killed():
    """The requirement in one test: the database goes away, and the process does not.

    This is not a simulation — the connections are terminated from inside Postgres, exactly
    as a restart, a failover or an administrator would do it.
    """
    from memora.core.database import manager

    async with manager.session("other", commit=False) as db:
        assert (await db.execute(text("SELECT 1"))).scalar_one() == 1

    async with manager.session("other", commit=False) as db:
        me = (await db.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        killed = (await db.execute(text("""
            SELECT count(*) FROM (
                SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                WHERE datname = current_database() AND pid <> :me
            ) t
        """), {"me": me})).scalar_one()
    assert killed >= 0

    # Every pooled connection is now dead. The next caller must not notice.
    for _ in range(5):
        async with manager.session("other", commit=False) as db:
            assert (await db.execute(text("SELECT 1"))).scalar_one() == 1
    assert manager.health.ok


@_async
async def test_a_request_still_works_after_the_database_is_cut(client):
    """The same thing through the front door, which is where it matters."""
    from memora.core.database import manager

    _, tok = await signup(client, name="끊김")
    assert (await client.get("/api/agents", headers=auth(tok))).status_code == 200

    async with manager.session("other", commit=False) as db:
        me = (await db.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        await db.execute(text("""
            SELECT pg_terminate_backend(pid) FROM pg_stat_activity
            WHERE datname = current_database() AND pid <> :me
        """), {"me": me})

    r = await client.get("/api/agents", headers=auth(tok))
    assert r.status_code == 200, r.text


@_async
async def test_a_database_that_is_away_is_a_503_and_then_recovers():
    """A dependency being down is not the request's fault: 503, not 500 — and the retry
    means a blip makes requests slow rather than failed.

    On its own manager, not the shared one: the supervisor and the event bus are using that
    one, and a test that breaks their connections is testing them too.
    """
    from memora.config import get_settings
    from memora.core.database import DatabaseManager, DatabaseUnavailable

    mgr = DatabaseManager()
    calls = {"n": 0}
    real = mgr.sessionmaker

    class Boom:
        def __init__(self) -> None:
            self._s = real()

        async def connection(self):
            calls["n"] += 1
            if calls["n"] <= 2:      # away for the first two attempts, back for the third
                raise OperationalError("connect", {}, Exception("could not connect"))
            return await self._s.connection()

        def __getattr__(self, k):
            return getattr(self._s, k)

    assert mgr.engine is not None   # build it, then stand in for its sessionmaker
    mgr._sessionmaker = Boom
    try:
        async with mgr.session("other", commit=False) as db:
            assert (await db.execute(text("SELECT 1"))).scalar_one() == 1
        assert calls["n"] == 3, "it did not retry through the outage"

        # …and when it never comes back, the answer is a 503 with a reason, not a 500
        calls["n"] = -10_000
        with pytest.raises(DatabaseUnavailable) as e:
            async with mgr.session("other"):
                pass
        assert e.value.status == 503
        assert calls["n"] == -10_000 + get_settings().db_connect_attempts
    finally:
        await mgr.stop()


@_async
async def test_releasing_a_session_early_gives_back_the_lane_slot_too():
    """Releasing the connection but keeping the right to take one would rebuild the same
    ceiling one layer up: open browser tabs would exhaust the lane instead of the pool.

    Driven through ``release_db``, which is what the streaming endpoints actually call.
    """
    from starlette.requests import Request

    from memora.core.database import manager
    from memora.core.deps import release_db

    before = manager.stats()["lanes"].get("chat", {}).get("in_use", 0)
    async with manager.session("chat", commit=False) as db:
        assert manager.stats()["lanes"]["chat"]["in_use"] == before + 1
        req = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "state": {}})
        req.state.db = db
        await release_db(req)
        # both handed back, while the scope is still open — as it is for a whole stream
        assert manager.stats()["lanes"]["chat"]["in_use"] == before
    assert manager.stats()["lanes"]["chat"]["in_use"] == before   # and not double-released


@_async
async def test_the_manager_rebuilds_itself_and_keeps_working():
    """The last resort has to work: an engine whose pool is wedged recovers by not being
    that engine any more."""
    from memora.core.database import DatabaseManager

    mgr = DatabaseManager()
    try:
        assert await mgr.ping()
        gen = mgr._generation
        await mgr.reset("test")
        assert await mgr.ping(), "it did not come back after being rebuilt"
        assert mgr._generation > gen
        assert mgr.health.reconnects >= 1
    finally:
        await mgr.stop()


@_async
async def test_leasing_an_account_leaves_no_lock_in_the_callers_transaction():
    """The deadlock that stopped the queue (plan/44).

    Leasing used to write the account's bookkeeping onto the caller's session, so the caller
    held a row lock on that account for as long as its transaction stayed open — for a
    worker job, the whole model call. The health verdict at the end of that call is written
    from a second session on purpose, so a rollback cannot lose a cooldown, and that second
    session then waited for the lock the first was holding. One job, deadlocked against
    itself. Caught on production as two connections from the same worker: one
    `idle in transaction`, the other `active / Lock: transactionid` on
    `UPDATE claude_accounts`.

    So: after leasing, another session must be able to take that row immediately.
    """
    from memora.core.database import manager
    from memora.core.security import encrypt
    from memora.models import ClaudeAccount
    from memora.services import claude_pool as CP
    from memora.services import settings as S

    async with manager.session("worker") as db:
        was = await S.get(db, "providers.claude_code.pool.enabled")
        await S.put(db, "providers.claude_code.pool.enabled", True)
        await db.execute(text("DELETE FROM claude_accounts WHERE label = '잠금시험'"))
        db.add(ClaudeAccount(label="잠금시험", auth_mode="api_key", enabled=True,
                             api_key=encrypt("sk-ant-test"), status="ready", max_concurrency=4))

    lease = None
    try:
        async with manager.session("worker", commit=False) as db:
            lease = await CP.acquire(db, purpose="background")
            assert lease is not None, "the pool handed out nothing, so this proves nothing"
            # Stated directly: the caller's session must be carrying no pending write to the
            # account. That is the invariant — a pending write becomes an UPDATE at the next
            # flush, and the row lock it takes is held until this transaction ends, which for
            # a worker job is after the model call that deadlocks against it.
            assert not db.dirty, f"the caller's session is still holding writes: {db.dirty}"

            # …and the consequence, checked behaviourally: another session can take the row.
            async with manager.session("other", commit=False) as other:
                await other.execute(text("SET LOCAL lock_timeout = '2s'"))
                await other.execute(text("SELECT id FROM claude_accounts FOR UPDATE"))
    finally:
        # Put the install back exactly as it was. Leaving a usable account and an enabled
        # pool behind sends every later test looking for a Claude CLI that is not there.
        if lease is not None:
            lease.release()
        async with manager.session("worker") as db:
            await db.execute(text("DELETE FROM claude_accounts WHERE label = '잠금시험'"))
            await S.put(db, "providers.claude_code.pool.enabled", was)
        S.invalidate("providers.claude_code")


@_async
async def test_a_lane_keeps_its_floor_while_another_sits_on_its_ceiling():
    """plan/32 §3, end to end. The arithmetic is covered by the test below; this one is
    that the manager actually applies it and reports it."""
    from memora.core.database import manager

    cap = manager.capacity()
    gate = manager._gate
    floor_c, _ = gate.limits("community", cap)
    _, ceil_chat = gate.limits("chat", cap)
    held: list = []
    try:
        for _ in range(ceil_chat):
            cm = manager.session("chat", commit=False)
            await cm.__aenter__()
            held.append(cm)
        assert gate.used["chat"] == ceil_chat            # chat is at its ceiling

        for _ in range(floor_c):                          # …and community still gets its floor
            cm = manager.session("community", commit=False)
            await cm.__aenter__()
            held.append(cm)
        assert gate.used["community"] == floor_c
    finally:
        for cm in reversed(held):
            await cm.__aexit__(None, None, None)

    st = manager.stats()["lanes"]["community"]
    assert st["floor"] == floor_c and st["ceiling"] >= floor_c
    assert st["statement_timeout_s"] == 15.0


@_async
async def test_a_lane_may_not_take_the_slots_another_is_owed():
    """The floor has to be withheld from whoever would otherwise take it."""
    from memora.core.database import _LaneGate

    gate = _LaneGate()
    cap = 30
    now = 1000.0
    # community has asked recently, so it is active and owed its floor
    gate.last_seen["community"] = now
    floor_c, _ = gate.limits("community", cap)

    # chat fills up to the point where only community's floor is left
    gate.used["chat"] = cap - floor_c
    gate.last_seen["chat"] = now
    assert not gate.admits("chat", cap, now), "chat took the slots community is owed"
    assert gate.admits("community", cap, now)

    # an idle lane is not owed anything — its floor is not withheld from everyone else
    gate2 = _LaneGate()
    gate2.used["chat"] = 5
    gate2.last_seen["chat"] = now
    assert gate2.admits("chat", cap, now)


@_async
async def test_each_lane_gets_its_own_query_timeout():
    """plan/32 §5. 120s was written for a chat turn whose tools can take minutes; a
    community list query holding a pooled connection that long is a runaway scan."""
    from memora.core.database import LANE_STATEMENT_TIMEOUT_S, manager

    assert LANE_STATEMENT_TIMEOUT_S["community"] < LANE_STATEMENT_TIMEOUT_S["chat"]
    for lane, expected in (("community", 15.0), ("chat", 120.0), ("worker", 300.0)):
        async with manager.session(lane, commit=False) as db:
            # Postgres normalises the unit it reports — "15s" for one lane, "2min" for
            # another — so let it do the arithmetic rather than parsing its spelling.
            seconds = (await db.execute(text(
                "SELECT extract(epoch FROM current_setting('statement_timeout')::interval)"))).scalar_one()
            assert float(seconds) == expected, (lane, seconds)
