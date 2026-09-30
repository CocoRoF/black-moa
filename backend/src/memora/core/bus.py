"""A live event bus over Postgres LISTEN/NOTIFY.

Several backend pods serve this app, and the pod that creates an inbox item is rarely the
one holding that user's open stream. An in-process pub/sub would deliver to whoever
happened to be connected locally and silently drop the rest — which looks exactly like
"notifications sometimes don't arrive". Postgres is already the one thing every pod shares,
so it carries the fan-out; no new broker to run or lose.

Payloads are small and advisory: a client that misses one still sees the truth on its next
fetch. NOTIFY has an 8000-byte limit and is not durable, so nothing here is a source of
record.
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.database import manager as dbm
from memora.core.logging import get_logger

log = get_logger("memora.bus")
CHANNEL = "memora_events"

_subs: dict[uuid.UUID, set[asyncio.Queue]] = {}
_task: asyncio.Task | None = None


# NOTIFY refuses a payload of 8000 bytes or more. Korean is three bytes a character, so the
# limit is counted in bytes, with room to spare.
MAX_BYTES = 7600
LONG_TEXT = 600


def _shrink(v: Any) -> Any:
    if isinstance(v, str):
        return v if len(v) <= LONG_TEXT else v[:LONG_TEXT]
    if isinstance(v, dict):
        return {k: _shrink(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_shrink(x) for x in v[:20]]
    return v


def encode(owner_id: uuid.UUID, kind: str, data: dict[str, Any]) -> str:
    """The NOTIFY body, always whole JSON under the byte limit (plan/69).

    It used to be cut at 7000 *characters*: a long Korean answer went over the byte limit
    (the NOTIFY then failed inside the caller's transaction) or was cut mid-JSON (and every
    listener dropped it). Too big now means: long strings are shortened and the event says
    `truncated`, so a client knows to fetch the real thing. Ids are never lost.
    """
    body = json.dumps({"owner": str(owner_id), "kind": kind, "data": data}, ensure_ascii=False)
    if len(body.encode()) <= MAX_BYTES:
        return body
    small = {**_shrink(data), "truncated": True}
    body = json.dumps({"owner": str(owner_id), "kind": kind, "data": small}, ensure_ascii=False)
    if len(body.encode()) <= MAX_BYTES:
        return body
    ids = {k: v for k, v in data.items() if isinstance(v, (str, int, float, bool)) and len(str(v)) <= 80}
    return json.dumps({"owner": str(owner_id), "kind": kind, "data": {**ids, "truncated": True}}, ensure_ascii=False)


async def publish(db: AsyncSession, *, owner_id: uuid.UUID, kind: str, data: dict[str, Any]) -> None:
    """Announce something that just happened. Never raises into the caller's transaction —
    a missed nudge must not roll back the thing it was announcing. The NOTIFY runs in a
    savepoint: a failure there would otherwise leave the whole transaction aborted, and the
    turn or message it was announcing would not be saved."""
    body = encode(owner_id, kind, data)
    try:
        async with db.begin_nested():
            await db.execute(text("SELECT pg_notify(:ch, :body)"), {"ch": CHANNEL, "body": body})
    except Exception as e:  # noqa: BLE001
        log.warning("bus publish failed", err=str(e)[:200])


@contextlib.asynccontextmanager
async def subscribe(owner_id: uuid.UUID) -> AsyncIterator[asyncio.Queue]:
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subs.setdefault(owner_id, set()).add(q)
    try:
        yield q
    finally:
        subs = _subs.get(owner_id)
        if subs is not None:
            subs.discard(q)
            if not subs:
                _subs.pop(owner_id, None)


def _fanout(payload: str) -> None:
    try:
        msg = json.loads(payload)
        owner = uuid.UUID(msg["owner"])
    except Exception:  # noqa: BLE001
        return
    for q in list(_subs.get(owner, ())):
        # A stream nobody is draining must not hold up the listener for everyone else.
        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(msg)


def _set(event: asyncio.Event, *_a: Any) -> None:
    event.set()


def _return_to_pool(raw: Any) -> None:
    """Hand the listener's checkout back. A connection that is only dropped is not freed
    until the garbage collector gets to it, one terminated connection at a time — which is
    what a listener that reconnects every few seconds turns into."""
    if raw is not None:
        with contextlib.suppress(Exception):
            raw.close()


async def _listen_forever() -> None:
    while True:
        raw = None
        try:
            # Asked of the manager each time round, never captured: a rebuilt engine
            # would otherwise leave the listener holding a disposed one and retrying
            # against it forever — silently, since the only symptom is notifications that
            # stop arriving.
            raw = await dbm.engine.raw_connection()
            # `raw` is SQLAlchemy's pool proxy (_ConnectionFairy) and `driver_connection`
            # is the asyncpg connection underneath it — the one that can actually LISTEN.
            # There is no `get_raw_connection` on the proxy; asking for one raised on every
            # single attempt, so this listener never attached and every notification the
            # app published was dropped. The bell only moved on the next poll.
            conn = raw.driver_connection
            await conn.add_listener(CHANNEL, lambda *a: _fanout(a[-1]))
            # Asked to be told the moment the connection dies, rather than finding out on
            # the next poll. Polling alone meant a restart cost up to half a minute of
            # silently dropped notifications — the listener was gone and nothing knew.
            lost: asyncio.Event = asyncio.Event()
            with contextlib.suppress(Exception):
                conn.add_termination_listener(functools.partial(_set, lost))
            log.info("bus listening", channel=CHANNEL)
            while True:
                # The poll stays as the belt to that braces: a connection can also go quiet
                # without ever announcing it.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(lost.wait(), timeout=5)
                if lost.is_set() or conn.is_closed():
                    raise ConnectionError("listener connection closed")
        except asyncio.CancelledError:
            _return_to_pool(raw)
            raise
        except Exception as e:  # noqa: BLE001
            _return_to_pool(raw)
            log.warning("bus listener restarting", err=str(e)[:200])
            await asyncio.sleep(3)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_listen_forever())


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
