"""Isolation and the traffic record (plan/40)."""
from __future__ import annotations

import asyncio
import time

import pytest
from httpx import AsyncClient

from tests.conftest import auth, signup

_async = pytest.mark.asyncio


@_async
async def test_one_saturated_lane_does_not_delay_another():
    """The whole point of naming the work.

    Everything used to share the interpreter's single default executor, so a burst of
    document parsing took the threads a chat turn then waited for. Separate pools, separate
    queues: filling one is not a way to slow the other down.
    """
    from memora.core.pools import SIZES, run_blocking, stats

    hold = asyncio.Event()

    def blocker() -> None:
        # Sync sleep on purpose: this is what a blocking library call looks like.
        while not hold.is_set():
            time.sleep(0.01)

    docs = [asyncio.create_task(run_blocking("docs", blocker, label="test-blocker")) for _ in range(SIZES["docs"] + 4)]
    try:
        await asyncio.sleep(0.3)
        st = stats()["docs"]
        # Saturation has to read as saturation: every thread busy, the rest waiting.
        assert st["in_flight"] == SIZES["docs"], st
        assert st["queued"] == 4, st

        t0 = time.monotonic()
        assert await run_blocking("llm", lambda: 7, label="test-quick") == 7
        assert time.monotonic() - t0 < 1.0, "an llm call queued behind document work"
    finally:
        hold.set()
        await asyncio.gather(*docs)


@_async
async def test_every_request_is_recorded_with_its_lane(client: AsyncClient):
    """A record of what was served, written off the request's own path."""
    from memora.core import traffic as TF
    from memora.db.session import session_scope
    from memora.services import traffic as TR

    _, tok = await signup(client, name="측정")
    TF.take_batch(10_000)                      # start from a known point
    await client.get("/api/agents", headers=auth(tok))
    await client.get("/api/community/boards", headers=auth(tok))

    rows = TF.take_batch()
    lanes = {r["lane"] for r in rows}
    routes = {r["route"] for r in rows}
    assert "other" in lanes and "community" in lanes, lanes
    assert any("/api/agents" in r for r in routes), routes
    assert all(r["ms"] >= 0 and r["status"] < 500 for r in rows)

    # …and it lands in the table the dashboard reads, aggregated there rather than in a browser.
    # The buffer is shared with the housekeeping that normally drains it, so the rows go back
    # in with no await between putting them there and taking them out again.
    async with session_scope() as db:
        for r in rows:
            TF._state.buffer.append(r)
        assert await TR.flush(db) == len(rows)
        await db.commit()
    async with session_scope() as db:
        s = await TR.summary(db, minutes=60)
        assert s["overall"]["n"] >= len(rows)
        assert any(x["lane"] == "community" for x in s["lanes"])
        assert await TR.endpoints(db, 60) and isinstance(await TR.anomalies(db, 60), list)


@_async
async def test_a_request_in_flight_is_visible_while_it_runs(app, client: AsyncClient):
    """The list that finds a bad call while it is still happening.

    Asked from inside a request that is still running, because that is the situation the
    live list exists for — an operator looking at a call that has not come back yet.
    """
    from memora.core import traffic as TF

    seen: dict = {}

    @app.get("/api/_test/slow")
    async def _slow():                       # a stand-in for anything that takes its time
        await asyncio.sleep(0.05)
        rows = [r for r in TF.in_flight() if r["route"].endswith("/_test/slow")]
        seen.update(rows[0] if rows else {})
        return {"ok": True}

    r = await client.get("/api/_test/slow")
    assert r.status_code in (200, 401, 403), r.text
    if r.status_code == 200:
        assert seen, "a request that was running was not on the live list"
        assert {"route", "lane", "elapsed_ms", "stuck"} <= set(seen)
        assert seen["elapsed_ms"] >= 40 and seen["stuck"] is False


