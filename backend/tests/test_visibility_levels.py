"""Three levels of공개, and who counts as known (plan/41 §8).

The middle level is the point: a connection, or somebody who proved the same employer,
should hear more than a stranger and less than the owner. Prompt wording cannot be what
enforces that, so these tests check the rendered profile and the redactor's list.
"""
from __future__ import annotations

import uuid as _uuid

from httpx import AsyncClient

from blackmoa.db.session import session_scope
from blackmoa.models import OwnerProfile
from blackmoa.services import people as P
from blackmoa.services import profile as PF
from tests.conftest import auth, signup
from tests.test_blog import _open_page


def test_a_level_decides_who_may_read_it():
    assert PF.visible_to("public", "stranger") and PF.visible_to("public", "known")
    assert not PF.visible_to("known", "stranger")
    assert PF.visible_to("known", "known") and PF.visible_to("known", "owner")
    assert not PF.visible_to("private", "stranger") and not PF.visible_to("private", "known")
    assert PF.visible_to("private", "owner")
    # Anything unrecognised is private, never public by accident.
    assert PF.normalize_visibility("on_request") == "private" and PF.normalize_visibility("nonsense") == "private"
    assert PF.normalize_visibility("known") == "known"


async def _prof(user_id: str) -> OwnerProfile:
    async with session_scope() as db:
        return await PF.get(db, _uuid.UUID(user_id))


async def test_the_secretary_says_more_to_somebody_you_know(client: AsyncClient):
    user, tok = await signup(client)
    await client.put("/api/users/me/profile", headers=auth(tok), json={
        "data": {"title": "백엔드 개발자", "location": "서울 광진구", "bio": "비밀 일기"},
        "visibility": {"title": "public", "location": "known", "bio": "private"}})
    prof = await _prof(user["id"])

    stranger = PF.render_profile(prof, {}, "visitor", viewer="stranger")
    known = PF.render_profile(prof, {}, "visitor", viewer="known")
    owner = PF.render_profile(prof, {}, "owner", viewer="owner")
    assert "백엔드 개발자" in stranger and "광진구" not in stranger and "비밀 일기" not in stranger
    assert "광진구" in known and "비밀 일기" not in known
    assert "광진구" in owner and "비밀 일기" in owner

    # And the redactor agrees: what a stranger may not read is masked even if the model
    # writes it anyway; for the person they know, it is not.
    assert any("광진구" in x for x in PF.private_literals(prof, {}, viewer="stranger"))
    assert not any("광진구" in x for x in PF.private_literals(prof, {}, viewer="known"))
    assert any("비밀 일기" in x for x in PF.private_literals(prof, {}, viewer="known"))


async def test_a_connection_and_a_verified_colleague_are_known(client: AsyncClient):
    me, mytok = await signup(client)
    friend, ftok = await signup(client)
    stranger, _ = await signup(client)

    async with session_scope() as db:
        assert await P.viewer_level(db, _uuid.UUID(me["id"]), None) == "stranger"
        assert await P.viewer_level(db, _uuid.UUID(me["id"]), _uuid.UUID(me["id"])) == "owner"
        assert await P.viewer_level(db, _uuid.UUID(me["id"]), _uuid.UUID(stranger["id"])) == "stranger"

    # 인맥: each of them connects to the other (plan/43).
    await client.post(f"/api/network/people/{friend['id']}/follow", headers=auth(mytok))
    await client.post(f"/api/network/people/{me['id']}/follow", headers=auth(ftok))
    async with session_scope() as db:
        assert await P.viewer_level(db, _uuid.UUID(me["id"]), _uuid.UUID(friend["id"])) == "known"

    # A colleague nobody connected with, proven by the same company, is known too.
    colleague, _ = await signup(client)
    async with session_scope() as db:
        from blackmoa.models import Company, CompanyDomain, CompanyVerification
        from blackmoa.services.companies.merge import normalise_name
        c = Company(name=f"같은회사{_uuid.uuid4().hex[:5]}", name_norm=normalise_name("같은회사"), market="코스닥")
        db.add(c)
        await db.flush()
        db.add(CompanyDomain(domain=f"same{_uuid.uuid4().hex[:5]}.com", company_id=c.id, source="admin", status="confirmed"))
        for uid in (me["id"], colleague["id"]):
            db.add(CompanyVerification(user_id=_uuid.UUID(uid), company_id=c.id, domain="same.com",
                                       email_hash=_uuid.uuid4().hex, code_hash="x",
                                       code_expires_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                                       status="verified"))
        await db.commit()
    async with session_scope() as db:
        assert await P.viewer_level(db, _uuid.UUID(me["id"]), _uuid.UUID(colleague["id"])) == "known"


