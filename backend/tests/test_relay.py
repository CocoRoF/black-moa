"""Secretary-to-secretary conversations (plan/38).

Two owners, two secretaries, one public link. The fake LLM answers a visitor by echoing
what it was told, and calls a tool when the text carries a ``[[tool:…]]`` marker, which is
enough to drive the whole loop: start → hop → hop → … → close, on every stopping rule.
"""
from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from tests.conftest import auth, read_sse, signup

pytestmark = pytest.mark.asyncio


async def _settings(**kv):
    from memora.db.session import session_scope
    from memora.services import settings as S
    async with session_scope() as db:
        for k, v in kv.items():
            await S.put(db, k, v)


async def _pair(client: AsyncClient, *, allow_agents: bool | None = None, agent_turns_per_day: int | None = None):
    """Owner X with secretary A; owner Y with secretary B and a public link to it."""
    await _settings(**{"relay.hop_delay_s": 0})
    xu, xtok = await signup(client, name="현우")
    a = (await client.post("/api/agents", json={"name": "에이"}, headers=auth(xtok))).json()
    _, ytok = await signup(client, name="서연")
    b = (await client.post("/api/agents", json={"name": "비"}, headers=auth(ytok))).json()
    link = (await client.post(f"/api/agents/{b['id']}/links", json={"label": "명함"}, headers=auth(ytok))).json()
    settings = {}
    if allow_agents is not None:
        settings["allow_agents"] = allow_agents
    if agent_turns_per_day is not None:
        settings["agent_turns_per_day"] = agent_turns_per_day
    if settings:
        r = await client.patch(f"/api/links/{link['id']}", json={"settings": settings}, headers=auth(ytok))
        assert r.status_code == 200, r.text
        link = r.json()
    return xtok, a, ytok, b, link


async def _drive(relay_id: str, max_hops: int = 12) -> list[dict]:
    """Play the worker and the API process: claim each queued hop, start its turn, wait for it."""
    from memora.db.session import session_scope
    from memora.models import AgentRelay
    from memora.pipeline.events import journals
    from memora.services import jobs as J
    from memora.services import relay as REL
    log = []
    for _ in range(max_hops):
        async with session_scope() as db:
            job = await J.claim(db, "test-worker", ["relay.hop"])
            if job is None:
                return log
            jid = job.id
        async with session_scope() as db:
            out = await REL.run_hop(db, uuid.UUID(relay_id))
        log.append(out)
        async with session_scope() as db:
            from memora.models import Job
            await J.finish(db, await db.get(Job, jid), result=out)
            r = await db.get(AgentRelay, uuid.UUID(relay_id))
            tid = r.in_flight_turn_id
        if tid:
            j = journals.get(tid)
            if j and j.task:
                await j.task
    return log


async def _relay(client, tok, rid) -> dict:
    r = await client.get(f"/api/relays/{rid}", headers=auth(tok))
    assert r.status_code == 200, r.text
    return r.json()


async def _assert_transcripts(client, xtok, ytok, a, b, rid):
    """The invariant this feature stands on: what each owner reads in their secretary's history
    is the whole exchange, message for message, whichever way it ended."""
    d = await _relay(client, xtok, rid)
    ledger = [m for m in d["messages"] if m["side"] != "system"]
    xa = (await client.get(f"/api/agents/{a['id']}/conversations", params={"kind": "agent"}, headers=auth(xtok))).json()["items"]
    yb = (await client.get(f"/api/agents/{b['id']}/conversations", params={"kind": "agent"}, headers=auth(ytok))).json()["items"]
    xa = [c for c in xa if c["relay_id"] == rid]
    yb = [c for c in yb if c["relay_id"] == rid]
    assert len(xa) == 1 and len(yb) == 1, (xa, yb)
    am = sorted((await client.get(f"/api/agents/{a['id']}/conversations/{xa[0]['id']}/messages", headers=auth(xtok))).json()["items"], key=lambda m: m["created_at"])
    bm = sorted((await client.get(f"/api/agents/{b['id']}/conversations/{yb[0]['id']}/messages", headers=auth(ytok))).json()["items"], key=lambda m: m["created_at"])
    am = [m for m in am if m["role"] in ("user", "assistant")]
    bm = [m for m in bm if m["role"] in ("user", "assistant")]
    exp_a = [("assistant" if m["side"] == "initiator" else "user", m["content"]) for m in ledger]
    exp_b = [("user" if m["side"] == "initiator" else "assistant", m["content"]) for m in ledger]
    # A turn's own answer is stored as the model wrote it (trailing newline and all); the
    # ledger and every delivered copy are stripped. Same words either way.
    got_a = [(m["role"], m["content"].strip()) for m in am]
    got_b = [(m["role"], m["content"].strip()) for m in bm]
    exp_a = [(r, c.strip()) for r, c in exp_a]
    exp_b = [(r, c.strip()) for r, c in exp_b]
    assert got_a == exp_a, ("A transcript", [(r, c[:30]) for r, c in got_a], [(r, c[:30]) for r, c in exp_a])
    assert got_b == exp_b, ("B transcript", [(r, c[:30]) for r, c in got_b], [(r, c[:30]) for r, c in exp_b])
    return d


