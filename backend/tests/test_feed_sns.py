"""소식 as the screen you open by reflex (plan/42).

Three things have to hold. The page is never empty. The square can never bury the people I
chose. And nothing that crosses from the square carries a real name with it.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select

from memora.db.session import session_scope
from memora.models import User
from tests.conftest import auth, signup, square_name


async def _verified(user_id: str) -> None:
    async with session_scope() as db:
        (await db.get(User, _uuid.UUID(user_id))).email_verified_at = datetime.now(UTC)
        await db.commit()


async def _square_post(client: AsyncClient, tok: str, title: str) -> dict:
    """광장에 한 편. 이름은 계정에 하나뿐이라 글마다 적지 않는다 (plan/52)."""
    slug = (await client.get("/api/community/boards", headers=auth(tok))).json()["items"][0]["slug"]
    await square_name(client, tok)
    r = await client.post("/api/community/posts", headers=auth(tok),
                          json={"board": slug, "title": title, "body": "본문입니다. 충분히 길게 씁니다."})
    assert r.status_code == 201, r.text
    return r.json()


async def _befriend(client: AsyncClient, a_user: dict, a_tok: str, b_user: dict, b_tok: str) -> None:
    """인맥: each of them connects to the other (plan/43)."""
    await client.post(f"/api/network/people/{b_user['id']}/follow", headers=auth(a_tok))
    await client.post(f"/api/network/people/{a_user['id']}/follow", headers=auth(b_tok))

async def test_an_empty_feed_offers_people_not_other_peoples_writing(client: AsyncClient):
    """소식 is where you come to see people you know. Filling a quiet page with the square's
    writing makes it a second entrance to the community, so it offers people instead."""
    writer, wtok = await signup(client)
    await _verified(writer["id"])
    await _square_post(client, wtok, "광장에서 잘 읽힌 글")

    _, mytok = await signup(client)
    j = (await client.get("/api/feed", headers=auth(mytok))).json()
    assert j["items"] == [], "the square reached 소식"
    assert "광장에서 잘 읽힌 글" not in str(j)
    assert "suggestions" in j


async def test_the_community_never_appears_in_the_feed(client: AsyncClient):
    """Even for somebody with people to read, the two rooms stay separate (plan/42 §2)."""
    me, mytok = await signup(client)
    friend, ftok = await signup(client)
    await _verified(friend["id"])
    await _befriend(client, me, mytok, friend, ftok)
    await client.post("/api/blog", headers=auth(ftok), json={"body": "친구가 남긴 한 줄", "kind": "note"})
    await _square_post(client, ftok, "같은 사람이 광장에 쓴 글")

    items = (await client.get("/api/feed", headers=auth(mytok))).json()["items"]
    assert [i["body"] for i in items] == ["친구가 남긴 한 줄"]
    assert "같은 사람이 광장에 쓴 글" not in str(items)


async def test_the_page_carries_on_where_it_left_off(client: AsyncClient):
    me, mytok = await signup(client)
    friend, ftok = await signup(client)
    await _befriend(client, me, mytok, friend, ftok)
    for n in range(7):
        await client.post("/api/blog", headers=auth(ftok), json={"title": f"글 {n}", "body": "내용"})

    first = (await client.get("/api/feed?limit=3", headers=auth(mytok))).json()
    assert first["cursor"], "a full page should say where to carry on from"
    second = (await client.get(f"/api/feed?limit=3&cursor={first['cursor']}", headers=auth(mytok))).json()
    seen = {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
    assert not seen, "the second page repeated something from the first"


async def test_a_short_note_needs_no_title(client: AsyncClient):
    """The box at the top of 소식 asks for one line, not for a headline (plan/42 §4)."""
    user, tok = await signup(client)
    r = await client.post("/api/blog", headers=auth(tok),
                          json={"body": "오늘 처음으로 혼자 배포했다.\n손이 떨렸다.", "kind": "note"})
    assert r.status_code == 201, r.text
    post = r.json()
    assert post["kind"] == "note" and post["slug"]
    # The heading it needs for its own address comes from its first line.
    assert post["title"] == "오늘 처음으로 혼자 배포했다."
    # And a card draws the body, not a title repeating the first line back.
    assert post["body"].startswith("오늘 처음으로")

    # An article still has to be named.
    bad = await client.post("/api/blog", headers=auth(tok), json={"body": "제목 없는 글"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "empty_title"


async def test_a_post_can_be_liked_and_replied_to_by_people_who_can_read_it(client: AsyncClient):
    author, atok = await signup(client, name="글쓴이")
    friend, ftok = await signup(client, name="친구")
    stranger, stok = await signup(client, name="남")
    await _befriend(client, author, atok, friend, ftok)

    open_post = (await client.post("/api/blog", headers=auth(atok),
                                   json={"body": "누구나 보는 글", "kind": "note"})).json()
    close_post = (await client.post("/api/blog", headers=auth(atok),
                                    json={"body": "인맥만 보는 글", "kind": "note", "visibility": "friends"})).json()

    r = await client.post(f"/api/blog/{open_post['id']}/like", headers=auth(ftok), json={"on": True})
    assert r.status_code == 200 and r.json() == {"liked": True, "like_count": 1}
    # Liking twice is still one like.
    await client.post(f"/api/blog/{open_post['id']}/like", headers=auth(ftok), json={"on": True})
    assert (await client.post(f"/api/blog/{open_post['id']}/like", headers=auth(ftok),
                              json={"on": False})).json()["like_count"] == 0

    r = await client.post(f"/api/blog/{open_post['id']}/comments", headers=auth(ftok), json={"body": "축하해요"})
    assert r.status_code == 201 and r.json()["author"]["name"] == "친구"
    rows = (await client.get(f"/api/blog/{open_post['id']}/comments", headers=auth(stok))).json()["items"]
    assert [c["body"] for c in rows] == ["축하해요"]

    # A post somebody may not read is a post they may not touch, and is not announced as
    # existing either way.
    assert (await client.post(f"/api/blog/{close_post['id']}/like", headers=auth(stok),
                              json={"on": True})).status_code == 404
    assert (await client.post(f"/api/blog/{close_post['id']}/comments", headers=auth(stok),
                              json={"body": "안녕"})).status_code == 404
    assert (await client.get(f"/api/blog/{close_post['id']}/comments", headers=auth(ftok))).status_code == 200


async def test_the_writer_hears_about_a_reply_and_can_remove_it(client: AsyncClient):
    author, atok = await signup(client)
    reader, rtok = await signup(client, name="읽은이")
    post = (await client.post("/api/blog", headers=auth(atok), json={"body": "한 줄 남김", "kind": "note"})).json()
    c = (await client.post(f"/api/blog/{post['id']}/comments", headers=auth(rtok), json={"body": "잘 봤어요"})).json()

    items = (await client.get("/api/inbox", headers=auth(atok))).json()["items"]
    told = [i for i in items if i["kind"] == "post_comment"]
    assert told and told[0]["payload"]["excerpt"] == "잘 봤어요"
    assert told[0]["payload"]["actor_name"] == "읽은이"

    # Replying to my own post does not put it in my own inbox.
    await client.post(f"/api/blog/{post['id']}/comments", headers=auth(atok), json={"body": "고마워요"})
    assert len([i for i in (await client.get("/api/inbox", headers=auth(atok))).json()["items"]
                if i["kind"] == "post_comment"]) == 1

    # The writer may take a reply off their own post; a bystander may not.
    other, otok = await signup(client)
    assert (await client.delete(f"/api/blog/{post['id']}/comments/{c['id']}", headers=auth(otok))).status_code == 404
    assert (await client.delete(f"/api/blog/{post['id']}/comments/{c['id']}", headers=auth(atok))).status_code == 200
    left = (await client.get(f"/api/blog/{post['id']}/comments", headers=auth(atok))).json()["items"]
    assert [x["body"] for x in left] == ["고마워요"]
    assert (await client.get(f"/api/blog/{post['id']}", headers=auth(atok))).json()["comment_count"] == 1


async def _photo(client: AsyncClient, tok: str) -> str:
    """A one-pixel PNG, uploaded the way the box at the top of 소식 uploads one."""
    png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000004000000040802000000269309290000"
                        "001449444154789c633ca1a1c100034c0c48003707003854012024ef7a6b0000000049454e44ae426082")
    r = await client.post("/api/uploads", headers=auth(tok),
                          files={"file": ("a.png", png, "image/png")}, data={"kind": "attachment"})
    assert r.status_code in (200, 201), r.text
    return r.json()["upload_id"]


async def test_a_photo_is_the_post_and_needs_no_words(client: AsyncClient):
    """A picture arriving shrunk next to a paragraph is writing with pictures attached
    (plan/42 §3). It is allowed to be the whole post."""
    user, tok = await signup(client)
    up = await _photo(client, tok)
    r = await client.post("/api/blog", headers=auth(tok), json={"body": "", "kind": "note", "images": [up]})
    assert r.status_code == 201, r.text
    post = r.json()
    assert len(post["images"]) == 1 and post["images"][0].startswith("/api/public/posts/images/")
    assert post["title"], "even a wordless post needs an address"

    # The address works with no session at all, because a visitor reading the page has none.
    img = post["images"][0]
    assert (await client.get(img)).status_code == 200

    # And it is the signature that opens it, not the id.
    bare = img.split("?")[0]
    assert (await client.get(bare)).status_code == 404
    assert (await client.get(f"{bare}?t=made-up")).status_code == 404


async def test_a_photo_cannot_be_borrowed_from_somebody_else(client: AsyncClient):
    """An id in a request is a claim, not a fact."""
    owner, otok = await signup(client)
    thief, ttok = await signup(client)
    up = await _photo(client, otok)
    post = (await client.post("/api/blog", headers=auth(ttok),
                              json={"body": "남의 사진", "kind": "note", "images": [up]})).json()
    assert post["images"] == []


async def test_a_post_carries_its_photos_into_the_feed_and_the_public_page(client: AsyncClient):
    me, mytok = await signup(client)
    friend, ftok = await signup(client)
    await _befriend(client, me, mytok, friend, ftok)
    up = await _photo(client, ftok)
    await client.post("/api/blog", headers=auth(ftok),
                      json={"body": "오늘의 한 장", "kind": "note", "images": [up]})

    item = (await client.get("/api/feed", headers=auth(mytok))).json()["items"][0]
    assert len(item["images"]) == 1
    assert (await client.get(item["images"][0])).status_code == 200


async def test_naming_somebody_points_at_the_person_not_at_a_string(client: AsyncClient):
    """Most people have not claimed an address, and they still have to be namable: a
    mention is a person (plan/42 §11)."""
    author, atok = await signup(client, name="글쓴이")
    nameless, ntok = await signup(client, name="김이름")
    addressed, _ = await signup(client, name="박주소")
    async with session_scope() as db:
        (await db.get(User, _uuid.UUID(addressed["id"]))).mail_handle = "juso"
        await db.commit()

    # Picked from the list, written as their name because they have no address.
    r = await client.post("/api/blog", headers=auth(atok),
                          json={"body": "@김이름 고마워요.", "kind": "note", "mentions": [nameless["id"]]})
    assert r.status_code == 201, r.text
    assert r.json()["mentions"] == [{"id": nameless["id"], "label": "김이름", "handle": ""}]

    told = [i for i in (await client.get("/api/inbox", headers=auth(ntok))).json()["items"]
            if i["kind"] == "post_mention"]
    assert len(told) == 1 and told[0]["payload"]["actor_name"] == "글쓴이"

    # Typing an address by hand still works, with nothing picked.
    r = await client.post("/api/blog", headers=auth(atok), json={"body": "@juso 님도요.", "kind": "note"})
    assert r.json()["mentions"] == [{"id": addressed["id"], "label": "juso", "handle": "juso"}]

    # Picking somebody and then deleting their name is not a mention.
    r = await client.post("/api/blog", headers=auth(atok),
                          json={"body": "혼잣말", "kind": "note", "mentions": [nameless["id"]]})
    assert r.json()["mentions"] == []

    # And a picked id that is not a real account is dropped rather than trusted.
    r = await client.post("/api/blog", headers=auth(atok),
                          json={"body": "@김이름 다시", "kind": "note", "mentions": [str(_uuid.uuid4())]})
    assert r.json()["mentions"] == []


async def test_editing_does_not_summon_the_same_person_again(client: AsyncClient):
    author, atok = await signup(client)
    friend, ftok = await signup(client, name="불린이")
    made = await client.post("/api/blog", headers=auth(atok),
                             json={"body": "@불린이 고마워요.", "kind": "note", "mentions": [friend["id"]]})
    pid = made.json()["id"]
    await client.patch(f"/api/blog/{pid}", headers=auth(atok),
                       json={"body": "@불린이 정말 고마워요.", "mentions": [friend["id"]]})
    assert len([i for i in (await client.get("/api/inbox", headers=auth(ftok))).json()["items"]
                if i["kind"] == "post_mention"]) == 1


async def test_the_mention_picker_offers_the_people_i_am_connected_to(client: AsyncClient):
    """Typing @ opens my own graph, not the account table (plan/42 §11)."""
    me, mytok = await signup(client)
    friend, ftok = await signup(client, name="김하나")
    fan, fantok = await signup(client, name="박두나")
    stranger, _ = await signup(client, name="남세나")
    async with session_scope() as db:
        for uid, handle in ((friend["id"], "hanaya"), (fan["id"], "dunaya"), (stranger["id"], "senaya")):
            (await db.get(User, _uuid.UUID(uid))).mail_handle = handle
        await db.commit()

    await client.post(f"/api/network/people/{friend['id']}/follow", headers=auth(mytok))
    await client.post(f"/api/network/people/{me['id']}/follow", headers=auth(fantok))

    items = (await client.get("/api/network/people/mentionable", headers=auth(mytok))).json()["items"]
    assert {x["display_name"] for x in items} == {"김하나", "박두나"}, "either direction counts, a stranger does not"

    by_handle = (await client.get("/api/network/people/mentionable", params={"q": "han"}, headers=auth(mytok))).json()["items"]
    assert [x["handle"] for x in by_handle] == ["hanaya"]
    by_name = (await client.get("/api/network/people/mentionable", params={"q": "두나"}, headers=auth(mytok))).json()["items"]
    assert [x["handle"] for x in by_name] == ["dunaya"]

    # Somebody who never claimed an address is still on the list: a mention is a person.
    async with session_scope() as db:
        (await db.get(User, _uuid.UUID(friend["id"]))).mail_handle = None
        await db.commit()
    again = (await client.get("/api/network/people/mentionable", headers=auth(mytok))).json()["items"]
    assert {x["display_name"] for x in again} == {"김하나", "박두나"}
    assert next(x for x in again if x["display_name"] == "김하나")["handle"] == ""


# ── naming a secretary (plan/43 §6) ─────────────────────────────────

async def _published_agent(client: AsyncClient, tok: str, name: str) -> dict:
    agent = (await client.post("/api/agents", json={"name": name}, headers=auth(tok))).json()
    link = (await client.post(f"/api/agents/{agent['id']}/links", json={}, headers=auth(tok))).json()
    return {**agent, "code": link["code"]}


async def test_a_published_secretary_can_be_named_and_is_asked_to_answer(client: AsyncClient):
    """Naming one is asking it to read the post and reply under it."""
    from memora.models import Job

    user, tok = await signup(client)
    bot = await _published_agent(client, tok, "서기")

    listed = (await client.get("/api/network/people/mentionable", headers=auth(tok))).json()["items"]
    assert [x["display_name"] for x in listed if x["kind"] == "agent"] == ["서기"]

    r = await client.post("/api/blog", headers=auth(tok),
                          json={"body": "@서기 이 사진 어때요?", "kind": "note", "mentions": [bot["id"]]})
    assert r.status_code == 201, r.text
    named = r.json()["mentions"]
    assert [x["id"] for x in named] == [bot["id"]]
    assert named[0]["agent"] is True and named[0]["code"] == bot["code"], "the mention has to lead to the door"

    async with session_scope() as db:
        jobs = (await db.execute(select(Job).where(Job.kind == "post.secretary_reply"))).scalars().all()
    assert [j.payload["agent_id"] for j in jobs] == [bot["id"]], "the secretary has to actually be asked"


async def test_naming_a_fourth_secretary_is_refused(client: AsyncClient):
    """Every named secretary is a turn somebody pays for. The cap is not announced up
    front; whoever reaches it is told then."""
    user, tok = await signup(client)
    # One secretary each: a plan caps how many one account may have, and the cap under test
    # is per post rather than per owner.
    bots = []
    for n in range(4):
        _, other = await signup(client)
        bots.append(await _published_agent(client, other, f"서기{n}"))

    body = " ".join(f"@서기{n}" for n in range(3)) + " 봐주세요"
    ok = await client.post("/api/blog", headers=auth(tok),
                           json={"body": body, "kind": "note", "mentions": [b["id"] for b in bots[:3]]})
    assert ok.status_code == 201, ok.text
    assert len(ok.json()["mentions"]) == 3

    body4 = " ".join(f"@서기{n}" for n in range(4)) + " 봐주세요"
    too_many = await client.post("/api/blog", headers=auth(tok),
                                 json={"body": body4, "kind": "note", "mentions": [b["id"] for b in bots]})
    assert too_many.status_code == 409
    assert too_many.json()["error"]["code"] == "too_many_agents"


async def test_a_secretary_nobody_can_reach_is_not_a_mention(client: AsyncClient):
    """A secretary with no public link is not a door, so naming it does nothing."""
    user, tok = await signup(client)
    private = (await client.post("/api/agents", json={"name": "속기"}, headers=auth(tok))).json()
    r = await client.post("/api/blog", headers=auth(tok),
                          json={"body": "@속기 있나요", "kind": "note", "mentions": [private["id"]]})
    assert r.status_code == 201 and r.json()["mentions"] == []


async def test_a_secretarys_reply_is_signed_by_the_secretary(client: AsyncClient):
    """Its owner did not write it. A byline that says they did is a person saying something
    a person never said (plan/43 §6)."""
    from memora.db.session import session_scope
    from memora.models import User as _User
    from memora.services import blog as B

    owner, otok = await signup(client, name="비서주인")
    bot = await _published_agent(client, otok, "제니")
    post = (await client.post("/api/blog", headers=auth(otok), json={"body": "한 줄", "kind": "note"})).json()

    async with session_scope() as db:
        me = await db.get(_User, _uuid.UUID(owner["id"]))
        await B.comment(db, me, _uuid.UUID(post["id"]), body="비서가 답합니다.", as_agent=_uuid.UUID(bot["id"]))
        await db.commit()

    rows = (await client.get(f"/api/blog/{post['id']}/comments", headers=auth(otok))).json()["items"]
    assert [c["author"]["name"] for c in rows] == ["제니"]
    assert rows[0]["author"]["agent"] is True
    assert rows[0]["author"]["id"] == bot["id"], "the byline is the secretary, not its owner"

    # A person's own reply is still theirs.
    await client.post(f"/api/blog/{post['id']}/comments", headers=auth(otok), json={"body": "제가 씁니다."})
    rows = (await client.get(f"/api/blog/{post['id']}/comments", headers=auth(otok))).json()["items"]
    assert [c["author"]["name"] for c in rows] == ["제니", "비서주인"]
    assert "agent" not in rows[1]["author"]


async def test_an_edit_that_says_nothing_about_names_keeps_them(client: AsyncClient):
    """The blog editor patches the words and the shelf, never the mention list (plan/42 §11).

    Without this, changing a post from 공개 to 인맥 quietly unlinked everybody named in it,
    and a named secretary lost the door its chip pointed at.
    """
    from memora.models import Job

    author, atok = await signup(client)
    friend, _ = await signup(client, name="불린이")
    bot = await _published_agent(client, atok, "서기")
    made = await client.post("/api/blog", headers=auth(atok), json={
        "body": "@불린이 @서기 고마워요.", "kind": "note", "mentions": [friend["id"], bot["id"]]})
    pid = made.json()["id"]
    assert len(made.json()["mentions"]) == 2

    kept = (await client.patch(f"/api/blog/{pid}", headers=auth(atok), json={"visibility": "friends"})).json()
    assert [m["id"] for m in kept["mentions"]] == [friend["id"], bot["id"]], "an edit is not a deletion"
    assert next(m for m in kept["mentions"] if m.get("agent"))["code"] == bot["code"]

    # Still checked against the words: a name taken out of the text stops being a mention.
    gone = (await client.patch(f"/api/blog/{pid}", headers=auth(atok), json={"body": "고마워요."})).json()
    assert gone["mentions"] == []

    async with session_scope() as db:
        jobs = (await db.execute(select(Job).where(Job.kind == "post.secretary_reply"))).scalars().all()
    assert len([j for j in jobs if j.payload["post_id"] == pid]) == 1, "asked once, not again on every edit"


async def test_putting_a_draft_up_summons_the_people_in_it(client: AsyncClient):
    """Nobody was told while it was a draft, so publishing is the first summons."""
    from memora.models import Job

    author, atok = await signup(client)
    friend, ftok = await signup(client, name="불린이")
    bot = await _published_agent(client, atok, "서기")
    made = await client.post("/api/blog", headers=auth(atok), json={
        "body": "@불린이 @서기 곧 올릴게요.", "kind": "note", "publish": False,
        "mentions": [friend["id"], bot["id"]]})
    pid = made.json()["id"]
    assert not [i for i in (await client.get("/api/inbox", headers=auth(ftok))).json()["items"]
                if i["kind"] == "post_mention"]

    await client.patch(f"/api/blog/{pid}", headers=auth(atok), json={"status": "published"})
    assert len([i for i in (await client.get("/api/inbox", headers=auth(ftok))).json()["items"]
                if i["kind"] == "post_mention"]) == 1
    async with session_scope() as db:
        jobs = (await db.execute(select(Job).where(Job.kind == "post.secretary_reply"))).scalars().all()
    assert [j.payload["agent_id"] for j in jobs if j.payload["post_id"] == pid] == [bot["id"]]


async def test_a_secretary_behind_an_expired_link_is_not_a_door(client: AsyncClient):
    """The picker, the graph and a caption all mean the same thing by reachable."""
    from datetime import UTC, datetime, timedelta

    from memora.models import ShareLink

    user, tok = await signup(client)
    bot = await _published_agent(client, tok, "서기")
    async with session_scope() as db:
        link = (await db.execute(select(ShareLink).where(ShareLink.code == bot["code"]))).scalars().first()
        link.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()

    listed = (await client.get("/api/network/people/mentionable", headers=auth(tok))).json()["items"]
    assert [x for x in listed if x["kind"] == "agent"] == []
    r = await client.post("/api/blog", headers=auth(tok),
                          json={"body": "@서기 있나요", "kind": "note", "mentions": [bot["id"]]})
    assert r.status_code == 201 and r.json()["mentions"] == []


# ── a reply under a reply (plan/42 §5) ──────────────────────────────

async def test_a_comment_can_be_answered_and_the_thread_stays_two_deep(client: AsyncClient):
    """Answering an answer joins that thread instead of starting a third column."""
    author, atok = await signup(client)
    friend, ftok = await signup(client, name="불린이")
    await _befriend(client, author, atok, friend, ftok)
    pid = (await client.post("/api/blog", headers=auth(atok),
                             json={"body": "오늘 이야기", "kind": "note"})).json()["id"]

    root = (await client.post(f"/api/blog/{pid}/comments", headers=auth(ftok), json={"body": "좋네요"})).json()
    assert root["parent_id"] is None
    kid = (await client.post(f"/api/blog/{pid}/comments", headers=auth(atok),
                             json={"body": "고마워요", "parent_id": root["id"]})).json()
    assert kid["parent_id"] == root["id"]
    grand = (await client.post(f"/api/blog/{pid}/comments", headers=auth(ftok),
                               json={"body": "아니에요", "parent_id": kid["id"]})).json()
    assert grand["parent_id"] == root["id"], "answering an answer joins the thread it is in"

    rows = (await client.get(f"/api/blog/{pid}/comments", headers=auth(atok))).json()["items"]
    assert [r["body"] for r in rows] == ["좋네요", "고마워요", "아니에요"]
    assert (await client.get("/api/feed", headers=auth(atok))).json()["items"][0]["comment_count"] == 3


async def test_being_answered_is_worth_hearing_about(client: AsyncClient):
    """The person answered hears it, and the post's author is not told twice."""
    author, atok = await signup(client)
    friend, ftok = await signup(client, name="불린이")
    await _befriend(client, author, atok, friend, ftok)
    pid = (await client.post("/api/blog", headers=auth(atok),
                             json={"body": "오늘 이야기", "kind": "note"})).json()["id"]
    root = (await client.post(f"/api/blog/{pid}/comments", headers=auth(ftok), json={"body": "좋네요"})).json()
    await client.post(f"/api/blog/{pid}/comments", headers=auth(atok),
                      json={"body": "고마워요", "parent_id": root["id"]})

    mine = (await client.get("/api/inbox", headers=auth(ftok))).json()["items"]
    assert [i["kind"] for i in mine if i["kind"].startswith("post_")] == ["post_reply"]
    # My own reply under my own post tells me nothing.
    theirs = [i for i in (await client.get("/api/inbox", headers=auth(atok))).json()["items"]
              if i["kind"] == "post_comment"]
    assert len(theirs) == 1, "one card for the comment, none for my own answer to it"