async def test_the_public_page_shows_a_stranger_less_than_a_connection(client: AsyncClient):
    owner, otok = await signup(client)
    friend, ftok = await signup(client)
    tag = _uuid.uuid4().hex[:5]
    await _open_page(owner["id"], f"lv{tag}")
    await client.put("/api/users/me/profile", headers=auth(otok), json={
        "data": {"title": "디자이너", "location": "부산"},
        "visibility": {"title": "public", "location": "known"}})

    anon = (await client.get(f"/api/public/people/lv{tag}")).json()["fields"]
    assert anon.get("title") == "디자이너" and "location" not in anon
    signed_in = (await client.get(f"/api/public/people/lv{tag}", headers=auth(ftok))).json()["fields"]
    assert "location" not in signed_in, "an account is not a relationship"

    # 인맥: each of them connects to the other (plan/43).
    await client.post(f"/api/network/people/{friend['id']}/follow", headers=auth(otok))
    await client.post(f"/api/network/people/{owner['id']}/follow", headers=auth(ftok))
    now_known = (await client.get(f"/api/public/people/lv{tag}", headers=auth(ftok))).json()["fields"]
    assert now_known.get("location") == "부산"


async def test_a_conversation_really_is_held_at_the_visitors_level(client: AsyncClient):
    """The levels are only worth something if the live conversation uses them.

    Everything above tests the rules. This runs a real visitor turn through the pipeline
    twice — once as a stranger, once as somebody the owner accepted — and reads back what
    the redactor was told to mask each time.
    """
    import uuid as _uuid

    from blackmoa.pipeline.runtime import runtime_key, runtimes
    from tests.conftest import read_sse

    me, mytok = await signup(client)
    await client.put("/api/users/me/profile", headers=auth(mytok), json={
        "data": {"title": "백엔드 개발자", "location": "서울 광진구"},
        "visibility": {"title": "public", "location": "known"}})
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(mytok))).json()
    code = (await client.post(f"/api/agents/{agent['id']}/links", json={}, headers=auth(mytok))).json()["code"]

    async def talk(headers: dict[str, str] | None) -> object:
        v = (await client.post(f"/api/public/links/{code}/visitor", json={}, headers=headers or {})).json()
        cid = v["conversation_id"]
        async with client.stream("POST", f"/api/public/conversations/{cid}/turns",
                                 json={"text": "안녕하세요"}, headers=auth(v["visitor_token"])) as r:
            await read_sse(r)
        rt = runtimes._items.get(runtime_key(_uuid.UUID(agent["id"]), "visitor", _uuid.UUID(cid)))
        assert rt is not None
        return rt.ctx

    stranger_ctx = await talk(None)
    assert stranger_ctx.viewer_level == "stranger"
    assert any("광진구" in x for x in stranger_ctx.private_literals)

    friend, ftok = await signup(client)
    # 인맥: each of them connects to the other (plan/43).
    await client.post(f"/api/network/people/{friend['id']}/follow", headers=auth(mytok))
    await client.post(f"/api/network/people/{me['id']}/follow", headers=auth(ftok))

    friend_ctx = await talk(auth(ftok))
    assert friend_ctx.viewer_level == "known", "an accepted connection is still being treated as a stranger"
    assert not any("광진구" in x for x in friend_ctx.private_literals)