def test_nothing_blocking_is_left_on_the_shared_executor():
    """The isolation is only as good as its least-migrated call site.

    ``asyncio.to_thread`` runs on the interpreter's single default executor, which is the
    shared resource this whole design exists to stop existing. One call left behind is one
    class of work that can still be starved by another, so the rule is checked rather than
    remembered.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "memora"
    offenders = []
    for f in root.rglob("*.py"):
        if f.name == "pools.py":
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if "asyncio.to_thread(" in line and not line.lstrip().startswith("#"):
                offenders.append(f"{f.relative_to(root)}:{i}")
    assert not offenders, "use pools.to_thread(<pool>, ...) instead: " + ", ".join(offenders)


def test_every_pool_a_call_site_names_actually_exists():
    """A typo in a pool name is silent: _pool() would happily make a fourth pool of four
    threads named "docsx" and the dashboard would show it as a stranger."""
    import pathlib
    import re

    from memora.core.pools import SIZES

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "memora"
    used = set()
    for f in root.rglob("*.py"):
        for m in re.finditer(r'(?:run_blocking|pools\.to_thread|to_thread)\(\s*"([a-z_]+)"', f.read_text()):
            used.add(m.group(1))
    assert used and used <= set(SIZES), f"unknown pool(s): {used - set(SIZES)}"


def test_community_images_do_not_resize_in_the_document_pool():
    """plan/32 §2. Community pictures used to resize in the ``docs`` pool, so a few images
    on a board pushed back knowledge indexing — one feature degrading an unrelated one."""
    import inspect

    from memora.core.pools import SIZES
    from memora.services import uploads as U

    assert "community" in SIZES and "crawl" in SIZES, SIZES
    assert "lane" in inspect.signature(U.store).parameters
    src = inspect.getsource(U.store)
    assert 'to_thread(lane' in src, "the resize still names a fixed pool"


def test_a_lane_can_be_rewidened_without_a_deploy(monkeypatch):
    """A class of work invented later has to be tunable the day it ships."""
    from memora.core import pools

    monkeypatch.setenv("MEMORA_POOL_CRAWL", "24")
    assert pools._configured("crawl") == 24
    monkeypatch.setenv("MEMORA_POOL_CRAWL", "banana")
    assert pools._configured("crawl") == pools.DEFAULT_SIZES["crawl"]   # ignored, not obeyed
    monkeypatch.setenv("MEMORA_POOL_CRAWL", "999999")
    assert pools._configured("crawl") == pools.DEFAULT_SIZES["crawl"]
    assert pools._configured("something-new") == pools.DEFAULT_OTHER    # still gets a pool


def test_a_class_named_before_its_handlers_still_has_a_ceiling():
    """plan/32 §4. The places-map crawlers are ``crawl.*`` and do not exist yet.

    The tally used to be taken from the exact kind→class map, which has no entry for a
    prefix class — so the crawl ceiling counted zero jobs however many were running.
    """
    from memora.worker.__main__ import CLASS_LIMITS, _blocked, _class_of

    assert _class_of("crawl.places") == "crawl"
    limit = CLASS_LIMITS["crawl"]
    assert _blocked({"crawl.places": limit - 1}, 8) == ([], [])
    kinds, prefixes = _blocked({"crawl.places": limit}, 8)
    # Expressed as a prefix, because there is no list of crawl kinds to exclude
    assert "crawl." in prefixes and kinds == []


def test_the_last_slot_is_kept_for_work_someone_is_waiting_on():
    """plan/32 §4. Ceilings stop monopolies but promise nobody a turn: with every long
    class at its limit, a notification a person is waiting for still queues behind minutes
    of work. The reservation is the floor that ceilings cannot express."""
    from memora.worker.__main__ import CONCURRENCY, RESERVED, _blocked

    busy = {"knowledge.index": 3, "crawl.places": 3, "community.rank": 1}
    assert sum(busy.values()) == CONCURRENCY - 1

    kinds, prefixes = _blocked(busy, free_slots=1)
    assert "knowledge.index" in kinds and "crawl." in prefixes    # long work steps back
    assert "notify.send" not in kinds and "mail.send" not in kinds   # the floor is for these

    # Once the reserved class actually holds its slot, the reservation is satisfied and the
    # only limits left are the ordinary ceilings.
    served = {"knowledge.index": 3, "crawl.places": 3, "notify.send": RESERVED["interactive"]}
    kinds2, _ = _blocked(served, free_slots=1)
    assert "community.rank" not in kinds2

    # Plenty of room: nothing is held back at all.
    assert _blocked({}, CONCURRENCY) == ([], [])


def test_one_class_of_work_cannot_take_every_worker_slot():
    """The ceiling that per-kind limits missed.

    Importing twenty documents used to put four ``knowledge.index`` jobs into all four
    slots, and nothing else ran until they were done — no notifications, no credit sweeps,
    no ranking. Per-kind limits did not help because the kinds were the same kind, and the
    thread pools do not help because the scarce resource here is a worker slot.
    """
    from memora.worker.__main__ import CLASS_LIMITS, CONCURRENCY, KIND_CLASS, _blocked

    docs_limit = CLASS_LIMITS["docs"]
    assert _blocked({}) == ([], [])
    assert _blocked({"knowledge.index": 1}) == ([], [])              # one is fine
    blocked, _ = _blocked({"knowledge.index": docs_limit})
    assert "knowledge.index" in blocked
    # the whole class steps back together, so a sibling kind cannot take the last slots
    assert set(blocked) == {k for k, c in KIND_CLASS.items() if c == "docs"}
    # …and mixed kinds inside the class count towards the same ceiling
    mixed = {"knowledge.index": docs_limit - 1, "retention.sweep": 1}
    assert "knowledge.index" in _blocked(mixed)[0]
    # something is always left for everyone else
    assert docs_limit < CONCURRENCY
    assert "notify.send" not in _blocked({"knowledge.index": docs_limit})[0]


def test_a_long_stream_is_not_abnormal_but_a_silent_one_is():
    """What "stuck" means once a request can legitimately stay open for hours."""
    import time

    from memora.core.traffic import SILENT_S, STUCK_S, Live

    now = time.monotonic()

    def live(**kw) -> Live:
        kw.setdefault("started", now)
        return Live(id="x", route="/api/x", method="GET", lane="chat", **kw)

    # nothing sent yet, and minutes gone: this one is holding something
    assert live(started=now - STUCK_S - 1).stuck
    assert not live(started=now - 5).stuck
    # a notification stream open all afternoon, still sending keepalives: normal
    tab = live(started=now - 6 * 3600, responded=True, streaming=True, last_at=now - 1)
    assert not tab.stuck
    # …the same stream gone quiet: abnormal
    dead = live(started=now - 6 * 3600, responded=True, streaming=True, last_at=now - SILENT_S - 1)
    assert dead.stuck
    # a plain response that has answered is never stuck
    assert not live(started=now - 10_000, responded=True, last_at=now - 10_000).stuck


@pytest.mark.asyncio
async def test_one_owner_bulk_import_does_not_bury_everyone_else():
    """The queue is served round-robin across owners (plan/45).

    Ordering used to be priority then age, which is first-come: a person importing five
    hundred documents put all five hundred ahead of the next person's one, and that person
    waited for the whole import. Kind ceilings did not help — the kinds are the same kind.
    """
    import uuid as _uuid

    from sqlalchemy import text as _text

    from memora.core.database import manager
    from memora.services import jobs as J

    big, small = _uuid.uuid4(), _uuid.uuid4()
    async with manager.session("worker") as db:
        await db.execute(_text("DELETE FROM jobs WHERE kind = 'test.fair'"))
        for _ in range(40):                       # the bulk import, queued first
            await J.enqueue(db, "test.fair", {"who": "big"}, owner_id=big)
        await J.enqueue(db, "test.fair", {"who": "small"}, owner_id=small)   # …then one job

    try:
        claimed = []
        async with manager.session("worker") as db:
            for _ in range(4):
                job = await J.claim(db, "w-fair", kinds=["test.fair"])
                assert job is not None
                claimed.append(job.payload["who"])
        # The one job behind forty must not be served fortieth.
        assert "small" in claimed, f"the second owner waited behind the whole import: {claimed}"
        assert claimed.count("small") == 1
    finally:
        async with manager.session("worker") as db:
            await db.execute(_text("DELETE FROM jobs WHERE kind = 'test.fair'"))


@pytest.mark.asyncio
async def test_a_prefix_ceiling_actually_filters_the_claim(client: AsyncClient):
    """The exclusion has to reach the SQL, not just the caller's arithmetic.

    It did not: the claim query was rewritten for owner fairness and the prefix clause was
    left computed but never interpolated, so a `crawl` ceiling was arithmetic with no
    effect. Nothing caught it because no `crawl.*` handler exists yet.
    """
    from memora.db.session import session_scope
    from memora.services import jobs as J

    mine = ["crawl.places", "notify.send"]
    async with session_scope("worker") as db:
        await J.enqueue(db, "crawl.places", {"n": 1})
        await J.enqueue(db, "notify.send", {"n": 2})
        await db.commit()

    # `kinds=` so the assertion is about these two jobs and not whatever else the suite
    # has left in the queue.
    async with session_scope("worker") as db:
        got = await J.claim(db, "test-worker", kinds=mine, exclude_prefixes=["crawl."])
        assert got is not None and got.kind == "notify.send", got and got.kind
        await db.rollback()

    async with session_scope("worker") as db:
        got = await J.claim(db, "test-worker-2", kinds=["crawl.places"])
        assert got is not None and got.kind == "crawl.places", "the prefix was not why it was skipped"
        await db.rollback()


@pytest.mark.asyncio
async def test_the_worker_is_visible_from_the_api_process(client: AsyncClient):
    """plan/32 §6. An allocation nobody can observe is one nobody knows is holding.

    Pools, lanes and in-flight requests are in-memory, so the console only ever saw the
    process that answered the request — the worker's pools and its share of the connection
    pool were on no screen at all, which is a poor place to tune an allocation from.
    """
    from memora.db.session import session_scope
    from memora.services import procstats as PS

    async with session_scope("worker") as db:
        await PS.publish(db, "api")
        await PS.publish(db, "worker")
        await db.commit()

    async with session_scope("worker") as db:
        f = await PS.fleet(db)

    keys = {p["key"].split(":")[0] for p in f["processes"]}
    assert {"api", "worker"} <= keys, keys
    assert f["fresh"] == len(f["processes"]) and not f["stale"]

    # the totals are the sum over live processes, so the worker's threads are counted
    per_proc = [p for p in f["processes"] if p["key"].startswith("worker:")][0]
    assert per_proc["pools"]["docs"]["size"] > 0
    assert f["pools"]["docs"]["size"] >= per_proc["pools"]["docs"]["size"]
    assert f["db"]["capacity"] > 0
    # …and each role reports what only it knows
    assert "worker" in per_proc and per_proc["worker"]["concurrency"] > 0
    api_proc = [p for p in f["processes"] if p["key"].startswith("api:")][0]
    assert "sessions" in api_proc


@pytest.mark.asyncio
async def test_a_process_that_stopped_publishing_is_not_counted(client: AsyncClient):
    """Summing a dead process's numbers overstates the capacity that actually exists."""
    from datetime import UTC, datetime, timedelta

    from memora.db.session import session_scope
    from memora.models import ProcessStat
    from memora.services import procstats as PS

    async with session_scope("worker") as db:
        await PS.publish(db, "worker")
        await db.commit()
    async with session_scope("worker") as db:
        stale = (await db.get(ProcessStat, f"worker:{__import__('memora.config', fromlist=['x']).get_settings().worker_id}"))
        stale.at = datetime.now(UTC) - timedelta(seconds=PS.FRESH_S + 30)
        await db.commit()

    async with session_scope("worker") as db:
        f = await PS.fleet(db)
    assert f["stale"], "a process that stopped publishing was still counted as live"
    dead = [p for p in f["processes"] if not p["fresh"]]
    assert dead and dead[0]["age_s"] > PS.FRESH_S