async def test_removing_a_comment_takes_its_answers(client: AsyncClient):
    """A reply with nothing above it is a sentence addressed to a hole."""
    author, atok = await signup(client)
    friend, ftok = await signup(client, name="불린이")
    await _befriend(client, author, atok, friend, ftok)
    pid = (await client.post("/api/blog", headers=auth(atok),
                             json={"body": "오늘 이야기", "kind": "note"})).json()["id"]
    root = (await client.post(f"/api/blog/{pid}/comments", headers=auth(ftok), json={"body": "좋네요"})).json()
    await client.post(f"/api/blog/{pid}/comments", headers=auth(atok), json={"body": "고마워요", "parent_id": root["id"]})
    await client.post(f"/api/blog/{pid}/comments", headers=auth(ftok), json={"body": "또요", "parent_id": root["id"]})

    r = await client.delete(f"/api/blog/{pid}/comments/{root['id']}", headers=auth(ftok))
    assert r.status_code == 200 and r.json()["removed"] == 3
    assert (await client.get(f"/api/blog/{pid}/comments", headers=auth(atok))).json()["items"] == []
    assert (await client.get("/api/feed", headers=auth(atok))).json()["items"][0]["comment_count"] == 0


async def test_a_reply_cannot_be_hung_on_another_posts_comment(client: AsyncClient):
    author, atok = await signup(client)
    a = (await client.post("/api/blog", headers=auth(atok), json={"body": "하나", "kind": "note"})).json()["id"]
    b = (await client.post("/api/blog", headers=auth(atok), json={"body": "둘", "kind": "note"})).json()["id"]
    c = (await client.post(f"/api/blog/{a}/comments", headers=auth(atok), json={"body": "댓글"})).json()
    r = await client.post(f"/api/blog/{b}/comments", headers=auth(atok), json={"body": "답글", "parent_id": c["id"]})
    assert r.status_code == 404


