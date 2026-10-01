"""The system section of the admin console (plan/46).

Six screens that have to answer, between them, "what is this server doing and why". Each
endpoint is checked for the shape the page relies on, because a dashboard that renders
undefined is worse than no dashboard: it is a wrong answer delivered confidently.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth, signup

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def admin_client(client: AsyncClient):
    """An administrator, and the install left as it was found."""
    import uuid as _uuid

    from blackmoa.db.session import session_scope
    from blackmoa.models import User

    user, tok = await signup(client, f"console-{_uuid.uuid4().hex[:6]}@example.com")
    async with session_scope() as db:
        (await db.get(User, _uuid.UUID(user["id"]))).role = "admin"
    yield client, tok, []
    async with session_scope() as db:
        (await db.get(User, _uuid.UUID(user["id"]))).role = "user"


async def test_llm_overview_joins_capacity_into_one_picture(admin_client):
    client, tok, _ = admin_client
    from blackmoa.core.llm_manager import manager as LLM

    cid = LLM.begin(provider="anthropic", model="claude-sonnet-5", kind="turn", owner_id="o", account="기본")
    LLM.end(cid, ok=True, input_tokens=100, output_tokens=20)
    bad = LLM.begin(provider="openai", model="gpt-x", kind="background")
    LLM.end(bad, ok=False, code="rate_limited", error="429")

    d = (await client.get("/api/admin/llm", headers=auth(tok))).json()
    assert {"totals", "providers", "models", "kinds", "in_flight", "recent", "load", "pool",
            "providers_configured", "sessions"} <= set(d)
    assert d["totals"]["calls"] >= 2
    assert d["providers"]["anthropic"]["input_tokens"] >= 100
    assert d["providers"]["openai"]["failures"] >= 1
    assert d["providers"]["openai"]["codes"].get("rate_limited", 0) >= 1
    # the machine's share of it, which is the point of joining these up
    assert "llm_pool" in d["load"] and "loop_lag_s" in d["load"]
    assert any(p["id"] == "claude_code" for p in d["providers_configured"])


async def test_a_call_that_never_returns_is_visible_and_then_forgotten():
    """The in-flight list is only useful if it is real work."""
    import time as _t

    from blackmoa.core import llm_manager as M

    mgr = M.LLMManager()
    cid = mgr.begin(provider="p", model="m", kind="turn")
    assert [r["id"] for r in mgr.in_flight()] == [cid]
    assert mgr.in_flight()[0]["stuck"] is False

    mgr.live[cid].started = _t.monotonic() - M.STUCK_S - 1
    assert mgr.in_flight()[0]["stuck"] is True, "a call open for ten minutes is not normal"

    # …and one that cannot still be running is dropped rather than haunting the list
    mgr.live[cid].started = _t.monotonic() - M.LOST_S - 1
    for _ in range(8):
        mgr.end(mgr.begin(provider="p", model="m"), ok=True)
    assert cid not in mgr.live


async def test_jobs_overview_answers_the_queue_questions(admin_client):
    client, tok, _ = admin_client
    # A heartbeat row on purpose: the first version of this test passed against an empty
    # table, so the worker list was never actually rendered and shipped reading a column
    # that does not exist.
    from datetime import UTC, datetime

    from blackmoa.db.session import session_scope
    from blackmoa.models import WorkerHeartbeat

    async with session_scope() as db:
        await db.merge(WorkerHeartbeat(worker_id="test-worker", last_seen_at=datetime.now(UTC), info={"pid": 1}))

    r = await client.get("/api/admin/jobs/overview", headers=auth(tok))
    assert r.status_code == 200, r.text
    d = r.json()
    assert any(w["id"] == "test-worker" and w["stale"] is False for w in d["workers"]), d["workers"]
    assert {"kinds", "series", "owners", "running", "workers", "limits"} <= set(d)
    # the ceilings are shown beside what is running, so a queue that is not moving can be
    # read against the rule holding it
    assert d["limits"]["concurrency"] >= 1
    assert "memory.distill" in d["limits"]["kinds"]
    assert d["limits"]["classes"].get("docs")


@pytest.mark.parametrize(("tab", "expected"), [
    ("server", {"process", "host", "disk", "pools", "loop_lag_s", "sessions"}),
    ("database", {"pool"}),
    ("storage", {"mode", "health", "uploads"}),
])
async def test_each_diagnostics_tab_reports_its_component(admin_client, tab: str, expected: set):
    client, tok, _ = admin_client
    r = await client.get(f"/api/admin/diagnostics/{tab}", headers=auth(tok))
    assert r.status_code == 200, r.text
    assert expected <= set(r.json()), f"{tab}: {sorted(set(r.json()))}"


async def test_diagnostics_are_admin_only(client: AsyncClient):
    for tab in ("server", "database", "storage"):
        assert (await client.get(f"/api/admin/diagnostics/{tab}")).status_code in (401, 403)
    assert (await client.get("/api/admin/llm")).status_code in (401, 403)