async def _turn_credits(conversation_id: str) -> float:
    from memora.db.session import session_scope
    from memora.models import Turn
    async with session_scope() as db:
        return float((await db.execute(select(func.coalesce(func.sum(Turn.credits), 0)).where(Turn.conversation_id == uuid.UUID(conversation_id)))).scalar_one() or 0)


# ── the rules, one by one ─────────────────────────────────────────────────────

async def test_helpers_read_links_acks_and_redact():
    from memora.services import relay as REL
    assert REL.parse_target("https://memo-ora.com/secretary/hrjang-geny") == "hrjang-geny"
    assert REL.parse_target("  Abc-12 ") == "abc-12"
    from memora.core.errors import ValidationFailed
    with pytest.raises(ValidationFailed):
        REL.parse_target("not a link!")
    assert REL.is_ack("감사합니다!") and REL.is_ack("Thanks, bye") and REL.is_ack("네, 알겠습니다.")
    assert not REL.is_ack("내일 3시 괜찮으세요?") and not REL.is_ack("감사합니다. 그런데 장소는 어디가 좋을까요")
    assert REL.redact("번호는 010-1234-5678 이고 메일은 a@b.c", ["010-1234-5678", "a@b.c"]) == "번호는 [비공개] 이고 메일은 [비공개]"


async def test_a_link_can_refuse_other_secretaries(client: AsyncClient):
    xtok, a, ytok, b, link = await _pair(client, allow_agents=False)
    assert link["settings"] == {"allow_agents": False, "agent_turns_per_day": 20, "findable": True, "layout": "chat"}
    r = await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["url"], "message": "안녕하세요, 미팅 가능하실까요?"}, headers=auth(xtok))
    assert r.status_code == 201, r.text
    rel = r.json()
    assert rel["status"] == "closed" and rel["close_reason"] == "refused" and rel["message_count"] == 0
    assert rel["my_conversation_id"] is None                      # nothing was created on either side
    d = await _relay(client, xtok, rel["id"])
    assert [m["kind"] for m in d["messages"]] == ["system"]
    inbox = (await client.get("/api/inbox", headers=auth(xtok))).json()["items"]
    assert [i["kind"] for i in inbox] == ["relay_result"] and inbox[0]["payload"]["reason"] == "refused"
    assert (await client.get("/api/inbox", headers=auth(ytok))).json()["items"] == []
    # Y never sees a relay they refused; X sees it as the initiator.
    assert (await client.get("/api/relays", headers=auth(ytok))).json()["items"][0]["role"] == "target"