# ── one post, wherever it was pressed (plan/42 §12) ─────────────────

async def test_a_post_opens_the_same_way_wherever_it_was_pressed(client: AsyncClient):
    """One shape, from one place: a card in 소식, a tile in a grid, a row in my own blog."""
    author, atok = await signup(client)
    friend, ftok = await signup(client, name="불린이")
    await _befriend(client, author, atok, friend, ftok)
    pid = (await client.post("/api/blog", headers=auth(atok),
                             json={"body": "오늘 이야기", "kind": "note"})).json()["id"]

    mine = (await client.get(f"/api/feed/posts/{pid}", headers=auth(atok))).json()
    assert mine["why"] == "mine" and mine["can_edit"] is True
    assert mine["author"]["id"] == author["id"] and mine["body"] == "오늘 이야기"
    assert mine["image_ids"] == [], "my own post hands back the uploads, for editing"

    theirs = (await client.get(f"/api/feed/posts/{pid}", headers=auth(ftok))).json()
    assert theirs["why"] == "friend" and theirs["can_edit"] is False
    assert "image_ids" not in theirs

    stranger, stok = await signup(client, name="남세나")
    assert (await client.get(f"/api/feed/posts/{pid}", headers=auth(stok))).status_code == 200, "it is public"


async def test_my_own_draft_opens_for_me_and_for_nobody_else(client: AsyncClient):
    """My blog lists a draft, so pressing it has to open it."""
    author, atok = await signup(client)
    other, otok = await signup(client, name="남세나")
    pid = (await client.post("/api/blog", headers=auth(atok),
                             json={"title": "아직", "body": "쓰는 중", "publish": False})).json()["id"]

    mine = (await client.get(f"/api/feed/posts/{pid}", headers=auth(atok))).json()
    assert mine["status"] == "draft" and mine["at"] is None and mine["can_edit"] is True
    assert (await client.get(f"/api/feed/posts/{pid}", headers=auth(otok))).status_code == 404

    listed = (await client.get("/api/blog", headers=auth(atok))).json()["items"]
    assert [x["id"] for x in listed] == [pid]
    assert listed[0]["author"]["id"] == author["id"] and listed[0]["why"] == "mine"
    assert listed[0]["liked"] is False and listed[0]["can_edit"] is True


