"""Subscribing, and the feed that comes of it (plan/41 §5, plan/42).

Everything in 소식 comes from somebody this person knows or chose to read. Nothing from the
square is ever in it.
"""
from __future__ import annotations

import uuid as _uuid

from httpx import AsyncClient

from tests.conftest import auth, signup, square_name
from tests.test_blog import _open_page


async def _post(client: AsyncClient, tok: str, title: str, *, visibility: str = "public") -> dict:
    r = await client.post("/api/blog", headers=auth(tok), json={"title": title, "body": f"{title}의 내용", "visibility": visibility})
    assert r.status_code == 201, r.text
    return r.json()


async def _befriend(client: AsyncClient, a_user: dict, a_tok: str, b_user: dict, b_tok: str) -> None:
    """인맥: each of them connects to the other (plan/43)."""
    await client.post(f"/api/network/people/{b_user['id']}/follow", headers=auth(a_tok))
    await client.post(f"/api/network/people/{a_user['id']}/follow", headers=auth(b_tok))

async def test_the_feed_carries_friends_and_the_people_i_read(client: AsyncClient):
    me, mytok = await signup(client, name="나")
    friend, ftok = await signup(client, name="친구")
    writer, wtok = await signup(client, name="작가")
    stranger, stok = await signup(client, name="남")
    for uid, handle in ((friend["id"], f"fr{_uuid.uuid4().hex[:5]}"), (writer["id"], f"wr{_uuid.uuid4().hex[:5]}"),
                        (stranger["id"], f"st{_uuid.uuid4().hex[:5]}")):
        await _open_page(uid, handle)

    await _befriend(client, me, mytok, friend, ftok)
    assert (await client.post(f"/api/network/people/{writer['id']}/follow", headers=auth(mytok))).status_code == 200

    await _post(client, ftok, "친구의 공개글")
    await _post(client, ftok, "친구의 친구글", visibility="friends")
    await _post(client, ftok, "친구의 비공개글", visibility="private")
    await _post(client, wtok, "작가의 공개글")
    await _post(client, wtok, "작가의 친구글", visibility="friends")
    await _post(client, stok, "남의 공개글")

    j = (await client.get("/api/feed", headers=auth(mytok))).json()
    house = j["items"]
    titles = {i["title"] for i in house}
    # A connection's posts for friends are in. A followed stranger's are not: following is
    # not being let in. Somebody I neither know nor read never appears.
    assert titles == {"친구의 공개글", "친구의 친구글", "작가의 공개글"}, titles
    assert j["sources"] == {"friends": True, "following": True}
    why = {i["title"]: i["why"] for i in house}
    assert why["친구의 공개글"] == "friend" and why["작가의 공개글"] == "following"
    assert all(i["author"]["name"] for i in house)

    # Newest first.
    assert [i["title"] for i in house][0] == "작가의 공개글"


async def test_a_stranger_never_reaches_the_house_lane(client: AsyncClient):
    """The square may fill a quiet page (plan/42 §2), but somebody's own writing only ever
    reaches me because I connected with them or chose to read them."""
    me, tok = await signup(client)
    other, otok = await signup(client)
    await _open_page(other["id"], f"ot{_uuid.uuid4().hex[:5]}")
    await _post(client, otok, "아무도 구독하지 않은 글")
    j = (await client.get("/api/feed", headers=auth(tok))).json()
    assert j["items"] == []
    assert j["sources"] == {"friends": False, "following": False}


async def test_connecting_is_one_sided_and_tells_the_person(client: AsyncClient):
    me, mytok = await signup(client, name="독자")
    target, ttok = await signup(client)
    r = await client.post(f"/api/network/people/{target['id']}/follow", headers=auth(mytok))
    assert r.status_code == 200 and r.json()["added"] is True and r.json()["status"] == "outgoing"
    # Saying it twice changes nothing.
    assert (await client.post(f"/api/network/people/{target['id']}/follow", headers=auth(mytok))).json()["added"] is False

    box = (await client.get("/api/inbox", params={"source": "people"}, headers=auth(ttok))).json()["items"]
    assert [i["kind"] for i in box] == ["person_follow"] and box[0]["payload"]["actor_name"] == "독자"
    # The person followed owes nothing back: nobody has reached their house lane.
    assert (await client.get("/api/feed", headers=auth(ttok))).json()["items"] == []

    assert (await client.delete(f"/api/network/people/{target['id']}/follow", headers=auth(mytok))).status_code == 200
    assert (await client.get("/api/feed", headers=auth(mytok))).json()["sources"]["following"] is False


async def test_you_cannot_follow_yourself(client: AsyncClient):
    me, tok = await signup(client)
    assert (await client.post(f"/api/network/people/{me['id']}/follow", headers=auth(tok))).status_code == 422


