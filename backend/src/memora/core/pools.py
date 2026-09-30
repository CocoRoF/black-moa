"""Separate hands for separate work.

Every blocking call in this process used to go through ``asyncio.to_thread``, which means
the interpreter's one default executor — thirty-two threads shared by everything. That is
a single resource with no owner: a burst of document parsing, or one CLI client that stops
answering, takes threads that a chat turn then waits for. Two unrelated features become
each other's queue.

So the work is named and each name gets its own bounded pool:

  ``llm``     turns and background completions — talks to a CLI/API that can stall
  ``memory``  the per-turn memory index: warm, search, remember — small and latency-bound
  ``docs``    extraction, chunking, embedding, retention — CPU-heavy and bursty
  ``misc``    everything else that blocks briefly (files, images, object store)

``memory`` is separate from ``docs`` for the reason the whole module exists: both use the
same SQLite indexes, but one is on a chat turn's critical path and the other is a document
import that runs for a minute. Sharing threads makes the import a delay in the reply.

A pool that fills makes its own callers wait and nobody else. The sizes are deliberately
small enough that the machine keeps its head, and every wait is visible: ``stats()`` is
what the traffic dashboard shows, so a saturated pool is a number an operator can read
rather than a mystery slowdown.
"""
from __future__ import annotations

import asyncio
import functools
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from memora.core.logging import get_logger

log = get_logger("memora.pools")

#: How wide each pool is, and what each one is for.
#:
#: ``llm``       one CLI subprocess or HTTP exchange per slot, all of it spent waiting, so
#:               it is sized to the account pool's own concurrency rather than to cores —
#:               narrower than that and this pool, not the accounts, caps conversations.
#: ``memory``    recall and distillation: vector arithmetic, CPU-bound.
#: ``docs``      knowledge extraction, chunking, embedding. CPU-bound and bursty.
#: ``community`` posts and their images. It has its own pool because it did not: community
#:               image resizing ran in ``docs``, so a few pictures on a board pushed back
#:               document indexing — one feature's load degrading an unrelated one, which
#:               is the thing all of this exists to prevent.
#: ``crawl``     outbound fetching for the places map. Waiting on someone else's server,
#:               which is exactly the kind of slowness that must not be shared.
#: ``misc``      files, images, object store, everything else that blocks briefly.
#:
#: The CPU-bound lanes are sized near the core count on purpose: oversubscribing real CPU
#: work buys queueing, not throughput. The waiting lanes are wide because a waiting thread
#: costs almost nothing.
DEFAULT_SIZES = {"llm": 16, "memory": 6, "docs": 6, "community": 6, "crawl": 12, "misc": 16}

#: A lane invented later still gets a pool rather than sharing one by accident.
DEFAULT_OTHER = 4


def _configured(name: str) -> int:
    """``MEMORA_POOL_CRAWL=16`` rewidens a lane without a deploy.

    Read per name rather than from a fixed table, so a lane added tomorrow is tunable the
    day it ships. The bound is a sanity check, not a policy: a typo that asks for 100000
    threads should be ignored loudly, not honoured.
    """
    raw = os.environ.get(f"MEMORA_POOL_{name.upper()}", "").strip()
    if raw.isdigit() and 1 <= int(raw) <= 256:
        return int(raw)
    if raw:
        log.warning("ignoring unusable pool size", pool=name, value=raw)
    return DEFAULT_SIZES.get(name, DEFAULT_OTHER)


#: Still a dict named SIZES because the dashboard, the tests and ``stats()`` read it.
SIZES = {k: _configured(k) for k in DEFAULT_SIZES}


@dataclass
class _Pool:
    name: str
    size: int
    ex: ThreadPoolExecutor
    in_flight: int = 0
    queued: int = 0
    peak_in_flight: int = 0
    total: int = 0
    total_wait_s: float = 0.0
    total_run_s: float = 0.0
    slowest_s: float = 0.0
    slowest_label: str = ""
    # A plain lock, not asyncio's: these counters are written by worker threads.
    lock: threading.Lock = field(default_factory=threading.Lock)


