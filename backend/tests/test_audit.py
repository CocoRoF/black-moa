"""Adversarial audit regressions (2026-09-07): ownership fuzz, auth lockout, turn replay, credits, worker, knowledge,
network, notifications, uploads, admin validation, claude credentials guards."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from memora.db.session import session_scope
from tests.conftest import auth, read_sse, signup
from tests.test_domain import _run_jobs

pytestmark = pytest.mark.asyncio


async def _admin_token(client: AsyncClient) -> str:
    from memora.models import User
    async with session_scope() as db:
        admin = (await db.execute(select(User).where(User.role == "admin").order_by(User.created_at))).scalars().first()
    if admin is None:
        _, tok = await signup(client, "admin@example.com", "관리자")
        return tok
    r = await client.post("/api/auth/login", json={"email": admin.email, "password": "correct-horse-9"})
    return r.json()["access_token"]


async def _turn(client: AsyncClient, tok: str, agent_id: str, cid: str, text_: str, **extra) -> tuple[str, list[dict]]:
    async with client.stream("POST", f"/api/agents/{agent_id}/conversations/{cid}/turns", json={"text": text_, **extra}, headers=auth(tok)) as resp:
        assert resp.status_code == 200, await resp.aread()
        tid = resp.headers["x-turn-id"]
        events = await read_sse(resp)
    return tid, events


# ── 1. ownership fuzz ────────────────────────────────────────────────

async def test_cross_user_fuzz_every_owner_endpoint(client: AsyncClient):
    from memora.models import Connection, Fact, InboxItem
    u1, t1 = await signup(client, name="owner-one")
    u2, t2 = await signup(client, name="intruder")
    a = (await client.post("/api/agents", json={"name": "A1"}, headers=auth(t1))).json()["id"]
    c = (await client.post(f"/api/agents/{a}/conversations", json={}, headers=auth(t1))).json()["id"]
    turn_id, _ = await _turn(client, t1, a, c, "hello")
    link = (await client.post(f"/api/agents/{a}/links", json={"label": "x"}, headers=auth(t1))).json()
    v = (await client.post(f"/api/public/links/{link['code']}/visitor", json={})).json()
    doc = (await client.post("/api/knowledge/documents", data={"kind": "note", "title": "n", "body": "secret body"}, headers=auth(t1))).json()["id"]
    faq = (await client.post("/api/knowledge/faqs", json={"question": "q?", "answer": "a"}, headers=auth(t1))).json()["id"]
    n1 = (await client.post("/api/network/nodes", json={"name": "N1"}, headers=auth(t1))).json()["id"]
    n2 = (await client.post("/api/network/nodes", json={"name": "N2"}, headers=auth(t1))).json()["id"]
    e = (await client.post("/api/network/edges", json={"src_id": n1, "dst_id": n2, "rel": "knows"}, headers=auth(t1))).json()["id"]
    ch = (await client.get("/api/notifications/channels", headers=auth(t1))).json()["items"][0]["id"]
    rule = (await client.get("/api/notifications/rules", headers=auth(t1))).json()["items"][0]["id"]
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63f8cfc0f01f00050001ff89993d1d0000000049454e44ae426082")
    up = (await client.post("/api/uploads", files={"file": ("a.png", png, "image/png")}, data={"kind": "attachment"}, headers=auth(t1))).json()["upload_id"]
    async with session_scope() as db:
        from memora.services import network as N
        prop = await N.propose(db, uuid.UUID(u1["id"]), agent_id=None, kind="add_node", payload={"name": "P"})
        pid = str(prop.id)
        item = InboxItem(owner_id=uuid.UUID(u1["id"]), agent_id=uuid.UUID(a), kind="message", payload={"text": "hi"}, status="new")
        db.add(item)
        fact = Fact(owner_id=uuid.UUID(u1["id"]), subject="s", predicate="p", object="o")
        db.add(fact)
        conn = Connection(owner_id=uuid.UUID(u1["id"]), provider="google", account_label="x@y")
        db.add(conn)
        await db.flush()
        iid, fid, conn_id = str(item.id), str(fact.id), str(conn.id)
        vis = (await db.execute(text("SELECT id FROM visitors WHERE owner_id=:o"), {"o": u1["id"]})).scalar()
    vid = str(vis)
    calls = [
        ("GET", f"/api/agents/{a}", None), ("PATCH", f"/api/agents/{a}", {"name": "x"}), ("POST", f"/api/agents/{a}/actions/pause", None),
        ("DELETE", f"/api/agents/{a}", None), ("GET", f"/api/agents/{a}/prompt-preview", None), ("GET", f"/api/agents/{a}/tools", None),
        ("GET", f"/api/agents/{a}/links", None), ("POST", f"/api/agents/{a}/links", {}), ("PATCH", f"/api/links/{link['id']}", {"label": "x"}),
        ("DELETE", f"/api/links/{link['id']}", None), ("GET", f"/api/links/{link['id']}/qr.png", None), ("GET", f"/api/agents/{a}/memory", None),
        ("GET", f"/api/agents/{a}/memory/owner/notes", None), ("POST", f"/api/agents/{a}/memory/notes", {"title": "t", "body": "b"}),
        ("GET", f"/api/agents/{a}/memory/search?q=x", None), ("GET", f"/api/agents/{a}/facts", None),
        ("PATCH", f"/api/facts/{fid}", {"visibility": "public"}), ("GET", f"/api/agents/{a}/conversations", None),
        ("POST", f"/api/agents/{a}/conversations", {}), ("GET", f"/api/agents/{a}/conversations/{c}", None),
        ("PATCH", f"/api/agents/{a}/conversations/{c}", {"title": "x"}), ("DELETE", f"/api/agents/{a}/conversations/{c}", None),
        ("GET", f"/api/agents/{a}/conversations/{c}/messages", None), ("POST", f"/api/agents/{a}/conversations/{c}/turns", {"text": "hi"}),
        ("POST", f"/api/agents/{a}/simulate", None), ("GET", f"/api/agents/{a}/turns/{turn_id}/events", None),
        ("POST", f"/api/agents/{a}/turns/{turn_id}/cancel", None), ("GET", f"/api/agents/{a}/conversations/{c}/active-turn", None),
        ("GET", f"/api/agents/{a}/turns/{turn_id}", None), ("GET", f"/api/agents/{a}/stats", None),
        ("GET", f"/api/knowledge/documents/{doc}", None), ("PATCH", f"/api/knowledge/documents/{doc}", {"title": "x"}),
        ("DELETE", f"/api/knowledge/documents/{doc}", None), ("GET", f"/api/knowledge/documents/{doc}/chunks", None),
        ("POST", f"/api/knowledge/documents/{doc}/reindex", None), ("PATCH", f"/api/knowledge/faqs/{faq}", {"question": "a", "answer": "b"}),
        ("DELETE", f"/api/knowledge/faqs/{faq}", None), ("GET", f"/api/network/nodes/{n1}", None), ("PATCH", f"/api/network/nodes/{n1}", {"name": "x"}),
        ("DELETE", f"/api/network/nodes/{n1}", None), ("POST", f"/api/network/nodes/{n1}/merge", {"into_id": n2}),
        ("POST", f"/api/network/nodes/{n1}/interactions", {"kind": "meeting", "at": "2026-01-01T00:00:00+00:00"}),
        ("POST", "/api/network/edges", {"src_id": n1, "dst_id": n2, "rel": "knows"}), ("PATCH", f"/api/network/edges/{e}", {"rel": "x"}),
        ("DELETE", f"/api/network/edges/{e}", None), ("GET", f"/api/network/path?from_id={n1}&to_id={n2}", None),
        ("POST", f"/api/network/proposals/{pid}/accept", None), ("GET", f"/api/inbox/{iid}", None),
        ("POST", f"/api/inbox/{iid}/status", {"status": "read"}), ("POST", f"/api/inbox/{iid}/teach", {"answer": "x"}),
        ("POST", f"/api/inbox/visitors/{vid}/block", None), ("PATCH", f"/api/notifications/channels/{ch}", {"enabled": False}),
        ("DELETE", f"/api/notifications/channels/{ch}", None), ("POST", f"/api/notifications/channels/{ch}/test", None),
        ("PATCH", f"/api/notifications/rules/{rule}", {"event": "visitor_message"}), ("DELETE", f"/api/notifications/rules/{rule}", None),
        ("POST", f"/api/integrations/{conn_id}/sync", None), ("PATCH", f"/api/integrations/{conn_id}", {"capabilities": []}),
        ("DELETE", f"/api/integrations/{conn_id}", None), ("GET", f"/api/integrations/{conn_id}/preview", None),
        ("GET", f"/api/uploads/{up}", None),
    ]
    leaks = []
    for method, path, body in calls:
        r = await client.request(method, path, json=body, headers=auth(t2))
        if r.status_code not in (403, 404):
            leaks.append((method, path, r.status_code, r.text[:120]))
    assert not leaks, leaks
    # the intruder changed nothing
    assert (await client.get(f"/api/agents/{a}", headers=auth(t1))).json()["name"] == "A1"
    # visitor tokens: another visitor of the same agent cannot read this conversation
    v2 = (await client.post(f"/api/public/links/{link['code']}/visitor", json={})).json()
    assert v2["conversation_id"] != v["conversation_id"]
    r = await client.get(f"/api/public/conversations/{v['conversation_id']}/messages", headers=auth(v2["visitor_token"]))
    assert r.status_code == 404
    # blocked visitor cannot read messages any more
    await client.post(f"/api/inbox/visitors/{vid}/block", headers=auth(t1))
    r = await client.get(f"/api/public/conversations/{v['conversation_id']}/messages", headers=auth(v["visitor_token"]))
    assert r.status_code == 403 and r.json()["error"]["code"] == "visitor_blocked"


# ── 2. auth ──────────────────────────────────────────────────────────

async def test_login_lockout_is_persisted(client: AsyncClient):
    email = f"lock{uuid.uuid4().hex[:6]}@example.com"
    await signup(client, email)
    for _ in range(5):
        r = await client.post("/api/auth/login", json={"email": email, "password": "wrong-password-1"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    r = await client.post("/api/auth/login", json={"email": email, "password": "correct-horse-9"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "account_locked", r.text


async def test_google_callbacks_reject_wrong_state_kind(client: AsyncClient, google_on):
    """로그인의 state 로 데이터 연동을 마치거나 그 반대로 할 수 없다. 옛 모양의 state·위조한 state 도 받지 않는다."""
    from fastapi import Response

    from memora.core.security import sign_state
    from memora.services.oauth import state as OST

    def begin(purpose: str) -> tuple[str, str]:
        resp = Response()
        st, _ = OST.begin(resp, provider="google", purpose=purpose, next="/app")
        return st, resp.headers["set-cookie"].split(";")[0].split("=", 1)[1]

    data_state, bind = begin("connect")
    r = await client.get("/api/auth/google/callback", params={"code": "abc", "state": data_state}, cookies={"memora_oauth": bind},
                         follow_redirects=False)
    assert r.status_code == 302 and "error=bad_state" in r.headers["location"]
    login_state, bind = begin("login")
    r = await client.get("/api/integrations/google/callback", params={"code": "abc", "state": login_state},
                         cookies={"memora_oauth": bind}, follow_redirects=False)
    assert r.status_code == 302 and "error=bad_state" in r.headers["location"]
    old = sign_state({"kind": "data", "uid": None, "caps": [], "next": "/app"})
    r = await client.get("/api/integrations/google/callback", params={"code": "abc", "state": old}, follow_redirects=False)
    assert r.status_code == 302 and "error=bad_state" in r.headers["location"]
    r = await client.get("/api/auth/google/callback?code=abc&state=garbage", follow_redirects=False)
    assert r.status_code == 302 and "error=bad_state" in r.headers["location"]


async def test_email_verification_requires_real_code(client: AsyncClient):
    from memora.models import Job, User
    from memora.services import accounts as A
    from memora.services import settings as S
    async with session_scope() as db:
        await S.put(db, "signup.require_email_verification", True)
    try:
        user, tok = await signup(client, name="verify-me")
        assert user["email_verified"] is False
        async with session_scope() as db:
            jobs = (await db.execute(select(Job).where(Job.kind == "mail.send"))).scalars().all()
            mine = [j for j in jobs if j.payload.get("to") == user["email"] and "인증 코드" in j.payload.get("subject", "")]
            assert mine
            # A code arriving as one bare line reads like phishing, so the branded part
            # travels with it — and the plain text still has to stand on its own.
            assert all(j.payload.get("html", "").startswith("<!doctype html>") for j in mine)
            assert all("인증 코드:" in j.payload.get("text", "") for j in mine)
        r = await client.post("/api/auth/email/verify", json={"code": "000000"}, headers=auth(tok))
        assert r.status_code == 422
        async with session_scope() as db:
            u = await db.get(User, uuid.UUID(user["id"]))
            code = await A.start_email_verification(db, u)
        r = await client.post("/api/auth/email/verify", json={"code": code}, headers=auth(tok))
        assert r.status_code == 200, r.text
        assert (await client.get("/api/auth/me", headers=auth(tok))).json()["email_verified"] is True
    finally:
        async with session_scope() as db:
            await S.put(db, "signup.require_email_verification", False)


async def test_metrics_restricted_to_private_network_or_admin(app, client: AsyncClient):
    assert (await client.get("/metrics")).status_code == 200  # ASGI test client = 127.0.0.1
    async with AsyncClient(transport=ASGITransport(app=app, client=("8.8.8.8", 1234)), base_url="http://testserver") as public:
        r = await public.get("/metrics")
        assert r.status_code == 403
        tok = await _admin_token(client)
        assert (await public.get("/metrics", headers=auth(tok))).status_code == 200
        _, user_tok = await signup(public)
        assert (await public.get("/metrics", headers=auth(user_tok))).status_code == 403


# ── 3. turn pipeline ─────────────────────────────────────────────────

async def test_idempotent_turn_replays_after_journal_eviction(client: AsyncClient):
    from memora.pipeline.events import journals
    user, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "R"}, headers=auth(tok))).json()["id"]
    c = (await client.post(f"/api/agents/{a}/conversations", json={}, headers=auth(tok))).json()["id"]
    ctid = str(uuid.uuid4())
    tid, events = await _turn(client, tok, a, c, "first", client_turn_id=ctid)
    assert events[-1]["type"] == "turn.complete"
    j = journals.get(uuid.UUID(tid))
    await j.wait_flushed()
    journals._j.pop(uuid.UUID(tid))  # simulate the 10-minute eviction / process restart
    tid2, events2 = await _turn(client, tok, a, c, "first", client_turn_id=ctid)
    assert tid2 == tid, "same client_turn_id must reattach to the same turn"
    assert events2 and events2[-1]["type"] == "turn.complete" and any(e["type"] == "text.delta" for e in events2)
    msgs = (await client.get(f"/api/agents/{a}/conversations/{c}/messages", headers=auth(tok))).json()["items"]
    assert len(msgs) == 2, "an idempotent re-POST must not add messages"


async def test_agent_patch_bumps_updated_at_and_runtime_fingerprint(client: AsyncClient):
    from memora.models import Agent, ModelCatalog, Plan
    from memora.pipeline.runtime import _fingerprint
    user, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "F"}, headers=auth(tok))).json()
    async with session_scope() as db:
        ag = await db.get(Agent, uuid.UUID(a["id"]))
        cat = (await db.execute(select(ModelCatalog).where(ModelCatalog.provider == "fake"))).scalars().first()
        plan = (await db.execute(select(Plan))).scalars().first()
        fp0 = _fingerprint(ag, cat, set(), plan)
    await asyncio.sleep(0.01)
    r = await client.patch(f"/api/agents/{a['id']}", json={"custom_instructions": "be brief"}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["updated_at"] > a["updated_at"]
    async with session_scope() as db:
        ag = await db.get(Agent, uuid.UUID(a["id"]))
        assert _fingerprint(ag, cat, set(), plan) != fp0


async def test_attachment_payload_not_persisted_in_messages(client: AsyncClient):
    user, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "Att"}, headers=auth(tok))).json()["id"]
    c = (await client.post(f"/api/agents/{a}/conversations", json={}, headers=auth(tok))).json()["id"]
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63f8cfc0f01f00050001ff89993d1d0000000049454e44ae426082")
    up = (await client.post("/api/uploads", files={"file": ("a.png", png, "image/png")}, data={"kind": "attachment"}, headers=auth(tok))).json()
    _, events = await _turn(client, tok, a, c, "look", upload_ids=[up["upload_id"]])
    assert events[-1]["type"] == "turn.complete"
    msgs = (await client.get(f"/api/agents/{a}/conversations/{c}/messages", headers=auth(tok))).json()["items"]
    att = msgs[0]["attachments"][0]
    assert att["upload_id"] == up["upload_id"] and "data" not in att and "text" not in att
    r = await client.post(f"/api/agents/{a}/conversations/{c}/turns", json={"text": "x", "upload_ids": ["not-a-uuid"]}, headers=auth(tok))
    assert r.status_code == 422


async def test_journal_detaches_slow_consumer_and_persists_tail():
    from memora.pipeline.events import TurnJournal, load_persisted, stream_journal
    j = TurnJournal(uuid.uuid4())
    got: list[bytes] = []

    async def consume():
        async for chunk in stream_journal(j, 0, ping_interval=0.05):
            got.append(chunk)
    task = asyncio.create_task(consume())
    await asyncio.sleep(0.02)  # subscribed, waiting on its queue
    assert len(j.subscribers) == 1
    for _ in range(2100):
        j.emit("text.delta", {"text": "x"})  # queue maxsize 2000 → overflow → subscriber detached
    assert not j.subscribers
    await asyncio.wait_for(task, timeout=5)  # drained what it had, then ended instead of pinging forever
    assert sum(1 for c in got if c.startswith(b"id:")) == 2000
    j.emit("turn.complete", {"turn_id": "x"})
    await j.wait_flushed()
    rows = await load_persisted(j.turn_id, 0)
    assert rows and rows[-1]["type"] == "turn.complete" and rows[-1]["seq"] == 2101
    assert "".join(e["data"]["text"] for e in rows if e["type"] == "text.delta") == "x" * 2100
    assert len({r["seq"] for r in rows}) == len(rows)  # merged delta rows never collide with the event that flushed them
    # a delta followed by a non-delta (tool.start) must persist both rows
    j2 = TurnJournal(uuid.uuid4())
    j2.emit("turn.start", {})
    j2.emit("text.delta", {"text": "hi"})
    j2.emit("tool.start", {"name": "x"})
    j2.emit("turn.complete", {})
    await j2.wait_flushed()
    assert [(r["seq"], r["type"]) for r in await load_persisted(j2.turn_id, 0)] == [(1, "turn.start"), (2, "text.delta"), (3, "tool.start"), (4, "turn.complete")]


# ── 4. credits ───────────────────────────────────────────────────────

async def test_charge_usage_ledger_kinds(client: AsyncClient):
    from memora.services import credits as CR
    user, tok = await signup(client)
    uid = uuid.UUID(user["id"])
    async with session_scope() as db:
        await CR.charge_usage(db, owner_id=uid, kind="stt", credits=0.5, provider="openai", units=0.2)
        await CR.charge_usage(db, owner_id=uid, kind="embedding", credits=0.02)
        await CR.charge_usage(db, owner_id=uid, kind="summary", credits=0.1)
        await CR.charge_usage(db, owner_id=uid, kind="tts", credits=0)  # zero → no ledger row
    kinds = [x["kind"] for x in (await client.get("/api/credits/ledger", headers=auth(tok))).json()["items"]]
    assert kinds.count("usage") == 3 and "adjust" not in kinds and "turn" not in kinds
    assert CR.ledger_kind_for_usage("llm") == "turn"


async def test_monthly_grant_rollover_cap(client: AsyncClient):
    from memora.models import Plan, User
    from memora.services import credits as CR
    from memora.worker.handlers import grant_monthly_for_user, rollover_plan
    assert rollover_plan(700, 300) == (100.0, 300.0)   # carry-over capped at 2×monthly → 100 expires
    assert rollover_plan(500, 300) == (0.0, 300.0)
    assert rollover_plan(-40, 300) == (0.0, 300.0)     # debt carries over
    assert rollover_plan(10, 0) == (0.0, 0.0)
    user, tok = await signup(client)
    uid = uuid.UUID(user["id"])
    async with session_scope() as db:
        u = await db.get(User, uid)
        plan = await db.get(Plan, u.plan_id)
        bal = await CR.balance(db, uid)
        await CR.apply(db, uid, 700 - bal, "grant", note="test top-up")
        u.plan_cycle_anchor = datetime.now(UTC) - timedelta(days=31)
    # Derived from the plan, not hardcoded: the shipped grant is a product decision that
    # moves (it went 300 → 1000 in plan/34) and this test is about the rollover rule.
    monthly = plan.monthly_credits
    expire, grant = rollover_plan(700.0, monthly)
    async with session_scope() as db:
        u = await db.get(User, uid)
        assert await grant_monthly_for_user(db, u, plan, datetime.now(UTC)) is True
        assert await CR.balance(db, uid) == Decimal(700) - Decimal(str(expire)) + Decimal(str(grant))
        assert (datetime.now(UTC) - u.plan_cycle_anchor).days == 1
        assert await grant_monthly_for_user(db, u, plan, datetime.now(UTC)) is False  # inside the new cycle
    kinds = [(x["kind"], x["delta"]) for x in (await client.get("/api/credits/ledger", headers=auth(tok))).json()["items"]]
    assert ("monthly_grant", float(grant)) in kinds
    if expire:
        assert ("expire", -float(expire)) in kinds


# ── 5. worker ────────────────────────────────────────────────────────

async def test_requeue_stale_running_jobs():
    from memora.models import Job
    from memora.services import jobs as J
    async with session_scope() as db:
        j = await J.enqueue(db, "test.stale", {})
        await db.flush()
        j.status, j.locked_by, j.locked_at, j.attempts = "running", "dead-worker", datetime.now(UTC) - timedelta(minutes=45), 1
        jid = j.id
    async with session_scope() as db:
        assert await J.requeue_stale(db, minutes=20) >= 1
        j = await db.get(Job, jid)
        assert j.status == "queued" and j.locked_by is None and "requeued" in (j.last_error or "")


async def test_retention_sweep_removes_expired_visitor_threads_and_orphans(client: AsyncClient):
    from memora.models import Conversation, Fact, Message, ToolSpan, Turn, TurnEvent
    user, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "Ret"}, headers=auth(tok))).json()
    link = (await client.post(f"/api/agents/{a['id']}/links", json={}, headers=auth(tok))).json()
    v = (await client.post(f"/api/public/links/{link['code']}/visitor", json={})).json()
    async with client.stream("POST", f"/api/public/conversations/{v['conversation_id']}/turns", json={"text": "old chat"}, headers=auth(v["visitor_token"])) as resp:
        tid = uuid.UUID(resp.headers["x-turn-id"])
        await read_sse(resp)
    cid = uuid.UUID(v["conversation_id"])
    async with session_scope() as db:
        conv = await db.get(Conversation, cid)
        conv.last_message_at = datetime.now(UTC) - timedelta(days=200)
        db.add(ToolSpan(turn_id=tid, owner_id=uuid.UUID(user["id"]), name="x", input={}, started_at=datetime.now(UTC)))
        db.add(Fact(owner_id=uuid.UUID(user["id"]), subject="visitor", predicate="likes", object="tea", visibility="visitor_private", visitor_id=conv.visitor_id))
        from memora.pipeline.events import journals
        j = journals.get(tid)
        if j:
            await j.wait_flushed()
    from memora.worker.handlers import retention_sweep
    async with session_scope() as db:
        res = await retention_sweep(db, {})
        assert res["conversations_deleted"] >= 1
    async with session_scope() as db:
        assert await db.get(Conversation, cid) is None
        assert (await db.execute(select(Message).where(Message.conversation_id == cid))).first() is None
        assert await db.get(Turn, tid) is None
        assert (await db.execute(select(TurnEvent).where(TurnEvent.turn_id == tid))).first() is None
        assert (await db.execute(select(ToolSpan).where(ToolSpan.turn_id == tid))).first() is None
        assert (await db.execute(select(Fact).where(Fact.owner_id == uuid.UUID(user["id"]), Fact.visibility == "visitor_private"))).first() is None


async def test_integration_sync_persists_expired_status(google_on):
    from memora.models import Connection, User
    from memora.worker.handlers import integration_sync
    async with session_scope() as db:
        u = (await db.execute(select(User))).scalars().first()
        conn = Connection(owner_id=u.id, provider="google", account_label=f"exp-{uuid.uuid4().hex[:4]}@g", capabilities=["calendar_read"],
                          access_token_enc="", refresh_token_enc="", token_expires_at=datetime.now(UTC) - timedelta(hours=1))
        db.add(conn)
        await db.flush()
        cid = conn.id
    async with session_scope() as db:
        res = await integration_sync(db, {"connection_id": str(cid)})
        assert res.get("error") == "google_expired"
    async with session_scope() as db:
        conn = await db.get(Connection, cid)
        assert conn.status == "expired"


# ── 6. knowledge ─────────────────────────────────────────────────────

async def test_knowledge_index_failure_paths_and_faq_semantic_match(client: AsyncClient):
    from memora.models import Job
    from memora.services import settings as S
    user, tok = await signup(client)
    files = {"file": ("gone.txt", b"this file will vanish", "text/plain")}
    d = (await client.post("/api/knowledge/documents", files=files, data={"kind": "file"}, headers=auth(tok))).json()
    async with session_scope() as db:
        from memora.models import KnowledgeDocument
        doc = await db.get(KnowledgeDocument, uuid.UUID(d["id"]))
        os.remove(doc.storage_path)
    await _run_jobs(["knowledge.index"])
    got = (await client.get(f"/api/knowledge/documents/{d['id']}", headers=auth(tok))).json()
    assert got["status"] == "failed" and got["error"], got
    async with session_scope() as db:
        job = (await db.execute(select(Job).where(Job.kind == "knowledge.index", Job.payload["document_id"].astext == d["id"]))).scalars().first()
        assert job.status == "done"  # permanent failure: no retry storm
    # no embedding key → indexed anyway, minus the vector leg: the document is usable by
    # keyword today and gains semantic search when a key is configured and it is re-indexed
    async with session_scope() as db:
        await S.put(db, "embedding.provider", "openai")
    try:
        n = (await client.post("/api/knowledge/documents", data={"kind": "note", "title": "memo", "body": "재택근무 규정은 주 3일입니다."}, headers=auth(tok))).json()
        await _run_jobs(["knowledge.index"])
        got = (await client.get(f"/api/knowledge/documents/{n['id']}", headers=auth(tok))).json()
        assert got["status"] == "ready" and got["error"] in (None, ""), got
        listing = (await client.get("/api/knowledge/documents", headers=auth(tok))).json()
        assert listing["semantic_search"] is False
        hits = (await client.get("/api/knowledge/search", params={"q": "재택근무"}, headers=auth(tok))).json()["items"]
        assert any("재택근무" in h["text"] for h in hits), hits
        from memora.services import knowledge as K
        async with session_scope() as db:
            rd = await K.read_document(db, uuid.UUID(user["id"]), uuid.UUID(n["id"]))
            assert "재택근무" in rd["text"]
    finally:
        async with session_scope() as db:
            await S.put(db, "embedding.provider", "hash")
    await client.post(f"/api/knowledge/documents/{n['id']}/reindex", headers=auth(tok))
    await _run_jobs(["knowledge.index"])
    got = (await client.get(f"/api/knowledge/documents/{n['id']}", headers=auth(tok))).json()
    assert got["status"] == "ready" and got["chunk_count"] == 1
    # FAQ: identical question embeds identically (hash) → single-query semantic hit on top
    await client.post("/api/knowledge/faqs", json={"question": "강연 문의는 어떻게 하나요?", "answer": "이메일로 주세요."}, headers=auth(tok))
    hits = (await client.get("/api/knowledge/search", params={"q": "강연 문의는 어떻게 하나요?"}, headers=auth(tok))).json()["items"]
    assert hits and hits[0].get("faq") is True and hits[0]["score"] >= 0.82
    hits = (await client.get("/api/knowledge/search", params={"q": "완전히 다른 질문 %_"}, headers=auth(tok))).json()["items"]
    assert not any(h.get("faq") for h in hits)


# ── 7. network ───────────────────────────────────────────────────────

async def test_network_search_escapes_wildcards_proposal_relation_and_merge_collision(client: AsyncClient):
    from memora.services import network as N
    user, tok = await signup(client)
    uid = uuid.UUID(user["id"])
    a = (await client.post("/api/network/nodes", json={"name": "김철수"}, headers=auth(tok))).json()["id"]
    b = (await client.post("/api/network/nodes", json={"name": "이영희"}, headers=auth(tok))).json()["id"]
    x = (await client.post("/api/network/nodes", json={"name": "ACME", "kind": "organization"}, headers=auth(tok))).json()["id"]
    for q in ("%", "_", "%%%", "_철_"):
        items = (await client.get("/api/network/nodes", params={"q": q}, headers=auth(tok))).json()["items"]
        assert items == [], (q, items)
    assert (await client.get("/api/network/nodes", params={"q": "철수"}, headers=auth(tok))).json()["items"][0]["name"] == "김철수"
    # Accepting a proposal about somebody unreachable used to mint a card out of free text.
    # Now there is nothing to accept: it resolves to nobody and retires itself (plan/31).
    async with session_scope() as db:
        p = await N.propose(db, uid, agent_id=None, kind="add_node",
                            payload={"kind": "person", "name": "박민수", "relation_to_owner": "former colleague", "reason": "mentioned in chat"})
        pid = p.id
    r = await client.post(f"/api/network/proposals/{pid}/accept", headers=auth(tok))
    assert r.status_code == 422, r.text
    async with session_scope() as db:
        from memora.models import NetworkProposal
        assert (await db.get(NetworkProposal, pid)).status == "obsolete"
    assert (await client.get("/api/network/nodes", params={"q": "박민수"}, headers=auth(tok))).json()["items"] == []
    # merge with colliding edges: a→X knows and b→X knows → one edge survives
    await client.post("/api/network/edges", json={"src_id": a, "dst_id": x, "rel": "knows"}, headers=auth(tok))
    await client.post("/api/network/edges", json={"src_id": b, "dst_id": x, "rel": "knows"}, headers=auth(tok))
    await client.post("/api/network/edges", json={"src_id": a, "dst_id": b, "rel": "friend"}, headers=auth(tok))
    r = await client.post(f"/api/network/nodes/{a}/merge", json={"into_id": b}, headers=auth(tok))
    assert r.status_code == 200, r.text
    detail = (await client.get(f"/api/network/nodes/{b}", headers=auth(tok))).json()
    assert [e for e in detail["edges"] if e["rel"] == "knows"] and len(detail["edges"]) == 1
    assert (await client.get(f"/api/network/nodes/{a}", headers=auth(tok))).status_code == 404


# ── 8. notifications ─────────────────────────────────────────────────

async def test_unsubscribe_footer_and_telegram_secret(client: AsyncClient):
    from memora.services import notifications as NT
    from memora.services import settings as S
    user, tok = await signup(client)
    ch = (await client.get("/api/notifications/channels", headers=auth(tok))).json()["items"][0]
    subject, text_, html = NT.render("visitor_message", {"text": "hi <b>", "agent_name": "x"}, channel_id=uuid.UUID(ch["id"]))
    assert "/api/notifications/unsubscribe?token=" in text_ and "&lt;b&gt;" in html
    token = text_.split("token=")[1].split()[0]
    r = await client.get(f"/api/notifications/unsubscribe?token={token}")
    assert r.status_code == 200 and r.json()["disabled"] is True
    chans = (await client.get("/api/notifications/channels", headers=auth(tok))).json()["items"]
    assert next(c for c in chans if c["id"] == ch["id"])["enabled"] is False
    # a file_share token must not unsubscribe anything
    from memora.core.security import sign_state
    bad = sign_state({"kind": "file_share", "doc": "x", "ch": ch["id"]})
    assert (await client.get(f"/api/notifications/unsubscribe?token={bad}")).status_code == 403
    # telegram: documented derivation + webhook check
    async with session_scope() as db:
        await S.put(db, "telegram.bot_token", "123456:ABCDEF")
    try:
        import hashlib
        expected = hashlib.sha256(b"123456:ABCDEF").hexdigest()[:32]
        assert NT.telegram_webhook_secret("123456:ABCDEF") == expected
        r = await client.post("/api/notifications/telegram/webhook", json={"message": {"text": "/start x", "chat": {"id": 1}}},
                              headers={"X-Telegram-Bot-Api-Secret-Token": "nope"})
        assert r.status_code == 403
        r = await client.post("/api/notifications/telegram/webhook", json={"message": {"text": "/start x", "chat": {"id": 1}}},
                              headers={"X-Telegram-Bot-Api-Secret-Token": expected})
        assert r.status_code == 200
    finally:
        async with session_scope() as db:
            await S.put(db, "telegram.bot_token", "")


async def test_admin_telegram_set_webhook(client: AsyncClient, monkeypatch):
    from memora.services import settings as S
    tok = await _admin_token(client)
    async with session_scope() as db:
        await S.put(db, "telegram.bot_token", "")
        await S.put(db, "telegram.bot_username", "")
    r = await client.post("/api/admin/telegram/set-webhook", headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "telegram_not_configured"
    calls: list[dict] = []

    class _R:
        def __init__(self, j):
            self._j = j

        def json(self):
            return self._j

    async def fake_request(method, url, **kw):
        calls.append({"method": method, "url": url, **kw})
        if url.endswith("/setWebhook"):
            return _R({"ok": True, "description": "Webhook was set"})
        return _R({"ok": True, "result": {"username": "memora_test_bot"}})

    import memora.providers.http as H
    monkeypatch.setattr(H, "request", fake_request)
    async with session_scope() as db:
        await S.put(db, "telegram.bot_token", "999:TOKEN")
    try:
        r = await client.post("/api/admin/telegram/set-webhook", headers=auth(tok))
        assert r.status_code == 200 and r.json()["ok"] is True and r.json()["bot_username"] == "memora_test_bot"
        sw = next(c for c in calls if c["url"].endswith("/setWebhook"))
        import hashlib
        assert sw["json"]["secret_token"] == hashlib.sha256(b"999:TOKEN").hexdigest()[:32]
        assert sw["json"]["url"] == "http://testserver/api/notifications/telegram/webhook"
        async with session_scope() as db:
            assert await S.get(db, "telegram.bot_username", use_cache=False) == "memora_test_bot"
    finally:
        async with session_scope() as db:
            await S.put(db, "telegram.bot_token", "")
            await S.put(db, "telegram.bot_username", "")


# ── 9. uploads ───────────────────────────────────────────────────────

async def test_upload_rejects_mime_mismatch_and_sanitizes_filename(client: AsyncClient):
    user, tok = await signup(client)
    r = await client.post("/api/uploads", files={"file": ("x.png", b"<html><script>alert(1)</script></html>", "image/png")}, data={"kind": "avatar"}, headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "mime_mismatch"
    r = await client.post("/api/uploads", files={"file": ("x.txt", b"a\x00b", "text/plain")}, headers=auth(tok))
    assert r.status_code == 422
    r = await client.post("/api/uploads", files={"file": ("../../etc/passwd.txt", b"hello", "text/plain")}, headers=auth(tok))
    assert r.status_code == 201 and r.json()["filename"] == "passwd.txt"


# ── 10. admin validation ─────────────────────────────────────────────

async def test_admin_settings_type_validation_and_reindex_trigger(client: AsyncClient):
    from memora.services import settings as S
    tok = await _admin_token(client)
    for bad in ({"credits.usd_per_credit": "abc"}, {"credits.usd_per_credit": -1}, {"signup.mode": "weird"}, {"smtp.port": 1.5},
                {"smtp.use_tls": "maybe"}, {"stripe.price_ids": "x"}, {"embedding.dim": "big"}):
        r = await client.put("/api/admin/settings", json={"values": bad}, headers=auth(tok))
        assert r.status_code == 422, (bad, r.text)
    r = await client.put("/api/admin/settings", json={"values": {"credits.usd_per_credit": "0.002", "smtp.port": "2525", "smtp.use_tls": "false"}}, headers=auth(tok))
    assert r.status_code == 200
    async with session_scope() as db:
        assert await S.get(db, "credits.usd_per_credit", use_cache=False) == 0.002
        assert await S.get(db, "smtp.port", use_cache=False) == 2525
        assert await S.get(db, "smtp.use_tls", use_cache=False) is False
        await S.put(db, "credits.usd_per_credit", 0.001)
    # embedding provider change queues a full re-embed
    r = await client.put("/api/admin/settings", json={"values": {"embedding.model": "text-embedding-3-large"}}, headers=auth(tok))
    assert r.status_code == 200 and r.json().get("_reindex_queued", 0) >= 1
    r = await client.put("/api/admin/settings", json={"values": {"embedding.model": "text-embedding-3-small"}}, headers=auth(tok))
    assert r.status_code == 200
    await _run_jobs(["knowledge.index"], max_jobs=50)


async def test_admin_plan_and_model_validation(client: AsyncClient):
    tok = await _admin_token(client)
    r = await client.post("/api/admin/plans", json={"code": "team", "name": "Team", "max_agents": 0}, headers=auth(tok))
    assert r.status_code == 422
    r = await client.post("/api/admin/plans", json={"code": "free", "name": "dup"}, headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "plan_code_taken"
    r = await client.post("/api/admin/plans", json={"code": f"t{uuid.uuid4().hex[:5]}", "name": "Team", "max_agents": 5, "features": {"voice": True}}, headers=auth(tok))
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert (await client.patch(f"/api/admin/plans/{pid}", json={"monthly_credits": "lots"}, headers=auth(tok))).status_code == 422
    assert (await client.patch(f"/api/admin/plans/{pid}", json={"monthly_credits": 999, "id": "ignored"}, headers=auth(tok))).json()["monthly_credits"] == 999
    models = (await client.get("/api/admin/models", headers=auth(tok))).json()["items"]
    m = next(x for x in models if x["provider"] == "claude_code")
    assert (await client.patch(f"/api/admin/models/{m['id']}", json={"context_window": "huge"}, headers=auth(tok))).status_code == 422
    assert (await client.patch(f"/api/admin/models/{m['id']}", json={"sort_order": 7}, headers=auth(tok))).json()["sort_order"] == 7
    # user patch with a non-existent plan id → 404, malformed → 422
    users = (await client.get("/api/admin/users", headers=auth(tok))).json()["items"]
    target = next(u for u in users if u["role"] != "admin")
    assert (await client.patch(f"/api/admin/users/{target['id']}", json={"plan_id": str(uuid.uuid4())}, headers=auth(tok))).status_code == 404
    assert (await client.patch(f"/api/admin/users/{target['id']}", json={"plan_id": "nope"}, headers=auth(tok))).status_code == 422


async def test_user_delete_purges_storage_and_last_admin_guard(client: AsyncClient):
    from memora.config import get_settings
    user, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "Del"}, headers=auth(tok))).json()["id"]
    await client.post("/api/uploads", files={"file": ("n.txt", b"note", "text/plain")}, headers=auth(tok))
    up_dir = get_settings().upload_root / user["id"]
    assert up_dir.exists()
    admin_tok = await _admin_token(client)
    assert (await client.delete("/api/users/me", headers=auth(admin_tok))).status_code == 409  # sole admin
    r = await client.delete(f"/api/admin/users/{user['id']}", headers=auth(admin_tok))
    assert r.status_code == 200
    assert not up_dir.exists()
    async with session_scope() as db:
        assert (await db.execute(text("SELECT 1 FROM credit_balances WHERE owner_id = :o"), {"o": user["id"]})).first() is None
        assert (await db.execute(text("SELECT 1 FROM agents WHERE id = :a"), {"a": a})).first() is None
    assert (await client.get("/api/auth/me", headers=auth(tok))).status_code == 401


# ── 11. claude code credentials guards ───────────────────────────────

async def test_claude_credentials_backup_restore_and_probe_precheck():
    import time

    from memora.services import claude_code as CC
    from memora.services import settings as S
    p = CC.creds_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        p.unlink()
    async with session_scope() as db:
        await S.put(db, "providers.claude_code.credentials_json", "")
        await S.put(db, "providers.claude_code.auth_mode", "oauth")
        assert await CC.backup_credentials(db) is False   # no file → nothing written
        assert await CC.restore_credentials(db) is False  # nothing stored
        r = await CC.probe(db)
        assert r["ok"] is False and r["error"].startswith("credentials_missing")
    expired = {"claudeAiOauth": {"accessToken": "a", "refreshToken": "r", "expiresAt": int((time.time() - 10) * 1000)}}
    p.write_text(json.dumps(expired))
    async with session_scope() as db:
        assert await CC.backup_credentials(db) is False   # expired file never overwrites
        r = await CC.probe(db)
        assert r["error"].startswith("credentials_expired")
    valid = {"claudeAiOauth": {"accessToken": "a", "refreshToken": "r", "expiresAt": int((time.time() + 3600) * 1000)}}
    p.write_text(json.dumps(valid))
    async with session_scope() as db:
        assert await CC.backup_credentials(db) is True
        assert await CC.backup_credentials(db) is False   # unchanged → no rewrite
        assert await CC.restore_credentials(db) is False  # live file is as new → untouched
    newer = {"claudeAiOauth": {"accessToken": "b", "refreshToken": "r2", "expiresAt": int((time.time() + 7200) * 1000)}}
    p.write_text(json.dumps(newer))
    async with session_scope() as db:
        assert await CC.backup_credentials(db) is True
    p.unlink()
    async with session_scope() as db:
        assert await CC.restore_credentials(db) is True
        assert json.loads(p.read_text())["claudeAiOauth"]["accessToken"] == "b"
        assert oct(p.stat().st_mode & 0o777) == "0o600"
        await S.put(db, "providers.claude_code.credentials_json", "")
    p.unlink()


# ── 12. memory ───────────────────────────────────────────────────────

async def test_note_store_path_guard(tmp_path):
    from memora.memory.notes import NoteStore
    ns = NoteStore(tmp_path / "owner")
    other = NoteStore(tmp_path / "visitors")
    n = other.write(title="secret", body="visitor-only")
    for evil in (f"../visitors/notes/{n.id}", "../../etc/passwd", "/etc/passwd", "notes/../../x"):
        assert ns.read(evil) is None
        assert ns.delete(evil) is False
        with pytest.raises(PermissionError):
            ns.write(title="x", body="y", note_id=evil)
    assert other.read(n.id) is not None


async def test_distill_tolerates_garbage_json(client: AsyncClient, monkeypatch):
    from memora.memory import distill as D
    from memora.models import Fact
    from memora.services import settings as S
    user, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "Dst"}, headers=auth(tok))).json()["id"]
    c = (await client.post(f"/api/agents/{a}/conversations", json={}, headers=auth(tok))).json()["id"]
    tid, _ = await _turn(client, tok, a, c, "I love tea")
    outputs = iter(['[1, 2, 3]', '{"facts": [1, {"subject": "owner", "predicate": "likes", "object": "tea", "confidence": "high"}], "note": "nope", "people": ["a", {"name": 5}]}'])

    async def fake_complete(db, **kw):
        return next(outputs), {"input_tokens": 10, "output_tokens": 5}
    monkeypatch.setattr(D, "complete", fake_complete)
    async with session_scope() as db:
        await S.put(db, "memory.distill_enabled", True)
    try:
        async with session_scope() as db:
            r1 = await D.distill_turn(db, uuid.UUID(tid))
            assert r1["facts"] == 0 and r1["people"] == 0
            r2 = await D.distill_turn(db, uuid.UUID(tid))
            assert r2["facts"] == 1 and r2["people"] == 0
        async with session_scope() as db:
            f = (await db.execute(select(Fact).where(Fact.owner_id == uuid.UUID(user["id"]), Fact.predicate == "likes"))).scalars().first()
            assert f is not None and f.confidence == 0.7 and f.object == "tea"
    finally:
        async with session_scope() as db:
            await S.put(db, "memory.distill_enabled", False)


async def test_index_cache_open_race_keeps_single_handle(tmp_path):
    from memora.memory.synapse import IndexCache
    cache = IndexCache(max_open=10)
    root = tmp_path / "ns"
    a, b = await asyncio.gather(cache.get(root), cache.get(root))
    assert a is b and cache.open_count() == 1
    await cache.drop(root)
