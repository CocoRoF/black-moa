"""Worker process: polls the PG job queue, runs periodic schedules, heartbeats."""
from __future__ import annotations

import os

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
os.environ.setdefault("GENY_CLI_PREWARM", "0")

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import signal  # noqa: E402
import time  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from memora.config import get_settings  # noqa: E402
from memora.core.logging import get_logger, setup_logging  # noqa: E402
from memora.core.security import validate_security_settings  # noqa: E402
from memora.core.watchdog import install_loop_watchdog  # noqa: E402
from memora.db.session import session_scope  # noqa: E402
from memora.models import Job, WorkerHeartbeat  # noqa: E402
from memora.services import jobs as J  # noqa: E402
from memora.services.keycheck import verify_encryption_keys  # noqa: E402
from memora.worker.handlers import HANDLERS  # noqa: E402

log = get_logger("memora.worker")
SCHEDULE = [  # (kind, every_seconds, dedupe)
    ("credits.monthly_grant", 3600, True), ("credits.low_watch", 900, True), ("digest.daily", 1800, True), ("relationship.tick", 900, True), ("relay.sweep", 300, True),
    ("retention.sweep", 6 * 3600, True), ("claude_creds.backup", 3600, True), ("ops.watch", 300, True), ("stats.refresh", 900, True),
    ("credits.reservation_reaper", 600, True), ("community.rank", 300, True),
    # The company directory, once a day. The handler itself checks whether automatic
    # collection is switched on, so a fresh install does not start calling other people's
    # servers unasked (plan/33 §1).
    ("companies.refresh", 24 * 3600, True),
    # Popularity, views-in-the-last-week and open postings for the directory (plan/40).
    # Cheap — four statements — so often enough that "popular" follows what people do.
    ("companies.rank", 3600, True),
    # 사진이 붙었는데 아직 비서가 안 본 글을 뒤늦게 채운다 (plan/45 §2). 밀린 것이
    # 없으면 조회 한 번으로 끝나고, 있으면 하루에 몇 편씩만 집는다.
    ("photos.catchup", 6 * 3600, True),
    # 비서의 파일 (plan/55): 밀린 읽기를 다시 잡고, 지운 지 30일 지난 파일을 실제로 지운다.
    ("files.sweep", 1800, True),
    # 스케줄의 [연동]: 자동으로 가져올 때가 된 달력을 찾는다 (plan/58). 간격은 달력마다 따로.
    ("calendar.autosync", 300, True),
    # 메일함(10분)과 Google 연락처(하루) — 알려 주지 않는 것들을 때맞춰 가져온다 (plan/76).
    ("integrations.autosync", 300, True),
    # 한국의 공휴일·기념일을 공식 출처에서 (plan/60). 켜 두지 않았으면 조회 한 번으로 끝난다.
    ("holidays.sync", 24 * 3600, True),
    # 다운로드 센터 (plan/64): 앱의 GitHub 릴리스를 읽는다. 새것이 없으면 요청 하나로 끝난다.
    ("downloads.sync", 600, True),
]
_stop = asyncio.Event()


CONCURRENCY = get_settings().worker_concurrency

# How many of one kind this worker will run at once. Anything not listed is unlimited.
#
# The ones listed talk to an external CLI that can stop answering, and a call that never
# returns holds its slot. One each: a wedged one costs a quarter of this worker and the
# rest of the queue — indexing, notifications, credit sweeps — keeps moving.
KIND_LIMITS = {"memory.distill": 1, "notify.evaluate": 2, "relay.hop": 2, "downloads.mirror": 1}

# …and how many slots one *class* of work may hold, which is the limit that was missing.
# Per-kind ceilings did nothing for the ordinary case: importing twenty documents put four
# knowledge.index jobs in four slots and nothing else ran until they finished. The thread
# pools do not help here — a worker slot is the scarce resource, not a thread.
#
# Four classes, because "not documents" turned out to be several different things:
#   docs         long, bursty, CPU-bound — one job per file in an import
#   community    ranking and board upkeep
#   crawl        fetching someone else's website for the places map: slow by nature
#   interactive  short work a person is waiting on — a notification, an email
def _share(fraction: float, at_least: int = 1) -> int:
    return max(at_least, int(CONCURRENCY * fraction))


# Derived from CONCURRENCY rather than written out, so raising the worker's width does not
# quietly leave every class pinned at its old number.
CLASS_LIMITS = {"docs": _share(0.4), "community": _share(0.25), "crawl": _share(0.4),
                "interactive": _share(0.5), "relay": _share(0.25)}

#: Slots the long classes may never take, whatever else is queued. A ceiling stops one
#: class monopolising the worker but does not promise anyone a turn: with every other class
#: at its limit, a notification someone is waiting for still queues behind work that takes
#: minutes. This is the floor that ceilings cannot express.
RESERVED = {"interactive": 1}

