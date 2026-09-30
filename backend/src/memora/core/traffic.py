"""Every API request, measured — and every one still running, visible.

Two things an operator needs when the server feels slow, and neither existed: a record of
what has been served, and a list of what is being served *right now*. The second is the one
that finds a bad call: a request that has been open for four minutes is on the live list
with its route, its caller and its elapsed time, next to the loop lag it caused.

Cost discipline, because measuring traffic must never be why traffic is slow:
  * timing is two clock reads and a dict entry;
  * rows go to a bounded in-memory buffer and are written in batches by a background task,
    after the response has been sent — a full buffer drops rows rather than waiting;
  * health and dashboard reads never touch the request path.
"""
from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from starlette.types import ASGIApp

from memora.core.logging import get_logger
from memora.core.watchdog import loop_lag

log = get_logger("memora.traffic")

# The classes of work that must not block each other. A request is put in one of these by
# its path, so saturation can be read per class rather than as one average.
LANES = ("chat", "docs", "admin", "community", "public", "other")

#: A request that has not produced headers in this long is reported as abnormal without
#: waiting for it to end — whatever it is doing, nothing should take five minutes to begin
#: answering.
STUCK_S = 300.0
#: A stream that has been open but silent this long has died mid-answer. Streams are
#: judged on silence rather than duration: a notification stream is legitimately open for
#: as long as the tab is.
SILENT_S = 120.0
_BUFFER_MAX = 5000


def lane_of(path: str) -> str:
    if path.startswith("/api/admin"):
        return "admin"
    if path.startswith("/api/community"):
        return "community"
    if "/turns" in path or path.startswith(("/api/chat", "/api/agents")) and "/conversations" in path:
        return "chat"
    if path.startswith(("/api/knowledge", "/api/uploads")):
        return "docs"
    if path.startswith("/api/public"):
        return "public"
    if path.startswith("/api"):
        return "other"
    return "other"


@dataclass
class Live:
    """A request that has not finished yet."""

    id: str
    route: str
    method: str
    lane: str
    started: float
    ip: str = ""
    owner_id: str | None = None
    responded: bool = False    # headers are out
    streaming: bool = False    # a body arrived with more to follow
    last_at: float = 0.0       # when the last byte went out

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started

    @property
    def silent_s(self) -> float:
        return time.monotonic() - (self.last_at or self.started)

    @property
    def stuck(self) -> bool:
        """Two different failures, and a long stream is neither of them.

        A request that has sent no headers for minutes is holding something. A stream that
        has sent nothing for two minutes has died mid-answer. A notification stream open
        for six hours is a browser tab, and calling that abnormal would bury both.
        """
        if not self.responded:
            return self.elapsed_s > STUCK_S
        return self.streaming and self.silent_s > SILENT_S


@dataclass
class _State:
    live: dict[str, Live] = field(default_factory=dict)
    buffer: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=_BUFFER_MAX))
    dropped: int = 0
    served: int = 0
    by_lane: dict[str, int] = field(default_factory=dict)


_state = _State()


def in_flight() -> list[dict[str, Any]]:
    """What is running now, longest first — the list that finds a stuck call."""
    rows = sorted(_state.live.values(), key=lambda r: r.started)
    return [{"id": r.id, "route": r.route, "method": r.method, "lane": r.lane, "elapsed_ms": round(r.elapsed_s * 1000),
             "ip": r.ip, "owner_id": r.owner_id, "streaming": r.streaming, "silent_ms": round(r.silent_s * 1000),
             "stuck": r.stuck} for r in rows]


def counters() -> dict[str, Any]:
    return {"served": _state.served, "in_flight": len(_state.live), "buffered": len(_state.buffer),
            "dropped": _state.dropped, "by_lane": dict(_state.by_lane)}


def take_batch(limit: int = 500) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while _state.buffer and len(out) < limit:
        out.append(_state.buffer.popleft())
    return out


def _route_of(scope: dict[str, Any]) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return (path or scope.get("path") or "")[:200]


def _client_ip(scope: dict[str, Any]) -> str:
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
    ip = headers.get("cf-connecting-ip") or headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not ip:
        client = scope.get("client")
        ip = client[0] if client else ""
    return ip[:64]


class TrafficMiddleware:
    """Times the request, keeps it on the live list while it runs, buffers the row after.

    Pure ASGI rather than ``BaseHTTPMiddleware`` for one reason: the base class hands
    control back as soon as the *response object* exists, which for a streamed response is
    when the headers are ready. Everything interesting then happened after we had stopped
    watching — an SSE never appeared on the live list at all, a chat turn's recorded time
    was its time-to-first-byte (the chat lane read a p95 of 29ms for turns that ran fifteen
    seconds), and a stream that died mid-answer could never be flagged. Wrapping ``send``
    means the record closes on the last byte, which is when the request is actually over.

    Both numbers are kept, because they answer different questions: ``ttfb_ms`` is how fast
    the API answers, ``ms`` is how long the request held a slot.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or (scope.get("path") or "").startswith(("/health", "/api/health", "/metrics")):
            await self.app(scope, receive, send)
            return
        rid = uuid.uuid4().hex[:12]
        path = scope.get("path") or ""
        lane = lane_of(path)
        rec = Live(id=rid, route=path[:200], method=scope.get("method", ""), lane=lane, started=time.monotonic(),
                   ip=_client_ip(scope))
        _state.live[rid] = rec
        lag0 = loop_lag()
        state = {"status": 500, "ttfb": None, "bytes": 0}

        async def send_wrapper(message: dict) -> None:
            t = message["type"]
            if t == "http.response.start":
                state["status"] = message["status"]
                state["ttfb"] = (time.monotonic() - rec.started) * 1000
                rec.responded = True
                rec.last_at = time.monotonic()
            elif t == "http.response.body":
                state["bytes"] += len(message.get("body") or b"")
                rec.last_at = time.monotonic()
                if message.get("more_body"):
                    rec.streaming = True
            await send(message)

        error: str | None = None
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:  # noqa: BLE001 — recorded, then re-raised for the app's own handler
            error = f"{e.__class__.__name__}: {e}"[:300]
            raise
        finally:
            _state.live.pop(rid, None)
            ms = (time.monotonic() - rec.started) * 1000
            ttfb = state["ttfb"] if state["ttfb"] is not None else ms
            _state.served += 1
            _state.by_lane[lane] = _state.by_lane.get(lane, 0) + 1
            row = {"id": uuid.uuid4(), "route": _route_of(scope)[:200], "method": rec.method, "lane": lane,
                   "status": int(state["status"]), "ms": round(ms, 2), "ttfb_ms": round(float(ttfb), 2),
                   "lag_ms": round(max(0.0, loop_lag() - lag0) * 1000, 2),
                   "owner_id": scope.get("memora_owner_id"), "agent_id": scope.get("memora_agent_id"),
                   "ip": rec.ip, "ua": _ua(scope), "bytes_out": int(state["bytes"]), "error": error}
            if len(_state.buffer) >= _BUFFER_MAX:
                _state.dropped += 1
            else:
                _state.buffer.append(row)
            if ttfb > 10_000:
                log.warning("slow to answer", route=row["route"], lane=lane, ttfb_ms=round(ttfb), status=row["status"])


def _ua(scope: dict[str, Any]) -> str:
    for k, v in scope.get("headers") or []:
        if k == b"user-agent":
            return v.decode("latin-1")[:200]
    return ""
