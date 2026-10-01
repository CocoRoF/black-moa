from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import auth, read_sse, signup

pytestmark = pytest.mark.asyncio


async def test_owner_turn_and_credits(client: AsyncClient):
    user, tok = await signup(client, name="한지민")
    r = await client.post("/api/agents", json={"name": "지니", "role_line": "한지민의 업무 비서"}, headers=auth(tok))
    assert r.status_code == 201, r.text
    agent = r.json()
    assert agent["provider"] == "fake"
    bal0 = (await client.get("/api/credits/balance", headers=auth(tok))).json()["balance"]
    conv = (await client.post(f"/api/agents/{agent['id']}/conversations", json={}, headers=auth(tok))).json()
    async with client.stream("POST", f"/api/agents/{agent['id']}/conversations/{conv['id']}/turns", json={"text": "안녕! 나는 커피를 좋아해."}, headers=auth(tok)) as resp:
        assert resp.status_code == 200
        turn_id = resp.headers["x-turn-id"]
        events = await read_sse(resp)
    types = [e["type"] for e in events]
    assert types[0] == "turn.start"
    assert "text.delta" in types
    assert types[-1] == "turn.complete", types
    answer = "".join(e["data"]["text"] for e in events if e["type"] == "text.delta")
    assert "[owner]" in answer
    usage = next(e for e in events if e["type"] == "usage")["data"]
    assert usage["credits"] > 0
    bal1 = (await client.get("/api/credits/balance", headers=auth(tok))).json()["balance"]
    assert bal1 < bal0
    msgs = (await client.get(f"/api/agents/{agent['id']}/conversations/{conv['id']}/messages", headers=auth(tok))).json()["items"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    events2 = []
    async with client.stream("GET", f"/api/agents/{agent['id']}/turns/{turn_id}/events?after=0", headers=auth(tok)) as resp:
        events2 = await read_sse(resp)
    assert events2[-1]["type"] == "turn.complete"
    async with client.stream("POST", f"/api/agents/{agent['id']}/conversations/{conv['id']}/turns", json={"text": "기억 저장해줘 [[tool:memory_remember {\"title\":\"커피\",\"body\":\"오너는 커피를 좋아한다\"}]]"}, headers=auth(tok)) as resp:
        events = await read_sse(resp)
    types = [e["type"] for e in events]
    assert "tool.start" in types and "tool.end" in types and types[-1] == "turn.complete", types
    tool_ev = next(e for e in events if e["type"] == "tool.start")
    assert tool_ev["data"]["name"] == "memory_remember"
    notes = (await client.get(f"/api/agents/{agent['id']}/memory/owner/notes", headers=auth(tok))).json()["items"]
    assert any("커피" in n["title"] for n in notes)


async def test_share_link_visitor_flow_and_scoping(client: AsyncClient):
    user, tok = await signup(client, name="박서준")
    await client.put("/api/users/me/profile", json={"data": {"full_name": "박서준", "title": "CTO", "contact": {"phone": "010-1234-5678", "email": "seo@corp.com"}},
                                                  "visibility": {"contact.phone": "private"}}, headers=auth(tok))
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(tok))).json()
    owner_tools = {t["name"] for t in (await client.get(f"/api/agents/{agent['id']}/tools?audience=owner", headers=auth(tok))).json()["tools"]}
    visitor_tools = {t["name"] for t in (await client.get(f"/api/agents/{agent['id']}/tools?audience=visitor", headers=auth(tok))).json()["tools"]}
    assert "memory_remember" in owner_tools and "memory_remember" not in visitor_tools
    assert "email_search" not in visitor_tools and "profile_update" not in visitor_tools
    assert "leave_message" in visitor_tools and "leave_message" not in owner_tools
    link = (await client.post(f"/api/agents/{agent['id']}/links", json={"label": "명함"}, headers=auth(tok))).json()
    assert len(link["code"]) == 8
    bad = await client.post(f"/api/agents/{agent['id']}/links", json={"handle": "admin"}, headers=auth(tok))
    assert bad.status_code == 422
    pub = (await client.get(f"/api/public/links/{link['code']}")).json()
    assert pub["agent"]["name"] == "서기" and pub["link"]["status"] == "active"
    v = (await client.post(f"/api/public/links/{link['code']}/visitor", json={})).json()
    vtok, cid = v["visitor_token"], v["conversation_id"]
    assert (await client.get("/api/agents", headers=auth(vtok))).status_code == 401
    async with client.stream("POST", f"/api/public/conversations/{cid}/turns", json={"text": "안녕하세요, 서준님 계신가요?"}, headers=auth(vtok)) as resp:
        assert resp.status_code == 200
        events = await read_sse(resp)
    types = [e["type"] for e in events]
    assert types[-1] == "turn.complete", types
    assert "usage" not in types  # hidden from visitors
    assert "text.delta" in types  # visitors stream live (plan/12), sanitized at the source
    assert "[visitor]" in events[-1]["data"]["answer"]
    async with client.stream("POST", f"/api/public/conversations/{cid}/turns", json={"text": "메시지 남길게요 [[tool:leave_message {\"message\":\"연락 주세요\",\"visitor_name\":\"김민수\",\"contact\":\"minsu@x.com\"}]]"}, headers=auth(vtok)) as resp:
        events = await read_sse(resp)
    assert any(e["type"] == "card" and e["data"]["card_type"] == "leave_message" for e in events), [e["type"] for e in events]
    inbox = (await client.get("/api/inbox", headers=auth(tok))).json()
    assert inbox["new_count"] >= 1 and inbox["items"][0]["kind"] == "message"
    assert inbox["items"][0]["payload"]["visitor_name"] == "김민수"
    async with client.stream("POST", f"/api/public/conversations/{cid}/turns", json={"text": "[[tool:memory_remember {\"title\":\"x\",\"body\":\"y\"}]]"}, headers=auth(vtok)) as resp:
        events = await read_sse(resp)
    assert not any(e["type"] == "tool.start" and e["data"]["name"] == "memory_remember" for e in events)
    item = (await client.get(f"/api/inbox/{inbox['items'][0]['id']}", headers=auth(tok))).json()
    assert item["conversation"] and item["visitor"]["display_name"] == "김민수"


