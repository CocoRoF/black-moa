"""The one owner of every database connection in this process.

Before this, ``db/session.py`` built an engine at import time and handed the same
sessionmaker to everything: the API, the worker, community, the event bus. That is a shared
resource with no owner — nobody to ask how many connections are in use, nobody to stop one
class of work taking all of them, nobody to notice the database had gone away and come back.

So the pool gets a manager, and the manager is the only way to get a session:

  * **One instance, every consumer.** The API, the worker, community and the bus all take
    their connections from here. There is no second engine and no way to make one by
    accident, which is what makes the numbers below mean anything.

  * **No class of work can take the pool.** Every session is checked out under a lane, and
    a lane may hold at most half the pool. Chat cannot starve community, an import cannot
    starve chat. This is the same rule as the thread pools in ``core.pools``, one layer
    down — and it is the layer that actually ran out: streams used to hold a connection
    each, so thirty open browser tabs blocked every request in the service.

  * **It comes back.** A database that restarts, a failover, a connection killed by an
    administrator, a network blip — none of these may end with a process that has to be
    restarted. Dead connections are detected before use, replaced on a schedule, retried
    with backoff while establishing, and if the engine itself stops working a supervisor
    disposes it and builds a new one. The manager is not something that can die.

  * **Nothing may hold a connection forever.** Every connection carries a server-side
    statement timeout, so a runaway query fails instead of pinning a slot that everything
    else is queuing for.

What is deliberately *not* here: retrying a transaction. Establishing a connection is safe
to retry because nothing has happened yet; re-running a transaction that may already have
committed is how a credit gets charged twice. Retries stop at the first statement.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import text

from memora.config import get_settings
from memora.core.errors import MemoraError
from memora.core.logging import get_logger

log = get_logger("memora.db")

#: The classes of work that share the pool. Same names as the traffic lanes, so a saturated
#: lane on the dashboard and a starved lane here are the same word.
LANES = ("chat", "docs", "admin", "community", "public", "worker", "other")

#: What each lane is guaranteed and what it may never exceed, as fractions of the pool
#: (plan/32 §3). Fractions rather than counts because the API and the worker run the same
#: code against differently sized pools.
#:
#: A ceiling alone was the bug. It stops a lane monopolising the pool but promises nobody a
#: turn: with chat holding its fifteen and docs holding its fifteen, community got nothing —
#: every ceiling satisfied and a lane starved anyway. The floor is the other half of the
#: statement, and it is the half this plan exists for.
#:
#: Floors sum to about two thirds of the pool, so a third stays genuinely shared. They are
#: only honoured for lanes that are *in use* (see ``ACTIVE_S``), which is what lets the same
#: table be right in the worker, where only one lane is ever touched.
@dataclass(frozen=True)
class _Budget:
    floor: float      # guaranteed share
    ceiling: float    # maximum share


LANE_BUDGETS: dict[str, _Budget] = {
    "chat":      _Budget(0.20, 0.60),   # the most expensive work, and the most important
    "community": _Budget(0.12, 0.40),   # not being starved by the above is the point
    "public":    _Budget(0.08, 0.35),   # visitors
    "docs":      _Budget(0.08, 0.30),   # allowed to be slow
    "worker":    _Budget(0.08, 0.70),   # in the worker process this is the only lane
    "admin":     _Budget(0.05, 0.25),   # one person
    "other":     _Budget(0.08, 0.40),
}
DEFAULT_BUDGET = _Budget(0.05, 0.40)

#: A lane counts as active for this long after it last asked for a connection. An idle
#: lane's floor is not withheld from everyone else — but a lane that is being used keeps
#: its guarantee for a minute after each use, so a guarantee is still there at the moment
#: it is needed rather than only once the lane is already busy.
ACTIVE_S = 60.0

#: How long one query may run, by lane (plan/32 §5). The global 120s was written for a
#: chat turn whose tools can legitimately take minutes, and applying it to a community
#: list query means a runaway scan holds a pooled connection for two minutes.
LANE_STATEMENT_TIMEOUT_S: dict[str, float] = {
    "chat": 120.0, "docs": 300.0, "worker": 300.0,
    "community": 15.0, "public": 15.0, "admin": 15.0, "other": 60.0,
}

#: How long a caller waits for its lane's turn before being told the service is busy. A
#: request that waits forever for a connection is indistinguishable from a hung server.
LANE_WAIT_S = 10.0

#: Errors that mean "this connection is no good", as opposed to "your query was wrong".
_CONNECT_ERRORS = (OperationalError, InterfaceError, ConnectionError, OSError)


class DatabaseUnavailable(MemoraError):
    """The database could not be reached, after retrying. A 503, never a 500: the request
    was fine, the dependency was not, and the client may sensibly try again."""

    def __init__(self, detail: str = "") -> None:
        super().__init__("database temporarily unavailable", code="database_unavailable", status=503,
                         detail={"reason": detail[:200]} if detail else None)


class LaneBusy(MemoraError):
    """This class of work is already using its share of the pool."""

    def __init__(self, lane: str) -> None:
        super().__init__("server is busy", code="lane_saturated", status=503, detail={"lane": lane})


@dataclass
class _Counters:
    acquired: int = 0
    waited_s: float = 0.0
    waits: int = 0
    rejected: int = 0
    peak: int = 0
    in_use: int = 0


@dataclass
class _Health:
    ok: bool = True
    last_ok: float = 0.0
    last_error: str = ""
    consecutive_failures: int = 0
    reconnects: int = 0          # engines built after the first
    retries: int = 0             # individual acquisitions that needed a second try
    disposed_at: float = 0.0
    lanes: dict[str, _Counters] = field(default_factory=dict)


class _LaneGate:
    """Admission to the pool: floors, ceilings, and who is owed what.

    Deliberately counters under a condition rather than a semaphore per lane. A semaphore
    can express "at most n" and nothing else; the rule here is "at most your ceiling, and
    never the last slots another active lane is still owed", which needs to see all the
    lanes at once.
    """

    def __init__(self) -> None:
        self.used: dict[str, int] = {}
        self.last_seen: dict[str, float] = {}
        # A lock held only while the counters are read and written, never across a wait.
        # The first version waited on an asyncio.Condition under a timeout, which is a trap:
        # a cancelled Condition.wait() has to re-acquire the lock before it can propagate,
        # so timing out inside the condition left the lock in a state that failed the next
        # caller with a bare TimeoutError instead of a LaneBusy.
        self._lock = asyncio.Lock()
        self._released = asyncio.Event()

    def _budget(self, lane: str) -> _Budget:
        return LANE_BUDGETS.get(lane, DEFAULT_BUDGET)

    def limits(self, lane: str, capacity: int) -> tuple[int, int]:
        b = self._budget(lane)
        return max(1, int(capacity * b.floor)), max(2, int(capacity * b.ceiling))

    def _active(self, lane: str, now: float) -> bool:
        return self.used.get(lane, 0) > 0 or (now - self.last_seen.get(lane, 0.0)) < ACTIVE_S

    def _owed_to_others(self, lane: str, capacity: int, now: float) -> int:
        """Slots other active lanes are still short of their floor — the ones this caller
        may not take, however much room the pool appears to have."""
        owed = 0
        for other in set(LANE_BUDGETS) | set(self.used):
            if other == lane or not self._active(other, now):
                continue
            floor, _ = self.limits(other, capacity)
            owed += max(0, floor - self.used.get(other, 0))
        return owed

    def admits(self, lane: str, capacity: int, now: float) -> bool:
        used = self.used.get(lane, 0)
        floor, ceiling = self.limits(lane, capacity)
        if used >= ceiling:
            return False
        if used < floor:
            return True                       # its own guarantee, always available to it
        total = sum(self.used.values())
        return total + self._owed_to_others(lane, capacity, now) < capacity

    async def acquire(self, lane: str, capacity: int, timeout: float) -> None:
        """Wait for room in this lane, or raise ``TimeoutError``.

        Woken by a release, with a short poll as a backstop so that a missed wakeup costs
        milliseconds rather than the whole timeout — the admission rule depends on other
        lanes' activity ageing out, which no release announces.
        """
        deadline = time.monotonic() + timeout
        while True:
            async with self._lock:
                if self.admits(lane, capacity, time.monotonic()):
                    self.used[lane] = self.used.get(lane, 0) + 1
                    self.last_seen[lane] = time.monotonic()
                    return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(lane)
            self._released.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._released.wait(), min(remaining, 0.05))

    async def release(self, lane: str) -> None:
        async with self._lock:
            self.used[lane] = max(0, self.used.get(lane, 0) - 1)
            self.last_seen[lane] = time.monotonic()
        self._released.set()


class DatabaseManager:
    """Owns the engine, the pool, and the policy for using them."""

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self._gate = _LaneGate()
        self._rebuild_lock = asyncio.Lock()
        self._supervisor: asyncio.Task | None = None
        self._generation = 0
        self.health = _Health(last_ok=time.monotonic())

    # ── the engine ──────────────────────────────────────────────────

    def _build(self) -> AsyncEngine:
        s = get_settings()
        self._generation += 1
        # statement_timeout is the promise that no single query can hold a slot forever.
        # application_name is so `pg_stat_activity` says which process a connection belongs
        # to — the view an operator actually reaches for when the pool is full.
        return create_async_engine(
            s.database_url,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_timeout=s.db_pool_timeout_s,
            # Checked before every use: a connection killed while it sat idle — a restart, a
            # failover, an administrator with pg_terminate_backend — is replaced instead of
            # being handed out to fail one request.
            pool_pre_ping=True,
            # …and replaced on a schedule anyway, because a connection that has been open
            # for hours is the one a proxy or firewall silently drops.
            pool_recycle=s.db_pool_recycle_s,
            connect_args={
                "timeout": s.db_connect_timeout_s,
                "server_settings": {
                    "application_name": f"memora-{s.worker_id}",
                    "statement_timeout": str(int(s.db_statement_timeout_s * 1000)),
                    "idle_in_transaction_session_timeout": str(int(s.db_idle_tx_timeout_s * 1000)),
                },
            },
        )

    @property
    def engine(self) -> AsyncEngine:
        """The live engine. A property rather than a module global because a rebuild has to
        be picked up by everything, including anything holding a long-lived reference."""
        if self._engine is None:
            self._engine = self._build()
            self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False, class_=AsyncSession)
            log.info("database engine built", generation=self._generation)
        return self._engine

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        self.engine  # noqa: B018 — builds both on first use
        assert self._sessionmaker is not None
        return self._sessionmaker

    def capacity(self) -> int:
        s = get_settings()
        return s.db_pool_size + s.db_max_overflow

    async def reset(self, reason: str) -> None:
        """Throw the engine away and build a new one.

        The last resort, and it has to exist: pre-ping recovers individual connections, but
        an engine whose pool is wedged — every slot checked out by something that will never
        give it back — recovers by not being that engine any more.
        """
        async with self._rebuild_lock:
            old = self._engine
            self._engine = None
            self._sessionmaker = None
            self.health.reconnects += 1
            self.health.disposed_at = time.monotonic()
            log.warning("rebuilding the database engine", reason=reason[:200], generation=self._generation)
            if old is not None:
                # Not awaited on the request's path: disposing waits for checked-out
                # connections, and the point of a rebuild is not to wait for them.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(old.dispose(), timeout=10)

    # ── sessions ────────────────────────────────────────────────────

    @contextlib.asynccontextmanager
    async def session(self, lane: str = "other", *, commit: bool = True) -> AsyncIterator[AsyncSession]:
        """A session, under a lane, with the connection already established.

        The connection is opened here rather than lazily on first query so that a database
        that is briefly away is retried *before* the caller's work begins — the only moment
        at which retrying is safe, because nothing has happened yet.
        """
        counters = self.health.lanes.setdefault(lane, _Counters())
        t0 = time.monotonic()
        try:
            await self._gate.acquire(lane, self.capacity(), LANE_WAIT_S)
        except TimeoutError as e:
            counters.rejected += 1
            floor, ceiling = self._gate.limits(lane, self.capacity())
            log.warning("lane could not be admitted to the pool", lane=lane, waited_s=LANE_WAIT_S,
                        in_use=self._gate.used.get(lane, 0), floor=floor, ceiling=ceiling)
            raise LaneBusy(lane) from e
        waited = time.monotonic() - t0
        if waited > 0.05:
            counters.waits += 1
            counters.waited_s += waited
        counters.acquired += 1
        counters.in_use += 1
        counters.peak = max(counters.peak, counters.in_use)
        session: AsyncSession | None = None
        done = False

        async def _release() -> None:
            """Give the connection *and* the lane slot back, once.

            Exposed to the caller through ``session.info`` because a streaming endpoint
            finishes with its session long before its response ends, and holding the lane
            slot for the whole stream would rebuild the exact ceiling this replaced: the
            connection was handed back but the right to take one was not, so open browser
            tabs would still have run the lane out.
            """
            nonlocal done
            if done:
                return
            done = True
            if session is not None:
                with contextlib.suppress(Exception):
                    await session.close()
            counters.in_use -= 1
            await self._gate.release(lane)

        try:
            session = await self._connect_with_retry(lane)
            # SET LOCAL, so it lasts exactly this transaction and cannot leak into whoever
            # gets this pooled connection next. The value is an integer from our own table;
            # SET takes no bind parameters.
            ms = int(LANE_STATEMENT_TIMEOUT_S.get(lane, get_settings().db_statement_timeout_s) * 1000)
            with contextlib.suppress(Exception):
                await session.execute(text(f"SET LOCAL statement_timeout = {ms}"))
            session.info["memora_release"] = _release
            try:
                yield session
                if commit and not done:
                    await session.commit()
            except Exception:
                if not done:
                    with contextlib.suppress(Exception):
                        await session.rollback()
                raise
        finally:
            await _release()

    async def _connect_with_retry(self, lane: str) -> AsyncSession:
        """Open a session and prove its connection works, retrying while it does not.

        Safe to retry precisely because it happens before the caller's first statement. A
        restart or a failover is a few seconds of unavailability; without this it is a wave
        of 500s, and with it the requests that land during the gap simply take longer.
        """
        s = get_settings()
        delay = 0.25
        last = ""
        for attempt in range(1, s.db_connect_attempts + 1):
            session = self.sessionmaker()
            try:
                # Establishes the connection now, and nothing more: the pool's pre-ping
                # already proves it is alive on checkout, so a SELECT here would be a
                # second round trip per session to learn what we have just been told.
                await session.connection()
                if attempt > 1:
                    self.health.retries += 1
                    log.info("database connection recovered", lane=lane, attempt=attempt)
                self._note_ok()
                return session
            except _CONNECT_ERRORS as e:
                last = f"{e.__class__.__name__}: {e}"
                with contextlib.suppress(Exception):
                    await session.close()
                self._note_failure(last)
                if attempt >= s.db_connect_attempts:
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 2, 2.0)
            except DBAPIError as e:      # not a connection problem — the caller should see it
                with contextlib.suppress(Exception):
                    await session.close()
                raise e
        raise DatabaseUnavailable(last)

    def _note_ok(self) -> None:
        if not self.health.ok:
            log.info("database is back", after_failures=self.health.consecutive_failures)
        self.health.ok = True
        self.health.last_ok = time.monotonic()
        self.health.consecutive_failures = 0

    def _note_failure(self, err: str) -> None:
        self.health.consecutive_failures += 1
        self.health.last_error = err[:300]
        if self.health.ok:
            log.warning("database connection failed", err=err[:200])
        self.health.ok = False

    # ── supervision ─────────────────────────────────────────────────

    async def ping(self) -> bool:
        try:
            async with self.session("other", commit=False) as db:
                await db.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001
            return False

    async def _supervise(self) -> None:
        """Keep asking whether the database is there, and act when it stops being.

        A pool only discovers it is broken when somebody uses it, which on a quiet service
        means the first user after an outage discovers it for us. This asks on their behalf,
        and after enough consecutive failures stops trying to nurse the engine back and
        replaces it.
        """
        s = get_settings()
        while True:
            await asyncio.sleep(s.db_health_interval_s)
            ok = await self.ping()
            if ok or self.health.consecutive_failures < s.db_failures_before_reset:
                continue
            with contextlib.suppress(Exception):
                await self.reset(f"{self.health.consecutive_failures} consecutive health checks failed")
            # Give the new engine a chance to prove itself before counting failures again.
            self.health.consecutive_failures = 0

    def start(self) -> None:
        if self._supervisor is None or self._supervisor.done():
            self._supervisor = asyncio.create_task(self._supervise(), name="db-supervisor")

    async def stop(self) -> None:
        if self._supervisor is not None:
            self._supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor
            self._supervisor = None
        if self._engine is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._engine.dispose(), timeout=10)

    # ── what the dashboard shows ────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        pool = getattr(self._engine, "pool", None) if self._engine is not None else None
        cap = self.capacity()
        checked_out = 0
        with contextlib.suppress(Exception):
            checked_out = pool.checkedout() if pool is not None else 0
        lanes = {
            name: {
                "in_use": c.in_use,
                "floor": self._gate.limits(name, cap)[0],
                "ceiling": self._gate.limits(name, cap)[1],
                "statement_timeout_s": LANE_STATEMENT_TIMEOUT_S.get(name, get_settings().db_statement_timeout_s),
                "acquired": c.acquired,
                "peak": c.peak,
                "waits": c.waits,
                "avg_wait_ms": round(1000 * c.waited_s / c.waits, 1) if c.waits else 0.0,
                "rejected": c.rejected,
            }
            for name, c in sorted(self.health.lanes.items())
        }
        return {
            "capacity": cap,
            "checked_out": checked_out,
            "in_use": sum(c.in_use for c in self.health.lanes.values()),
            "generation": self._generation,
            "healthy": self.health.ok,
            "seconds_since_ok": round(time.monotonic() - self.health.last_ok, 1),
            "consecutive_failures": self.health.consecutive_failures,
            "reconnects": self.health.reconnects,
            "retries": self.health.retries,
            "last_error": self.health.last_error,
            "lanes": lanes,
        }


#: The instance. Everything in the process shares it — that is the point.
manager = DatabaseManager()
