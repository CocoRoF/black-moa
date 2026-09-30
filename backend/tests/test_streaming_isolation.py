"""A stream must not sit on a database connection while it waits (plan/42).

FastAPI unwinds a request's generator dependencies once the response body is sent. For SSE
that is when the client goes away, so every open stream held a pooled connection — measured
on production as twelve open streams holding twelve of thirty, every one of them
``idle in transaction``, which also stops VACUUM reclaiming anything. At thirty open browser
tabs every request in the service queues for a connection.

The first test watches the pool. The second guards the wiring, because the leak came back
the moment a fifth streaming endpoint was added without the release.
"""
from __future__ import annotations

import pathlib
import re

import pytest

_async = pytest.mark.asyncio


def checked_out() -> int:
    from memora.db.session import engine

    return engine.pool.checkedout()


@_async
async def test_release_db_hands_back_the_session_parked_on_the_request():
    """``release_db`` is the whole mechanism, so it is checked directly.

    Not through a live SSE response: httpx's ASGI transport owns a cancel scope per stream
    and an event-stream generator only notices the reader leaving between messages, so a
    test built on that measures the harness. The pool measurement that found this bug was
    taken against production (`pg_stat_activity`), and is repeated there after deploy.
    """
    from starlette.requests import Request

    from memora.core.deps import release_db

    class Recording:
        closed = False

        async def close(self) -> None:
            self.closed = True

    req = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "state": {}})
    db = Recording()
    req.state.db = db
    await release_db(req)
    assert db.closed

    # A request with no session of its own must not be an error: not every endpoint has one.
    await release_db(Request({"type": "http", "method": "GET", "path": "/", "headers": [], "state": {}}))


@_async
async def test_get_session_parks_the_session_where_release_db_looks_for_it():
    """The two halves of the mechanism have to agree on where the session lives."""
    from memora.db.session import get_session

    seen: dict = {}
    req = _FakeRequest(seen)
    agen = get_session(req)
    session = await anext(agen)
    try:
        assert seen.get("db") is session
    finally:
        await agen.aclose()


class _FakeRequest:
    """Just enough Request: the session is parked on ``state`` and checked out under the
    lane its path belongs to."""

    def __init__(self, sink: dict) -> None:
        self.state = _State(sink)
        self.url = _Url("/api/agents")


class _Url:
    def __init__(self, path: str) -> None:
        self.path = path


class _State:
    def __init__(self, sink: dict) -> None:
        object.__setattr__(self, "_sink", sink)

    def __setattr__(self, k: str, v: object) -> None:
        self._sink[k] = v


def test_every_event_stream_releases_its_request_session():
    """The wiring, checked rather than remembered.

    ``turn_stream`` is the one place a turn's SSE is built and it releases the session
    itself — but only if the caller hands it the request. Any other event-stream response
    has to do it explicitly.
    """
    api = pathlib.Path(__file__).resolve().parents[1] / "src" / "memora" / "api"
    offenders = []
    for f in api.rglob("*.py"):
        src = f.read_text()
        for m in re.finditer(r"turn_stream\((?!turn: )[^)]*\)", src):
            if "request=" not in m.group(0):
                offenders.append(f"{f.name}: {m.group(0)}")
        # an event-stream built anywhere else must release on its own
        if re.search(r"StreamingResponse\([^)]*text/event-stream", src, re.S) and "release_db" not in src:
            offenders.append(f"{f.name}: event-stream without release_db")
    assert not offenders, "streaming endpoints that keep their database session: " + "; ".join(sorted(set(offenders)))


@_async
async def test_an_oversized_upload_is_refused_without_being_held_in_memory():
    """A body at nginx's ceiling used to be read in full and only then measured against a
    limit a fraction of its size. The refusal has to happen while reading."""
    from memora.services import uploads as U

    read = {"bytes": 0}

    class Dribble:
        """Stands in for the request body: endless, so a reader without a ceiling never
        returns and the test would hang rather than fail politely."""

        async def read(self, n: int = -1) -> bytes:
            read["bytes"] += n
            return b"\0" * n

    with pytest.raises(Exception) as e:                      # ValidationFailed
        await U.read_capped(Dribble(), 2 * 1024 * 1024)
    assert "file_too_large" in str(getattr(e.value, "code", "")) or "larger than" in str(e.value)
    # it stopped as soon as the limit was passed, rather than draining the body
    assert read["bytes"] <= 4 * 1024 * 1024, f"read {read['bytes']} bytes for a 2MB limit"
