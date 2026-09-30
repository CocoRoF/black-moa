"""기업 기능 켜고 끄기 (plan/71).

관리자가 기업 기능을 끄면 기업 페이지·회사 인증이 닫히고, 소속은 어디에도 나가지 않으며 새로 쓰이지도 않는다.
저장된 것은 지우지 않는다 — 다시 켜면 그대로 돌아온다. 화면이 감추는 것은 이 서버가 알려 주는 값을 보고 하는
일이라, 알려 주는 값과 막고 걸러 내는 일을 여기서 고정한다.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest_asyncio
from httpx import AsyncClient

from memora.db.session import session_scope
from tests.conftest import auth, signup
from tests.test_blog import _open_page
from tests.test_company_reviews import make_company


async def _companies(on: bool) -> None:
    from memora.services import settings as S
    async with session_scope() as db:
        await S.put(db, "companies.enabled", on)
        await db.commit()
    S.invalidate("companies.")


@pytest_asyncio.fixture
async def companies_restored(app):
    yield
    await _companies(True)


async def _verify(user_id: str, cid: str) -> None:
    """회사 이메일 인증을 마친 것처럼: 인증 기록과 프로필의 회사."""
    from memora.models import CompanyVerification
    from memora.services import profile as PF
    async with session_scope("worker") as db:
        db.add(CompanyVerification(user_id=_uuid.UUID(user_id), company_id=_uuid.UUID(cid), domain="same.com",
                                   email_hash=_uuid.uuid4().hex, code_hash="x", code_expires_at=datetime.now(UTC),
                                   status="verified"))
        await PF.update(db, _uuid.UUID(user_id), data={"company_id": cid, "company_verified_at": datetime.now(UTC).isoformat(),
                                                       "company_domain": "same.com"}, trusted=True)
        await db.commit()


async def test_companies_are_on_by_default_and_the_status_says_so(client: AsyncClient):
    assert (await client.get("/api/auth/status")).json()["companies"] is True


async def test_turning_companies_off_closes_the_pages_and_verification(client: AsyncClient, companies_restored):
    _, tok = await signup(client)
    cid = await make_company("스위치전자")
    assert (await client.get(f"/api/community/companies/{cid}", headers=auth(tok))).status_code == 200

    await _companies(False)
    assert (await client.get("/api/auth/status")).json()["companies"] is False
    for method, path in [("get", "/api/community/companies"), ("get", "/api/community/companies/home"),
                         ("get", f"/api/community/companies/{cid}"), ("post", f"/api/community/companies/{cid}/follow"),
                         ("get", "/api/users/me/company"), ("post", "/api/users/me/company/start")]:
        kw = {"json": {"email": "a@b.co.kr"}} if method == "post" else {}
        r = await getattr(client, method)(path, headers=auth(tok), **kw)
        assert r.status_code == 403 and r.json()["error"]["code"] == "companies_disabled", (path, r.text)

    await _companies(True)
    assert (await client.get(f"/api/community/companies/{cid}", headers=auth(tok))).status_code == 200


async def test_off_the_company_is_hidden_everywhere_and_cannot_be_entered(client: AsyncClient, companies_restored):
    me, tok = await signup(client)
    other, otok = await signup(client)
    cid = await make_company("소속회사")
    tag = _uuid.uuid4().hex[:8]
    await _open_page(me["id"], f"co{tag}")
    r = await client.put("/api/users/me/profile", headers=auth(tok), json={
        "data": {"title": "백엔드 개발자", "company": "원래회사"}, "visibility": {"company": "public", "title": "public"}})
    assert r.json()["data"]["company"] == "원래회사"
    await _verify(me["id"], cid)

    await _companies(False)
    # 내 정보: 없는 칸이고, 넣어도 저장되지 않는다.
    mine = (await client.get("/api/users/me/profile", headers=auth(tok))).json()
    assert not any(k in mine["data"] for k in ("company", "company_id", "company_verified_at", "company_domain")), mine
    assert "company" not in mine["visibility"]
    r = await client.put("/api/users/me/profile", headers=auth(tok), json={
        "data": {"company": "새회사", "bio": "소개"}, "visibility": {"company": "private"}})
    assert r.status_code == 200 and "company" not in r.json()["data"] and r.json()["data"]["bio"] == "소개"
    # 회원 프로필과 공개 페이지에도 없다.
    prof = (await client.get(f"/api/network/people/{me['id']}", headers=auth(otok))).json()
    assert prof["fields"].get("title") == "백엔드 개발자"
    assert "company" not in prof["fields"] and "company_verified_at" not in prof["fields"], prof["fields"]
    page = (await client.get(f"/api/public/people/co{tag}")).json()
    assert "company" not in page["fields"] and "company_verified_at" not in page["fields"]
    # 광장의 글쓴이 줄에도.
    from memora.services import community as C
    async with session_scope() as db:
        author = (await C.authors_for(db, {_uuid.UUID(me["id"])}, me=None))[_uuid.UUID(me["id"])]
    assert author.job == "백엔드 개발자"

    # 다시 켜면 저장된 그대로 — 끈 동안 넣은 것은 저장되지 않았다.
    await _companies(True)
    mine = (await client.get("/api/users/me/profile", headers=auth(tok))).json()
    assert mine["data"]["company"] == "원래회사" and mine["data"]["company_id"] == cid and mine["visibility"]["company"] == "public"
    prof = (await client.get(f"/api/network/people/{me['id']}", headers=auth(otok))).json()
    assert prof["fields"]["company"] == "원래회사" and prof["fields"]["company_verified_at"]
    async with session_scope() as db:
        author = (await C.authors_for(db, {_uuid.UUID(me["id"])}, me=None))[_uuid.UUID(me["id"])]
    assert author.job == "백엔드 개발자 · 원래회사"


async def test_off_the_secretary_neither_knows_nor_writes_the_company(client: AsyncClient, companies_restored):
    from memora.pipeline.context import TurnContext
    from memora.pipeline.tools.base import tool_names_for
    from memora.pipeline.tools.profile_tools import ProfileGet, ProfileUpdate
    from memora.services import profile as PF

    me, tok = await signup(client)
    await client.put("/api/users/me/profile", headers=auth(tok), json={
        "data": {"title": "기획자", "company": "비밀상사"}, "visibility": {"company": "public"}})
    owner_id = _uuid.UUID(me["id"])

    await _companies(False)
    async with session_scope() as db:
        shown = await PF.shown(db, owner_id)
        stored = await PF.get(db, owner_id)
    assert "비밀상사" not in PF.render_profile(shown, {}, "owner", viewer="owner")
    assert "비밀상사" not in PF.render_profile(shown, {}, "visitor", viewer="stranger")
    assert stored.data["company"] == "비밀상사"          # 보이지 않을 뿐, 지워지지 않았다

    ctx = TurnContext(owner=SimpleNamespace(id=owner_id), agent=None, audience="owner", conversation_id=_uuid.uuid4(),
                      turn_id=None, profile=shown, plan=None, memory=None, visitor=None, features=set())
    got = await ProfileGet(ctx).run({})
    assert "company" not in got["data"]
    out = await ProfileUpdate(ctx).run({"data": {"company": "딴회사", "title": "PM"}})
    assert out["not_saved"] == ["company"] and out["fields"] == ["title"]
    async with session_scope() as db:
        assert (await PF.get(db, owner_id)).data["company"] == "비밀상사"
    # 기업을 찾는 도구도 없다.
    assert "company_lookup" not in tool_names_for(ctx)
    ctx.features = {"feature:companies"}
    assert "company_lookup" in tool_names_for(ctx)


async def test_off_a_colleague_is_a_stranger(client: AsyncClient, companies_restored):
    from memora.services import people as P

    me, _ = await signup(client)
    colleague, _ = await signup(client)
    cid = await make_company("동료회사")
    for u in (me, colleague):
        await _verify(u["id"], cid)
    async with session_scope() as db:
        assert await P.viewer_level(db, _uuid.UUID(me["id"]), _uuid.UUID(colleague["id"])) == "known"

    await _companies(False)
    async with session_scope() as db:
        assert await P.viewer_level(db, _uuid.UUID(me["id"]), _uuid.UUID(colleague["id"])) == "stranger"


async def test_jobs_move_with_companies(client: AsyncClient, companies_restored):
    """채용공고는 기업정보와 함께 켜지고 꺼진다: 목록·집계·등록·마감이 모두 닫히고, 켜면 올린 공고가 그대로다.
    분류표는 프로필의 직무·지역·업종도 쓰므로 열려 있다."""
    _, tok = await signup(client)
    title = f"스위치 공고 {_uuid.uuid4().hex[:6]}"
    r = await client.post("/api/community/jobs", headers=auth(tok), json={
        "title": title, "company": "채용상사", "region_codes": ["11"], "job_codes": ["dev.backend"]})
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    try:
        await _companies(False)
        for method, path, body in [("get", "/api/community/jobs", None), ("get", "/api/community/jobs/facets", None),
                                   ("post", "/api/community/jobs", {"title": "새 공고", "company": "딴회사"}),
                                   ("post", f"/api/community/jobs/{job_id}/close", None)]:
            r = await getattr(client, method)(path, headers=auth(tok), **({"json": body} if body else {}))
            assert r.status_code == 403 and r.json()["error"]["code"] == "companies_disabled", (path, r.text)
        assert (await client.get("/api/community/jobs/taxonomy", headers=auth(tok))).status_code == 200

        await _companies(True)
        jobs = (await client.get("/api/community/jobs", headers=auth(tok))).json()["items"]
        assert any(j["id"] == job_id and j["title"] == title for j in jobs)
    finally:
        await _companies(True)
        await client.post(f"/api/community/jobs/{job_id}/close", headers=auth(tok))


async def test_off_company_notices_leave_the_inbox(client: AsyncClient, companies_restored):
    from memora.services import inbox as I

    me, tok = await signup(client)
    async with session_scope() as db:
        await I.create(db, owner_id=_uuid.UUID(me["id"]), agent_id=None, kind="company_review",
                       payload={"company_id": str(_uuid.uuid4()), "company_name": "소식회사"}, notify=False)
        await db.commit()
    before = (await client.get("/api/inbox", headers=auth(tok))).json()
    assert any(i["kind"] == "company_review" for i in before["items"]) and before["new_count"] >= 1

    await _companies(False)
    after = (await client.get("/api/inbox", headers=auth(tok))).json()
    assert not any(i["kind"] == "company_review" for i in after["items"])
    assert after["new_count"] == before["new_count"] - 1
