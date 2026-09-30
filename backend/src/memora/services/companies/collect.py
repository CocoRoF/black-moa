"""Running a collection, and recording what it did (plan/33 §3).

One entry point for every source, so the admin screen, the worker handler and the tests
all take the same path. Each run leaves a row behind whether it worked or not — a source
that has been failing quietly for a week is the thing an operator most needs to see, and
"last run: never" tells them nothing about why.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.logging import get_logger
from memora.models import Company, CompanySourceRun
from memora.services import settings as S
from memora.services.companies import dart, krx, nts
from memora.services.companies.dart import NeedsKey
from memora.services.companies.merge import apply_rows

log = get_logger("memora.companies.collect")

#: Sources, in the order the admin screen lists them, cheapest and most useful first.
#: ``needs_key`` names the setting an administrator has to fill before the source can run —
#: the first one is deliberately ``None``, so the directory is populated before anybody has
#: registered for anything.
SOURCES: dict[str, dict[str, Any]] = {
    "krx": {
        "label": "한국거래소 상장법인목록", "needs_key": None,
        "note": "키 없이 바로 모을 수 있어요. 상장사 전체의 회사명, 종목코드, 업종, 지역, 대표자, 홈페이지",
        "where": None,
    },
    "dart_codes": {
        "label": "DART 공시대상 회사 목록", "needs_key": "companies.dart_key",
        "note": "비상장을 포함한 전체 법인 목록과 종목코드에 맞는 고유번호. 한 번이면 끝나요",
        "where": "https://opendart.fss.or.kr (무료·즉시 발급)",
    },
    "dart": {
        "label": "DART 기업개요", "needs_key": "companies.dart_key",
        "note": "사업자등록번호, 주소, 전화, 설립일. 회사마다 한 번씩이라 하루 한도 안에서 나눠 모아요",
        "where": "https://opendart.fss.or.kr (무료·즉시 발급)",
    },
    "nts": {
        "label": "국세청 사업자등록 상태", "needs_key": "companies.data_go_kr_key",
        "note": "계속·휴업·폐업 상태. 폐업 여부를 알 수 있는 유일한 출처예요",
        "where": "https://www.data.go.kr (사업자등록정보 진위확인 및 상태조회)",
    },
}


async def _collect(db: AsyncSession, source: str, record: CompanySourceRun | None = None,
                   apply: Callable[[list[dict[str, Any]]], Awaitable[dict[str, int]]] | None = None,
                   continuation: dict[str, Any] | None = None,
                   ) -> list[dict[str, Any]]:
    """Rows from one source, in the shape ``apply_rows`` merges.

    A source that collects for a long time is handed ``apply`` and uses it per chunk
    instead of returning everything: an hour of fetching followed by one merge loses the
    whole hour if the job dies, and shows nothing changing while it runs.
    """
    if source == "krx":
        return await krx.fetch()

    if source == "dart_codes":
        key = await S.get(db, "companies.dart_key")
        return await dart.fetch_codes(key)

    if source == "dart":
        key = await S.get(db, "companies.dart_key")
        if not key:
            raise NeedsKey("DART 키가 없어요")
        budget = await dart_budget(db)
        if budget <= 0:
            raise Budgeted("오늘 DART 한도를 모두 썼어요. 내일 이어서 모아요.")
        due = await dart.due_for_details(db, budget)
        applied = {"created": 0, "updated": 0, "skipped": 0}
        deadline = time.monotonic() + RUN_DEADLINE_S
        done = 0
        for i in range(0, len(due), dart.BATCH):
            chunk: list[dict[str, Any]] = []
            for corp_code, _ in due[i:i + dart.BATCH]:
                # The clock is checked per call, not per chunk: a hundred slow answers in
                # one chunk used to carry a run past the worker's limit before the chunk
                # ever ended, and the kill threw the chunk away.
                if time.monotonic() > deadline:
                    break
                detail = await dart.fetch_company(key, corp_code)
                done += 1
                if detail:
                    chunk.append({**detail, "corp_code": corp_code})
                await asyncio.sleep(dart.GAP_S)
            # The spend is written before the merge: those calls are gone whether or not
            # the rows go in, and the day's budget must know.
            if record is not None:
                record.fetched = done
            # One chunk's merge failing is one chunk lost, not the run. A savepoint keeps
            # the record and the earlier chunks; the error is noted and the run goes on.
            if chunk and apply is not None:
                try:
                    async with db.begin_nested():
                        counts = await apply(chunk)
                    for k in applied:
                        applied[k] += counts.get(k, 0)
                except Exception as e:  # noqa: BLE001 — a bad row, kept out of the run's way
                    log.warning("a chunk failed to merge; skipped", source=source, at=i, err=f"{e.__class__.__name__}: {e}"[:300])
                    if record is not None:
                        record.error = f"{i}번째 묶음을 저장하지 못했어요"[:500]
            if record is not None:
                record.created, record.updated, record.skipped = (
                    applied["created"], applied["updated"], applied["skipped"])
            await db.commit()
            if time.monotonic() > deadline:
                log.info("stopping inside the job's time budget", source=source, done=done, of=len(due))
                if continuation is not None and done < len(due):
                    continuation["more"] = len(due) - done
                break
        return []      # already applied, chunk by chunk

    if source == "nts":
        key = await S.get(db, "companies.data_go_kr_key")
        if not key:
            raise NeedsKey("공공데이터포털 키가 없어요")
        numbers = await nts.due_for_check(db, nts.BATCH * 20)
        applied = {"created": 0, "updated": 0, "skipped": 0}
        deadline = time.monotonic() + RUN_DEADLINE_S
        done = 0
        for i in range(0, len(numbers), nts.BATCH):
            if time.monotonic() > deadline:
                break
            batch = numbers[i:i + nts.BATCH]
            rows: list[dict[str, Any]] = []
            # The service times out now and then; one such answer used to end a run of
            # twenty batches. Three tries, then that batch is skipped and the next goes.
            for attempt in range(3):
                try:
                    rows = await nts.check(key, batch)
                    break
                except (TimeoutError, OSError) as e:
                    log.info("nts batch retry", at=i, attempt=attempt + 1, err=str(e)[:120])
                    await asyncio.sleep(2.0 * (attempt + 1))
            done += len(batch)
            if record is not None:
                record.fetched = done
            if rows and apply is not None:
                try:
                    async with db.begin_nested():
                        counts = await apply(rows)
                    for k in applied:
                        applied[k] += counts.get(k, 0)
                except Exception as e:  # noqa: BLE001
                    log.warning("an nts batch failed to merge; skipped", at=i, err=f"{e.__class__.__name__}: {e}"[:300])
            if record is not None:
                record.created, record.updated, record.skipped = (
                    applied["created"], applied["updated"], applied["skipped"])
            await db.commit()
            await asyncio.sleep(0.2)
        return []      # applied batch by batch

    raise RuntimeError(f"unknown source: {source}")


#: A collection stops itself after this long and reports what it did. The worker gives a
#: job 900 seconds; a run that ignores that is killed mid-merge, which is how 5,300 DART
#: calls were spent and none of them recorded. Finishing early and continuing next time is
#: strictly better than being killed.
RUN_DEADLINE_S = 600.0


class Budgeted(RuntimeError):
    """The day's allowance is spent. Not a failure — a boundary, reported as one."""


