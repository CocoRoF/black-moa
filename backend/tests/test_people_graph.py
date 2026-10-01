"""인맥 as a graph of real people (plan/31).

Three things are worth a test here, and they are the three that are easy to get subtly
wrong: a friendship is only a friendship when both people have it; a guest identity is
claimed by proof of address and not by typing one; and promoting a card to a person merges
into what the owner already wrote instead of forking it.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

from httpx import AsyncClient

from blackmoa.db.session import session_scope
from blackmoa.models import Agent, NetworkNode, User, Visitor
from blackmoa.services import people as P
from tests.conftest import auth, signup


async def _visitor(owner_id: str, *, name: str, email: str | None, turns: int = 3) -> tuple[str, str]:
    async with session_scope() as db:
        agent = Agent(owner_id=_uuid.UUID(owner_id), name="비서", provider="fake", model_id="fake-1")
        db.add(agent)
        await db.flush()
        now = datetime.now(UTC)
        v = Visitor(owner_id=_uuid.UUID(owner_id), agent_id=agent.id, token_hash=f"t-{_uuid.uuid4().hex}",
                    display_name=name, email=email, first_seen_at=now, last_seen_at=now, turn_count=turns)
        db.add(v)
        await db.flush()
        return str(v.id), str(agent.id)


async def _verify(user_id: str) -> None:
    """Prove the address the way the product does, without going through the mail."""
    async with session_scope() as db:
        u = await db.get(User, _uuid.UUID(user_id))
        u.email_verified_at = datetime.now(UTC)
        await P.claim_visitors_for(db, u)


# ── connecting: one act, and 인맥 when both do it (plan/43) ─────────

async def test_connecting_is_one_way_until_it_is_answered(client: AsyncClient):
    a_user, a_tok = await signup(client, name="가온")
    b_user, b_tok = await signup(client, name="나윤")

    found = (await client.get("/api/network/people/search", params={"q": b_user["email"]}, headers=auth(a_tok))).json()
    assert [x["id"] for x in found["items"]] == [b_user["id"]]

    r = await client.post(f"/api/network/people/{b_user['id']}/follow", headers=auth(a_tok))
    assert r.status_code == 200 and r.json()["status"] == "outgoing"

    # It shows on both sides straight away, each from where they stand.
    mine = (await client.get("/api/network/people/links", headers=auth(a_tok))).json()
    assert [x["id"] for x in mine["outgoing"]] == [b_user["id"]] and mine["friends"] == []
    theirs = (await client.get("/api/network/people/links", headers=auth(b_tok))).json()
    assert [x["id"] for x in theirs["incoming"]] == [a_user["id"]] and theirs["friends"] == []

    # And the picture says which way it points, in both graphs.
    ga = (await client.get("/api/network/graph", headers=auth(a_tok))).json()
    assert [e["direction"] for e in ga["edges"]] == ["outgoing"]
    gb = (await client.get("/api/network/graph", headers=auth(b_tok))).json()
    assert [e["direction"] for e in gb["edges"]] == ["incoming"]

    # Answering makes them 인맥. Nobody accepted anything: they each chose.
    r = await client.post(f"/api/network/people/{a_user['id']}/follow", headers=auth(b_tok))
    assert r.json()["status"] == "mutual"
    for tok, other in ((a_tok, b_user), (b_tok, a_user)):
        listed = (await client.get("/api/network/people/links", headers=auth(tok))).json()
        assert [x["id"] for x in listed["friends"]] == [other["id"]]
        assert listed["outgoing"] == [] and listed["incoming"] == []
        g = (await client.get("/api/network/graph", headers=auth(tok))).json()
        me = next(n for n in g["nodes"] if n["is_self"])
        them = next(n for n in g["nodes"] if n["user_id"] == other["id"])
        assert them["person"] == "member" and them["hops"] == 1
        assert [e["direction"] for e in g["edges"]] == ["both"]
        assert any({e["src_id"], e["dst_id"]} == {me["id"], them["id"]} for e in g["edges"])


async def test_only_인맥_counts_as_knowing_somebody(client: AsyncClient):
    """A one-way connection is not a claim about the other person."""
    from blackmoa.db.session import session_scope
    from blackmoa.services import people as P

    a_user, a_tok = await signup(client)
    b_user, b_tok = await signup(client)
    await client.post(f"/api/network/people/{b_user['id']}/follow", headers=auth(a_tok))
    async with session_scope() as db:
        assert await P.viewer_level(db, _uuid.UUID(b_user["id"]), _uuid.UUID(a_user["id"])) == "stranger"
    await client.post(f"/api/network/people/{a_user['id']}/follow", headers=auth(b_tok))
    async with session_scope() as db:
        assert await P.viewer_level(db, _uuid.UUID(b_user["id"]), _uuid.UUID(a_user["id"])) == "known"


async def test_disconnecting_takes_only_my_half_and_keeps_the_notes(client: AsyncClient):
    a_user, a_tok = await signup(client)
    b_user, b_tok = await signup(client)
    await client.post(f"/api/network/people/{b_user['id']}/follow", headers=auth(a_tok))
    await client.post(f"/api/network/people/{a_user['id']}/follow", headers=auth(b_tok))

    node_id = next(n["id"] for n in (await client.get("/api/network/graph", headers=auth(a_tok))).json()["nodes"]
                   if n["user_id"] == b_user["id"])
    await client.patch(f"/api/network/nodes/{node_id}", json={"notes": "2019년 컨퍼런스에서 만남"}, headers=auth(a_tok))

    assert (await client.delete(f"/api/network/people/links/{b_user['id']}", headers=auth(a_tok))).status_code == 200
    g = (await client.get("/api/network/graph", headers=auth(a_tok))).json()
    kept = next(n for n in g["nodes"] if n["id"] == node_id)
    assert kept["notes"] == "2019년 컨퍼런스에서 만남", "ending a relationship is not the same as never having met"
    # What they chose is still theirs: they connected to me and I did not undo that.
    assert [e["direction"] for e in g["edges"]] == ["incoming"]
    assert [x["id"] for x in (await client.get("/api/network/people/links", headers=auth(a_tok))).json()["incoming"]] == [b_user["id"]]


async def test_suggestions_only_name_people_who_did_something(client: AsyncClient):
    """Not a directory and not friends-of-friends: somebody who connected to me, or somebody
    who actually talked to my secretary (plan/43 §3)."""
    me, my_tok = await signup(client)
    fan, fan_tok = await signup(client, name="먼저온이")
    await signup(client, name="아무개")

    await client.post(f"/api/network/people/{me['id']}/follow", headers=auth(fan_tok))
    items = (await client.get("/api/network/people/suggestions", headers=auth(my_tok))).json()["items"]
    assert [x["id"] for x in items] == [fan["id"]]
    assert items[0]["reason"] == "connected_me"

    # Once I answer, they are 인맥 and no longer a suggestion.
    await client.post(f"/api/network/people/{fan['id']}/follow", headers=auth(my_tok))
    assert (await client.get("/api/network/people/suggestions", headers=auth(my_tok))).json()["items"] == []


async def test_the_directory_is_not_browsable(client: AsyncClient):
    _, tok = await signup(client)
    await signup(client, name="누군가")
    for q in ("", " ", "a"):
        assert (await client.get("/api/network/people/search", params={"q": q}, headers=auth(tok))).json()["items"] == [], \
            "a one-character query would be a way to page through every account"


# ── guests ─────────────────────────────────────────────────────────

async def test_a_guest_who_talked_to_my_secretary_can_be_added(client: AsyncClient):
    owner, tok = await signup(client)
    vid, _ = await _visitor(owner["id"], name="손성준", email="sj@example.com")

    listed = (await client.get("/api/network/guests", headers=auth(tok))).json()["items"]
    assert [g["visitor_id"] for g in listed] == [vid]
    assert listed[0]["node_id"] is None and listed[0]["turns"] == 3

    node = (await client.post(f"/api/network/guests/{vid}", headers=auth(tok))).json()
    assert node["person"] == "guest" and node["name"] == "손성준"
    g = (await client.get("/api/network/graph", headers=auth(tok))).json()
    assert next(n for n in g["nodes"] if n["id"] == node["id"])["hops"] == 1, "a guest joins the ego network at one hop"
    assert (await client.get("/api/network/guests", headers=auth(tok))).json()["items"][0]["node_id"] == node["id"]


async def test_a_guest_becomes_the_account_only_once_the_address_is_proven(client: AsyncClient):
    """The rule the whole guest design rests on.

    A guest identity carries somebody's real conversations. Typing their address into a
    signup form must not hand it over; verifying it must.
    """
    owner, tok = await signup(client)
    vid, _ = await _visitor(owner["id"], name="손성준", email="claimme@example.com")
    node = (await client.post(f"/api/network/guests/{vid}", headers=auth(tok))).json()

    guest_user, _ = await signup(client, email="claimme@example.com", name="손성준")
    after_signup = (await client.get("/api/network/graph", headers=auth(tok))).json()
    assert next(n for n in after_signup["nodes"] if n["id"] == node["id"])["person"] == "guest", \
        "signing up with an address is not proof of holding it"

    await _verify(guest_user["id"])
    after_verify = (await client.get("/api/network/graph", headers=auth(tok))).json()
    promoted = next(n for n in after_verify["nodes"] if n["id"] == node["id"])
    assert promoted["person"] == "member" and promoted["user_id"] == guest_user["id"]
    assert len([n for n in after_verify["nodes"] if n["user_id"] == guest_user["id"]]) == 1, \
        "the same person must not end up in the graph twice"


async def test_promotion_merges_into_the_card_the_owner_already_wrote(client: AsyncClient):
    """Years of notes must not fork because the person finally signed up."""
    owner, tok = await signup(client)
    card = (await client.post("/api/network/nodes", json={"kind": "person", "name": "박지훈",
                                                          "attrs": {"emails": ["jh@example.com"]},
                                                          "notes": "전 직장 동료"}, headers=auth(tok))).json()
    vid, _ = await _visitor(owner["id"], name="박지훈", email="jh@example.com")
    node = (await client.post(f"/api/network/guests/{vid}", headers=auth(tok))).json()
    assert node["id"] == card["id"], "the guest binding lands on the existing card, not beside it"

    friend, _ = await signup(client, email="jh@example.com", name="박지훈")
    await _verify(friend["id"])
    g = (await client.get("/api/network/graph", headers=auth(tok))).json()
    people = [n for n in g["nodes"] if not n["is_self"]]
    assert len(people) == 1
    assert people[0]["id"] == card["id"] and people[0]["person"] == "member"
    assert people[0]["notes"] == "전 직장 동료"


async def test_a_visitor_to_my_own_secretary_is_not_added_to_my_own_network(client: AsyncClient):
    """Signing into my own share link makes me a visitor of myself; the graph must not
    grow a second me out of it."""
    owner, tok = await signup(client)
    vid, _ = await _visitor(owner["id"], name="나", email=owner["email"])
    await _verify(owner["id"])
    async with session_scope() as db:
        v = await db.get(Visitor, _uuid.UUID(vid))
        assert v.user_id is None
        selves = (await db.execute(
            __import__("sqlalchemy").select(NetworkNode).where(NetworkNode.owner_id == _uuid.UUID(owner["id"]),
                                                               NetworkNode.is_self.is_(True)))).scalars().all()
        assert len(selves) <= 1


async def test_connecting_twice_changes_nothing(client: AsyncClient):
    """There is no request to answer twice. Connecting again is the state it already was."""
    _, a_tok = await signup(client)
    b_user, _ = await signup(client)
    first = await client.post(f"/api/network/people/{b_user['id']}/follow", headers=auth(a_tok))
    assert first.status_code == 200 and first.json()["added"] is True
    again = await client.post(f"/api/network/people/{b_user['id']}/follow", headers=auth(a_tok))
    assert again.status_code == 200 and again.json()["added"] is False
    assert again.json()["status"] == "outgoing"


# ── profiles and suggestions ───────────────────────────────────────

async def test_a_profile_shows_only_what_its_owner_published(client: AsyncClient):
    me, my_tok = await signup(client, name="보는사람")
    them, their_tok = await signup(client, name="박서준")
    r = await client.put("/api/users/me/profile", json={"data": {"title": "프로덕트 리드", "bio": "비밀 메모"},
                                                        "visibility": {"title": "public", "bio": "private"}},
                         headers=auth(their_tok))
    assert r.status_code == 200, r.text
    seen = (await client.get(f"/api/network/people/{them['id']}", headers=auth(my_tok))).json()
    assert seen["fields"].get("title") == "프로덕트 리드"
    assert "bio" not in seen["fields"], "a private field is private on the profile page too"
    assert seen.get("email") is None, "a stranger does not get an address"

    mine = (await client.get(f"/api/network/people/{me['id']}", headers=auth(my_tok))).json()
    assert mine["is_me"] and mine["email"] == me["email"]


async def test_a_connection_may_see_the_address(client: AsyncClient):
    a_user, a_tok = await signup(client)
    b_user, b_tok = await signup(client)
    await client.post(f"/api/network/people/{b_user['id']}/follow", headers=auth(a_tok))
    await client.post(f"/api/network/people/{a_user['id']}/follow", headers=auth(b_tok))
    seen = (await client.get(f"/api/network/people/{b_user['id']}", headers=auth(a_tok))).json()
    assert seen["email"] == b_user["email"] and seen["connections"] == 1


async def test_suggestions_come_with_a_reason_and_never_list_strangers(client: AsyncClient):
    owner, tok = await signup(client)
    # Someone unrelated must not surface just for existing.
    await signup(client, name="모르는사람")
    guest_user, _ = await signup(client, email="knocked@example.com", name="찾아온사람")
    await _visitor(owner["id"], name="찾아온사람", email="knocked@example.com", turns=5)

    items = (await client.get("/api/network/people/suggestions", headers=auth(tok))).json()["items"]
    assert [x["id"] for x in items] == [guest_user["id"]], "only people with a reason appear"
    assert items[0]["reason"] == "guest"


async def test_a_suggestion_disappears_once_it_is_answered(client: AsyncClient):
    owner, tok = await signup(client)
    guest_user, _ = await signup(client, email="asked@example.com")
    await _visitor(owner["id"], name="아는사람", email="asked@example.com")
    assert len((await client.get("/api/network/people/suggestions", headers=auth(tok))).json()["items"]) == 1
    await client.post(f"/api/network/people/{guest_user['id']}/follow", headers=auth(tok))
    assert (await client.get("/api/network/people/suggestions", headers=auth(tok))).json()["items"] == []


async def test_a_new_contact_goes_nowhere_until_a_secretary_picks_it(client: AsyncClient):
    """인맥에는 공개 범위가 없다 (plan/57). 외부인에게 누구를 쓸지는 비서마다 [지식] 탭에서 고르고,
    새로 넣은 사람은 고르기 전에는 어디에도 나가지 않는다. 나 자신은 고르는 목록에 없다."""
    from blackmoa.db.session import session_scope
    from blackmoa.models import Agent
    from blackmoa.services import outsider as OUT

    _, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "소개꾼"}, headers=auth(tok))).json()
    node = (await client.post("/api/network/nodes", json={"kind": "person", "name": "새 사람"}, headers=auth(tok))).json()
    assert "visibility" not in node
    async with session_scope() as db:
        a = await db.get(Agent, __import__("uuid").UUID(agent["id"]))
        sc = await OUT.scope(db, a, "network", "stranger")
    assert sc is not None and not sc.has(node["id"])
    items = (await client.get(f"/api/agents/{agent['id']}/outsider/items", params={"kind": "network"}, headers=auth(tok))).json()["items"]
    assert [i["title"] for i in items] == ["새 사람"], "my own node is the middle of my graph, not a contact to pick"
    await client.put(f"/api/agents/{agent['id']}/outsider/picks", json={"kind": "network", "ids": [node["id"]]}, headers=auth(tok))
    async with session_scope() as db:
        a = await db.get(Agent, __import__("uuid").UUID(agent["id"]))
        sc = await OUT.scope(db, a, "network", "stranger")
    assert sc.has(node["id"])


# ── the grid that replaced the album (plan/42 §9) ──────────────────

async def _png(client: AsyncClient, tok: str) -> str:
    """A real PNG through the real upload path — a post stores ids, not URLs."""
    raw = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000004000000040802000000269309290000"
                        "001449444154789c633ca1a1c100034c0c48003707003854012024ef7a6b0000000049454e44ae426082")
    r = await client.post("/api/uploads", files={"file": ("a.png", raw, "image/png")},
                          data={"kind": "attachment"}, headers=auth(tok))
    assert r.status_code in (200, 201), r.text
    return r.json()["upload_id"]


async def test_a_photo_on_a_profile_is_a_post_with_its_own_visibility(client: AsyncClient):
    """There is no separate album any more. A photo somebody shows is a post: it has a
    caption, an address, a visibility of its own, and somewhere to reply."""
    me, my_tok = await signup(client)
    _, their_tok = await signup(client)
    up = await _png(client, my_tok)
    r = await client.post("/api/blog", headers=auth(my_tok),
                          json={"body": "첫 사진", "kind": "note", "images": [up], "visibility": "private"})
    assert r.status_code == 201, r.text

    mine = (await client.get(f"/api/network/people/{me['id']}", headers=auth(my_tok))).json()
    assert [p["body"] for p in mine["posts"]] == ["첫 사진"]
    assert len(mine["posts"][0]["images"]) == 1
    assert "photos" not in mine, "the album should be gone, not hiding"

    # A private post is not on somebody else's view of the page, and saying so out loud is
    # the difference between a grid and an album with one switch.
    seen = (await client.get(f"/api/network/people/{me['id']}", headers=auth(their_tok))).json()
    assert seen["posts"] == []

    pid = mine["posts"][0]["id"]
    await client.patch(f"/api/blog/{pid}", headers=auth(my_tok), json={"visibility": "public"})
    seen = (await client.get(f"/api/network/people/{me['id']}", headers=auth(their_tok))).json()
    assert len(seen["posts"]) == 1 and len(seen["posts"][0]["images"]) == 1

    assert (await client.delete(f"/api/blog/{pid}", headers=auth(my_tok))).status_code == 200
    assert (await client.get(f"/api/network/people/{me['id']}", headers=auth(my_tok))).json()["posts"] == []


async def test_photos_is_no_longer_a_profile_field(client: AsyncClient):
    """Anything still writing to it would be building a second album."""
    _, tok = await signup(client)
    up = await _png(client, tok)
    await client.put("/api/users/me/profile", headers=auth(tok),
                     json={"data": {"photos": [{"id": up}]}, "visibility": {"photos": "public"}})
    prof = (await client.get("/api/users/me/profile", headers=auth(tok))).json()
    assert "photos" not in (prof.get("data") or {})


# ── proposals resolve to people, or they do not exist ──────────────

async def _propose(owner_id: str, **payload) -> str:
    async with session_scope() as db:
        from blackmoa.services import network as N
        p = await N.propose(db, _uuid.UUID(owner_id), agent_id=None, kind="add_node", payload=payload, confidence=0.9)
        return str(p.id)


async def test_a_proposed_account_becomes_a_connection_request_not_a_card(client: AsyncClient):
    owner, tok = await signup(client)
    friend, _ = await signup(client, email="mentioned@example.com", name="김해수")
    pid = await _propose(owner["id"], kind="person", name="김해수", attrs={"emails": ["mentioned@example.com"]})

    items = (await client.get("/api/network/proposals", headers=auth(tok))).json()["items"]
    assert [i["resolved"]["action"] for i in items] == ["connect"]
    assert items[0]["resolved"]["person"]["id"] == friend["id"]

    r = await client.post(f"/api/network/proposals/{pid}/accept", headers=auth(tok))
    assert r.status_code == 200 and r.json()["did"] == "connect"
    assert [x["id"] for x in (await client.get("/api/network/people/links", headers=auth(tok))).json()["outgoing"]] == [friend["id"]]
    # And no loose card was made for them along the way.
    g = (await client.get("/api/network/graph", headers=auth(tok))).json()
    assert [n["person"] for n in g["nodes"] if not n["is_self"]] == ["member"]


async def test_a_proposed_guest_becomes_that_guest(client: AsyncClient):
    owner, tok = await signup(client)
    await _visitor(owner["id"], name="손성준", email="sj@example.com", turns=4)
    pid = await _propose(owner["id"], kind="person", name="손성준", attrs={"emails": ["sj@example.com"]})
    items = (await client.get("/api/network/proposals", headers=auth(tok))).json()["items"]
    assert items[0]["resolved"]["action"] == "add_guest"
    assert (await client.post(f"/api/network/proposals/{pid}/accept", headers=auth(tok))).json()["did"] == "add_guest"
    g = (await client.get("/api/network/graph", headers=auth(tok))).json()
    assert [n["person"] for n in g["nodes"] if not n["is_self"]] == ["guest"]


async def test_a_proposal_about_nobody_retires_itself(client: AsyncClient):
    """The complaint this fixes: a queue of rows nobody can act on, growing forever."""
    owner, tok = await signup(client)
    for name in ("스쳐간 사람", "Plattier", "누군가"):
        await _propose(owner["id"], kind="person", name=name)
    assert (await client.get("/api/network/proposals", headers=auth(tok))).json()["items"] == []
    async with session_scope() as db:
        from sqlalchemy import select as _sel

        from blackmoa.models import NetworkProposal
        rows = (await db.execute(_sel(NetworkProposal).where(NetworkProposal.owner_id == _uuid.UUID(owner["id"])))).scalars().all()
        assert {r.status for r in rows} == {"obsolete"}, "retired, not left pending forever"
    # and the graph never grew a name that was never anybody
    g = (await client.get("/api/network/graph", headers=auth(tok))).json()
    assert [n for n in g["nodes"] if not n["is_self"]] == []


async def test_the_secretary_cannot_propose_someone_unreachable(client: AsyncClient):
    """Refused at the source, so the queue never fills in the first place."""
    from blackmoa.models import Agent, User
    from blackmoa.pipeline.tools import network_tools as NT

    owner, tok = await signup(client)
    async with session_scope() as db:
        u = await db.get(User, _uuid.UUID(owner["id"]))
        agent = Agent(owner_id=u.id, name="비서", provider="fake", model_id="fake-1")
        db.add(agent)
        await db.flush()

        class _Ctx:
            owner_id = u.id
            visitor = None
            turn_id = None
            is_owner = True

            def card(self, *a, **k):
                return None
        ctx = _Ctx()
        ctx.agent = agent
        tool = NT.NetworkPropose(ctx)
        r = await tool.run({"kind": "add_node", "payload": {"kind": "person", "name": "지나가는 사람"}})
    assert r["proposed"] is False and "memory" in r["message"].lower()
    assert (await client.get("/api/network/proposals", headers=auth(tok))).json()["items"] == []


async def test_a_guest_who_has_an_account_is_asked_not_filed(client: AsyncClient):
    """The rule that matters: if they are here, you ask. You do not keep a copy of them."""
    owner, tok = await signup(client)
    member, _ = await signup(client, email="both@example.com", name="유지수")
    await _visitor(owner["id"], name="유지수", email="both@example.com", turns=9)
    pid = await _propose(owner["id"], kind="person", name="유지수")   # no address in the payload
    items = (await client.get("/api/network/proposals", headers=auth(tok))).json()["items"]
    assert items[0]["resolved"]["action"] == "connect"
    assert items[0]["resolved"]["person"]["id"] == member["id"]
    assert (await client.post(f"/api/network/proposals/{pid}/accept", headers=auth(tok))).json()["did"] == "connect"


async def test_connecting_reaches_the_other_persons_inbox(client: AsyncClient):
    """Somebody choosing you is news about you, and it says whether that made you 인맥."""
    a_user, a_tok = await signup(client, name="가온")
    b_user, b_tok = await signup(client, name="나윤")

    await client.post(f"/api/network/people/{b_user['id']}/follow", headers=auth(a_tok))
    box = (await client.get("/api/inbox", params={"source": "people"}, headers=auth(b_tok))).json()
    assert [i["kind"] for i in box["items"]] == ["person_follow"], box
    told = box["items"][0]
    assert told["payload"]["actor_id"] == a_user["id"] and told["payload"]["actor_name"] == "가온"
    assert told["payload"]["mutual"] is False and told["status"] == "new"
    # The person who connected hears nothing, and it is not filed under a secretary.
    assert (await client.get("/api/inbox", params={"source": "people"}, headers=auth(a_tok))).json()["items"] == []
    assert (await client.get("/api/inbox", params={"source": "agent"}, headers=auth(b_tok))).json()["items"] == []

    # Answering tells the first one, and says it is 인맥 now.
    await client.post(f"/api/network/people/{a_user['id']}/follow", headers=auth(b_tok))
    back = (await client.get("/api/inbox", params={"source": "people"}, headers=auth(a_tok))).json()["items"]
    assert [i["kind"] for i in back] == ["person_follow"]
    assert back[0]["payload"]["actor_name"] == "나윤" and back[0]["payload"]["mutual"] is True


# ── two switches about my own people (plan/43 §5) ───────────────────

async def test_who_may_see_the_people_i_am_connected_to(client: AsyncClient):
    """Open by default: this is a place for people who want to be found."""
    me, my_tok = await signup(client)
    friend, f_tok = await signup(client, name="아는이")
    onlooker, o_tok = await signup(client)
    await client.post(f"/api/network/people/{friend['id']}/follow", headers=auth(my_tok))
    await client.post(f"/api/network/people/{me['id']}/follow", headers=auth(f_tok))

    seen = (await client.get(f"/api/network/people/{me['id']}", headers=auth(o_tok))).json()
    assert seen["connections_open"] is True
    assert [x["display_name"] for x in seen["connections_list"]] == ["아는이"]

    assert (await client.patch("/api/users/me", headers=auth(my_tok),
                               json={"network_public": "friends"})).status_code == 200
    closed = (await client.get(f"/api/network/people/{me['id']}", headers=auth(o_tok))).json()
    assert closed["connections_open"] is False and closed["connections_list"] == []
    # 인맥 still see it, and so do I.
    assert (await client.get(f"/api/network/people/{me['id']}", headers=auth(f_tok))).json()["connections_open"] is True
    assert (await client.get(f"/api/network/people/{me['id']}", headers=auth(my_tok))).json()["connections_open"] is True


async def test_the_secretary_always_sees_my_ledger(client: AsyncClient):
    """비서는 내 원장을 전부 본다 (plan/48 §2) — 나와의 대화에서는 모든 기능이 켜져 있다 (plan/57).

    예전에는 [비서에게 인맥 정보 제공] 스위치가 인맥 도구를 통째로 껐고, 비서 설정의
    [지식] 능력이 지식 도구를 껐다. 그 스위치를 끈 사람은 남에게 안 보이게 하려던
    것인데, 실제 효과는 **제 비서만 눈이 머는 것**이었다. 이제 스위치는 외부인 쪽,
    비서의 [지식] 탭에만 있다.
    """
    import uuid as _u

    from blackmoa.db.session import session_scope
    from blackmoa.models import Agent
    from blackmoa.models import User as _User
    from blackmoa.pipeline.tools.base import _allowed, all_tools

    user, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(tok))).json()
    tools = all_tools()

    class Ctx:
        audience = "owner"
        features: set[str] = set()

    async with session_scope() as db:
        ctx = Ctx()
        ctx.owner = await db.get(_User, _u.UUID(user["id"]))
        ctx.agent = await db.get(Agent, _u.UUID(agent["id"]))

        # 나와의 대화에서는 모든 기능이 켜져 있다 (plan/57) — 무엇을 꺼도, 메일 보내기와 웹 검색까지.
        ctx.agent.capabilities = {"voice": False, "leave_message": False, "meeting_request": False}
        ctx.agent.outsider = {"knowledge": "off", "network": "off", "web": False, "profile": False}
        for name in ("network_search", "knowledge_search", "email_send", "web_search", "calendar_availability"):
            assert _allowed(tools[name], ctx) is True, f"{name}: 나와의 대화에 스위치가 살아 있다"

        # 외부인 대화에서는 [지식] 탭이 정한다.
        ctx.audience = "visitor"
        ctx.relay_id = None
        for name in ("network_search", "knowledge_search", "web_search"):
            assert _allowed(tools[name], ctx) is False, f"{name}: 꺼 둔 줄이 외부인에게 열려 있다"
        assert _allowed(tools["email_send"], ctx) is False, "메일 보내기는 나와의 대화 전용이다"
        ctx.agent.outsider = {"knowledge": "known", "network": "public", "web": True}
        for name in ("network_search", "knowledge_search", "web_search"):
            assert _allowed(tools[name], ctx) is True, name
        # 외부인 대화에서 하는 일은 스튜디오의 능력이 정한다.
        assert _allowed(tools["leave_message"], ctx) is False
        ctx.agent.capabilities = {"leave_message": True}
        assert _allowed(tools["leave_message"], ctx) is True


async def test_field_visibility_has_one_source(client: AsyncClient):
    """칸이 어디까지 나가는지는 [내 정보] 하나가 정한다 (plan/48 §2).

    예전에는 비서의 `disclosure_policy.profile_fields` 가 두 번째로 답했다. 주인이
    안 정한 칸을 비서가 정했고, 기본값 표가 둘이라 `location` 이 한쪽은 공개
    한쪽은 비공개여서 **비서를 만든 사람과 안 만든 사람의 기본값이 달랐다.**
    """
    from blackmoa.models import OwnerProfile
    from blackmoa.services import profile as PF

    prof = OwnerProfile(owner_id=None, data={}, visibility={})
    # 비서가 무슨 말을 해도 칸의 범위는 안 바뀐다. 표에 없는 칸은 비공개다.
    loud = {"profile_fields": {"location": "public", "contact.email": "public", "bio": "private"}}
    assert "location" not in PF.DEFAULT_FIELD_VIS
    assert PF.field_visibility(prof, loud, "location") == "private"
    assert PF.field_visibility(prof, loud, "contact.email") == "private"
    assert PF.field_visibility(prof, loud, "bio") == "public"
    # 주인이 정하면 그것이 전부다.
    prof.visibility = {"bio": "known"}
    assert PF.field_visibility(prof, loud, "bio") == "known"
    # 기본값 표는 하나뿐이다.
    from blackmoa.services.agents import DEFAULT_DISCLOSURE
    assert "profile_fields" not in DEFAULT_DISCLOSURE



async def test_imported_people_hang_off_their_source_and_blackmoa_people_off_me(client):
    """[나] — [Google 연락처] — [가져온 사람], black-moa 인맥은 [나] — [그 사람] (plan/79)."""
    import uuid as _uuid

    from blackmoa.db.session import session_scope
    from blackmoa.models import NetworkNode

    user, tok = await signup(client)
    await client.get("/api/network/graph", headers=auth(tok))          # 나 자신이 생긴다
    async with session_scope() as db:
        for i in range(3):
            db.add(NetworkNode(owner_id=_uuid.UUID(user["id"]), kind="person", name=f"연락처{i}", source="google_contacts",
                               external_ref=f"people/c{i}"))
        await db.commit()
    r = await client.post("/api/network/nodes", json={"name": "직접 적은 사람"}, headers=auth(tok))
    assert r.status_code in (200, 201), r.text
    g = (await client.get("/api/network/graph", headers=auth(tok))).json()
    me = g["self_id"]
    hub = next(n for n in g["nodes"] if n["id"] == "source:google_contacts")
    assert hub["kind"] == "source" and hub["attrs"]["count"] == 3 and hub["hops"] == 1
    rels = {(e["src_id"], e["dst_id"]): e["rel"] for e in g["edges"]}
    assert rels[(me, hub["id"])] == "source"
    imported = [n for n in g["nodes"] if n["source"] == "google_contacts" and n["kind"] == "person"]
    assert len(imported) == 3 and all(rels.get((hub["id"], n["id"])) == "imported" and n["hops"] == 2 for n in imported)
    assert not any((me, n["id"]) in rels for n in imported)                   # 나에게 바로 붙지 않는다
    mine = next(n for n in g["nodes"] if n["name"] == "직접 적은 사람")
    assert rels.get((me, mine["id"])) == "network" and mine["hops"] == 1        # black-moa 인맥은 바로
