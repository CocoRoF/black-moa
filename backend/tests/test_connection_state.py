"""인맥의 상태 하나를 모든 화면이 같게 본다 (plan/69).

연결은 프로필·카드·인박스·관계도·추천 등 여러 곳에 보인다. 예전에는 인박스의 [인맥 맺기] 가 상태를 몰라 누른
뒤에도 그대로였다. 이제 모든 단추가 `/people/{id}/link` 하나를 읽고, 바뀌면 두 사람 모두에게 `link` 소식이 간다.
"""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth, signup


async def _link(client: AsyncClient, tok: str, other: str) -> str:
    r = await client.get(f"/api/network/people/{other}/link", headers=auth(tok))
    assert r.status_code == 200, r.text
    return r.json()["status"]


async def test_the_four_states_seen_from_both_sides(client: AsyncClient):
    a, a_tok = await signup(client, name="가온")
    b, b_tok = await signup(client, name="나윤")
    assert await _link(client, a_tok, b["id"]) == "none"
    assert await _link(client, a_tok, a["id"]) == "self"

    await client.post(f"/api/network/people/{b['id']}/follow", headers=auth(a_tok))
    assert await _link(client, a_tok, b["id"]) == "outgoing"   # 내가 연결
    assert await _link(client, b_tok, a["id"]) == "incoming"   # 상대가 나를 연결

    await client.post(f"/api/network/people/{a['id']}/follow", headers=auth(b_tok))
    assert await _link(client, a_tok, b["id"]) == "mutual"
    assert await _link(client, b_tok, a["id"]) == "mutual"

    # 인맥 지우기: 내 쪽만. 상대가 한 연결은 상대의 것이다.
    r = await client.delete(f"/api/network/people/{b['id']}/follow", headers=auth(a_tok))
    assert r.json()["status"] == "incoming"
    assert await _link(client, b_tok, a["id"]) == "outgoing"


async def test_every_change_is_announced_to_both_people(client: AsyncClient, monkeypatch):
    from blackmoa.core import bus

    sent: list[tuple[str, str, dict]] = []

    async def capture(db, *, owner_id, kind, data):
        sent.append((str(owner_id), kind, data))

    monkeypatch.setattr(bus, "publish", capture)
    a, a_tok = await signup(client, name="다온")
    b, b_tok = await signup(client, name="라온")

    await client.post(f"/api/network/people/{b['id']}/follow", headers=auth(a_tok))
    links = [(o, d["user_id"], d["status"]) for o, k, d in sent if k == "link"]
    assert (a["id"], b["id"], "outgoing") in links and (b["id"], a["id"], "incoming") in links

    sent.clear()
    await client.delete(f"/api/network/people/{b['id']}/follow", headers=auth(a_tok))
    links = [(o, d["user_id"], d["status"]) for o, k, d in sent if k == "link"]
    assert (a["id"], b["id"], "none") in links and (b["id"], a["id"], "none") in links

    # 이미 연결한 사람을 또 눌러도 아무 일도 없다 — 알릴 것도 없다.
    await client.post(f"/api/network/people/{b['id']}/follow", headers=auth(a_tok))
    sent.clear()
    r = await client.post(f"/api/network/people/{b['id']}/follow", headers=auth(a_tok))
    assert r.json()["added"] is False and r.json()["status"] == "outgoing"
    assert not [x for x in sent if x[1] == "link"]


async def test_lists_carry_the_state_of_each_person(client: AsyncClient):
    a, a_tok = await signup(client, name="마루")
    b, b_tok = await signup(client, name="바다")
    c, c_tok = await signup(client, name="사랑")
    await client.post(f"/api/network/people/{b['id']}/follow", headers=auth(a_tok))  # a→b
    await client.post(f"/api/network/people/{a['id']}/follow", headers=auth(c_tok))  # c→a
    mine = (await client.get("/api/network/people/links", headers=auth(a_tok))).json()
    assert [x["link"]["status"] for x in mine["outgoing"]] == ["outgoing"]
    assert [x["link"]["status"] for x in mine["incoming"]] == ["incoming"]
    sugg = (await client.get("/api/network/people/suggestions", headers=auth(a_tok))).json()["items"]
    back = [s for s in sugg if s["id"] == c["id"]]
    assert back and back[0]["reason"] == "connected_me" and back[0]["link"]["status"] == "incoming"