async def test_a_card_is_a_card_and_the_window_holds_the_post(client: AsyncClient):
    """Lists draw cards; what editing a post takes comes from opening it (plan/42 §14).

    A list that carried every article's body and every upload id made one screen of 소식
    into twenty documents. The window asks for the one post it is showing.
    """
    author, atok = await signup(client)
    friend, ftok = await signup(client, name="불린이")
    await _befriend(client, author, atok, friend, ftok)
    up = await _photo(client, atok)
    long_body = "본문. " * 400
    await client.post("/api/blog", headers=auth(atok), json={"title": "긴 글", "body": long_body})
    await client.post("/api/blog", headers=auth(atok),
                      json={"body": "사진 한 장", "kind": "note", "images": [up]})

    for row in (await client.get("/api/feed", headers=auth(atok))).json()["items"]:
        assert "image_ids" not in row, "a card does not carry the uploads"
        if row["kind"] == "article":
            assert "body" not in row, "a card does not carry the article"
    for row in (await client.get("/api/blog", headers=auth(atok))).json()["items"]:
        assert "image_ids" not in row

    pid = (await client.get("/api/feed", headers=auth(atok))).json()["items"][0]["id"]
    whole = (await client.get(f"/api/feed/posts/{pid}", headers=auth(atok))).json()
    assert whole["image_ids"] == [up] and whole["can_edit"] is True

    # The article opens whole for somebody else too, not as its own excerpt.
    art = next(r for r in (await client.get("/api/feed", headers=auth(ftok))).json()["items"]
               if r["kind"] == "article")
    opened = (await client.get(f"/api/feed/posts/{art['id']}", headers=auth(ftok))).json()
    assert opened["body"] == long_body.strip() and "image_ids" not in opened


