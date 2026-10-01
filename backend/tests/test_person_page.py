"""The public page a person has at /@handle (plan/41 §3).

The page is the front door of the house: anyone can read it, it carries only what its
owner published, and it opens onto their secretary.
"""
from __future__ import annotations

import uuid as _uuid

from httpx import AsyncClient

from blackmoa.db.session import session_scope
from blackmoa.models import Agent, ShareLink, User
from tests.conftest import auth, signup


async def _handle(user_id: str, handle: str) -> None:
    async with session_scope() as db:
        u = await db.get(User, _uuid.UUID(user_id))
        u.mail_handle = handle
        await db.commit()


async def _publish(user_id: str, *, code: str, name: str = "지니", status: str = "active") -> str:
    async with session_scope() as db:
        a = Agent(owner_id=_uuid.UUID(user_id), name=name, provider="fake", model_id="fake-1",
                  role_line="일정과 메시지를 맡아요", greeting="안녕하세요")
        db.add(a)
        await db.flush()
        db.add(ShareLink(owner_id=_uuid.UUID(user_id), agent_id=a.id, code=code, status=status))
        await db.commit()
        return str(a.id)


async def test_anyone_can_read_the_page_and_reach_the_secretary(client: AsyncClient):
    user, tok = await signup(client, name="장하람")
    tag = _uuid.uuid4().hex[:6]
    await _handle(user["id"], f"haram{tag}")
    await _publish(user["id"], code=f"door{tag}")
    await client.put("/api/users/me/profile", headers=auth(tok), json={
        "data": {"title": "백엔드 개발자", "company": "블랙모아", "bio": "서버를 만듭니다", "location": "서울"},
        "visibility": {"title": "public", "company": "public", "bio": "public", "location": "private"}})

    # No token at all: this is the whole point of the page.
    r = await client.get(f"/api/public/people/haram{tag}")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["handle"] == f"haram{tag}" and j["display_name"]
    assert j["fields"]["title"] == "백엔드 개발자" and j["fields"]["company"] == "블랙모아"
    # A field they kept private stays private on a page the whole internet can read.
    assert "location" not in j["fields"]
    assert j["secretary"]["name"] == "지니" and j["secretary"]["code"] == f"door{tag}"
    assert j["secretary"]["status"] == "active" and j["account"]["signed_in"] is False

    # The address is not case-sensitive: people type it off a business card.
    assert (await client.get(f"/api/public/people/HARAM{tag}")).status_code == 200
    assert (await client.get(f"/api/public/people/@haram{tag}")).status_code == 200


async def test_a_page_needs_an_address_and_a_published_secretary(client: AsyncClient):
    """Two choices make the page: claiming a handle and publishing a secretary. Neither is
    made on the person's behalf."""
    assert (await client.get("/api/public/people/nobody-here")).status_code == 404

    user, _ = await signup(client)
    tag = _uuid.uuid4().hex[:6]
    await _handle(user["id"], f"quiet{tag}")
    # A handle with nothing published is not a page.
    r = await client.get(f"/api/public/people/quiet{tag}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "page_not_open"

    # A revoked link does not open one either.
    await _publish(user["id"], code=f"gone{tag}", status="revoked")
    assert (await client.get(f"/api/public/people/quiet{tag}")).status_code == 404


async def test_the_page_shows_the_secretary_that_was_published_first(client: AsyncClient):
    """Several links, one front door: the oldest active one, so the address does not move
    under somebody who printed it."""
    user, _ = await signup(client)
    tag = _uuid.uuid4().hex[:6]
    await _handle(user["id"], f"many{tag}")
    await _publish(user["id"], code=f"first{tag}", name="첫비서")
    await _publish(user["id"], code=f"second{tag}", name="둘째비서")
    j = (await client.get(f"/api/public/people/many{tag}")).json()
    assert j["secretary"]["name"] == "첫비서" and j["secretary"]["code"] == f"first{tag}"


async def test_the_owner_reading_their_own_page_is_told_so(client: AsyncClient):
    user, tok = await signup(client)
    tag = _uuid.uuid4().hex[:6]
    await _handle(user["id"], f"mine{tag}")
    await _publish(user["id"], code=f"mine{tag}")
    j = (await client.get(f"/api/public/people/mine{tag}", headers=auth(tok))).json()
    assert j["account"] == {"signed_in": True, "is_owner": True}


async def test_a_person_decides_whether_search_engines_list_their_page(client: AsyncClient):
    """Readable by anyone with the address either way. Being listed is the part they agree to."""
    user, tok = await signup(client)
    tag = _uuid.uuid4().hex[:6]
    handle = f"listed{tag}"
    await _handle(user["id"], handle)
    await _publish(user["id"], code=f"door{tag}")

    r = await client.get(f"/api/public/people/{handle}")
    assert r.status_code == 200 and r.json()["indexable"] is True
    assert (await client.get("/api/public/sitemap")).json()["people"], "an open page should be listed"

    assert (await client.patch("/api/users/me", headers=auth(tok), json={"page_indexable": False})).status_code == 200
    r = await client.get(f"/api/public/people/{handle}")
    assert r.status_code == 200 and r.json()["indexable"] is False, "the page must still open"
    listed = [p["handle"] for p in (await client.get("/api/public/sitemap")).json()["people"]]
    assert handle not in listed
