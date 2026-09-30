"""Proving where you work with a work mailbox (plan/40 §10).

The hard part is not the code in the mail; it is knowing which company an address belongs
to. These tests follow the three answers: the homepage the exchange lists, a choice among
companies sharing a domain, and a proposal for a domain nobody mapped, which an
administrator settles.
"""
from __future__ import annotations

import uuid as _uuid

import pytest
from httpx import AsyncClient

from tests.conftest import auth, signup
from tests.test_company_reviews import answers_body, make_company

_async = pytest.mark.asyncio


@pytest.fixture
def outbox(monkeypatch):
    """The mail the person would receive: we read the code from it like they would."""
    sent: list[dict] = []

    async def fake_send(db, *, to, subject, text, html=None, **kw):
        sent.append({"to": to, "subject": subject, "text": text})

    monkeypatch.setattr("memora.api.company_verify.send_mail", fake_send)
    return sent


def code_of(mail: dict) -> str:
    import re
    return re.search(r"\b(\d{6})\b", mail["text"]).group(1)


async def sync_domains() -> None:
    from memora.db.session import session_scope
    from memora.services.companies.domains import sync_from_homepages

    async with session_scope("worker") as db:
        await sync_from_homepages(db)
        await db.commit()


async def make_admin(user_id: str) -> None:
    from memora.db.session import session_scope
    from memora.models import User

    async with session_scope("worker") as db:
        (await db.get(User, _uuid.UUID(user_id))).role = "admin"
        await db.commit()


def test_a_domain_is_the_part_somebody_registered():
    from memora.services.companies.domains import email_domain, homepage_domain, mask_email, registrable

    assert registrable("www.samsung.com") == "samsung.com"
    assert registrable("mail.sec.samsung.com") == "samsung.com"
    assert registrable("abc.co.kr") == "abc.co.kr" and registrable("mail.abc.co.kr") == "abc.co.kr"
    assert registrable("co.kr") == "co.kr" and registrable("localhost") is None and registrable("10.0.0.1") is None
    assert email_domain("Kim.Chulsoo@HR.Kakaocorp.com") == "kakaocorp.com"
    assert email_domain("not-an-address") is None and email_domain("a@b@c.com") is None
    assert homepage_domain("http://www.samsung.com/sec/") == "samsung.com"
    assert homepage_domain("kakaocorp.com") == "kakaocorp.com"
    assert homepage_domain("https://blog.naver.com/somecorp") is None       # a public host says nothing
    assert homepage_domain("https://somecorp.cafe24.com") is None            # nor does a hosting platform
    assert homepage_domain("") is None
    assert mask_email("chulsoo@abc.co.kr") == "c******@abc.co.kr"


@_async
async def test_the_homepage_domain_proves_the_company_end_to_end(client: AsyncClient, outbox):
    """One company at the address's domain: the code alone finishes it. The profile,
    the dashboard, the review badge and the detail page all read the same fact."""
    tag = _uuid.uuid4().hex[:8]
    cid = await make_company("인증전자", homepage=f"https://www.v{tag}.co.kr/ir")
    await sync_domains()
    user, tok = await signup(client)

    r = await client.post("/api/users/me/company/start", json={"email": f"Chulsoo@mail.v{tag}.co.kr"}, headers=auth(tok))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["state"] == "code_sent" and j["domain"] == f"v{tag}.co.kr" and j["email_masked"].startswith("c***")
    assert [c["id"] for c in j["candidates"]] == [cid]
    assert outbox and outbox[0]["to"] == f"chulsoo@mail.v{tag}.co.kr" and code_of(outbox[0]) in outbox[0]["subject"]

    r = await client.post("/api/users/me/company/confirm", json={"code": code_of(outbox[0])}, headers=auth(tok))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["state"] == "verified" and j["company"]["id"] == cid and j["mapping"] == "confirmed" and j["verified_at"]

    prof = (await client.get("/api/users/me/profile", headers=auth(tok))).json()
    assert prof["data"]["company_id"] == cid and prof["data"]["company_verified_at"] and prof["data"]["company"].startswith("인증전자")

    home = (await client.get("/api/community/companies/home", headers=auth(tok))).json()
    assert home["my_company"]["verified"] is True and home["my_company"]["company"]["id"] == cid

    r = await client.post(f"/api/community/companies/{cid}/reviews", json=answers_body(), headers=auth(tok))
    assert r.status_code == 201, r.text
    assert r.json()["review"]["verified"] is True and r.json()["stats"]["verified_n"] == 1
    d = (await client.get(f"/api/community/companies/{cid}", headers=auth(tok))).json()
    assert d["my_verified"] is True and d["stats"]["verified_n"] == 1
    lst = (await client.get(f"/api/community/companies/{cid}/reviews", headers=auth(tok))).json()
    assert lst["items"][0]["verified"] is True

    # Letting go clears the profile and the review keeps the badge it earned.
    assert (await client.delete("/api/users/me/company", headers=auth(tok))).status_code == 200
    j = (await client.get("/api/users/me/company", headers=auth(tok))).json()
    assert j["state"] == "none"
    prof = (await client.get("/api/users/me/profile", headers=auth(tok))).json()
    assert not prof["data"].get("company_id") and not prof["data"].get("company_verified_at")
    # A plain profile edit cannot claim a company it never proved.
    r = await client.put("/api/users/me/profile", json={"data": {"company_id": cid, "company_verified_at": "2026-01-01T00:00:00+00:00"}}, headers=auth(tok))
    assert r.status_code == 200 and not r.json()["data"].get("company_id")


