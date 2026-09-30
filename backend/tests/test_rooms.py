"""메신저 — 방 (plan/44).

세 가지가 참이어야 한다. 방에 있는 사람만 방을 본다. 어디까지 읽었는지는 기기가 아니라
사람에게 붙는다. 그리고 비서와의 대화는 방이 되었어도 턴은 그대로 돈다.
"""
from __future__ import annotations

import uuid as _uuid

from httpx import AsyncClient
from sqlalchemy import select

from memora.db.session import session_scope
from memora.models import Conversation, Room, RoomMember
from tests.conftest import auth, signup


async def _connect(client: AsyncClient, a: dict, atok: str, b: dict, btok: str) -> None:
    await client.post(f"/api/network/people/{b['id']}/follow", headers=auth(atok))
    await client.post(f"/api/network/people/{a['id']}/follow", headers=auth(btok))


async def test_a_room_opens_once_and_both_sides_land_in_it(client: AsyncClient):
    me, mytok = await signup(client)
    you, youtok = await signup(client, name="상대")
    await _connect(client, me, mytok, you, youtok)

    r = await client.post("/api/rooms/open", headers=auth(mytok), json={"user_id": you["id"]})
    assert r.status_code == 201, r.text
    room = r.json()
    assert room["kind"] == "dm" and [o["id"] for o in room["others"]] == [you["id"]]

    # Asking again lands on the same room, from either side.
    again = await client.post("/api/rooms/open", headers=auth(mytok), json={"user_id": you["id"]})
    assert again.json()["id"] == room["id"]
    theirs = await client.post("/api/rooms/open", headers=auth(youtok), json={"user_id": me["id"]})
    assert theirs.json()["id"] == room["id"]
    assert [o["id"] for o in theirs.json()["others"]] == [me["id"]]