async def test_a_note_is_a_thousand_characters(client: AsyncClient):
    """소식 에 적는 글은 카드에서 읽힌다. 그 길이를 넘으면 그건 제목이 있는 글이다."""
    user, tok = await signup(client)
    r = await client.post("/api/blog", headers=auth(tok), json={"body": "가" * 1500, "kind": "note"})
    assert r.status_code == 201
    assert len(r.json()["body"]) == 1000
    # An article keeps its own, much larger, room.
    a = await client.post("/api/blog", headers=auth(tok), json={"title": "긴 글", "body": "나" * 1500})
    assert len((await client.get(f"/api/feed/posts/{a.json()['id']}", headers=auth(tok))).json()["body"]) == 1500


async def test_my_blog_turns_pages(client: AsyncClient):
    """A shelf I go back to and look through, not a river."""
    user, tok = await signup(client)
    for i in range(12):
        await client.post("/api/blog", headers=auth(tok), json={"body": f"글 {i}", "kind": "note"})
    one = (await client.get("/api/blog", params={"page": 1, "limit": 5}, headers=auth(tok))).json()
    assert len(one["items"]) == 5 and one["page"] == 1 and one["pages"] == 3 and one["total"] == 12
    three = (await client.get("/api/blog", params={"page": 3, "limit": 5}, headers=auth(tok))).json()
    assert len(three["items"]) == 2
    assert not {x["id"] for x in one["items"]} & {x["id"] for x in three["items"]}


