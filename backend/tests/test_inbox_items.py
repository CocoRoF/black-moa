"""인박스 항목 하나를 열었을 때 (plan/70).

소식마다 창의 모양이 다르고, 비서끼리 나눈 대화의 창은 상대와 [인맥 맺기]를 보인다. 사람을 소식에 적기 전에
생긴 소식도 그 대화에서 두 사람을 찾아 채운다.
"""
from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.conftest import auth, signup


async def test_an_old_relay_notice_learns_who_the_other_side_was(client: AsyncClient):
    from memora.db.session import session_scope
    from memora.models import AgentRelay, InboxItem

    a, a_tok = await signup(client, name="가온")
    b, _ = await signup(client, name="나윤")
    aa = (await client.post("/api/agents", json={"name": "가온비서"}, headers=auth(a_tok))).json()["id"]
    async with session_scope() as db:
        # 상대 비서는 상대의 것이지만, 이 시험에는 두 사람의 id 만 있으면 된다.
        r = AgentRelay(initiator_agent_id=uuid.UUID(aa), initiator_owner_id=uuid.UUID(a["id"]),
                       target_agent_id=uuid.UUID(aa), target_owner_id=uuid.UUID(b["id"]), status="closed")
        db.add(r)
        await db.flush()
        item = InboxItem(owner_id=uuid.UUID(a["id"]), agent_id=uuid.UUID(aa), kind="relay_result",
                         payload={"relay_id": str(r.id), "text": "인사를 나눴어요", "target_owner_name": "나윤"})
        db.add(item)
        await db.commit()
        iid = str(item.id)
    got = (await client.get(f"/api/inbox/{iid}", headers=auth(a_tok))).json()
    assert got["payload"]["target_user_id"] == b["id"] and got["payload"]["initiator_user_id"] == a["id"]
    assert got["status"] == "read"   # 열면 읽은 것이 된다