@pytest.mark.asyncio
async def test_community_has_a_request_budget_per_account(client: AsyncClient, monkeypatch):
    """plan/32 §7, the last layer: a scraper must not take the backend's request
    throughput from everyone else.

    The real numbers come from the traffic record rather than from taste — over a day the
    busiest actual caller averaged well under one request a minute — so a person reading a
    board will never meet them. The limit is lowered here so the test does not have to send
    a hundred and twenty requests to prove the wiring.
    """
    import memora.api.community as C
    from memora.core.ratelimit import limiter

    assert C.WRITES_PER_MIN < C.READS_PER_MIN      # writes cost more, so they are tighter

    # The suite disables the limiter globally; this one test is about the limiter.
    monkeypatch.delenv("MEMORA_RATELIMIT_DISABLED", raising=False)
    monkeypatch.setattr(C, "READS_PER_MIN", 3)
    limiter._buckets.clear()

    _, tok = await signup(client, name="게시판")
    seen = [(await client.get("/api/community/boards", headers=auth(tok))).status_code for _ in range(6)]
    assert 200 in seen and 429 in seen, seen
    assert seen.index(429) >= 3, f"throttled before the budget was spent: {seen}"

    # …and a different account is unaffected, because the budget is per account
    _, other = await signup(client, name="다른사람")
    assert (await client.get("/api/community/boards", headers=auth(other))).status_code == 200
    limiter._buckets.clear()


def test_the_worker_measures_its_loop_rather_than_its_age():
    """The watchdog has to be installed in every process that reports lag.

    It was only in the API, so in the worker `loop_lag()` subtracted from a clock nothing
    ticked: an idle worker reported a three-minute stall that grew for ever. A number that
    is wrong in that direction is worse than no number, because it is the one an operator
    would act on.
    """
    import pathlib
    import re

    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "memora" / "worker" / "__main__.py").read_text()
    assert re.search(r"^\s*install_loop_watchdog\(\)", src, re.M), "the worker never starts the watchdog"
