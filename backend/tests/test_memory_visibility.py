"""기억은 비서의 것이고, 어디까지 나갈지는 기억마다 정한다 (plan/48 §2).

예전에는 **방 이름이 곧 공개 여부**였다. `owner` 는 주인만, `shared` 는 방문자도.
그래서 "이 기억을 남에게 보일까" 의 답이 폴더를 옮기는 일이 됐고, 화면에는 공개
설정이 아니라 칸 이름으로 보였다. 주인은 `shared` 에 넣는 것이 남에게 보여 주는
일이라는 걸 화면만 보고는 알 수 없었다.
"""
from __future__ import annotations

import uuid

import pytest

from memora.memory.facade import AgentMemory, note_level

#: 금고의 판정은 파일을 읽지 않고 규칙만 보므로 대부분 동기 함수다. 원장 요약만
#: 서버를 태운다.
pytestmark = pytest.mark.asyncio


def test_old_rooms_keep_their_old_meaning():
    """이미 쌓인 기억의 범위가 이 변경으로 넓어지지도 좁아지지도 않는다."""
    # 범위가 안 적힌 옛 기억: shared 에 있었으면 방문자가 읽던 것이다.
    assert note_level("shared", {"meta": {}}) == "public"
    assert note_level("owner", {"meta": {}}) == "private"
    assert note_level("visitors", {"meta": {}}) == "private"
    # 적혀 있으면 그것이 이긴다.
    assert note_level("owner", {"meta": {"visibility": "public"}}) == "public"
    assert note_level("shared", {"meta": {"visibility": "private"}}) == "private"


def test_each_reader_sees_only_what_is_theirs():
    aid = uuid.uuid4()
    owner_mem = AgentMemory(aid, "owner")
    friend_mem = AgentMemory(aid, "visitor", uuid.uuid4(), viewer="known")
    stranger_mem = AgentMemory(aid, "visitor", uuid.uuid4(), viewer="stranger")

    cases = [("private", False, False), ("known", True, False), ("public", True, True)]
    for level, friend_sees, stranger_sees in cases:
        note = {"meta": {"visibility": level}}
        assert owner_mem._visible("owner", note) is True, f"주인은 {level} 도 본다"
        assert friend_mem._visible("owner", note) is friend_sees, level
        assert stranger_mem._visible("owner", note) is stranger_sees, level


def test_a_visitor_never_reads_another_visitors_memory():
    """손님 방은 제 것만 본다. 남의 손님 이야기가 새면 범위 문제가 아니라 사고다."""
    aid = uuid.uuid4()
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    mem = AgentMemory(aid, "visitor", mine, viewer="known")
    # 인맥이어도, 심지어 [모두 공개] 라고 적혀 있어도 남의 손님 기록은 못 본다.
    assert mem._visible("visitors", {"meta": {"visitor_id": str(theirs), "visibility": "public"}}) is False
    assert mem._visible("visitors", {"meta": {"visitor_id": str(mine)}}) is True
    # 주인은 제 비서가 만난 손님 기록을 전부 본다.
    assert AgentMemory(aid, "owner")._visible("visitors", {"meta": {"visitor_id": str(theirs)}}) is True


def test_a_new_memory_is_private_until_somebody_says_otherwise():
    """고르지 않은 것이 공개되면 안 된다."""
    from memora.core import visibility as VIS

    assert VIS.normalize(None) == "private"
    assert VIS.normalize("") == "private"


def test_the_owner_turn_reads_every_room():
    """비서는 제 기억을 전부 본다. 범위는 밖으로 나갈 때만 걸린다."""
    mem = AgentMemory(uuid.uuid4(), "owner")
    assert set(mem.read_ns) == {"owner", "shared", "visitors"}
    assert mem.write_ns == "owner"
    assert AgentMemory(uuid.uuid4(), "visitor", uuid.uuid4()).write_ns == "visitors"


async def test_a_fact_belongs_to_the_secretary_that_learned_it(client):
    """사실은 비서가 만든 것이라 그 비서의 것이다 (plan/49).

    주인이 직접 넣은 것(프로필·지식·인맥·내 글)은 [내 정보] 에 있고 **모든 비서가
    전부 본다.** 사실과 기억은 비서가 겪은 것이라 그 비서에게 남는다. 둘을 섞으면
    비서 셋을 둔 사람의 화면에서 같은 목록이 세 군데 보이고, 어디서 지워도 셋 다에서
    사라진다.
    """
    import uuid as _u

    from memora.db.session import session_scope
    from memora.models import Fact
    from memora.pipeline.runner import _facts_block
    from memora.services import outsider as OUT
    from tests.conftest import auth, signup

    user, tok = await signup(client)
    ra = await client.post("/api/agents", json={"name": "하나"}, headers=auth(tok))
    assert ra.status_code == 201, ra.text
    a = ra.json()
    oid = _u.UUID(user["id"])

    async with session_scope() as db:
        # 두 번째 비서는 요금제 상한에 걸리므로 직접 만든다. 이 검사가 보려는 것은
        # 비서를 몇 개까지 만들 수 있나가 아니라, 사실이 어느 비서에게 붙느냐다.
        from memora.models import Agent
        second = Agent(id=_u.uuid4(), owner_id=oid, name="둘", status="active")
        db.add(second)
        await db.commit()
        b = {"id": str(second.id), "name": "둘"}

    async with session_scope() as db:
        db.add(Fact(id=_u.uuid4(), owner_id=oid, agent_id=_u.UUID(a["id"]), subject="주인", predicate="좋아하다",
                    object="하나만 아는 것", kind="context", visibility="private", status="active"))
        db.add(Fact(id=_u.uuid4(), owner_id=oid, agent_id=_u.UUID(b["id"]), subject="주인", predicate="좋아하다",
                    object="둘만 아는 것", kind="context", visibility="private", status="active"))
        await db.commit()

    # 화면: 각자 제 것만 본다.
    for agent, mine, theirs in ((a, "하나만", "둘만"), (b, "둘만", "하나만")):
        items = (await client.get(f"/api/agents/{agent['id']}/facts", headers=auth(tok))).json()["items"]
        said = " ".join(i["object"] for i in items)
        assert mine in said and theirs not in said, agent["name"]

    # 프롬프트: 같은 규칙이다. 화면과 프롬프트가 다르면 화면이 거짓말을 한다.
    async with session_scope() as db:
        for agent, mine, theirs in ((a, "하나만", "둘만"), (b, "둘만", "하나만")):
            block = await _facts_block(db, oid, _u.UUID(agent["id"]), OUT.OWNER, None, "")
            assert mine in block and theirs not in block, agent["name"]