async def test_the_loop_alternates_and_stops_at_the_message_cap(client: AsyncClient):
    xtok, a, ytok, b, link = await _pair(client)
    r = await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "안녕하세요, 서연님 다음 주 미팅 가능한 시간이 있을까요?",
                                                                    "purpose": "다음 주 미팅 시간 확인", "max_messages": 4}, headers=auth(xtok))
    assert r.status_code == 201, r.text
    rel = r.json()
    assert rel["status"] == "open" and rel["hop_pending"] == "target" and rel["message_count"] == 1
    log = await _drive(rel["id"])
    assert [x.get("side") for x in log] == ["target", "initiator", "target"], log

    d = await _relay(client, xtok, rel["id"])
    assert d["status"] == "closed" and d["close_reason"] == "max_messages" and d["closed_by"] == "system"
    kinds = [(m["seq"], m["side"], m["kind"]) for m in d["messages"] if m["side"] != "system"]
    assert kinds == [(1, "initiator", "open"), (2, "target", "reply"), (3, "initiator", "reply"), (4, "target", "reply")]
    # B answered what A said: the text travelled.
    assert "미팅 가능한 시간" in d["messages"][1]["content"]
    assert d["role"] == "initiator" and d["peer_agent_name"] == "비" and d["my_agent_name"] == "에이"

    # Each side keeps its own conversation, tagged as a secretary conversation.
    xa = (await client.get(f"/api/agents/{a['id']}/conversations", params={"kind": "agent"}, headers=auth(xtok))).json()["items"]
    yb = (await client.get(f"/api/agents/{b['id']}/conversations", params={"kind": "agent"}, headers=auth(ytok))).json()["items"]
    assert len(xa) == 1 and xa[0]["kind"] == "agent" and xa[0]["relay_id"] == rel["id"] and xa[0]["audience"] == "visitor"
    assert len(yb) == 1 and yb[0]["kind"] == "agent" and yb[0]["relay_id"] == rel["id"]
    assert (await client.get(f"/api/agents/{a['id']}/conversations", params={"kind": "human"}, headers=auth(xtok))).json()["items"] == []
    am = (await client.get(f"/api/agents/{a['id']}/conversations/{xa[0]['id']}/messages", headers=auth(xtok))).json()["items"]
    bm = (await client.get(f"/api/agents/{b['id']}/conversations/{yb[0]['id']}/messages", headers=auth(ytok))).json()["items"]
    assert [m["role"] for m in sorted(am, key=lambda m: m["created_at"])] == ["assistant", "user", "assistant", "user"]
    assert [m["role"] for m in sorted(bm, key=lambda m: m["created_at"])] == ["user", "assistant", "user", "assistant"]
    # The last word reached A's transcript without A taking a turn on it.
    assert am[-1]["content"] == d["messages"][-1]["content"] if am[-1]["role"] == "user" else True

    # Both owners paid for their own secretary's turns, nobody for the other's.
    assert await _turn_credits(xa[0]["id"]) > 0 and await _turn_credits(yb[0]["id"]) > 0
    assert d["my_credits"] == pytest.approx(await _turn_credits(xa[0]["id"]))
    yd = await _relay(client, ytok, rel["id"])
    assert yd["role"] == "target" and yd["my_credits"] == pytest.approx(await _turn_credits(yb[0]["id"]))
    assert yd["messages"][0]["mine"] is False and yd["messages"][1]["mine"] is True

    # Both owners were told; the visitor rows say what they are.
    xi = (await client.get("/api/inbox", headers=auth(xtok))).json()["items"]
    yi = (await client.get("/api/inbox", headers=auth(ytok))).json()["items"]
    assert any(i["kind"] == "relay_result" and i["payload"]["reason"] == "max_messages" for i in xi)
    assert any(i["kind"] == "relay_visit" and i["payload"]["initiator_agent_name"] == "에이" for i in yi)
    from memora.db.session import session_scope
    from memora.models import Visitor
    async with session_scope() as db:
        tv = (await db.execute(select(Visitor).where(Visitor.agent_id == uuid.UUID(b["id"])))).scalars().first()
        assert tv.kind == "agent" and str(tv.peer_agent_id) == a["id"] and tv.display_name.startswith("에이 (")
        # No memory distillation for relay turns: two machines talking is not owner knowledge.
        from memora.models import Job, Turn
        turn_ids = {str(t) for (t,) in (await db.execute(select(Turn.id).where(Turn.conversation_id.in_([uuid.UUID(xa[0]["id"]), uuid.UUID(yb[0]["id"])])))).all()}
        assert turn_ids, "the relay ran turns"
        distilled = [j for j in (await db.execute(select(Job).where(Job.kind == "memory.distill"))).scalars().all() if str((j.payload or {}).get("turn_id")) in turn_ids]
        assert distilled == []
        # and the prompt block tells each side what this is
        from memora.models import Agent, AgentRelay, User
        from memora.services import relay as REL
        relay = await db.get(AgentRelay, uuid.UUID(rel["id"]))
        blk = await REL.prompt_block(db, relay.id, relay.target_conversation_id, await db.get(Agent, relay.target_agent_id), await db.get(User, relay.target_owner_id))
        assert "This exchange" in blk and "에이" in blk and "relay_close" in blk and len(blk) < 400
    # Nothing left queued, and both histories are the ledger.
    assert await _drive(rel["id"]) == []
    await _assert_transcripts(client, xtok, ytok, a, b, rel["id"])