async def dart_budget(db: AsyncSession) -> int:
    """How many DART calls this run may make: the per-run cap, capped again by whatever is
    left of the day."""
    per_run = int(await S.get(db, "companies.dart_per_run") or 1000)
    daily = int(await S.get(db, "companies.dart_daily_limit") or 10000)
    spent = int((await db.execute(text("""
        SELECT coalesce(sum(fetched), 0) FROM company_source_runs
        WHERE source = 'dart' AND started_at >= date_trunc('day', now())
    """))).scalar_one() or 0)
    return max(0, min(per_run, daily - spent))


async def in_flight(db: AsyncSession, source: str) -> bool:
    """Whether a run of this source is already going.

    Two collections of the same source at once is duplicated work and, worse, duplicated
    quota: both compute their candidate list at the start, so they fetch largely the same
    companies and spend twice the allowance doing it. Observed with two `dart` jobs running
    together, each budgeted for the whole day.
    """
    return bool((await db.execute(text("""
        SELECT 1 FROM company_source_runs
        -- Just over the worker's 900-second job timeout: a run killed by it leaves its row
        -- open, and blocking every later collection for hours because of that is worse than
        -- the duplicate this guard exists to prevent.
        WHERE source = :s AND finished_at IS NULL AND started_at > now() - interval '20 minutes'
        LIMIT 1
    """), {"s": source})).first())


