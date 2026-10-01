"""Asking around: finding somebody to ask, from what they published (plan/41 §6).

The point is the other person's time. A member with a question gets an answer without
anybody being interrupted, so the list of who to ask has to come from what people chose to
publish, and it may only contain people whose secretary actually takes inquiries.
"""
from __future__ import annotations

import uuid as _uuid

from httpx import AsyncClient

from blackmoa.db.session import session_scope
from blackmoa.models import Agent, User
from blackmoa.services import relay as REL
from tests.conftest import auth, signup
from tests.test_blog import _open_page


def test_the_words_worth_searching_for():
    """The noun the question is about must survive; the way it was asked must not."""
    assert "이직" in REL.keywords("이직을 고민 중인데 누구한테 물어보지?")
    assert "스타트업" in REL.keywords("스타트업 문화가 어떤지 궁금해요")
    for junk in ("누구", "어떻게", "물어보지"):
        assert junk not in REL.keywords(f"{junk} 이직 고민")
    assert REL.keywords("") == [] and REL.keywords("누가 어떻게?") == []


async def _owner_and_agent(user_id: str) -> tuple[User, Agent]:
    async with session_scope() as db:
        owner = await db.get(User, _uuid.UUID(user_id))
        agent = Agent(owner_id=owner.id, name="내비서", provider="fake", model_id="fake-1")
        db.add(agent)
        await db.flush()
        await db.commit()
        return owner, agent


async def test_the_people_to_ask_come_from_what_they_wrote(client: AsyncClient):
    asker, atok = await signup(client, name="묻는사람")
    writer, wtok = await signup(client, name="쓴사람")
    quiet, qtok = await signup(client, name="조용한사람")
    tag = _uuid.uuid4().hex[:5]
    await _open_page(writer["id"], f"wr{tag}")
    await _open_page(quiet["id"], f"qu{tag}")

    await client.post("/api/blog", headers=auth(wtok), json={
        "title": "스타트업으로 이직하며 배운 것", "body": "이직을 결심하기까지 반년이 걸렸습니다."})
    # Something nobody asked about, and a private post that must not count.
    await client.post("/api/blog", headers=auth(qtok), json={
        "title": "내 텃밭 가꾸기", "body": "상추가 잘 자랍니다."})
    await client.post("/api/blog", headers=auth(qtok), json={
        "title": "이직 준비 기록", "body": "비공개로 적어둡니다.", "visibility": "private"})

    owner, agent = await _owner_and_agent(asker["id"])
    async with session_scope() as db:
        owner = await db.get(User, owner.id)
        agent = await db.get(Agent, agent.id)
        items = await REL.find_by_topic(db, owner=owner, agent=agent, question="이직 고민인데 누구한테 물어보지?",
                                        conversation_id=None, turn_id=None)
        await db.commit()
    assert [i["name"] for i in items] == ["쓴사람"], items
    got = items[0]
    assert got["source"] == "wrote" and "이직" in got["why"]
    # Reachable, with a candidate to confirm against: sending happens in a later turn.
    assert got["reachable"] is True and got["candidate_id"]


async def test_profiles_answer_when_nobody_wrote_about_it(client: AsyncClient):
    asker, _ = await signup(client)
    dev, dtok = await signup(client, name="개발자")
    tag = _uuid.uuid4().hex[:5]
    await _open_page(dev["id"], f"dev{tag}")
    await client.put("/api/users/me/profile", headers=auth(dtok), json={
        "data": {"title": "백엔드 개발자", "bio": "결제 시스템을 만듭니다"},
        "visibility": {"title": "public", "bio": "public"}})

    owner, agent = await _owner_and_agent(asker["id"])
    async with session_scope() as db:
        owner = await db.get(User, owner.id)
        agent = await db.get(Agent, agent.id)
        items = await REL.find_by_topic(db, owner=owner, agent=agent, question="결제 시스템은 어떻게 만드나요",
                                        conversation_id=None, turn_id=None)
        await db.commit()
    assert [i["name"] for i in items] == ["개발자"]
    assert items[0]["source"] == "profile" and "결제" in items[0]["why"]


async def test_somebody_who_cannot_be_asked_is_not_offered(client: AsyncClient):
    """A name search may return people with no way in, because the owner can still be told
    to get a link. A topic search may not: it exists to produce a question that gets asked."""
    asker, _ = await signup(client)
    hidden, htok = await signup(client, name="숨은사람")
    # A post, but no published secretary: nothing to ask.
    await client.post("/api/blog", headers=auth(htok), json={"title": "케이크 굽는 법", "body": "오븐을 180도로 예열합니다."})

    owner, agent = await _owner_and_agent(asker["id"])
    async with session_scope() as db:
        owner = await db.get(User, owner.id)
        agent = await db.get(Agent, agent.id)
        items = await REL.find_by_topic(db, owner=owner, agent=agent, question="케이크 굽는 법 알려주세요",
                                        conversation_id=None, turn_id=None)
        await db.commit()
    assert items == []


async def test_you_are_not_offered_yourself(client: AsyncClient):
    """Asking around is for reaching other people. My own writing is not an answer to me."""
    me, tok = await signup(client, name="나")
    tag = _uuid.uuid4().hex[:5]
    await _open_page(me["id"], f"me{tag}")
    marker = f"두리안{tag}"
    await client.post("/api/blog", headers=auth(tok), json={"title": f"내가 쓴 {marker} 이야기", "body": f"{marker}은 어렵다."})
    owner, agent = await _owner_and_agent(me["id"])
    async with session_scope() as db:
        owner = await db.get(User, owner.id)
        agent = await db.get(Agent, agent.id)
        items = await REL.find_by_topic(db, owner=owner, agent=agent, question=f"{marker} 이야기",
                                        conversation_id=None, turn_id=None)
        await db.commit()
    # Nobody else wrote about it, and the one person who did is the asker.
    assert items == [], items
    assert me["id"] not in [i["user_id"] for i in items]


async def test_the_address_book_hands_back_people_to_ask_when_it_has_nobody(client: AsyncClient):
    """The model reaches for the address book when the owner asks who to ask. Telling it to
    look elsewhere did not stick, so the lookup happens here and the answer comes back with
    the result (plan/41 §6)."""
    asker, atok = await signup(client)
    writer, wtok = await signup(client, name="아는사람")
    tag = _uuid.uuid4().hex[:5]
    topic = f"사내카페테리아{tag}"
    await _open_page(writer["id"], f"cafe{tag}")
    await client.post("/api/blog", headers=auth(wtok), json={"title": f"{topic} 운영을 맡으며", "body": f"{topic} 운영을 2년째 맡고 있습니다."})

    owner, agent = await _owner_and_agent(asker["id"])
    from blackmoa.pipeline.tools.network_tools import NetworkSearch

    class _Ctx:
        owner_id = owner.id
        is_owner = True
        audience = "owner"
        conversation_id = None
        turn_id = None
        cards: list = []

        def __init__(self, agent_id):
            self.agent = type("A", (), {"id": agent_id})()

        def card(self, kind, payload):
            self.cards.append((kind, payload))

    ctx = _Ctx(agent.id)
    tool = NetworkSearch.__new__(NetworkSearch)
    tool.ctx = ctx
    out = await tool.run({"query": f"{topic} 담당자"})
    assert out["results"] == []
    assert [p["name"] for p in out.get("people_to_ask", [])] == ["아는사람"], out
    assert topic in out["people_to_ask"][0]["why"]
    assert ctx.cards and ctx.cards[0][0] == "relay_candidates"