async def test_a_side_can_close_it_with_the_tool(client: AsyncClient):
    xtok, a, ytok, b, link = await _pair(client)
    opener = '안녕하세요, 확인만 부탁드려요 [[tool:relay_close {"summary":"확인 완료, 더 물을 것 없음"}]]'
    rel = (await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": opener, "max_messages": 8}, headers=auth(xtok))).json()
    log = await _drive(rel["id"])
    assert [x.get("side") for x in log] == ["target"], log
    d = await _relay(client, xtok, rel["id"])
    assert d["status"] == "closed" and d["close_reason"] == "done" and d["closed_by"] == "target"
    assert d["summary"] == "확인 완료, 더 물을 것 없음"
    assert [m["kind"] for m in d["messages"] if m["side"] != "system"] == ["open", "close"]
    # A's transcript still got B's closing line — as a message, with no turn of A's.
    am = (await client.get(f"/api/agents/{a['id']}/conversations/{d['my_conversation_id']}/messages", headers=auth(xtok))).json()["items"]
    assert [m["role"] for m in sorted(am, key=lambda m: m["created_at"])] == ["assistant", "user"]
    assert await _turn_credits(d["my_conversation_id"]) == 0
    await _assert_transcripts(client, xtok, ytok, a, b, rel["id"])


async def test_started_from_the_owners_chat_and_reported_back_there(client: AsyncClient):
    xtok, a, ytok, b, link = await _pair(client)
    conv = (await client.post(f"/api/agents/{a['id']}/conversations", json={"title": ""}, headers=auth(xtok))).json()
    ask = ('비 비서한테 물어봐줘 [[tool:secretary_ask {"link":"' + link["url"] + '","message":"안녕하세요, 서연님 이번 주 통화 가능한 날이 있을까요?",'
           '"purpose":"통화 가능일 확인","max_messages":2}]]')
    async with client.stream("POST", f"/api/agents/{a['id']}/conversations/{conv['id']}/turns", json={"text": ask}, headers=auth(xtok)) as resp:
        events = await read_sse(resp)
    cards = [e["data"] for e in events if e.get("type") == "card"]
    assert cards and cards[0]["card_type"] == "relay_started" and cards[0]["payload"]["target_agent_name"] == "비"
    rid = cards[0]["payload"]["relay_id"]
    assert cards[0]["payload"]["status"] == "open"
    await _drive(rid)
    d = await _relay(client, xtok, rid)
    assert d["status"] == "closed" and d["close_reason"] == "max_messages" and d["message_count"] == 2
    assert d["purpose"] == "통화 가능일 확인"
    # The result came back into the chat it was asked in.
    msgs = (await client.get(f"/api/agents/{a['id']}/conversations/{conv['id']}/messages", headers=auth(xtok))).json()["items"]
    result = [m for m in msgs if any(c["card_type"] == "relay_result" for c in (m["cards"] or []))]
    assert len(result) == 1 and result[0]["role"] == "assistant" and "비(" in result[0]["content"]
    assert result[0]["cards"][0]["payload"]["relay_id"] == rid
    lst = (await client.get("/api/relays", params={"agent_id": a["id"]}, headers=auth(xtok))).json()["items"]
    assert [x["id"] for x in lst] == [rid]


async def test_no_self_talk_and_a_daily_cap_on_starting(client: AsyncClient):
    xtok, a, ytok, b, link = await _pair(client)
    own = (await client.post(f"/api/agents/{a['id']}/links", json={"label": "me"}, headers=auth(xtok))).json()
    r = await client.post(f"/api/agents/{a['id']}/relays", json={"target": own["code"], "message": "나야"}, headers=auth(xtok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "relay_self"
    r = await client.post(f"/api/agents/{a['id']}/relays", json={"target": "no-such-link-xyz", "message": "안녕"}, headers=auth(xtok))
    assert r.status_code == 404
    await _settings(**{"relay.threads_per_day": 1})
    try:
        r1 = await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "첫 번째", "max_messages": 2}, headers=auth(xtok))
        assert r1.status_code == 201
        r2 = await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "두 번째", "max_messages": 2}, headers=auth(xtok))
        assert r2.status_code == 409 and r2.json()["error"]["code"] == "relay_daily_cap"
    finally:
        await _settings(**{"relay.threads_per_day": 10})
    await _drive(r1.json()["id"])


async def test_a_revoked_link_closes_the_exchange(client: AsyncClient):
    xtok, a, ytok, b, link = await _pair(client)
    rel = (await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "안녕하세요, 질문이 있어요", "max_messages": 8}, headers=auth(xtok))).json()
    # one round trip: B answers, A answers back, now it is B's turn again
    log = await _drive(rel["id"], max_hops=2)
    assert [x.get("side") for x in log] == ["target", "initiator"]
    assert (await _relay(client, xtok, rel["id"]))["hop_pending"] == "target"
    assert (await client.delete(f"/api/links/{link['id']}", headers=auth(ytok))).status_code == 200
    log = await _drive(rel["id"])
    assert log and log[-1].get("closed") == "link_closed"
    d = await _relay(client, xtok, rel["id"])
    assert d["status"] == "closed" and d["close_reason"] == "link_closed" and d["message_count"] == 3
    # A's last line never got a turn on B's side — it must still be in B's history.
    await _assert_transcripts(client, xtok, ytok, a, b, rel["id"])


async def test_the_links_daily_budget_for_secretaries_holds(client: AsyncClient):
    xtok, a, ytok, b, link = await _pair(client, agent_turns_per_day=1)
    rel = (await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "안녕하세요", "max_messages": 8}, headers=auth(xtok))).json()
    assert rel["status"] == "open"
    log = await _drive(rel["id"])
    # B answered once (its one allowed turn today), A replied, B's second turn was refused.
    assert [x.get("side") for x in log[:2]] == ["target", "initiator"] and log[-1].get("closed") == "target_busy"
    assert (await _relay(client, xtok, rel["id"]))["close_reason"] == "target_busy"
    await _assert_transcripts(client, xtok, ytok, a, b, rel["id"])
    # A second relay today is refused at the door.
    rel2 = (await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "또 왔어요"}, headers=auth(xtok))).json()
    assert rel2["status"] == "closed" and rel2["close_reason"] == "target_busy"