async def ran_recently(db: AsyncSession, source: str, *, hours: int = 20) -> bool:
    """Whether this source finished a successful run within the window — what the daily
    pass checks so a worker restart does not start the day over."""
    return bool((await db.execute(text("""
        SELECT 1 FROM company_source_runs
        WHERE source = :s AND ok = true AND finished_at > now() - make_interval(hours => :h)
        LIMIT 1
    """), {"s": source, "h": hours})).first())


async def _close_record(record_id, *, ok: bool | None, error: str | None,
                        counts: dict[str, int] | None = None, fetched: int | None = None) -> None:
    """Write the run's end in a session of its own.

    The run's session may be anything by now — mid-transaction, rolled back after a failed
    flush, cancelled — and a record that only closes when that session is healthy is a
    record that stays open ("수집 중…") until the next boot. This one always closes.
    """
    from memora.db.session import session_scope

    async with session_scope("worker") as db:
        rec = await db.get(CompanySourceRun, record_id)
        if rec is None:
            return
        if rec.finished_at is None:
            rec.finished_at = datetime.now(UTC)
        rec.ok = ok
        if error:
            rec.error = error[:500]
        if fetched is not None and fetched > rec.fetched:
            rec.fetched = fetched
        if counts:
            rec.created, rec.updated, rec.skipped = counts["created"], counts["updated"], counts["skipped"]
        await db.commit()