async def test_cross_user_isolation(client: AsyncClient):
    u1, t1 = await signup(client)
    u2, t2 = await signup(client)
    a1 = (await client.post("/api/agents", json={"name": "A"}, headers=auth(t1))).json()
    assert (await client.get(f"/api/agents/{a1['id']}", headers=auth(t2))).status_code == 404
    assert (await client.patch(f"/api/agents/{a1['id']}", json={"name": "hack"}, headers=auth(t2))).status_code == 404
    assert (await client.get(f"/api/agents/{a1['id']}/conversations", headers=auth(t2))).status_code == 404
    assert (await client.delete(f"/api/agents/{a1['id']}", headers=auth(t2))).status_code == 404


async def test_refresh_rotation_and_reuse_detection(client: AsyncClient):
    """Rotation, and the line between a racing client and a stolen token.

    This used to require that *any* replay of a rotated token revoked the whole family. It
    is the right answer to theft and the wrong one to the ordinary case — a reload while a
    refresh is in flight, a second tab, a component mounting twice — which sends the same
    cookie twice and was signing real people out of every device. So the line is now drawn
    by time: within the grace window it is the race, outside it is theft.
    """
    from blackmoa.services import accounts as A

    u, tok = await signup(client)
    cookie = client.cookies.get("blackmoa_refresh")
    assert cookie
    r1 = await client.post("/api/auth/refresh")
    assert r1.status_code == 200
    new_cookie = client.cookies.get("blackmoa_refresh")
    assert new_cookie != cookie, "the token did not rotate"

    # the racing twin, arriving right behind its replacement
    client.cookies.set("blackmoa_refresh", cookie, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 200

    # the same replay, once the race is over
    grace, A.REFRESH_GRACE_S = A.REFRESH_GRACE_S, 0.0
    try:
        client.cookies.set("blackmoa_refresh", cookie, path="/api/auth")
        assert (await client.post("/api/auth/refresh")).status_code == 401
    finally:
        A.REFRESH_GRACE_S = grace

    # …and the family went with it: every sibling token is dead too
    client.cookies.set("blackmoa_refresh", new_cookie, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_a_session_from_before_the_rename_still_refreshes(client: AsyncClient):
    """The cookie was renamed on 2026-09-09. Reading the old name is what keeps every
    already-signed-in browser signed in; without it the rename is a silent mass logout."""
    await signup(client)
    legacy = client.cookies.get("blackmoa_refresh")
    client.cookies.clear()
    client.cookies.set("mfsg_refresh", legacy, path="/api/auth")

    r = await client.post("/api/auth/refresh")
    assert r.status_code == 200, r.text
    # ...and the session comes back under the new name, so the fallback is needed once.
    assert client.cookies.get("blackmoa_refresh")


async def test_a_share_link_lives_under_its_own_prefix(client: AsyncClient):
    """Codes used to sit at the root, competing with the app's own pages for one namespace.

    A new top-level route could shadow a link somebody had already printed, and the only
    thing standing between them was a hand-kept list of forbidden words.
    """
    from blackmoa.core.codes import LINK_PREFIX

    _user, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(tok))).json()
    link = (await client.post(f"/api/agents/{agent['id']}/links", json={"label": "명함"}, headers=auth(tok))).json()

    assert link["url"].endswith(f"/{LINK_PREFIX}/{link['code']}"), link["url"]
    assert f"/{LINK_PREFIX}/" in link["url"]

    # The installed-app manifest has to be scoped to the same path or the shortcut opens
    # somewhere the link no longer is.
    man = (await client.get(f"/api/public/links/{link['code']}/manifest.webmanifest")).json()
    assert man["start_url"] == f"/{LINK_PREFIX}/{link['code']}"
    assert man["scope"] == f"/{LINK_PREFIX}/{link['code']}"

    # The prefix itself can never be handed out as a code.
    clash = await client.post(f"/api/agents/{agent['id']}/links", json={"handle": LINK_PREFIX}, headers=auth(tok))
    assert clash.status_code == 422, clash.text