async def test_private_details_never_leave_in_the_opener(client: AsyncClient):
    xtok, a, ytok, b, link = await _pair(client)
    r = await client.put("/api/users/me/profile", json={"data": {"contact": {"phone": "010-9999-0000"}}, "visibility": {"contact.phone": "private"}}, headers=auth(xtok))
    assert r.status_code == 200, r.text
    rel = (await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "제 번호 010-9999-0000 로 연락 주세요", "max_messages": 2}, headers=auth(xtok))).json()
    assert "010-9999-0000" not in rel["opener"] and "[비공개]" in rel["opener"]
    await _drive(rel["id"])
    yb = (await client.get(f"/api/agents/{b['id']}/conversations", params={"kind": "agent"}, headers=auth(ytok))).json()["items"]
    bm = (await client.get(f"/api/agents/{b['id']}/conversations/{yb[0]['id']}/messages", headers=auth(ytok))).json()["items"]
    assert all("010-9999-0000" not in m["content"] for m in bm)


async def test_an_owner_can_stop_it(client: AsyncClient):
    xtok, a, ytok, b, link = await _pair(client)
    rel = (await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "안녕하세요", "max_messages": 8}, headers=auth(xtok))).json()
    await _drive(rel["id"], max_hops=1)
    # B answered; A's turn is due but has not started — that answer must still reach A's history.
    r = await client.post(f"/api/relays/{rel['id']}/stop", headers=auth(ytok))
    assert r.status_code == 200 and r.json()["status"] == "closed" and r.json()["close_reason"] == "owner_stop"
    assert (await _drive(rel["id"]))[-1:] in ([], [{"skipped": "not_pending"}])
    await _assert_transcripts(client, xtok, ytok, a, b, rel["id"])
    # a stranger cannot even see it
    _, ztok = await signup(client)
    assert (await client.get(f"/api/relays/{rel['id']}", headers=auth(ztok))).status_code == 404
    assert (await client.post(f"/api/relays/{rel['id']}/stop", headers=auth(ztok))).status_code == 404


async def test_the_sweep_retries_stalls_and_expires_old_ones(client: AsyncClient):
    from memora.db.session import session_scope
    from memora.models import AgentRelay, Job
    from memora.services import relay as REL
    xtok, a, ytok, b, link = await _pair(client)
    rel = (await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "안녕하세요", "max_messages": 8}, headers=auth(xtok))).json()
    async with session_scope() as db:
        # drop the queued hop and pretend it went quiet for a while
        for j in (await db.execute(select(Job).where(Job.kind == "relay.hop", Job.status == "queued"))).scalars().all():
            await db.delete(j)
        r = await db.get(AgentRelay, uuid.UUID(rel["id"]))
        r.pending_since = datetime.now(UTC) - timedelta(minutes=30)
    async with session_scope() as db:
        out = await REL.sweep(db)
        assert out["retried"] == 1 and out["expired"] == 0
        assert (await db.execute(select(func.count(Job.id)).where(Job.kind == "relay.hop", Job.status == "queued"))).scalar_one() == 1
    await _drive(rel["id"], max_hops=1)
    async with session_scope() as db:
        r = await db.get(AgentRelay, uuid.UUID(rel["id"]))
        r.created_at = datetime.now(UTC) - timedelta(hours=30)
    async with session_scope() as db:
        out = await REL.sweep(db)
        assert out["expired"] == 1
    assert (await _relay(client, xtok, rel["id"]))["close_reason"] == "expired"
    await _assert_transcripts(client, xtok, ytok, a, b, rel["id"])


async def test_the_credit_cap_closes_it_and_the_histories_stay_whole(client: AsyncClient):
    xtok, a, ytok, b, link = await _pair(client)
    rel = (await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "안녕하세요, 견적 문의드립니다", "max_messages": 20, "credit_cap": 1}, headers=auth(xtok))).json()
    assert rel["status"] == "open" and rel["credit_cap"] == 1
    log = await _drive(rel["id"])
    d = await _relay(client, xtok, rel["id"])
    assert d["status"] == "closed" and d["close_reason"] == "credit_cap", (log, d["close_reason"])
    assert d["message_count"] >= 2
    await _assert_transcripts(client, xtok, ytok, a, b, rel["id"])


async def test_stopping_while_a_turn_runs_keeps_what_it_said(client: AsyncClient):
    """An owner stops it mid-turn: the turn is cancelled, the relay closes, and anything the
    cancelled turn still wrote is kept in the ledger and mirrored to the other side."""
    import asyncio

    from memora.db.session import session_scope
    from memora.models import AgentRelay
    from memora.pipeline.events import journals
    from memora.services import jobs as J
    from memora.services import relay as REL
    xtok, a, ytok, b, link = await _pair(client)
    rel = (await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "안녕하세요, 잠깐 여쭤볼게요", "max_messages": 8}, headers=auth(xtok))).json()
    async with session_scope() as db:
        job = await J.claim(db, "test-worker", ["relay.hop"])
        assert job is not None
    async with session_scope() as db:
        out = await REL.run_hop(db, uuid.UUID(rel["id"]))
        assert out.get("turn_id")
    r = await client.post(f"/api/relays/{rel['id']}/stop", headers=auth(xtok))
    assert r.status_code == 200 and r.json()["close_reason"] == "owner_stop"
    async with session_scope() as db:
        rr = await db.get(AgentRelay, uuid.UUID(rel["id"]))
        assert rr.status == "closed"
    j = journals.get(uuid.UUID(out["turn_id"]))
    if j and j.task:
        with contextlib.suppress(asyncio.CancelledError):
            await j.task
    await _assert_transcripts(client, xtok, ytok, a, b, rel["id"])