async def test_somebodys_posts_turn_pages_and_only_show_what_i_may_see(client: AsyncClient):
    them, ttok = await signup(client, name="남세나")
    me, mytok = await signup(client)
    for i in range(5):
        await client.post("/api/blog", headers=auth(ttok), json={"body": f"공개 {i}", "kind": "note"})
    await client.post("/api/blog", headers=auth(ttok),
                      json={"body": "인맥만", "kind": "note", "visibility": "friends"})

    page = (await client.get(f"/api/network/people/{them['id']}/posts",
                             params={"page": 1, "limit": 3}, headers=auth(mytok))).json()
    assert page["total"] == 5 and page["pages"] == 2 and len(page["items"]) == 3
    two = (await client.get(f"/api/network/people/{them['id']}/posts",
                            params={"page": 2, "limit": 3}, headers=auth(mytok))).json()
    assert len(two["items"]) == 2
    assert all("인맥만" not in (x.get("body") or "") for x in page["items"] + two["items"])


async def test_a_suspended_account_goes_quiet_at_its_own_address_too(client: AsyncClient):
    from memora.models import User as _U

    them, ttok = await signup(client, name="남세나")
    me, mytok = await signup(client)
    pid = (await client.post("/api/blog", headers=auth(ttok),
                             json={"body": "곧 조용해져요", "kind": "note"})).json()["id"]
    assert (await client.get(f"/api/feed/posts/{pid}", headers=auth(mytok))).status_code == 200
    async with session_scope() as db:
        (await db.get(_U, _uuid.UUID(them["id"]))).status = "suspended"
        await db.commit()
    assert (await client.get(f"/api/feed/posts/{pid}", headers=auth(mytok))).status_code == 404