async def run(db: AsyncSession, source: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Collect from one source. Never raises on its own account: the outcome is the return
    value and the row. Cancellation (the job timeout, a worker going down) is let through
    — after the row is closed, so the screen never shows a run that is not there.

    A `dart` run that stops at its time budget with companies left and allowance left
    queues its own continuation, so a day's enrichment is a chain of short jobs, each of
    which a restart can only cost a chunk.
    """
    from memora.services import jobs as J

    payload = payload or {}
    spec = SOURCES.get(source)
    if spec is None:
        return {"ok": False, "error": f"unknown source: {source}"}
    if await in_flight(db, source):
        log.info("a collection of this source is already running", source=source)
        return {"ok": False, "source": source, "busy": True, "error": "이미 수집이 돌고 있어요"}

    started = datetime.now(UTC)
    record = CompanySourceRun(source=source, started_at=started)
    db.add(record)
    # Committed now, not at the end. A run that takes three minutes was invisible for all
    # of them: the row lived in the job's uncommitted transaction, so the screen showed the
    # previous run and an operator watching had no way to tell the difference between
    # "working" and "nothing happened".
    await db.commit()
    await db.refresh(record)
    record_id = record.id

    merge_as = "dart" if source == "dart_codes" else source

    async def apply(chunk: list[dict[str, Any]]) -> dict[str, int]:
        return await apply_rows(db, merge_as, chunk)

    continuation: dict[str, Any] = {}
    try:
        rows = await _collect(db, source, record, apply, continuation)
        # Every source goes through the same merge with its own field ownership. One that
        # applied its own chunks returns nothing and has already filled the record in.
        counts = await apply(rows) if rows else {"created": record.created, "updated": record.updated,
                                                 "skipped": record.skipped}
        fetched = len(rows) if rows else record.fetched
        note = record.error
        await db.commit()
        await _close_record(record_id, ok=True, error=note, counts=counts, fetched=fetched)
        log.info("collected companies", source=source, **counts, fetched=fetched)
        out = {"ok": True, "source": source, "fetched": fetched, **counts}
        if continuation.get("more"):
            # The next slice, a few seconds from now, as its own job. Deduped on the run
            # it continues from, so a retry of this job cannot queue it twice.
            job = await J.enqueue(db, "crawl.companies", {"source": source, "continue": str(record_id)},
                                  delay_s=5, dedupe_key=f"companies:{source}:continue:{record_id}", max_attempts=2)
            await db.commit()
            out["continued"] = job is not None
            out["remaining"] = int(continuation["more"])
            log.info("collection continues in a new job", source=source, remaining=continuation["more"])
    except Budgeted as e:
        # Nothing went wrong; there was simply nothing left today.
        await db.rollback()
        await _close_record(record_id, ok=True, error=str(e))
        log.info("dart daily budget spent", source=source)
        out = {"ok": True, "source": source, "budget_spent": True, "note": str(e)}
    except NeedsKey as e:
        # Not a failure of the collector: something an administrator has not done. Recorded
        # as a run so the screen can say which key is missing rather than showing a stack.
        await db.rollback()
        await _close_record(record_id, ok=False, error=str(e))
        log.info("company source needs a key", source=source, err=str(e)[:200])
        out = {"ok": False, "source": source, "needs_key": True, "error": str(e)[:500]}
    except asyncio.CancelledError:
        # The job timeout or the worker going down. Close the row honestly and let the
        # cancellation through — the job layer requeues, and the next run resumes.
        # No attribute of `record` is read here: after a cancel the session is not to be
        # trusted, and the spend was committed chunk by chunk anyway.
        await _close_record(record_id, ok=False, error="중단됨. 시간이 다 되었거나 서버가 다시 시작됐어요")
        raise
    except Exception as e:  # noqa: BLE001 — a failed collection is data, not a crash
        err = f"{e.__class__.__name__}: {e}"[:500]
        await db.rollback()
        # Nothing is read off `record` after the rollback: its attributes are expired and
        # loading one here is IO in an except clause. The row keeps what was committed.
        await _close_record(record_id, ok=False, error=err)
        log.warning("company collection failed", source=source, err=err)
        out = {"ok": False, "source": source, "error": err}
    return out


async def coverage(db: AsyncSession) -> dict[str, Any]:
    """How complete the directory is, field by field — each against the population that
    can actually have that field.

    A single denominator lies here. The regulator's dictionary contributes 115,000 unlisted
    companies and carries no industry or region, so measuring industry against everything
    reported 2.3% the moment it landed — which reads as a catastrophe and means "we have
    industry for every listed company, and the dictionary never had any". Each field is
    therefore measured against what could hold it.
    """
    total = (await db.execute(select(func.count()).select_from(Company))).scalar_one() or 0
    #: Currently traded, which is `market` — set by the exchange. A stock code is not the
    #: same test: the regulator keeps one for every company that ever listed, so using it
    #: put 1,231 delisted companies in this count.
    listed = (await db.execute(select(func.count()).select_from(Company)
                               .where(Company.market != ""))).scalar_one() or 0
    #: Companies the exchange has reported at all. This, not "listed", is the population
    #: that can have an industry or a region: only the exchange supplies them, so measuring
    #: against anything else gives a figure over 100% or well under the truth.
    from_krx = (await db.execute(select(func.count()).select_from(Company)
                                 .where(Company.sources.has_key("krx")))).scalar_one() or 0
    with_biz = (await db.execute(select(func.count()).select_from(Company)
                                 .where(Company.biz_no.is_not(None)))).scalar_one() or 0
    #: Companies a reader is shown. The same expression the directory filters by, imported
    #: rather than restated — written twice, the two drifted and the panel reported 3,990
    #: visible while the directory showed a different set.
    from memora.services.companies.query import substantive

    visible = (await db.execute(select(func.count()).select_from(Company)
                                .where(Company.hidden.is_(False), substantive()))).scalar_one() or 0

    counts = (await db.execute(select(
        func.count().filter(func.jsonb_array_length(Company.industry_codes) > 0),
        func.count().filter(Company.region_code != ""),
        func.count().filter(Company.corp_code.is_not(None)),
        func.count().filter(Company.biz_no.is_not(None)),
        func.count().filter(Company.address != ""),
        func.count().filter(Company.status != "unknown"),
        func.count().filter(Company.status == "closed"),
        func.count().filter(func.jsonb_array_length(Company.locked_fields) > 0),
    ))).one()
    names = ("industry_codes", "region_code", "corp_code", "biz_no", "address",
             "status_known", "closed", "hand_corrected")
    fields = {n: int(c or 0) for n, c in zip(names, counts, strict=True)}

    #: What each field is measured against, and why.
    of = {"industry_codes": from_krx, "region_code": from_krx,   # only the exchange supplies these
          "corp_code": total, "biz_no": total, "address": total,
          "status_known": with_biz}                           # can only ask about a registered number
    return {"total": int(total), "listed": int(listed), "visible": int(visible),
            "from_krx": int(from_krx),
            "fields": fields,
            "pct": {n: (round(100 * fields[n] / of[n], 1) if of.get(n) else 0.0) for n in of},
            "of": {n: int(v) for n, v in of.items()},
            "filled_by": {"industry_codes": "krx", "region_code": "krx", "corp_code": "dart_codes",
                          "biz_no": "dart", "address": "dart", "status_known": "nts"}}


async def status(db: AsyncSession) -> dict[str, Any]:
    """What the admin screen shows: every source, its last run, and the directory's size."""
    total = (await db.execute(select(func.count()).select_from(Company))).scalar_one()
    by_market = dict((await db.execute(
        select(Company.market, func.count()).group_by(Company.market).order_by(func.count().desc())
    )).all())
    auto = bool(await S.get(db, "companies.auto_collect"))
    sources = []
    for name, spec in SOURCES.items():
        runs = (await db.execute(
            select(CompanySourceRun).where(CompanySourceRun.source == name)
            .order_by(CompanySourceRun.started_at.desc()).limit(8)
        )).scalars().all()
        last = runs[0] if runs else None
        setting = spec["needs_key"]
        sources.append({
            "source": name, "label": spec["label"], "note": spec["note"],
            "needs_key": setting, "where": spec.get("where"),
            # Whether the key is actually there, so the screen distinguishes "not set up"
            # from "set up and failing" — which are different problems with different fixes.
            "key_set": True if setting is None else bool(await S.get(db, setting)),
            "history": [{"at": r.started_at.isoformat(), "ok": r.ok, "fetched": r.fetched,
                         "created": r.created, "updated": r.updated,
                         "running": r.finished_at is None,
                         "seconds": None if r.finished_at is None else
                         round((r.finished_at - r.started_at).total_seconds(), 1)} for r in runs],
            "last_run": None if last is None else {
                "at": last.started_at.isoformat(), "ok": last.ok,
                "fetched": last.fetched, "created": last.created, "updated": last.updated,
                "skipped": last.skipped, "error": last.error,
                "seconds": None if last.finished_at is None else round((last.finished_at - last.started_at).total_seconds(), 1),
            },
        })
    return {"total": int(total), "by_market": {k or "비상장": int(v) for k, v in by_market.items()},
            "sources": sources, "auto_collect": auto, "enabled": bool(await S.get(db, "companies.enabled")),
            # The DART budget, so the screen can show and change it next to the source it
            # governs rather than sending an operator to a settings list.
            "dart_per_run": int(await S.get(db, "companies.dart_per_run") or 1000),
            "dart_daily_limit": int(await S.get(db, "companies.dart_daily_limit") or 10000),
            "dart_spent_today": int((await db.execute(text("""
                SELECT coalesce(sum(fetched), 0) FROM company_source_runs
                WHERE source = 'dart' AND started_at >= date_trunc('day', now())
            """))).scalar_one() or 0),
            "coverage": await coverage(db)}


async def close_abandoned(db: AsyncSession) -> int:
    """Close run records left open by a process that is no longer here.

    A worker restart — a deploy, a crash, the job timeout — kills a collection mid-flight
    and its row stays `finished_at IS NULL` for ever, which reads as "still collecting" on
    the screen and blocks the next run through the single-flight guard. Only the worker
    calls this, at boot, when it can be certain nothing of its own is running.
    """
    r = await db.execute(text("""
        UPDATE company_source_runs
        SET finished_at = now(), ok = false,
            error = coalesce(error, '중단됨. 서버가 다시 시작됐어요')
        WHERE finished_at IS NULL
    """))
    return int(r.rowcount or 0)