KIND_CLASS = {"knowledge.index": "docs", "files.ingest": "docs", "files.sweep": "docs", "retention.purge_memory": "docs", "retention.sweep": "docs",
              "integration.sync": "docs", "calendar.sync": "docs", "calendar.autosync": "docs", "integrations.autosync": "docs",
              "community.rank": "community",
              "notify.send": "interactive", "post.secretary_reply": "interactive", "post.describe_photos": "interactive", "mail.send": "interactive", "admin.notify": "interactive"}

#: Matched on a prefix, so a class can exist before its handlers do — the places-map
#: crawlers register as ``crawl.*`` and are budgeted from the day the class is named.
CLASS_PREFIX = (("crawl.", "crawl"), ("community.", "community"), ("relay.", "relay"))


def _class_of(kind: str) -> str | None:
    cls = KIND_CLASS.get(kind)
    if cls:
        return cls
    for prefix, name in CLASS_PREFIX:
        if kind.startswith(prefix):
            return name
    return None


def _kinds_in(classes: set[str]) -> set[str]:
    """Every *named* kind belonging to these classes.

    Prefix-only classes cannot be enumerated — there is no list of ``crawl.*`` kinds — so
    a reservation is expressed as "exclude everything we know is not interactive", which is
    why the reserved classes are the ones with named kinds.
    """
    return {k for k, c in KIND_CLASS.items() if c in classes}


def _blocked(in_flight: dict[str, int], free_slots: int | None = None) -> tuple[list[str], list[str]]:
    """What this worker will not claim right now, as (kinds, kind prefixes).

    Three reasons a kind is held back: it is at its own ceiling, its class is at the class
    ceiling, or the worker is down to its reserved slots and this is not what they are for.
    """
    full = {k for k, limit in KIND_LIMITS.items() if in_flight.get(k, 0) >= limit}
    prefixes: set[str] = set()
    per_class: dict[str, int] = {}
    for kind, n in in_flight.items():
        # _class_of, not the exact map: a prefix-only class has no entry there, so tallying
        # from KIND_CLASS meant `crawl.*` jobs never counted towards the crawl ceiling and
        # the class limit silently did nothing.
        cls = _class_of(kind)
        if cls and n:
            per_class[cls] = per_class.get(cls, 0) + n
    for cls, limit in CLASS_LIMITS.items():
        if per_class.get(cls, 0) >= limit:
            full |= {k for k, c in KIND_CLASS.items() if c == cls}
            prefixes |= {p for p, c in CLASS_PREFIX if c == cls}
    # The floor: while only the reserved slots are left, they are only for the classes the
    # reservation is for.
    if free_slots is not None:
        held = sum(n for kind, n in in_flight.items() if _class_of(kind) in RESERVED)
        owed = sum(n for cls, n in RESERVED.items() if held < n)
        if owed and free_slots <= owed:
            long_classes = {c for c in CLASS_LIMITS if c not in RESERVED}
            full |= _kinds_in(long_classes)
            prefixes |= {p for p, c in CLASS_PREFIX if c in long_classes}
    return sorted(full), sorted(prefixes)