_pools: dict[str, _Pool] = {}


def _pool(name: str) -> _Pool:
    p = _pools.get(name)
    if p is None:
        size = SIZES.get(name) or _configured(name)
        p = _Pool(name=name, size=size, ex=ThreadPoolExecutor(max_workers=size, thread_name_prefix=f"memora-{name}"))
        _pools[name] = p
    return p


async def run_blocking[T](pool: str, fn: Callable[[], T], *, label: str = "", timeout_s: float | None = None) -> T:
    """Run a blocking callable in the named pool.

    ``label`` is what the dashboard shows for a slow one — the point of naming the work is
    being able to say *which* call is holding a pool, not just that one is.

    The bookkeeping is done by the worker thread rather than by this coroutine, because the
    two disagree about the only thing these numbers are for. Submitting to an executor
    returns a future immediately, so counting there reported eight calls "in flight" on a
    pool of four with nothing queued — the exact reading a saturated pool must not give.
    A thread counts itself in when it actually picks the work up.
    """
    p = _pool(pool)
    loop = asyncio.get_running_loop()
    t0 = time.monotonic()
    with p.lock:
        p.queued += 1
    picked = False

    def _run() -> T:
        nonlocal picked
        started = time.monotonic()
        with p.lock:
            picked = True
            p.queued -= 1
            p.in_flight += 1
            p.peak_in_flight = max(p.peak_in_flight, p.in_flight)
        try:
            return fn()
        finally:
            ran = time.monotonic() - started
            with p.lock:
                p.in_flight -= 1
                p.total += 1
                p.total_wait_s += started - t0
                p.total_run_s += ran
                if ran > p.slowest_s:
                    p.slowest_s, p.slowest_label = ran, label or getattr(fn, "__name__", "?")
            if started - t0 > 1.0:
                log.warning("blocking pool is saturated", pool=pool, waited_s=round(started - t0, 2),
                            label=label, size=p.size)

    fut = loop.run_in_executor(p.ex, _run)
    try:
        return await (asyncio.wait_for(fut, timeout=timeout_s) if timeout_s else fut)
    except (TimeoutError, asyncio.CancelledError):
        # Gave up before a thread ever picked it up: the executor drops a cancelled future,
        # so nothing else will take this call back out of the queue count.
        with p.lock:
            if not picked:
                p.queued -= 1
        raise


async def to_thread[T](pool: str, fn: Callable[..., T], /, *args: Any, label: str = "", **kwargs: Any) -> T:
    """``asyncio.to_thread``, but in a named pool instead of the one shared executor.

    Exists so that moving a call site off the shared executor is a one-word edit and not a
    rewrite into ``functools.partial`` — a migration that is awkward to make is a migration
    that gets made in half the places.
    """
    fn2 = functools.partial(fn, *args, **kwargs) if (args or kwargs) else fn
    return await run_blocking(pool, fn2, label=label or getattr(fn, "__name__", "") or "?")


def stats() -> dict[str, dict[str, Any]]:
    """What each pool is doing right now, and what it has done."""
    out: dict[str, dict[str, Any]] = {}
    for name, p in _pools.items():
        out[name] = {"size": p.size, "in_flight": p.in_flight, "queued": p.queued, "peak_in_flight": p.peak_in_flight,
                     "calls": p.total, "avg_wait_ms": round(1000 * p.total_wait_s / p.total, 1) if p.total else 0.0,
                     "avg_run_ms": round(1000 * p.total_run_s / p.total, 1) if p.total else 0.0,
                     "slowest_ms": round(1000 * p.slowest_s, 1), "slowest": p.slowest_label}
    for name in SIZES:
        out.setdefault(name, {"size": SIZES[name], "in_flight": 0, "queued": 0, "peak_in_flight": 0, "calls": 0,
                              "avg_wait_ms": 0.0, "avg_run_ms": 0.0, "slowest_ms": 0.0, "slowest": ""})
    return out


def shutdown() -> None:
    for p in _pools.values():
        p.ex.shutdown(wait=False, cancel_futures=True)
    _pools.clear()