async def test_a_long_thread_keeps_its_present_not_its_beginning(client: AsyncClient):
    """Past the window it is the oldest that go: a reply from a minute ago must not vanish."""
    author, atok = await signup(client)
    pid = (await client.post("/api/blog", headers=auth(atok),
                             json={"body": "오래 가는 글", "kind": "note"})).json()["id"]
    for i in range(8):
        await client.post(f"/api/blog/{pid}/comments", headers=auth(atok), json={"body": f"말 {i}"})
    rows = (await client.get(f"/api/blog/{pid}/comments", params={"limit": 3}, headers=auth(atok))).json()["items"]
    assert [r["body"] for r in rows] == ["말 5", "말 6", "말 7"], "newest kept, still oldest first"


async def test_the_house_has_a_ceiling_nothing_human_reaches(client: AsyncClient, monkeypatch):
    """소식 에도 문지기를 둔다 (plan/42 §14).

    사람은 1분에 글을 여섯 편 쓰지 않는다. 댓글은 그만큼 빠를 수 있으니 따로 센다.
    광장에만 있던 한도가 내 집에는 없어서, 한 계정이 끝없이 밀어 넣을 수 있었다.
    """
    import memora.api.blog as A
    from memora.core.ratelimit import limiter

    assert A.POSTS_PER_MIN < A.COMMENTS_PER_MIN < A.TAPS_PER_MIN

    user, tok = await signup(client)
    pid = (await client.post("/api/blog", headers=auth(tok),
                             json={"body": "첫 글", "kind": "note"})).json()["id"]

    monkeypatch.delenv("MEMORA_RATELIMIT_DISABLED", raising=False)
    monkeypatch.setattr(A, "POSTS_PER_MIN", 3)
    limiter._buckets.clear()
    seen = [(await client.post("/api/blog", headers=auth(tok),
                               json={"body": f"글 {i}", "kind": "note"})).status_code for i in range(6)]
    assert 201 in seen and 429 in seen, seen
    assert seen.index(429) >= 3, f"throttled before the budget was spent: {seen}"

    # Replying is its own budget: running out of posts must not silence a conversation.
    assert (await client.post(f"/api/blog/{pid}/comments", headers=auth(tok),
                              json={"body": "말"})).status_code == 201

    # And it is per account.
    _, other = await signup(client, name="다른사람")
    assert (await client.post("/api/blog", headers=auth(other),
                              json={"body": "남의 글", "kind": "note"})).status_code == 201
    limiter._buckets.clear()