async def run_job(job_id) -> None:
    async with session_scope("worker") as db:
        job = await db.get(Job, job_id)
        if job is None:
            return
        kind, payload = job.kind, dict(job.payload or {})
        fn = HANDLERS.get(kind)
        if fn is None:
            await J.fail(db, job, f"no handler for {kind}")
            job.status = "dead"
            return
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(fn(db, payload), timeout=900)
            await J.finish(db, job, result=result if isinstance(result, dict) else {"result": str(result)[:500]})
            log.info("job done", kind=kind, ms=int((time.monotonic() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            await db.rollback()
            job = await db.get(Job, job_id)
            await J.fail(db, job, f"{e.__class__.__name__}: {e}")
            # The class name, not just the message: a TimeoutError has none, and "err: \"\""
            # in the log is how an hour goes into finding out which line hung.
            log.warning("job failed", kind=kind, attempts=job.attempts, err=f"{e.__class__.__name__}: {e}"[:300])


async def poll_loop(worker_id: str, concurrency: int = CONCURRENCY) -> None:
    sem = asyncio.Semaphore(concurrency)
    running: set[asyncio.Task] = set()
    in_flight: dict[str, int] = {}
    while not _stop.is_set():
        # The slot first, then the claim. Claiming first marked a job `running` in the
        # database and then waited for a slot, so the queue view showed work that was not
        # being done and `oldest_running_s` counted time nobody was spending.
        await sem.acquire()
        claimed = None
        try:
            # Free slots counted from what is running, including the one just acquired —
            # the semaphore knows this too, but only privately.
            skip, skip_prefixes = _blocked(in_flight, CONCURRENCY - sum(in_flight.values()))
            async with session_scope("worker") as db:
                job = await J.claim(db, worker_id, exclude=skip or None, exclude_prefixes=skip_prefixes or None)
                claimed = (job.id, job.kind) if job else None
        except Exception as e:  # noqa: BLE001
            log.warning("claim failed", err=str(e)[:200])
            sem.release()
            await asyncio.sleep(3)
            continue
        if claimed is None:
            sem.release()
            await asyncio.sleep(1.0)
            continue
        job_id, job_kind = claimed
        in_flight[job_kind] = in_flight.get(job_kind, 0) + 1

        async def _run(jid, kind):
            try:
                await run_job(jid)
            finally:
                in_flight[kind] = max(0, in_flight.get(kind, 0) - 1)
                sem.release()

        task = asyncio.create_task(_run(job_id, job_kind))
        running.add(task)
        task.add_done_callback(running.discard)
    if running:
        await asyncio.wait(running, timeout=30)


async def _seed_schedule(last: dict[str, float]) -> None:
    """Start each schedule's clock from its last job in the database, not from zero.

    With in-memory clocks every restart fired every schedule at once — and in development
    there are many restarts a day. The daily company collection was starting on each
    deploy, running into the next deploy, and never finishing anything.
    """
    now = time.monotonic()
    with contextlib.suppress(Exception):
        async with session_scope() as db:
            for kind, every, _ in SCHEDULE:
                at = await J.last_enqueued_at(db, kind)
                if at is None:
                    continue
                elapsed = (datetime.now(UTC) - at).total_seconds()
                if 0 <= elapsed < every:
                    last[kind] = now - elapsed


async def schedule_loop() -> None:
    last: dict[str, float] = {}
    await _seed_schedule(last)
    while not _stop.is_set():
        now = time.monotonic()
        if now - last.get("_reaper", 0) >= 300:
            last["_reaper"] = now
            with contextlib.suppress(Exception):
                async with session_scope() as db:
                    n = await J.requeue_stale(db, minutes=20)
                    if n:
                        log.warning("requeued stale running jobs", count=n)
        for kind, every, dedupe in SCHEDULE:
            if now - last.get(kind, 0) >= every:
                last[kind] = now
                with contextlib.suppress(Exception):
                    async with session_scope() as db:
                        await J.enqueue(db, kind, {}, priority=9, dedupe_key=f"sched:{kind}" if dedupe else None, max_attempts=1)
        await asyncio.sleep(30)


HEARTBEAT_FILE = "/.worker-alive"


def _touch_liveness() -> None:
    """Filesystem twin of the DB heartbeat: the container healthcheck reads this.

    autoheal and the pgrep healthcheck are gone (docker.sock exposure / no procps), so
    without this a wedged-but-running worker would look healthy to docker forever.
    """
    import contextlib

    from memora.config import get_settings
    with contextlib.suppress(Exception):
        path = get_settings().data_dir / HEARTBEAT_FILE.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(int(time.time())))


async def heartbeat_loop(worker_id: str) -> None:
    while not _stop.is_set():
        _touch_liveness()
        with contextlib.suppress(Exception):
            async with session_scope("worker") as db:
                await db.execute(insert(WorkerHeartbeat).values(worker_id=worker_id, last_seen_at=datetime.now(UTC), info={"handlers": len(HANDLERS)})
                                 .on_conflict_do_update(index_elements=["worker_id"], set_={"last_seen_at": datetime.now(UTC)}))
        # The worker's pools and connection lanes live in this process and are on no screen
        # otherwise — this is the only place they can come from (plan/32 §6).
        with contextlib.suppress(Exception):
            from memora.services import procstats as PS
            async with session_scope("worker") as db:
                await PS.publish(db, "worker")
        await asyncio.sleep(30)


async def main() -> None:
    s = get_settings()
    validate_security_settings()
    setup_logging(s.log_level)
    # Without this the worker's `loop_lag()` is time-since-import, not lag: nothing ticks
    # the clock it subtracts from. It reported a growing three-minute stall on an idle
    # worker, which is worse than reporting nothing.
    install_loop_watchdog()
    try:
        async with session_scope() as db:
            await verify_encryption_keys(db)
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001
        log.warning("could not verify encryption keys at startup")
    worker_id = f"{s.worker_id}-{os.getpid()}"
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop.set)
    log.info("worker up", worker_id=worker_id, handlers=sorted(HANDLERS))
    # Nothing of ours can be running: this process has only just started. A collection
    # killed by a restart otherwise reads as "still collecting" for ever and blocks the
    # next one (plan/33).
    with contextlib.suppress(Exception):
        from memora.services.companies.collect import close_abandoned
        async with session_scope("worker") as db:
            n = await close_abandoned(db)
            if n:
                log.info("closed collections abandoned by a restart", n=n)
    await asyncio.gather(poll_loop(worker_id), schedule_loop(), heartbeat_loop(worker_id))
    log.info("worker down")


if __name__ == "__main__":
    asyncio.run(main())