# ── finding the other secretary by name (plan/39) ─────────────────────────────

async def _friend(client, xtok, ytok, xuid, yuid):
    """인맥: each of them connects to the other (plan/43)."""
    assert (await client.post(f"/api/network/people/{yuid}/follow", headers=auth(xtok))).status_code == 200
    assert (await client.post(f"/api/network/people/{xuid}/follow", headers=auth(ytok))).status_code == 200


async def test_find_then_confirm_then_send(client: AsyncClient):
    from tests.conftest import signup as _signup
    await _settings(**{"relay.hop_delay_s": 0})
    xu, xtok = await signup(client, name="현우")
    a = (await client.post("/api/agents", json={"name": "에이"}, headers=auth(xtok))).json()
    yu, ytok = await _signup(client, name="배조스완")
    b = (await client.post("/api/agents", json={"name": "루나"}, headers=auth(ytok))).json()
    link = (await client.post(f"/api/agents/{b['id']}/links", json={"label": "명함"}, headers=auth(ytok))).json()
    assert link["settings"]["findable"] is True
    await _friend(client, xtok, ytok, xu["id"], yu["id"])
    conv = (await client.post(f"/api/agents/{a['id']}/conversations", json={"title": ""}, headers=auth(xtok))).json()

    # turn 1: the owner names the person; the secretary finds and must not send yet
    async with client.stream("POST", f"/api/agents/{a['id']}/conversations/{conv['id']}/turns", json={"text": '스완한테 인사 보내줘 [[tool:secretary_find {"name":"스완"}]]'}, headers=auth(xtok)) as resp:
        events = await read_sse(resp)
    cards = [e["data"] for e in events if e.get("type") == "card" and e["data"]["card_type"] == "relay_candidates"]
    assert cards, [e.get("type") for e in events]
    items = cards[0]["payload"]["items"]
    # accepting the friend link also put them in the owner's network — the strongest reason wins
    assert len(items) == 1 and items[0]["name"] == "배조스완" and items[0]["source"] == "network" and items[0]["reachable"] is True and items[0]["secretary"] == "루나"
    cand = items[0]["candidate_id"]
    # trying to send in the very same turn is refused by the server (not just by the prompt)
    from memora.db.session import session_scope
    from memora.models import Agent, RelayCandidate, User
    from memora.services import relay as REL
    async with session_scope() as db:
        c = await db.get(RelayCandidate, uuid.UUID(cand))
        owner = await db.get(User, c.owner_id)
        agent = await db.get(Agent, uuid.UUID(a["id"]))
        with pytest.raises(Exception) as ei:
            await REL.start(db, owner=owner, agent=agent, target="", message="안녕하세요", origin_conversation_id=c.conversation_id, origin_turn_id=c.turn_id, candidate_id=c.id)
        assert getattr(ei.value, "code", "") == "confirm_first"
        # …and handing the code over as a plain link in that same turn is refused too
        with pytest.raises(Exception) as ei2:
            await REL.start(db, owner=owner, agent=agent, target=link["code"], message="안녕하세요", origin_conversation_id=c.conversation_id, origin_turn_id=c.turn_id)
        assert getattr(ei2.value, "code", "") == "confirm_first"
        await db.rollback()

    # a second search in the same conversation hands back the same candidate (same id, same earlier turn)
    async with session_scope() as db:
        owner = await db.get(User, (await db.get(RelayCandidate, uuid.UUID(cand))).owner_id)
        agent = await db.get(Agent, uuid.UUID(a["id"]))
        again = await REL.find_candidates(db, owner=owner, agent=agent, query="배조", conversation_id=uuid.UUID(conv["id"]), turn_id=uuid.uuid4())
        assert [i["candidate_id"] for i in again] == [cand]
        await db.rollback()

    # turn 2: the owner confirms; now the send goes through with the candidate
    async with client.stream("POST", f"/api/agents/{a['id']}/conversations/{conv['id']}/turns", json={"text": '응 그 사람 맞아 [[tool:secretary_ask {"candidate_id":"' + cand + '","message":"안녕하세요, 현우님 비서 에이입니다. 안부 인사 드립니다.","purpose":"인사","max_messages":2}]]'}, headers=auth(xtok)) as resp:
        events = await read_sse(resp)
    started = [e["data"] for e in events if e.get("type") == "card" and e["data"]["card_type"] == "relay_started"]
    assert started and started[0]["payload"]["status"] == "open" and started[0]["payload"]["target_agent_name"] == "루나"
    rid = started[0]["payload"]["relay_id"]
    await _drive(rid)
    d = await _relay(client, xtok, rid)
    assert d["status"] == "closed" and d["message_count"] == 2
    await _assert_transcripts(client, xtok, ytok, a, b, rid)