async def test_talking_starts_with_connecting(client: AsyncClient):
    me, mytok = await signup(client)
    stranger, _ = await signup(client, name="남세나")
    r = await client.post("/api/rooms/open", headers=auth(mytok), json={"user_id": stranger["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_connected"
    assert (await client.post("/api/rooms/open", headers=auth(mytok),
                              json={"user_id": me["id"]})).status_code == 422


async def test_a_room_i_am_not_in_is_not_announced_as_existing(client: AsyncClient):
    me, mytok = await signup(client)
    you, youtok = await signup(client, name="상대")
    nosy, nosytok = await signup(client, name="남세나")
    await _connect(client, me, mytok, you, youtok)
    rid = (await client.post("/api/rooms/open", headers=auth(mytok), json={"user_id": you["id"]})).json()["id"]
    await client.post(f"/api/rooms/{rid}/messages", headers=auth(mytok), json={"body": "우리끼리"})

    assert (await client.get(f"/api/rooms/{rid}", headers=auth(nosytok))).status_code == 404
    assert (await client.get(f"/api/rooms/{rid}/messages", headers=auth(nosytok))).status_code == 404
    assert (await client.post(f"/api/rooms/{rid}/messages", headers=auth(nosytok),
                              json={"body": "끼어들기"})).status_code == 404
    assert (await client.get("/api/rooms", headers=auth(nosytok))).json()["items"] == []


async def test_what_is_said_reaches_the_other_side(client: AsyncClient):
    me, mytok = await signup(client)
    you, youtok = await signup(client, name="상대")
    await _connect(client, me, mytok, you, youtok)
    rid = (await client.post("/api/rooms/open", headers=auth(mytok), json={"user_id": you["id"]})).json()["id"]

    await client.post(f"/api/rooms/{rid}/messages", headers=auth(mytok), json={"body": "안녕하세요"})
    await client.post(f"/api/rooms/{rid}/messages", headers=auth(youtok), json={"body": "네 안녕하세요"})

    rows = (await client.get(f"/api/rooms/{rid}/messages", headers=auth(youtok))).json()
    assert [m["body"] for m in rows["items"]] == ["안녕하세요", "네 안녕하세요"]
    assert rows["items"][0]["sender_user_id"] == me["id"]
    assert {m["id"] for m in rows["members"]} == {me["id"], you["id"]}
    assert (await client.post(f"/api/rooms/{rid}/messages", headers=auth(mytok),
                              json={"body": "  "})).status_code == 422


async def test_how_far_i_have_read_is_mine_not_my_devices(client: AsyncClient):
    """폰에서 읽으면 데스크톱에서도 읽힌 것이다. 답은 사람에게 붙는다."""
    me, mytok = await signup(client)
    you, youtok = await signup(client, name="상대")
    await _connect(client, me, mytok, you, youtok)
    rid = (await client.post("/api/rooms/open", headers=auth(mytok), json={"user_id": you["id"]})).json()["id"]

    await client.post(f"/api/rooms/{rid}/messages", headers=auth(mytok), json={"body": "읽어주세요"})
    # 말한 사람에게는 새것이 아니다.
    assert (await client.get("/api/rooms", headers=auth(mytok))).json()["unread"] == 0
    mine = (await client.get("/api/rooms", headers=auth(youtok))).json()
    assert mine["unread"] == 1 and mine["items"][0]["unread"] is True

    # 다른 기기로 읽어도 같은 자리에 적힌다.
    assert (await client.post(f"/api/rooms/{rid}/read", headers=auth(youtok))).json()["unread"] == 0
    assert (await client.get("/api/rooms", headers=auth(youtok))).json()["items"][0]["unread"] is False


async def test_my_own_secretary_chat_is_a_room_and_the_turn_still_runs(client: AsyncClient):
    """봉투가 생겼을 뿐 안에서 도는 것은 그대로다 (plan/44 §2)."""
    user, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(tok))).json()

    r = await client.post("/api/rooms/open", headers=auth(tok), json={"agent_id": agent["id"]})
    assert r.status_code == 201, r.text
    room = r.json()
    assert room["kind"] == "secretary" and room["conversation_id"]
    assert [o["kind"] for o in room["others"]] == ["agent"]
    assert [o["name"] for o in room["others"]] == ["서기"]

    async with session_scope() as db:
        conv = await db.get(Conversation, _uuid.UUID(room["conversation_id"]))
        assert conv is not None and conv.audience == "owner"
        mem = (await db.execute(select(RoomMember).where(
            RoomMember.room_id == _uuid.UUID(room["id"])))).scalars().all()
        assert {m.role for m in mem} == {"member", "secretary"}

    # 대화에 말이 쌓이면 방에도 쌓인다. 한 줄이 두 군데로 갈라지지 않는다.
    async with session_scope() as db:
        from memora.services import conversations as CV
        conv = await db.get(Conversation, _uuid.UUID(room["conversation_id"]))
        await CV.add_message(db, conv, role="user", content="안녕하세요")
        await db.commit()
    rows = (await client.get(f"/api/rooms/{room['id']}/messages", headers=auth(tok))).json()["items"]
    assert [m["body"] for m in rows] == ["안녕하세요"]
    assert rows[0]["sender_user_id"] == user["id"]


async def test_a_secretary_i_never_visited_is_visited_from_here(client: AsyncClient):
    """남의 비서와의 방은 여기서 바로 시작한다. 공개 문이 하는 일을 계정으로 한다 (plan/44 §5)."""
    from memora.models import Visitor

    them, ttok = await signup(client, name="남세나")
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(ttok))).json()
    await client.post(f"/api/agents/{agent['id']}/links", json={}, headers=auth(ttok))

    me, mytok = await signup(client)
    r = await client.post("/api/rooms/open", headers=auth(mytok), json={"agent_id": agent["id"]})
    assert r.status_code == 201, r.text
    room = r.json()
    assert room["kind"] == "secretary" and room["own_secretary"] is False
    assert room["others"][0]["owner_name"] == "남세나"
    async with session_scope() as db:
        v = (await db.execute(select(Visitor).where(Visitor.user_id == _uuid.UUID(me["id"])))).scalars().first()
        assert v is not None and v.agent_id == _uuid.UUID(agent["id"]) and v.kind == "human"
    # 같은 사람은 같은 방. 다시 열어도 하나다.
    again = await client.post("/api/rooms/open", headers=auth(mytok), json={"agent_id": agent["id"]})
    assert again.json()["id"] == room["id"]


