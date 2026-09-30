"""집의 나머지 문에도 같은 문지기를 둔다 (plan/42 §15 의 규칙).

글·댓글·좋아요·방에는 천장이 있었는데 인맥과 알림에는 없었다. 둘 다 바깥으로 무언가를
내보내는 문이다. 연결은 상대의 인박스에 한 줄을 남기고, 알림 채널은 메일을 보낸다.
"""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth, signup


async def test_reaching_one_person_over_and_over_stops(client: AsyncClient, monkeypatch):
    """전체에 천장을 두는 게 아니라 **상대별**로 센다 (plan/43).

    몇 명과 연결하든 그건 그 사람의 사정이다. 문제가 되는 것은 한 사람에게 반복해서
    닿는 일이다: 연결할 때마다 그 사람 인박스에 한 줄이 남으니, 끊었다 잇기를 되풀이하면
    그 줄이 계속 쌓인다. 다른 사람들과는 아무 상관이 없어야 한다.
    """
    import memora.services.blog as B

    me, tok = await signup(client)
    a, _ = await signup(client, name="상대 가")
    b, _ = await signup(client, name="상대 나")

    monkeypatch.setattr(B, "REACH_PER_TARGET", 3)
    for _ in range(3):
        assert (await client.post(f"/api/network/people/{a['id']}/follow", headers=auth(tok))).status_code == 200
        assert (await client.delete(f"/api/network/people/{a['id']}/follow", headers=auth(tok))).status_code == 200

    blocked = await client.post(f"/api/network/people/{a['id']}/follow", headers=auth(tok))
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "reached_too_often"

    # 막힌 것은 그 사람에게 가는 길뿐이다.
    assert (await client.post(f"/api/network/people/{b['id']}/follow", headers=auth(tok))).status_code == 200


async def test_a_mail_channel_is_silent_until_the_address_is_proven(client: AsyncClient):
    """주소는 어디든 적을 수 있다. 다만 거기로 간 코드를 가져와야 알림이 나간다.

    증명 없이 보낼 수 있으면 채널 하나로 우리 메일 서버가 남에게 보내는 통로가 된다.
    """
    import uuid as _u

    from memora.db.session import session_scope
    from memora.models import NotificationChannel

    user, tok = await signup(client)
    ch = (await client.post("/api/notifications/channels", headers=auth(tok),
                            json={"kind": "email", "label": "메일",
                                  "config": {"to": "somebody-else@example.com"}})).json()
    # 주소는 적은 그대로 남는다.
    assert ch["config"]["to"] == "somebody-else@example.com"
    # 그러나 확인되기 전까지는 아무것도 나가지 않고, [테스트 발송]으로 대신할 수도 없다.
    assert ch["verified_at"] is None
    t = await client.post(f"/api/notifications/channels/{ch['id']}/test", headers=auth(tok))
    assert t.status_code == 422 and t.json()["error"]["code"] == "channel_unverified", t.text

    # 틀린 코드로는 열리지 않는다.
    bad = await client.post(f"/api/notifications/channels/{ch['id']}/verify", headers=auth(tok),
                            json={"code": "000000"})
    assert bad.status_code in (409, 422)

    async with session_scope() as db:
        row = await db.get(NotificationChannel, _u.UUID(ch["id"]))
        assert row.verified_at is None


async def test_a_post_reply_does_not_become_a_fact_about_the_owner(client: AsyncClient):
    """글에 부른 비서의 턴은 주인이 말한 것이 아니다 (plan/45 §8).

    심부름 지시문("글에서 나를 불렀어요, 댓글로 답해 주세요")이 주인에 대한 사실로
    기억됐고, 남이 쓴 글이 내 사실이 될 수도 있었다. 운영에서 실제로 두 건 나왔다.
    """
    import inspect

    import memora.pipeline.runner as R

    src = inspect.getsource(R._finalize) if hasattr(R, "_finalize") else inspect.getsource(R)
    # 증류를 거는 자리에 simulated 가드가 서 있어야 한다.
    assert 'conv.kind != "agent" and not ids["simulated"]' in src, "simulated 턴이 증류로 새고 있다"


async def test_the_owner_cannot_set_how_fast_the_relationship_grows(client: AsyncClient):
    """관계가 자라는 빠르기를 그 관계를 맺는 사람이 정할 수 있으면 관계가 아니라 설정이다."""
    from memora.pipeline.personas import relationship_params

    for asked in ("fast", "slow", "normal", "nonsense"):
        assert relationship_params({"relationship": {"pace": asked}})["pace"] == "normal", asked