async def test_find_reports_unreachable_and_directory_only(client: AsyncClient):
    from tests.conftest import signup as _signup
    xu, xtok = await signup(client, name="현우")
    a = (await client.post("/api/agents", json={"name": "에이"}, headers=auth(xtok))).json()
    yu, ytok = await _signup(client, name="문정아")
    b = (await client.post("/api/agents", json={"name": "미아"}, headers=auth(ytok))).json()
    link = (await client.post(f"/api/agents/{b['id']}/links", json={"label": "명함"}, headers=auth(ytok))).json()
    from memora.db.session import session_scope
    from memora.models import Agent, User
    from memora.services import relay as REL
    async with session_scope() as db:
        owner = await db.get(User, uuid.UUID(xu["id"]))
        agent = await db.get(Agent, uuid.UUID(a["id"]))
        # a stranger: directory only, reachable while the link is findable
        items = await REL.find_candidates(db, owner=owner, agent=agent, query="정아", conversation_id=None, turn_id=None)
        assert [(i["source"], i["reachable"], i["secretary"]) for i in items] == [("directory", True, "미아")]
        # two letters minimum, and never the owner themself
        assert await REL.find_candidates(db, owner=owner, agent=agent, query="문", conversation_id=None, turn_id=None) == []
        mine = await REL.find_candidates(db, owner=owner, agent=agent, query="현우", conversation_id=None, turn_id=None)
        assert all(i["user_id"] != xu["id"] for i in mine)   # other 현우s may exist; never the owner themself
    # the member switches "findable" off: still found as a person, but not reachable by name
    r = await client.patch(f"/api/links/{link['id']}", json={"settings": {"findable": False}}, headers=auth(ytok))
    assert r.status_code == 200
    async with session_scope() as db:
        owner = await db.get(User, uuid.UUID(xu["id"]))
        agent = await db.get(Agent, uuid.UUID(a["id"]))
        items = await REL.find_candidates(db, owner=owner, agent=agent, query="문정아", conversation_id=None, turn_id=None)
        assert len(items) == 1 and items[0]["reachable"] is False and items[0]["secretary"] is None
        with pytest.raises(Exception) as ei:
            await REL.start(db, owner=owner, agent=agent, target="", message="안녕", candidate_id=uuid.UUID(items[0]["candidate_id"]))
        assert getattr(ei.value, "code", "") == "candidate_unreachable"
        await db.rollback()


async def test_the_same_door_twice_a_day_at_most(client: AsyncClient):
    xtok, a, ytok, b, link = await _pair(client)
    for _ in range(2):
        r = await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "안녕하세요", "max_messages": 2}, headers=auth(xtok))
        assert r.status_code == 201, r.text
        await _drive(r.json()["id"])
    r = await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "또 안녕하세요", "max_messages": 2}, headers=auth(xtok))
    assert r.status_code == 409 and r.json()["error"]["code"] == "relay_target_cap"


async def test_a_refused_send_shows_a_failed_card_not_a_sent_one(client: AsyncClient):
    """The card is the owner's truth: when the server refuses a send, the chat shows it failed."""
    xtok, a, ytok, b, link = await _pair(client)
    for _ in range(2):
        r = await client.post(f"/api/agents/{a['id']}/relays", json={"target": link["code"], "message": "안녕하세요", "max_messages": 2}, headers=auth(xtok))
        assert r.status_code == 201
        await _drive(r.json()["id"])
    conv = (await client.post(f"/api/agents/{a['id']}/conversations", json={"title": ""}, headers=auth(xtok))).json()
    async with client.stream("POST", f"/api/agents/{a['id']}/conversations/{conv['id']}/turns", json={"text": '한 번 더 보내줘 [[tool:secretary_ask {"link":"' + link["code"] + '","message":"또 안녕하세요"}]]'}, headers=auth(xtok)) as resp:
        events = await read_sse(resp)
    cards = [e["data"] for e in events if e.get("type") == "card" and e["data"]["card_type"] == "relay_started"]
    assert cards and cards[0]["payload"]["status"] == "failed" and cards[0]["payload"]["close_reason"] == "relay_target_cap"
    assert len((await client.get("/api/relays", params={"agent_id": a["id"]}, headers=auth(xtok))).json()["items"]) == 2