async def test_an_anonymous_visit_belongs_to_nobody(client: AsyncClient):
    """보여줄 사람이 없는 대화에는 방이 없다."""
    them, ttok = await signup(client, name="남세나")
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(ttok))).json()
    link = (await client.post(f"/api/agents/{agent['id']}/links", json={}, headers=auth(ttok))).json()
    r = await client.post(f"/api/public/links/{link['code']}/visitor", json={"display_name": "지나가던 사람"})
    assert r.status_code == 200, r.text
    cid = r.json()["conversation_id"]
    async with session_scope() as db:
        room = (await db.execute(select(Room).where(Room.conversation_id == _uuid.UUID(cid)))).scalars().first()
    assert room is None


async def test_what_i_said_to_somebody_elses_secretary_is_mine_too(client: AsyncClient):
    """로그인한 채로 남의 비서에게 말을 걸면 그 대화는 내 목록에도 있어야 한다 (plan/44 §5).

    그 대화는 비서 주인의 것이기도 하다. 주인은 지금처럼 [대화]에서 본다. 새로 보여지는
    것은 없고, 말을 건 사람에게 문이 하나 생겼을 뿐이다.
    """
    them, ttok = await signup(client, name="남세나")
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(ttok))).json()
    link = (await client.post(f"/api/agents/{agent['id']}/links", json={}, headers=auth(ttok))).json()

    me, mytok = await signup(client)
    r = await client.post(f"/api/public/links/{link['code']}/visitor", json={}, headers=auth(mytok))
    assert r.status_code == 200, r.text
    cid = r.json()["conversation_id"]

    async with session_scope() as db:
        from memora.services import conversations as CV
        conv = await db.get(Conversation, _uuid.UUID(cid))
        await CV.add_message(db, conv, role="user", content="안녕하세요, 사장님 계신가요")
        await db.commit()

    rooms = (await client.get("/api/rooms", headers=auth(mytok))).json()["items"]
    assert len(rooms) == 1 and rooms[0]["conversation_id"] == cid
    assert [o["name"] for o in rooms[0]["others"]] == ["서기"]
    rows = (await client.get(f"/api/rooms/{rooms[0]['id']}/messages", headers=auth(mytok))).json()["items"]
    assert [m["body"] for m in rows] == ["안녕하세요, 사장님 계신가요"]

    # 그리고 이제는 메신저에서 바로 그 방을 다시 열 수 있다.
    again = await client.post("/api/rooms/open", headers=auth(mytok), json={"agent_id": agent["id"]})
    assert again.status_code == 201 and again.json()["id"] == rooms[0]["id"]

    # 비서 주인에게는 이 방이 없다. 자기 비서가 받은 방문은 [대화]에서 본다.
    assert (await client.get("/api/rooms", headers=auth(ttok))).json()["items"] == []


async def test_a_relay_is_not_a_room(client: AsyncClient):
    """비서끼리의 대화에는 사람이 들어가 있지 않다 (plan/44 §3)."""
    from memora.models import Visitor

    them, ttok = await signup(client, name="남세나")
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(ttok))).json()
    me, mytok = await signup(client)

    async with session_scope() as db:
        from memora.services import conversations as CV
        v = Visitor(owner_id=_uuid.UUID(them["id"]), agent_id=_uuid.UUID(agent["id"]),
                    user_id=_uuid.UUID(me["id"]), kind="agent", token_hash=_uuid.uuid4().hex,
                    first_seen_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                    last_seen_at=__import__("datetime").datetime.now(__import__("datetime").UTC))
        db.add(v)
        await db.flush()
        conv = await CV.create(db, owner_id=_uuid.UUID(them["id"]), agent_id=_uuid.UUID(agent["id"]),
                               audience="visitor", visitor_id=v.id)
        conv.kind = "agent"
        await CV.add_message(db, conv, role="assistant", content="비서끼리 하는 말")
        await db.commit()
        room = (await db.execute(select(Room).where(Room.conversation_id == conv.id))).scalars().first()
    assert room is None
    assert (await client.get("/api/rooms", headers=auth(mytok))).json()["items"] == []