async def test_signup_names_reach_the_profile(client: AsyncClient):
    """The form asks for a real name, a nickname and an email. Without seeding, they lived
    only on the account row and the profile page opened blank — asking again for what was
    just typed."""
    email = f"seed{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/api/auth/signup", json={"email": email, "password": "Passw0rd!23",
                                                    "display_name": "장하렴", "nickname": "하렴님", "agree_terms": True})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]

    profile = (await client.get("/api/users/me/profile", headers=auth(tok))).json()["data"]
    assert profile["full_name"] == "장하렴"
    assert profile["preferred_name"] == "하렴님"
    assert profile["contact"]["email"] == email

    # Seeding never overwrites: an edited profile survives a later seed.
    await client.put("/api/users/me/profile", json={"data": {"preferred_name": "다른이름"}}, headers=auth(tok))
    from blackmoa.db.session import session_scope
    from blackmoa.models import User
    from blackmoa.services import profile as PF
    async with session_scope() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalars().first()
        await PF.seed_from_account(db, u)
        await db.commit()
    again = (await client.get("/api/users/me/profile", headers=auth(tok))).json()["data"]
    assert again["preferred_name"] == "다른이름"


async def test_the_password_rule_the_form_states_is_the_one_enforced(client: AsyncClient):
    """A hint the backend does not check is a lie with extra steps."""
    # Two of upper / lower / digit / symbol, and eight characters.
    for bad in ("Short1!", "abcdefgh", "12345678", "!!!!!!!!", "ABCDEFGH"):
        r = await client.post("/api/auth/signup", json={"email": f"pw{uuid.uuid4().hex[:8]}@example.com",
                                                        "password": bad, "display_name": "x", "agree_terms": True})
        assert r.status_code == 422, (bad, r.status_code)
    for good in ("abcdefg1", "abcdefg!", "12345678!", "ABCDEFGx", "ABCDEFG1"):
        r = await client.post("/api/auth/signup", json={"email": f"pw{uuid.uuid4().hex[:8]}@example.com",
                                                        "password": good, "display_name": "x", "agree_terms": True})
        assert r.status_code == 200, (good, r.text)


