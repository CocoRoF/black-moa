"""The one owner of this process's LLM capacity.

The database got a manager because a shared pool with no owner is a resource nobody can
answer questions about. The same was true here, and more so: an LLM call is the most
expensive thing this service does, it is the thing that holds a worker slot, a thread, a
pooled account and a session all at once, and it was spread across four modules that did
not know about each other —

  ``services/claude_pool``   which account a call runs on, and whether that account is well
  ``pipeline/runtime``       the live sessions, each pinned to an account for its whole life
  ``core/pools``             the threads a blocking client call sits in
  ``providers/llm/simple``   background completions, serialised one at a time

Nothing joined them up, so "which provider is this load coming from", "what is that account
doing right now" and "why is the machine busy" had no answer. This module is that join. It
does not replace the pool — the pool still decides *which* account — it records what
actually happened and presents capacity as one picture:

  * every call, by provider and model: how many, how long, how many failed and why
  * every live session, with the account it holds and how long it has held it
  * the accounts themselves, their health and their share of the load
  * what that costs the machine: threads in use, queueing, event-loop lag

It is deliberately cheap. Recording a call is two clock reads and a dict update, the
history is a bounded deque, and nothing here ever touches the database on a call path.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from memora.core.logging import get_logger

log = get_logger("memora.llm")

#: How many recent calls to keep for the dashboard's latency view. Bounded on purpose: this
#: is a window onto what is happening, not a record of what happened — the traffic table is
#: where history lives.
_RECENT_MAX = 400

#: A call open longer than this is reported as abnormal. Generous, because a long
#: conversation turn legitimately takes minutes; the point is to catch the one that never
#: came back at all.
STUCK_S = 600.0

#: Past this a call is not slow, it was lost: nothing here outlives its own timeout by an
#: hour. Such entries are dropped so the in-flight list stays a list of real work.
LOST_S = 3600.0


@dataclass
class _Stat:
    """What one provider (or one model) has been doing."""

    calls: int = 0
    failures: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    in_flight: int = 0
    peak_in_flight: int = 0
    last_at: float = 0.0
    last_error: str = ""
    codes: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls, "failures": self.failures, "in_flight": self.in_flight,
            "peak_in_flight": self.peak_in_flight,
            "avg_ms": round(self.total_ms / self.calls, 1) if self.calls else 0.0,
            "max_ms": round(self.max_ms, 1),
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "error_rate": round(self.failures / self.calls, 4) if self.calls else 0.0,
            "seconds_since_last": round(time.monotonic() - self.last_at, 1) if self.last_at else None,
            "last_error": self.last_error, "codes": dict(sorted(self.codes.items(), key=lambda kv: -kv[1])[:6]),
        }


@dataclass
class InFlight:
    """A call that has not come back yet."""

    id: str
    provider: str
    model: str
    kind: str                 # turn | background | probe
    started: float
    owner_id: str | None = None
    agent_id: str | None = None
    account: str = ""

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "provider": self.provider, "model": self.model, "kind": self.kind,
                "elapsed_ms": round(self.elapsed_s * 1000), "owner_id": self.owner_id,
                "agent_id": self.agent_id, "account": self.account, "stuck": self.elapsed_s > STUCK_S}


class LLMManager:
    """Records every call and presents LLM capacity as one picture."""

    def __init__(self) -> None:
        self.by_provider: dict[str, _Stat] = {}
        self.by_model: dict[str, _Stat] = {}
        self.by_kind: dict[str, _Stat] = {}
        self.live: dict[str, InFlight] = {}
        self.recent: deque[dict[str, Any]] = deque(maxlen=_RECENT_MAX)
        self._seq = 0

    # ── recording ───────────────────────────────────────────────────

    def begin(self, *, provider: str, model: str, kind: str = "turn", owner_id: str | None = None,
              agent_id: str | None = None, account: str = "") -> str:
        self._reap()
        self._seq += 1
        cid = f"{kind[:1]}{self._seq:06d}"
        self.live[cid] = InFlight(id=cid, provider=provider, model=model, kind=kind, started=time.monotonic(),
                                  owner_id=owner_id, agent_id=agent_id, account=account)
        for stat in (self.by_provider.setdefault(provider, _Stat()), self.by_model.setdefault(f"{provider}/{model}", _Stat()),
                     self.by_kind.setdefault(kind, _Stat())):
            stat.in_flight += 1
            stat.peak_in_flight = max(stat.peak_in_flight, stat.in_flight)
        return cid

    def end(self, cid: str, *, ok: bool = True, code: str | None = None, error: str = "",
            input_tokens: int = 0, output_tokens: int = 0) -> None:
        rec = self.live.pop(cid, None)
        if rec is None:
            return
        ms = rec.elapsed_s * 1000
        for stat in (self.by_provider.setdefault(rec.provider, _Stat()),
                     self.by_model.setdefault(f"{rec.provider}/{rec.model}", _Stat()),
                     self.by_kind.setdefault(rec.kind, _Stat())):
            stat.in_flight = max(0, stat.in_flight - 1)
            stat.calls += 1
            stat.total_ms += ms
            stat.max_ms = max(stat.max_ms, ms)
            stat.input_tokens += input_tokens
            stat.output_tokens += output_tokens
            stat.last_at = time.monotonic()
            if not ok:
                stat.failures += 1
                stat.last_error = (error or code or "")[:200]
                key = code or "unknown"
                stat.codes[key] = stat.codes.get(key, 0) + 1
        self.recent.appendleft({"provider": rec.provider, "model": rec.model, "kind": rec.kind,
                                "ms": round(ms, 1), "ok": ok, "code": code, "account": rec.account,
                                "owner_id": rec.owner_id, "error": (error or "")[:200],
                                "input_tokens": input_tokens, "output_tokens": output_tokens,
                                "at": time.time()})

    def _reap(self) -> None:
        """Forget calls that cannot still be running.

        Every path that starts a call also ends it, but "every path" is a claim about code
        that changes. A turn is bounded by its own timeout, so anything still open an hour
        later was lost rather than slow, and leaving it would quietly turn the in-flight
        list — the one an operator trusts — into a list of ghosts.
        """
        # No cheap-out on size: a leak is usually one entry, and skipping the scan until
        # eight of them had piled up meant the reaper never ran in the case it exists for.
        # The list is bounded by concurrency, so the scan is a handful of subtractions.
        lost = [cid for cid, r in self.live.items() if r.elapsed_s > LOST_S]
        for cid in lost:
            rec = self.live.pop(cid, None)
            if rec is not None:
                log.warning("llm call was never completed", provider=rec.provider, model=rec.model,
                            kind=rec.kind, elapsed_s=round(rec.elapsed_s))

    # ── the picture ─────────────────────────────────────────────────

    def in_flight(self) -> list[dict[str, Any]]:
        return [r.as_dict() for r in sorted(self.live.values(), key=lambda r: r.started)]

    def totals(self) -> dict[str, Any]:
        calls = sum(s.calls for s in self.by_provider.values())
        fails = sum(s.failures for s in self.by_provider.values())
        ms = sum(s.total_ms for s in self.by_provider.values())
        return {
            "calls": calls, "failures": fails,
            "error_rate": round(fails / calls, 4) if calls else 0.0,
            "avg_ms": round(ms / calls, 1) if calls else 0.0,
            "in_flight": len(self.live),
            "stuck": sum(1 for r in self.live.values() if r.elapsed_s > STUCK_S),
            "input_tokens": sum(s.input_tokens for s in self.by_provider.values()),
            "output_tokens": sum(s.output_tokens for s in self.by_provider.values()),
        }

    def stats(self) -> dict[str, Any]:
        """Everything the dashboard needs that lives in this process."""
        from memora.core import pools
        from memora.core.watchdog import loop_lag

        return {
            "totals": self.totals(),
            "providers": {k: v.as_dict() for k, v in sorted(self.by_provider.items())},
            "models": {k: v.as_dict() for k, v in sorted(self.by_model.items(), key=lambda kv: -kv[1].calls)[:20]},
            "kinds": {k: v.as_dict() for k, v in sorted(self.by_kind.items())},
            "in_flight": self.in_flight(),
            "recent": list(self.recent)[:60],
            # What the calls cost the machine. The thread pool is where a blocking client
            # sits, so a full one with a queue behind it is LLM work becoming everyone's
            # problem — which is the question this dashboard exists to answer.
            "load": {"llm_pool": pools.stats().get("llm", {}), "loop_lag_s": round(loop_lag(), 3)},
        }


#: The instance. One per process, like the database manager.
manager = LLMManager()


async def sessions(db: Any) -> list[dict[str, Any]]:
    """The live conversations, with what each of them is holding.

    A session is the expensive unit: it pins a CLI process, a pooled account and its prompt
    cache for as long as it lives. Counting them was all that was possible before; this says
    which agent, whose, on what model, on which account, and for how long.
    """
    import uuid as _uuid

    from sqlalchemy import select as _select

    from memora.models import Agent, User
    from memora.pipeline.runtime import runtimes

    rows = runtimes.snapshot()
    agent_ids = {r["agent_id"] for r in rows if r.get("agent_id")}
    names: dict[str, tuple[str, str]] = {}
    if agent_ids:
        res = (await db.execute(
            _select(Agent.id, Agent.name, User.display_name, User.email)
            .join(User, User.id == Agent.owner_id)
            .where(Agent.id.in_([_uuid.UUID(a) for a in agent_ids])))).all()
        names = {str(r[0]): (r[1], r[2] or r[3]) for r in res}
    for r in rows:
        agent, owner = names.get(r.get("agent_id") or "", ("", ""))
        r["agent_name"], r["owner_name"] = agent, owner
    return rows