async def test_a_secretary_is_not_answered_by_dropping_a_line_in_the_room(client: AsyncClient):
    """비서에게 하는 말은 턴이다. 이 문은 조용히 받지 않고 거절한다."""
    user, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(tok))).json()
    room = (await client.post("/api/rooms/open", headers=auth(tok), json={"agent_id": agent["id"]})).json()
    r = await client.post(f"/api/rooms/{room['id']}/messages", headers=auth(tok), json={"body": "안녕"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "use_turn"
    assert r.json()["error"]["detail"]["conversation_id"] == room["conversation_id"]


async def test_the_messenger_asks_a_secretary_the_way_the_public_door_does(client: AsyncClient):
    """방이 손잡이고, 문지기는 그대로다 (plan/44 §7)."""
    them, ttok = await signup(client, name="남세나")
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(ttok))).json()
    link = (await client.post(f"/api/agents/{agent['id']}/links", json={}, headers=auth(ttok))).json()
    me, mytok = await signup(client)
    cid = (await client.post(f"/api/public/links/{link['code']}/visitor", json={},
                             headers=auth(mytok))).json()["conversation_id"]
    async with session_scope() as db:
        from memora.services import conversations as CV
        conv = await db.get(Conversation, _uuid.UUID(cid))
        await CV.add_message(db, conv, role="user", content="문 열어 두기")
        await db.commit()
    rid = (await client.get("/api/rooms", headers=auth(mytok))).json()["items"][0]["id"]

    # 방에 있지 않은 사람은 그 문을 두드릴 수도 없다.
    other, othertok = await signup(client, name="남")
    assert (await client.post(f"/api/rooms/{rid}/turns", headers=auth(othertok),
                              json={"text": "안녕"})).status_code == 404

    # 링크를 닫으면 메신저로도 못 들어간다. 공개 문과 같은 자물쇠다.
    links = (await client.get(f"/api/agents/{agent['id']}/links", headers=auth(ttok))).json()["items"]
    await client.patch(f"/api/links/{links[0]['id']}", headers=auth(ttok), json={"status": "revoked"})
    r = await client.post(f"/api/rooms/{rid}/turns", headers=auth(mytok), json={"text": "안녕"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "link_closed"


async def test_a_room_says_whether_the_secretary_in_it_is_mine(client: AsyncClient):
    """전체 화면 채팅은 내 비서의 것이다. 남의 비서는 이 판으로 만난다."""
    me, mytok = await signup(client)
    mine = (await client.post("/api/agents", json={"name": "내서기"}, headers=auth(mytok))).json()
    own = (await client.post("/api/rooms/open", headers=auth(mytok), json={"agent_id": mine["id"]})).json()
    assert own["own_secretary"] is True

    them, ttok = await signup(client, name="남세나")
    theirs = (await client.post("/api/agents", json={"name": "남서기"}, headers=auth(ttok))).json()
    link = (await client.post(f"/api/agents/{theirs['id']}/links", json={}, headers=auth(ttok))).json()
    cid = (await client.post(f"/api/public/links/{link['code']}/visitor", json={},
                             headers=auth(mytok))).json()["conversation_id"]
    async with session_scope() as db:
        from memora.services import conversations as CV
        conv = await db.get(Conversation, _uuid.UUID(cid))
        await CV.add_message(db, conv, role="user", content="안녕하세요")
        await db.commit()
    rows = (await client.get("/api/rooms", headers=auth(mytok))).json()["items"]
    visit = next(r for r in rows if r["conversation_id"] == cid)
    assert visit["own_secretary"] is False


async def test_i_can_take_back_what_i_said(client: AsyncClient):
    me, mytok = await signup(client)
    you, youtok = await signup(client, name="상대")
    await _connect(client, me, mytok, you, youtok)
    rid = (await client.post("/api/rooms/open", headers=auth(mytok), json={"user_id": you["id"]})).json()["id"]
    a = (await client.post(f"/api/rooms/{rid}/messages", headers=auth(mytok), json={"body": "첫 마디"})).json()
    b = (await client.post(f"/api/rooms/{rid}/messages", headers=auth(mytok), json={"body": "무른 말"})).json()

    # 남의 말은 못 지운다.
    assert (await client.delete(f"/api/rooms/{rid}/messages/{a['id']}", headers=auth(youtok))).status_code == 404
    assert (await client.delete(f"/api/rooms/{rid}/messages/{b['id']}", headers=auth(mytok))).status_code == 200
    rows = (await client.get(f"/api/rooms/{rid}/messages", headers=auth(youtok))).json()["items"]
    assert [m["body"] for m in rows] == ["첫 마디"]
    # 목록의 마지막 말도 따라 물러난다.
    assert (await client.get("/api/rooms", headers=auth(youtok))).json()["items"][0]["last"]["body"] == "첫 마디"


async def test_a_secretarys_transcript_is_not_edited_line_by_line(client: AsyncClient):
    user, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(tok))).json()
    room = (await client.post("/api/rooms/open", headers=auth(tok), json={"agent_id": agent["id"]})).json()
    async with session_scope() as db:
        from memora.services import conversations as CV
        conv = await db.get(Conversation, _uuid.UUID(room["conversation_id"]))
        m = await CV.add_message(db, conv, role="user", content="한 마디")
        await db.commit()
        mid = str(m.id)
    r = await client.delete(f"/api/rooms/{room['id']}/messages/{mid}", headers=auth(tok))
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_a_dm"