async def test_a_new_secretary_can_be_given_its_face_at_creation(client: AsyncClient):
    """The wizard picks a photo and a background before the secretary exists (plan/32).

    Creating without them and patching afterwards would leave a window where the agent is
    live with no face, so both travel with the create call.
    """
    _, tok = await signup(client, name="정해인")
    body = {"name": "하나", "avatar_url": "/presets/secretary-female.png", "cover_url": "/api/public/uploads/abc"}
    a = (await client.post("/api/agents", json=body, headers=auth(tok))).json()
    assert a["avatar_url"] == "/presets/secretary-female.png" and a["cover_url"] == "/api/public/uploads/abc"
    again = (await client.get(f"/api/agents/{a['id']}", headers=auth(tok))).json()
    assert again["avatar_url"] == body["avatar_url"] and again["cover_url"] == body["cover_url"]
    # …and a secretary made without one has neither, rather than an empty string. (A new
    # account, because a plan caps how many secretaries one owner may have.)
    _, tok2 = await signup(client, email="plain@example.com", name="윤아")
    plain = (await client.post("/api/agents", json={"name": "둘"}, headers=auth(tok2))).json()
    assert plain["avatar_url"] is None and plain["cover_url"] is None


async def test_a_plan_narrows_the_pool_it_draws_from(client: AsyncClient):
    """Two dials (plan/33): the catalog says what this install runs, the plan says what
    this plan may use of it. A plan with no picks gets everything."""
    from sqlalchemy import select as _select

    from blackmoa.db.session import session_scope
    from blackmoa.models import ModelCatalog, Plan
    from blackmoa.services import catalog as CAT

    _, tok = await signup(client, name="문가영")
    async with session_scope() as db:
        rows = (await db.execute(_select(ModelCatalog).where(ModelCatalog.enabled.is_(True)))).scalars().all()
        assert len(rows) >= 2, "the fixture install needs at least two models to narrow"
        plan = (await db.execute(_select(Plan).where(Plan.is_default.is_(True)))).scalars().first()
        keep, drop = rows[0], rows[1]
        # no picks → the whole pool
        assert len(await CAT.allowed_for_plan(db, plan)) == len(rows)
        plan.models = [CAT.model_key(keep)]
        await db.commit()

    offered = (await client.get("/api/models", headers=auth(tok))).json()["items"]
    assert [(m["provider"], m["model_id"]) for m in offered] == [(keep.provider, keep.model_id)]

    # …and the save refuses what the picker no longer offers, instead of silently taking it
    a = (await client.post("/api/agents", json={"name": "가영비서"}, headers=auth(tok))).json()
    assert (a["provider"], a["model_id"]) == (keep.provider, keep.model_id)
    r = await client.patch(f"/api/agents/{a['id']}", json={"provider": drop.provider, "model_id": drop.model_id}, headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "model_not_enabled"

    async with session_scope() as db:
        plan = (await db.execute(_select(Plan).where(Plan.is_default.is_(True)))).scalars().first()
        # a plan whose picks all left the pool must not be left with nothing to answer with
        plan.models = ["nowhere:gone"]
        await db.commit()
        assert len(await CAT.allowed_for_plan(db, plan)) == len(rows)
        plan.models = []
        await db.commit()


async def test_a_secretary_carries_its_own_budget(client: AsyncClient):
    """Usage caps belong to the secretary, not the plan (plan/34).

    The account's balance is the limit that always applies; these are the owner's own
    guard rails on one secretary, and a plan no longer carries them at all.
    """
    from blackmoa.models import Plan

    _, tok = await signup(client, name="이도현")
    a = (await client.post("/api/agents", json={"name": "예산"}, headers=auth(tok))).json()
    # shipped defaults: something per turn, nothing per day or month
    assert a["turn_cost_cap_credits"] == 50 and a["daily_credit_cap"] == 0 and a["monthly_credit_cap"] == 0
    # 공개 비서는 울타리를 세운 채로 나온다 (plan/53). 받는 쪽이 내는 구조에서
    # "상한 없음" 기본값은 링크가 퍼지면 잔액이 사라진다는 말과 같다.
    vs = a["visitor_settings"] or {}
    assert vs.get("turns_per_day") == 200 and vs.get("sessions_per_hour") == 30 and vs.get("rate_per_minute") == 10

    patched = (await client.patch(f"/api/agents/{a['id']}", headers=auth(tok),
                                  json={"turn_cost_cap_credits": 12, "daily_credit_cap": 300, "monthly_credit_cap": 4000,
                                        "visitor_settings": {"turns_per_day": 40}})).json()
    assert patched["turn_cost_cap_credits"] == 12 and patched["daily_credit_cap"] == 300
    assert patched["monthly_credit_cap"] == 4000 and patched["visitor_settings"]["turns_per_day"] == 40
    # a turn must always be able to hold something, so 0 per turn is not "unlimited" here
    assert (await client.patch(f"/api/agents/{a['id']}", json={"turn_cost_cap_credits": 0},
                               headers=auth(tok))).json()["turn_cost_cap_credits"] == 1

    # …and the plan no longer speaks about any of it
    assert not hasattr(Plan, "daily_credit_cap") and not hasattr(Plan, "visitor_turns_per_day")
    assert not hasattr(Plan, "max_network_nodes") and not hasattr(Plan, "turn_cost_cap_credits")
    plan_payload = (await client.get("/api/credits/balance", headers=auth(tok))).json()["plan"]
    assert set(plan_payload) == {"code", "name", "monthly_credits", "max_agents", "max_share_links", "max_storage_mb", "features"}


async def test_a_shared_link_card_is_addressed_per_secretary(client: AsyncClient):
    """Every secretary's card has its own address (plan/37).

    Link previews are cached by the image's URL, so two secretaries must never share one —
    and the version has to live in the path, because scrapers are unreliable about query
    strings on og:image.
    """
    _, tok = await signup(client, name="차은우")
    a = (await client.post("/api/agents", json={"name": "하나"}, headers=auth(tok))).json()
    l1 = (await client.post(f"/api/agents/{a['id']}/links", json={"label": "one"}, headers=auth(tok))).json()
    _, tok2 = await signup(client, name="차은석")   # 비서 하나에 링크 하나 (plan/80) — 다른 비서의 것
    b = (await client.post("/api/agents", json={"name": "둘"}, headers=auth(tok2))).json()
    l2 = (await client.post(f"/api/agents/{b['id']}/links", json={"label": "two"}, headers=auth(tok2))).json()
    assert l1["code"] != l2["code"]

    bare = await client.get(f"/api/public/links/{l1['code']}/og.png")
    assert bare.status_code == 200 and bare.headers["content-type"] == "image/png"
    assert "max-age=300" in bare.headers["cache-control"]      # the address old previews hold: let it heal

    versioned = await client.get(f"/api/public/links/{l1['code']}/og-abc123.png")
    assert versioned.status_code == 200 and versioned.content == bare.content
    assert "immutable" in versioned.headers["cache-control"]   # content-addressed: hold it forever

    other = await client.get(f"/api/public/links/{l2['code']}/og-abc123.png")
    assert other.status_code == 200
    assert (await client.get("/api/public/links/nosuchcode/og-abc123.png")).status_code == 404