async def test_nobody_can_ask_what_a_person_wrote_in_the_square(client: AsyncClient):
    """광장은 **익명 커뮤니티**다 (plan/51).

    예전에는 필명을 안 붙이면 실명으로 남았고, 그 글은 남이 "이 사람이 뭘 썼나" 고
    물으면 나왔다. 이제 광장의 모든 글에 필명이 붙으므로 **그 질문에 나올 글이
    하나도 없다.** 내 글은 나에게만 보인다.
    """
    author, atok = await signup(client)
    reader, rtok = await signup(client)
    async with __import__("blackmoa.db.session", fromlist=["session_scope"]).session_scope() as db:
        from blackmoa.models import User
        u = await db.get(User, _uuid.UUID(author["id"]))
        u.email_verified_at = __import__("datetime").datetime.now(__import__("datetime").UTC)
        await db.commit()
    await square_name(client, atok, "익명의글쓴이")
    await square_name(client, rtok, "익명의읽는이")
    boards = (await client.get("/api/community/boards", headers=auth(atok))).json()["items"]
    slug = boards[0]["slug"]
    # 이름을 안 골라도 광장 이름이 붙는다. 실명으로 쓰는 길은 없다.
    open_post = await client.post("/api/community/posts", headers=auth(atok),
                                  json={"board": slug, "title": "이름을 안 고른 글", "body": "본문입니다. 충분히 길게 씁니다."})
    assert open_post.status_code == 201, open_post.text
    hidden = await client.post("/api/community/posts", headers=auth(atok),
                               json={"board": slug, "title": "또 쓴 글", "body": "본문입니다. 충분히 길게 씁니다."})
    assert hidden.status_code == 201, hidden.text

    # 남이 "이 사람이 뭘 썼나" 고 물으면 하나도 안 나온다.
    seen = (await client.get("/api/community/posts", params={"author": author["id"]}, headers=auth(rtok))).json()["items"]
    assert seen == [], seen

    # 글은 광장에 있지만 계정 id 를 달고 있지 않다. 둘 다 그렇다.
    everything = (await client.get("/api/community/posts", headers=auth(rtok))).json()["items"]
    here = {p["title"]: p for p in everything}
    # 한 사람은 한 이름이다. 글마다 이름이 달라지면 대화가 이어지지 않는다.
    assert here["또 쓴 글"]["author"]["name"] == here["이름을 안 고른 글"]["author"]["name"] == "익명의글쓴이"
    for title in ("이름을 안 고른 글", "또 쓴 글"):
        assert not here[title]["author"]["id"], title
        assert here[title]["author"]["pen_name"], title
    # 그 이름은 계정 이름이 아니다.
    assert here["이름을 안 고른 글"]["author"]["name"] != author["display_name"]

    # 내 글은 나에게 보인다. 둘 다.
    mine = (await client.get("/api/community/posts", params={"mine": True}, headers=auth(atok))).json()["items"]
    assert {p["title"] for p in mine} == {"이름을 안 고른 글", "또 쓴 글"}

    # Answering a comment on their own pen-named post keeps the pen name. Replying under
    # the real name there is what ties the two together, and it can never be taken back.
    pid = hidden.json()["id"]
    assert (await client.post(f"/api/community/posts/{pid}/comments", headers=auth(rtok),
                              json={"body": "궁금한 게 있어요."})).status_code == 201
    assert (await client.post(f"/api/community/posts/{pid}/comments", headers=auth(atok),
                              json={"body": "제가 쓴 글인데, 이렇습니다."})).status_code == 201
    cs = (await client.get(f"/api/community/posts/{pid}/comments", headers=auth(rtok))).json()["items"]
    byline = {c["body"]: c["author"] for c in cs}
    mine_c = byline["제가 쓴 글인데, 이렇습니다."]
    assert mine_c["name"] == "익명의글쓴이" and not mine_c["id"] and mine_c.get("pen_name")
    # 묻는 쪽도 익명이다. 예전에는 여기서 실명이 나왔다 — 남의 익명 글에 한 줄
    # 달았다는 이유로 광장에 이름이 걸렸다 (plan/51).
    asked = byline["궁금한 게 있어요."]
    assert not asked["id"] and asked.get("pen_name")
    assert asked["name"] == "익명의읽는이", asked

    # 댓글도 익명이다. 남의 글에 한 줄 달았다고 실명이 광장에 걸리면 안 된다.
    oid = open_post.json()["id"]
    await client.post(f"/api/community/posts/{oid}/comments", headers=auth(atok), json={"body": "글쓴이가 답합니다."})
    await client.post(f"/api/community/posts/{oid}/comments", headers=auth(rtok), json={"body": "남이 답합니다."})
    cs = (await client.get(f"/api/community/posts/{oid}/comments", headers=auth(rtok))).json()["items"]
    assert len(cs) == 2
    for c in cs:
        assert not c["author"]["id"] and c["author"]["pen_name"], c
        assert c["author"]["name"] not in (author["display_name"], reader["display_name"]), c
    # 글쓴이는 그 글에 적힌 이름 그대로다. 제 글 아래에서 이름이 바뀌면 남처럼 보인다.
    said = {c["body"]: c["author"]["name"] for c in cs}
    assert said["글쓴이가 답합니다."] == "익명의글쓴이", said
    assert said["남이 답합니다."] == "익명의읽는이", said


async def test_a_suspended_account_goes_quiet_in_other_peoples_feeds(client: AsyncClient):
    """Its page already 404s. The feed must not be the one place it still speaks."""
    from blackmoa.db.session import session_scope
    from blackmoa.models import User

    _, mytok = await signup(client)
    writer, wtok = await signup(client)
    await client.post(f"/api/network/people/{writer['id']}/follow", headers=auth(mytok))
    await client.post("/api/blog", json={"title": "조용히 지나간 하루", "body": "별일 없었습니다."}, headers=auth(wtok))

    assert len((await client.get("/api/feed", headers=auth(mytok))).json()["items"]) == 1

    async with session_scope() as db:
        (await db.get(User, _uuid.UUID(writer["id"]))).status = "suspended"
        await db.commit()
    assert (await client.get("/api/feed", headers=auth(mytok))).json()["items"] == []
