"""Saying an answer was wrong, and what was actually the case (plan/41 §8).

The product knew how to keep a secret and had no way to be told it was wrong. The test
that matters is not that a row was written: it is that the correction comes back as an
answer the secretary can find.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select

from memora.db.session import session_scope
from memora.models import Agent, Conversation, KnowledgeFaq, Message, Turn, User
from tests.conftest import auth, signup


async def _turn(owner_id: str, *, asked: str, said: str) -> tuple[str, str]:
    async with session_scope() as db:
        owner = await db.get(User, _uuid.UUID(owner_id))
        agent = Agent(owner_id=owner.id, name="비서", provider="fake", model_id="fake-1")
        db.add(agent)
        await db.flush()
        conv = Conversation(owner_id=owner.id, agent_id=agent.id, audience="visitor", title="t")
        db.add(conv)
        await db.flush()
        turn = Turn(conversation_id=conv.id, owner_id=owner.id, agent_id=agent.id, audience="visitor",
                    status="done", started_at=datetime.now(UTC))
        db.add(turn)
        await db.flush()
        now = datetime.now(UTC)
        db.add(Message(conversation_id=conv.id, owner_id=owner.id, role="user", content=asked, turn_id=turn.id, created_at=now))
        db.add(Message(conversation_id=conv.id, owner_id=owner.id, role="assistant", content=said, turn_id=turn.id, created_at=now))
        await db.commit()
        return str(agent.id), str(turn.id)


async def _faqs(owner_id: str) -> list[KnowledgeFaq]:
    async with session_scope() as db:
        return list((await db.execute(select(KnowledgeFaq).where(KnowledgeFaq.owner_id == _uuid.UUID(owner_id)))).scalars().all())


async def test_a_correction_becomes_an_answer_the_secretary_can_find(client: AsyncClient):
    user, tok = await signup(client)
    agent_id, turn_id = await _turn(user["id"], asked="사무실이 어디예요?", said="강남에 있습니다.")

    r = await client.post(f"/api/agents/{agent_id}/turns/{turn_id}/feedback", headers=auth(tok),
                          json={"verdict": "wrong", "note": "판교입니다. 강남 사무실은 작년에 정리했어요."})
    assert r.status_code == 200, r.text
    assert r.json()["verdict"] == "wrong" and r.json()["faq_id"]
    assert r.json()["question"] == "사무실이 어디예요?"

    faqs = await _faqs(user["id"])
    assert len(faqs) == 1
    assert faqs[0].question == "사무실이 어디예요?" and faqs[0].answer.startswith("판교입니다")
    assert faqs[0].source == "corrected"
    # 외부인이 물은 것을 주인이 고친 답이라, 그 비서는 외부인과의 대화에서도 이 답을 쓴다 (plan/57).
    from memora.models import Agent
    from memora.services import outsider as OUT
    async with session_scope() as db:
        sc = await OUT.scope(db, await db.get(Agent, _uuid.UUID(agent_id)), "knowledge", "stranger")
    assert sc is not None and sc.has_faq(faqs[0].id)

    # Saying it again replaces the verdict rather than piling up rows.
    r = await client.post(f"/api/agents/{agent_id}/turns/{turn_id}/feedback", headers=auth(tok),
                          json={"verdict": "wrong", "note": "판교 H스퀘어입니다."})
    assert r.status_code == 200
    faqs = await _faqs(user["id"])
    assert len(faqs) == 1 and faqs[0].answer == "판교 H스퀘어입니다."


async def test_wrong_without_a_correction_is_still_recorded(client: AsyncClient):
    """Marking it wrong with no time to fix it is a signal, not nothing."""
    user, tok = await signup(client)
    agent_id, turn_id = await _turn(user["id"], asked="언제 시간 되세요?", said="아무 때나 됩니다.")
    r = await client.post(f"/api/agents/{agent_id}/turns/{turn_id}/feedback", headers=auth(tok), json={"verdict": "wrong"})
    assert r.status_code == 200 and r.json()["faq_id"] is None
    assert await _faqs(user["id"]) == []


async def test_only_the_owner_judges_their_own_secretary(client: AsyncClient):
    user, tok = await signup(client)
    _, other_tok = await signup(client)
    agent_id, turn_id = await _turn(user["id"], asked="무슨 일 하세요?", said="개발자입니다.")
    r = await client.post(f"/api/agents/{agent_id}/turns/{turn_id}/feedback", headers=auth(other_tok),
                          json={"verdict": "wrong", "note": "아닙니다"})
    assert r.status_code == 404
    assert (await client.post(f"/api/agents/{agent_id}/turns/{turn_id}/feedback", headers=auth(tok),
                              json={"verdict": "무효"})).status_code == 422


async def test_a_correction_stays_visible_on_the_answer_it_corrected(client: AsyncClient):
    """Reopening the conversation has to show what was already said about an answer.

    Without it the owner reads the same wrong sentence a week later with nothing to say it
    was dealt with, and tells the secretary the same thing twice.
    """
    user, tok = await signup(client)
    agent_id, turn_id = await _turn(user["id"], asked="주차 되나요?", said="건물에 주차장이 없습니다.")
    async with session_scope() as db:
        turn = await db.get(Turn, _uuid.UUID(turn_id))
        cid = str(turn.conversation_id)

    before = (await client.get(f"/api/agents/{agent_id}/conversations/{cid}/messages", headers=auth(tok))).json()["items"]
    assert all("feedback" not in m for m in before)

    await client.post(f"/api/agents/{agent_id}/turns/{turn_id}/feedback", headers=auth(tok),
                      json={"verdict": "wrong", "note": "지하 주차장이 있습니다."})
    after = (await client.get(f"/api/agents/{agent_id}/conversations/{cid}/messages", headers=auth(tok))).json()["items"]
    marked = [m for m in after if m.get("feedback")]
    assert len(marked) == 2  # both messages of that turn carry the mark
    assert marked[0]["feedback"]["verdict"] == "wrong"
    assert marked[0]["feedback"]["note"] == "지하 주차장이 있습니다."