async def test_find_by_the_public_profile_name(client: AsyncClient):
    """People are known by the name on their profile, not by their account label."""
    from tests.conftest import signup as _signup
    xu, xtok = await signup(client, name="현우")
    a = (await client.post("/api/agents", json={"name": "에이"}, headers=auth(xtok))).json()
    yu, ytok = await _signup(client, name="계정라벨")
    b = (await client.post("/api/agents", json={"name": "루나"}, headers=auth(ytok))).json()
    await client.post(f"/api/agents/{b['id']}/links", json={"label": "명함"}, headers=auth(ytok))
    r = await client.put("/api/users/me/profile", json={"data": {"preferred_name": "배조스완"}, "visibility": {"preferred_name": "public"}}, headers=auth(ytok))
    assert r.status_code == 200, r.text
    from memora.db.session import session_scope
    from memora.models import Agent, User
    from memora.services import relay as REL
    async with session_scope() as db:
        owner = await db.get(User, uuid.UUID(xu["id"]))
        agent = await db.get(Agent, uuid.UUID(a["id"]))
        items = await REL.find_candidates(db, owner=owner, agent=agent, query="스완", conversation_id=None, turn_id=None)
        mine = [i for i in items if i["user_id"] == yu["id"]]   # other tests may have made other 스완s
        assert [(i["name"], i["source"], i["secretary"]) for i in mine] == [("배조스완", "directory", "루나")]
        await db.rollback()
    # …but a private profile name is not searchable
    r = await client.put("/api/users/me/profile", json={"data": {"preferred_name": "배조스완"}, "visibility": {"preferred_name": "private"}}, headers=auth(ytok))
    assert r.status_code == 200
    async with session_scope() as db:
        owner = await db.get(User, uuid.UUID(xu["id"]))
        agent = await db.get(Agent, uuid.UUID(a["id"]))
        items = await REL.find_candidates(db, owner=owner, agent=agent, query="스완", conversation_id=None, turn_id=None)
        assert all(i["user_id"] != yu["id"] for i in items)


async def test_find_by_the_secretarys_own_name(client: AsyncClient):
    from tests.conftest import signup as _signup
    xu, xtok = await signup(client, name="현우")
    a = (await client.post("/api/agents", json={"name": "에이"}, headers=auth(xtok))).json()
    _, ytok = await _signup(client, name="아무개")
    b = (await client.post("/api/agents", json={"name": "오렌지비서"}, headers=auth(ytok))).json()
    await client.post(f"/api/agents/{b['id']}/links", json={"label": "명함"}, headers=auth(ytok))
    from memora.db.session import session_scope
    from memora.models import Agent, User
    from memora.services import relay as REL
    async with session_scope() as db:
        owner = await db.get(User, uuid.UUID(xu["id"]))
        agent = await db.get(Agent, uuid.UUID(a["id"]))
        items = await REL.find_candidates(db, owner=owner, agent=agent, query="오렌지", conversation_id=None, turn_id=None)
        assert [(i["source"], i["secretary"], i["reachable"]) for i in items] == [("secretary", "오렌지비서", True)]
        await db.rollback()


async def test_a_name_handed_to_secretary_ask_becomes_a_lookup(client: AsyncClient):
    """The model may skip secretary_find and pass a name as the link: the tool does the lookup,
    shows candidates, and refuses to send until the owner confirms in a later turn."""
    from tests.conftest import signup as _signup
    await _settings(**{"relay.hop_delay_s": 0})
    _, xtok = await signup(client, name="현우")
    a = (await client.post("/api/agents", json={"name": "에이"}, headers=auth(xtok))).json()
    yu, ytok = await _signup(client, name="한지민")
    b = (await client.post("/api/agents", json={"name": "지미"}, headers=auth(ytok))).json()
    await client.post(f"/api/agents/{b['id']}/links", json={"label": "명함"}, headers=auth(ytok))
    conv = (await client.post(f"/api/agents/{a['id']}/conversations", json={"title": ""}, headers=auth(xtok))).json()
    async with client.stream("POST", f"/api/agents/{a['id']}/conversations/{conv['id']}/turns", json={"text": '지민한테 인사 보내줘 [[tool:secretary_ask {"link":"한지민","message":"안녕하세요"}]]'}, headers=auth(xtok)) as resp:
        events = await read_sse(resp)
    cards = [e["data"] for e in events if e.get("type") == "card"]
    assert [cd["card_type"] for cd in cards] == ["relay_candidates"]
    items = [i for i in cards[0]["payload"]["items"] if i["user_id"] == yu["id"]]   # other 한지민s may exist from earlier tests
    assert items and items[0]["name"] == "한지민" and items[0]["secretary"] == "지미"
    assert (await client.get("/api/relays", params={"agent_id": a["id"]}, headers=auth(xtok))).json()["items"] == []
    # next turn, the owner confirms → sent
    async with client.stream("POST", f"/api/agents/{a['id']}/conversations/{conv['id']}/turns", json={"text": '네 그분 맞아요 [[tool:secretary_ask {"candidate_id":"' + items[0]["candidate_id"] + '","message":"안녕하세요, 현우님 비서입니다.","max_messages":2}]]'}, headers=auth(xtok)) as resp:
        events = await read_sse(resp)
    started = [e["data"] for e in events if e.get("type") == "card" and e["data"]["card_type"] == "relay_started"]
    assert started and started[0]["payload"]["status"] == "open"
    await _drive(started[0]["payload"]["relay_id"])
    assert (await _relay(client, xtok, started[0]["payload"]["relay_id"]))["status"] == "closed"