async def test_a_reply_whose_root_fell_out_of_the_window_is_still_there(client: AsyncClient):
    """A long thread loses its beginning. What is left has to still be all of it."""
    author, atok = await signup(client)
    pid = (await client.post("/api/blog", headers=auth(atok),
                             json={"body": "긴 대화", "kind": "note"})).json()["id"]
    root = (await client.post(f"/api/blog/{pid}/comments", headers=auth(atok), json={"body": "뿌리"})).json()
    for i in range(3):
        await client.post(f"/api/blog/{pid}/comments", headers=auth(atok), json={"body": f"사이 {i}"})
    await client.post(f"/api/blog/{pid}/comments", headers=auth(atok),
                      json={"body": "늦은 답글", "parent_id": root["id"]})

    rows = (await client.get(f"/api/blog/{pid}/comments", params={"limit": 2}, headers=auth(atok))).json()["items"]
    assert [r["body"] for r in rows] == ["사이 2", "늦은 답글"]
    orphan = next(r for r in rows if r["body"] == "늦은 답글")
    assert orphan["parent_id"] == root["id"], "it still says what it answers, gone or not"


async def test_my_blog_reads_in_the_order_its_dates_say(client: AsyncClient):
    """Sorting by last-touched put an old post edited this morning above a newer one."""
    user, tok = await signup(client)
    old = (await client.post("/api/blog", headers=auth(tok), json={"body": "먼저", "kind": "note"})).json()
    new = (await client.post("/api/blog", headers=auth(tok), json={"body": "나중", "kind": "note"})).json()
    await client.patch(f"/api/blog/{old['id']}", headers=auth(tok), json={"body": "먼저 (고침)"})
    listed = (await client.get("/api/blog", headers=auth(tok))).json()["items"]
    assert [x["id"] for x in listed] == [new["id"], old["id"]]


async def test_a_comment_is_five_hundred_characters(client: AsyncClient):
    """댓글도 피드의 크기다 (plan/42 §4). 넘겨 보내면 받지 않는다 — 조용히 자르면 쓴
    사람은 자기 말이 어디까지 남았는지 알 길이 없다."""
    user, tok = await signup(client)
    post = (await client.post("/api/blog", headers=auth(tok), json={"body": "한 줄", "kind": "note"})).json()
    ok = await client.post(f"/api/blog/{post['id']}/comments", headers=auth(tok), json={"body": "다" * 500})
    assert ok.status_code == 201, ok.text
    assert len(ok.json()["body"]) == 500
    over = await client.post(f"/api/blog/{post['id']}/comments", headers=auth(tok), json={"body": "다" * 501})
    assert over.status_code == 422


async def test_the_feed_calls_people_what_they_call_themselves(client: AsyncClient):
    """집 안에서는 어디서나 그 사람이 고른 이름이다. 소식만 계정의 본명을 찍으면 한 사람이
    화면마다 다른 사람이 된다."""
    user, tok = await signup(client)
    async with session_scope() as db:
        me = await db.get(User, _uuid.UUID(user["id"]))
        me.display_name, me.nickname = "장하렴", "하렴"
        await db.commit()
    post = (await client.post("/api/blog", headers=auth(tok), json={"body": "한 줄", "kind": "note"})).json()
    assert (await client.get("/api/feed", headers=auth(tok))).json()["items"][0]["author"]["name"] == "하렴"
    assert (await client.get("/api/blog", headers=auth(tok))).json()["items"][0]["author"]["name"] == "하렴"
    await client.post(f"/api/blog/{post['id']}/comments", headers=auth(tok), json={"body": "댓글"})
    rows = (await client.get(f"/api/blog/{post['id']}/comments", headers=auth(tok))).json()["items"]
    assert rows[0]["author"]["name"] == "하렴"