async def test_one_room_per_person_and_secretary_however_many_sittings(client: AsyncClient):
    """대화가 넷이어도 비서는 목록에 한 번 나온다. 방은 짝이다 (plan/44 §3)."""
    user, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(tok))).json()
    cids = []
    for i in range(3):
        c = (await client.post(f"/api/agents/{agent['id']}/conversations", json={}, headers=auth(tok))).json()
        cids.append(c["id"])
        async with session_scope() as db:
            from memora.services import conversations as CV
            conv = await db.get(Conversation, _uuid.UUID(c["id"]))
            await CV.add_message(db, conv, role="user", content=f"자리 {i}")
            await db.commit()
    rooms = (await client.get("/api/rooms", headers=auth(tok))).json()["items"]
    assert len(rooms) == 1, [r["title"] for r in rooms]
    assert rooms[0]["title"] == "서기", "the room is named after who is in it, not the first line typed"
    assert rooms[0]["conversation_id"] == cids[-1], "a turn from here goes to the newest sitting"
    rows = (await client.get(f"/api/rooms/{rooms[0]['id']}/messages", headers=auth(tok))).json()["items"]
    assert [m["body"] for m in rows] == ["자리 0", "자리 1", "자리 2"], "all sittings, one timeline"


async def test_a_room_nobody_spoke_in_is_not_on_the_list_yet(client: AsyncClient):
    me, mytok = await signup(client)
    you, youtok = await signup(client, name="상대")
    await _connect(client, me, mytok, you, youtok)
    rid = (await client.post("/api/rooms/open", headers=auth(mytok), json={"user_id": you["id"]})).json()["id"]
    assert (await client.get("/api/rooms", headers=auth(mytok))).json()["items"] == []
    assert (await client.get(f"/api/rooms/{rid}", headers=auth(mytok))).status_code == 200, "still there for whoever opens it"
    await client.post(f"/api/rooms/{rid}/messages", headers=auth(mytok), json={"body": "이제 있다"})
    assert [r["id"] for r in (await client.get("/api/rooms", headers=auth(mytok))).json()["items"]] == [rid]