@_async
async def test_personal_mail_wrong_codes_and_a_reused_mailbox_are_refused(client: AsyncClient, outbox):
    tag = _uuid.uuid4().hex[:8]
    cid = await make_company("인증상사", homepage=f"http://w{tag}.com")
    await sync_domains()
    _, tok = await signup(client)

    r = await client.post("/api/users/me/company/start", json={"email": "someone@gmail.com"}, headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "free_mail", r.text
    r = await client.post("/api/users/me/company/start", json={"email": "nonsense"}, headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_email"
    r = await client.post("/api/users/me/company/confirm", json={"code": "000000"}, headers=auth(tok))
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_pending_verification"

    r = await client.post("/api/users/me/company/start", json={"email": f"lee@w{tag}.com"}, headers=auth(tok))
    assert r.status_code == 200, r.text
    code = code_of(outbox[-1])
    wrong = "000000" if code != "000000" else "111111"
    r = await client.post("/api/users/me/company/confirm", json={"code": wrong}, headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_code" and r.json()["error"]["detail"]["attempts_left"] == 4
    r = await client.post("/api/users/me/company/confirm", json={"code": code}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["state"] == "verified" and r.json()["company"]["id"] == cid

    # The same mailbox cannot prove a second account.
    _, tok2 = await signup(client)
    r = await client.post("/api/users/me/company/start", json={"email": f"LEE@w{tag}.com"}, headers=auth(tok2))
    assert r.status_code == 409 and r.json()["error"]["code"] == "company_email_taken", r.text


@_async
async def test_a_shared_domain_asks_which_company(client: AsyncClient, outbox):
    """A group's subsidiaries share a domain: the code alone is not enough, the person
    picks one of the companies known there."""
    tag = _uuid.uuid4().hex[:8]
    a = await make_company("그룹전자", homepage=f"https://www.g{tag}.com/electronics")
    b = await make_company("그룹물산", homepage=f"https://ct.g{tag}.com")
    await sync_domains()
    _, tok = await signup(client)
    r = await client.post("/api/users/me/company/start", json={"email": f"park@g{tag}.com"}, headers=auth(tok))
    assert r.status_code == 200 and {c["id"] for c in r.json()["candidates"]} == {a, b}
    # Reopened before the code is typed, the card still knows who shares the domain.
    j = (await client.get("/api/users/me/company", headers=auth(tok))).json()
    assert j["state"] == "code_sent" and {c["id"] for c in j["candidates"]} == {a, b}
    r = await client.post("/api/users/me/company/confirm", json={"code": code_of(outbox[-1])}, headers=auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "choose" and {c["id"] for c in r.json()["candidates"]} == {a, b}
    # The code is spent once: coming back later still asks for the company, not the code.
    j = (await client.get("/api/users/me/company", headers=auth(tok))).json()
    assert j["state"] == "choose" and len(j["candidates"]) == 2
    r = await client.post("/api/users/me/company/confirm", json={"company_id": b}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["state"] == "verified" and r.json()["company"]["id"] == b
    assert r.json()["mapping"] == "confirmed"


@_async
async def test_an_unmapped_domain_becomes_a_proposal_an_administrator_settles(client: AsyncClient, outbox):
    """Nobody mapped the domain: the person names the company. They are verified for
    themselves, but the badge waits until the directory stands behind the mapping."""
    tag = _uuid.uuid4().hex[:8]
    cid = await make_company("무명기업", homepage="")
    _, tok = await signup(client)
    r = await client.post("/api/users/me/company/start", json={"email": f"choi@n{tag}.co.kr"}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["candidates"] == []
    r = await client.post("/api/users/me/company/confirm", json={"code": code_of(outbox[-1])}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["state"] == "propose", r.text
    r = await client.post("/api/users/me/company/confirm", json={"company_id": cid}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["state"] == "verified" and r.json()["mapping"] == "pending", r.text

    r = await client.post(f"/api/community/companies/{cid}/reviews", json=answers_body(), headers=auth(tok))
    assert r.status_code == 201 and r.json()["review"]["verified"] is False

    admin, atok = await signup(client)
    await make_admin(admin["id"])
    claims = (await client.get("/api/admin/companies/domain-claims", headers=auth(atok))).json()["items"]
    mine = [c for c in claims if c["company_id"] == cid]
    assert len(mine) == 1 and mine[0]["domain"] == f"n{tag}.co.kr" and mine[0]["claims"] == 1
    r = await client.post(f"/api/admin/companies/domain-claims/{mine[0]['id']}/approve", headers=auth(atok))
    assert r.status_code == 200
    doms = (await client.get(f"/api/admin/companies/{cid}/domains", headers=auth(atok))).json()["items"]
    assert doms[0]["status"] == "confirmed" and doms[0]["source"] == "admin"
    j = (await client.get("/api/users/me/company", headers=auth(tok))).json()
    assert j["state"] == "verified" and j["mapping"] == "confirmed"
    # Re-saving the review now earns the badge.
    r = await client.post(f"/api/community/companies/{cid}/reviews", json=answers_body(), headers=auth(tok))
    assert r.status_code == 201 and r.json()["review"]["verified"] is True

    # An administrator can add a domain by hand, and a personal-mail domain is refused.
    r = await client.post(f"/api/admin/companies/{cid}/domains", json={"domain": f"@Mail.N{tag}-Group.com"}, headers=auth(atok))
    assert r.status_code == 201 and r.json()["domain"] == f"n{tag}-group.com"
    r = await client.post(f"/api/admin/companies/{cid}/domains", json={"domain": "naver.com"}, headers=auth(atok))
    assert r.status_code == 422
    r = await client.delete(f"/api/admin/companies/{cid}/domains/{doms[0]['id']}", headers=auth(atok))
    assert r.status_code == 200
    doms = (await client.get(f"/api/admin/companies/{cid}/domains", headers=auth(atok))).json()["items"]
    assert [d["domain"] for d in doms] == [f"n{tag}-group.com"]
