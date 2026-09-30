"""Turn journal: seq-numbered events, live fan-out, PG persistence, SSE encoding (plan/18)."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from memora.core.logging import get_logger
from memora.db.session import session_scope
from memora.models import Turn, TurnEvent

log = get_logger("memora.journal")
TERMINAL = {"turn.complete", "turn.error", "turn.cancelled"}
RING = 5000
DELTA_MERGE_CHARS = 64

# Visitor streams are an explicit projection of the internal event stream. New
# internal event types are hidden by default so adding telemetry/debug events can
# never accidentally expand the public surface.
# ``text.delta`` is on this list because the runner feeds visitor deltas through
# guard.StreamRedactor before they ever reach the journal: what streams here is
# already sanitized, and turn.complete still carries the authoritative final answer.
VISITOR_EVENT_ALLOWLIST = {
    "turn.start", "text.delta", "thinking.status", "tool.start", "tool.end", "card",
    "notice", "turn.complete", "turn.error", "turn.cancelled",
}


class TurnJournal:
    def __init__(self, turn_id: uuid.UUID):
        self.turn_id = turn_id
        self.seq = 0
        self.events: list[dict[str, Any]] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.done = False
        self.task: asyncio.Task | None = None
        self._pending: list[dict[str, Any]] = []
        self._delta_buf: str = ""
        self._delta_last_seq = 0
        self._flush_task: asyncio.Task | None = None
        self._sleeping = False
        self.answer = ""
        self.thinking_chars = 0
        # 도구가 끼어들었다 — 다음 말은 새 문단이다. 도구는 실행기 흐름으로도, CLI 의 MCP 다리(api/internal_mcp)로도
        # 알려지는데 다리 쪽은 러너의 흐름을 지나지 않는다. 그래서 러너가 아니라 여기서 적는다.
        self.broke = False

    def emit(self, type_: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        self.seq += 1
        ev = {"seq": self.seq, "type": type_, "at": datetime.now(UTC).isoformat(), "data": data or {}}
        self.events.append(ev)
        if len(self.events) > RING:
            del self.events[: len(self.events) - RING]
        if type_ in ("tool.start", "tool.end", "card"):
            self.broke = True
        if type_ == "text.delta":
            self.answer += ev["data"].get("text", "")
            self._delta_buf += ev["data"].get("text", "")
            self._delta_last_seq = self.seq
            if len(self._delta_buf) >= DELTA_MERGE_CHARS:
                self._pending.append({**ev, "data": {"text": self._delta_buf}})
                self._delta_buf = ""
        else:
            if self._delta_buf:
                # merged row keeps the LAST delta's seq — never this event's seq, or the two rows collide on
                # the (turn_id, seq) primary key and the terminal event is silently dropped by on_conflict_do_nothing
                self._pending.append({"seq": self._delta_last_seq, "type": "text.delta", "at": ev["at"], "data": {"text": self._delta_buf}})
                self._delta_buf = ""
            self._pending.append(ev)
        for q in list(self.subscribers):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                # slow consumer: detach it; stream_journal notices the detachment and ends the response
                # so the client falls back to the resume URL (plan/18).
                self.subscribers.discard(q)
        if type_ in TERMINAL:
            self.done = True
            for q in list(self.subscribers):
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass
        self._schedule_flush(force=type_ in TERMINAL)
        return ev

    def _schedule_flush(self, force: bool = False) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_later(0 if force else 0.25))
        elif force and self._sleeping:
            self._flush_task.cancel()  # wake the debounce sleep: terminal events must not wait 250ms

    async def _flush_later(self, delay: float) -> None:
        if delay:
            self._sleeping = True
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                t = asyncio.current_task()
                if t is not None:
                    t.uncancel()
            finally:
                self._sleeping = False
        # events emitted while a flush was in flight would otherwise wait for the next emit (or the 10-minute
        # forget timer) — drain until nothing is pending so terminal events reach PG promptly.
        while True:
            await self.flush()
            if not self._pending:
                break

    async def wait_flushed(self, timeout: float = 5.0) -> None:
        """Test/ops helper: block until the current flush task has drained."""
        t = self._flush_task
        if t is not None and not t.done():
            await asyncio.wait_for(asyncio.shield(t), timeout=timeout)
        if self._pending:
            await self.flush()

    def pending_count(self) -> int:
        return len(self._pending) + (1 if self._delta_buf else 0)

    async def flush(self) -> None:
        batch, self._pending = self._pending, []
        if not batch:
            return
        rows = [{"turn_id": self.turn_id, "seq": e["seq"], "type": e["type"], "data": e["data"], "at": datetime.fromisoformat(e["at"])}
                for e in batch]
        try:
            async with session_scope() as db:
                await db.execute(insert(TurnEvent).values(rows).on_conflict_do_nothing())
        except Exception as e:  # noqa: BLE001
            log.warning("journal flush failed", err=str(e)[:200])

    def subscribe(self, after: int = 0) -> tuple[list[dict[str, Any]], asyncio.Queue | None]:
        backlog = [e for e in self.events if e["seq"] > after]
        if self.done:
            return backlog, None
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self.subscribers.add(q)
        return backlog, q

    def unsubscribe(self, q: asyncio.Queue | None) -> None:
        if q is not None:
            self.subscribers.discard(q)


class JournalRegistry:
    def __init__(self) -> None:
        self._j: dict[uuid.UUID, TurnJournal] = {}

    def create(self, turn_id: uuid.UUID) -> TurnJournal:
        j = TurnJournal(turn_id)
        self._j[turn_id] = j
        return j

    def get(self, turn_id: uuid.UUID) -> TurnJournal | None:
        return self._j.get(turn_id)

    def forget(self, turn_id: uuid.UUID, delay_s: float = 600) -> None:
        async def _later():
            await asyncio.sleep(delay_s)
            j = self._j.pop(turn_id, None)
            if j:
                await j.flush()
        asyncio.create_task(_later())

    def active_count(self) -> int:
        return sum(1 for j in self._j.values() if not j.done)


journals = JournalRegistry()


def sse(ev: dict[str, Any]) -> bytes:
    return f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n".encode()


async def _final_answer(turn_id: uuid.UUID) -> str:
    async with session_scope() as db:
        return str((await db.execute(select(Turn.answer_text).where(Turn.id == turn_id))).scalar_one_or_none() or "")


def _visitor_projection(ev: dict[str, Any]) -> dict[str, Any] | None:
    """Fail-closed public projection. Raw model text and internal telemetry never cross this boundary."""
    type_ = ev.get("type")
    if type_ not in VISITOR_EVENT_ALLOWLIST:
        return None
    d = dict(ev.get("data") or {})
    if type_ == "text.delta":
        return {**ev, "data": {"text": str(d.get("text", ""))}}
    if type_ == "turn.start":
        d = {"turn_id": d.get("turn_id"), "conversation_id": d.get("conversation_id")}
    elif type_ == "tool.start":
        d = {"call_id": d.get("call_id"), "name": "activity", "label": d.get("label") or "확인하는 중", "label_en": d.get("label_en") or "Checking"}
    elif type_ == "tool.end":
        d = {"call_id": d.get("call_id"), "is_error": bool(d.get("is_error")), "duration_ms": d.get("duration_ms", 0)}
    elif type_ == "turn.complete":
        d = {"turn_id": d.get("turn_id"), "message_id": d.get("message_id"), "stop_reason": d.get("stop_reason", "end_turn")}
    elif type_ == "turn.error":
        d = {"code": d.get("code", "unknown"), "message": d.get("message", "오류가 발생했어요."), "retryable": bool(d.get("retryable"))}
    elif type_ == "turn.cancelled":
        d = {"turn_id": d.get("turn_id")}
    return {**ev, "data": d}


async def _project_visitor_terminal(turn_id: uuid.UUID, ev: dict[str, Any]) -> dict[str, Any]:
    out = _visitor_projection(ev) or ev
    if out.get("type") == "turn.complete":
        data = dict(out.get("data") or {})
        data["answer"] = await _final_answer(turn_id)
        out = {**out, "data": data}
    return out


async def stream_journal(j: TurnJournal, after: int = 0, *, visitor: bool = False, ping_interval: float = 15.0):
    """Async generator of SSE bytes: backlog + live, with 15s pings.

    Visitor streams never emit raw ``text.delta``. The complete, redacted answer
    is attached to the terminal event only after the final transaction commits.
    """
    backlog, q = j.subscribe(after)
    try:
        for ev in backlog:
            if visitor:
                projected = _visitor_projection(ev)
                if projected is None:
                    continue
                if projected["type"] == "turn.complete":
                    projected = await _project_visitor_terminal(j.turn_id, projected)
                yield sse(projected)
            else:
                yield sse(ev)
        if q is None:
            return
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=ping_interval)
            except TimeoutError:
                if q not in j.subscribers:
                    return
                yield b": ping\n\n"
                continue
            if ev is None:
                return
            if visitor:
                projected = _visitor_projection(ev)
                if projected is None:
                    continue
                if projected["type"] == "turn.complete":
                    projected = await _project_visitor_terminal(j.turn_id, projected)
                yield sse(projected)
            else:
                yield sse(ev)
    finally:
        j.unsubscribe(q)


async def load_persisted(turn_id: uuid.UUID, after: int = 0) -> list[dict[str, Any]]:
    async with session_scope() as db:
        rows = (await db.execute(select(TurnEvent).where(TurnEvent.turn_id == turn_id, TurnEvent.seq > after).order_by(TurnEvent.seq))).scalars().all()
    return [{"seq": r.seq, "type": r.type, "at": r.at.isoformat(), "data": r.data} for r in rows]


async def replay_persisted(turn_id: uuid.UUID, after: int, *, running: bool, visitor: bool = False):
    """SSE generator for a turn whose in-memory journal is gone (process restart / 10-min eviction):
    persisted events, then — if the row still says running — a retryable error so the client re-syncs."""
    events = await load_persisted(turn_id, after)
    if visitor:
        projected: list[dict[str, Any]] = []
        for ev in events:
            p = _visitor_projection(ev)
            if p is None:
                continue
            if p["type"] == "turn.complete":
                p = await _project_visitor_terminal(turn_id, p)
            projected.append(p)
        events = projected
    for ev in events:
        yield sse(ev)
    if running and not any(e["type"] in TERMINAL for e in events):
        yield sse({"seq": (events[-1]["seq"] if events else after) + 1, "type": "turn.error", "at": datetime.now(UTC).isoformat(),
                   "data": {"code": "unknown", "message": "연결이 끊겼어요. 다시 시도해 주세요.", "retryable": True}})
