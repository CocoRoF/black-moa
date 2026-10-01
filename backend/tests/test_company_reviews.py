"""Company reviews, follows, and the dashboard built from them (plan/40).

Every assertion is about a number a screen shows: the rating on a card, the recommendation
rate in the statistics panel, which company sits on the pay shelf. A review that saves but
leaves the company's numbers stale would pass a "create returns 201" test and still be a
broken product.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from tests.conftest import auth, signup

_async = pytest.mark.asyncio


async def make_company(name: str, *, market: str = "코스닥", industry: str = "소프트웨어 개발업",
                       codes: list[str] | None = None, homepage: str = "https://example.com") -> str:
    from datetime import date

    from blackmoa.db.session import session_scope
    from blackmoa.models import Company
    from blackmoa.services.companies.merge import normalise_name

    tail = _uuid.uuid4().hex[:6]
    async with session_scope("worker") as db:
        # Shaped like a row the exchange collector wrote: the provenance stamp and the
        # listing date are what the coverage panel and the "newly listed" shelf read.
        c = Company(name=f"{name}{tail}", name_norm=normalise_name(f"{name}{tail}"), market=market,
                    stock_code=f"8{_uuid.uuid4().int % 99999:05d}", industry_text=industry,
                    industry_codes=codes or ["it"], region_code="11", region_text="서울특별시",
                    homepage=homepage, ceo="홍길동", listed_on=date.today(),
                    sources={"krx": datetime.now(UTC).isoformat()})
        db.add(c)
        await db.flush()
        cid = str(c.id)
        await db.commit()
    return cid


def review_body(**over) -> dict:
    body = {"employment": "current", "job_code": "dev.backend", "work_year": datetime.now(UTC).year,
            "title": "성장하기 좋은 곳", "pros": "연봉이 업계 평균보다 높고 동료들이 좋아요. 워라밸도 괜찮습니다.",
            "cons": "승진이 느린 편이고 경영진 소통이 아쉽습니다. 야근이 가끔 있어요.",
            "rating": 4, "rating_pay": 5, "rating_balance": 4, "rating_culture": 4, "rating_promotion": 2,
            "rating_management": 3, "recommend": True, "ceo_approval": True, "growth": "up",
            "salary": 6500, "experience_years": 4,
            "interview": {"difficulty": 3, "result": "pass", "questions": "최근 프로젝트에서 어려웠던 점"},
            "benefits": ["bonus", "flex", "meal"]}
    body.update(over)
    return body


@_async
async def test_a_review_changes_the_numbers_a_card_shows(client: AsyncClient):
    """Saving a review must move the company's rating, count, axes, recommendation rate,
    salary median and tags in the same transaction — a stale card is a wrong card."""
    _, tok = await signup(client)
    cid = await make_company("리뷰전자")
    r = await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(), headers=auth(tok))
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["review"]["topics"] and "salary" in j["review"]["topics"], j["review"]["topics"]
    assert j["review"]["family_label"] == "개발" and j["review"]["job_label"] == "백엔드"
    st = j["stats"]
    assert st["n"] == 1 and st["rating"] == 4.0 and st["axes"]["pay"] == 5.0 and st["recommend"] == 100
    assert st["ceo"] == 100 and st["growth"] == 100 and st["salary"]["median"] == 6500
    assert st["interview"]["n"] == 1 and st["interview"]["pass_rate"] == 100
    assert st["benefits"][0]["code"] in ("bonus", "flex", "meal")
    assert st["by_job"]["dev"]["n"] == 1 and st["by_job"]["dev"]["salary"]["median"] == 6500

    d = (await client.get(f"/api/community/companies/{cid}", headers=auth(tok))).json()
    assert d["company"]["rating"] == 4.0 and d["company"]["review_count"] == 1
    assert d["my_review"]["id"] == j["review"]["id"]
    assert str(datetime.now(UTC).year) in d["years"]
    # No name anywhere on the review: the byline is a job family and a status.
    assert "author" not in j["review"] and "author_id" not in j["review"]


@_async
async def test_one_voice_per_person_per_company(client: AsyncClient):
    """A second submission edits the first instead of standing beside it."""
    _, tok = await signup(client)
    cid = await make_company("한목소리")
    a = await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(rating=2, rating_pay=1), headers=auth(tok))
    b = await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(rating=5, rating_pay=5), headers=auth(tok))
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["review"]["id"] == b.json()["review"]["id"]
    assert b.json()["review"]["version"] == 2
    st = b.json()["stats"]
    assert st["n"] == 1 and st["rating"] == 5.0 and st["axes"]["pay"] == 5.0


@_async
async def test_two_reviewers_average_and_the_year_filter_separates_them(client: AsyncClient):
    _, t1 = await signup(client)
    _, t2 = await signup(client)
    cid = await make_company("평균제약")
    year = datetime.now(UTC).year
    await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(rating=5, recommend=True, work_year=year), headers=auth(t1))
    r = await client.post(f"/api/community/companies/{cid}/reviews",
                          json=review_body(rating=3, recommend=False, work_year=year - 1, job_code="mkt.perf", salary=None), headers=auth(t2))
    st = r.json()["stats"]
    assert st["n"] == 2 and st["rating"] == 4.0 and st["recommend"] == 50
    assert st["dist"] == {"5": 1, "4": 0, "3": 1, "2": 0, "1": 0}
    assert st["by_year"][str(year)]["n"] == 1 and st["by_year"][str(year - 1)]["rating"] == 3.0
    assert st["salary"]["n"] == 1, "a review without a figure must not count towards the median"
    lst = (await client.get(f"/api/community/companies/{cid}/reviews", params={"year": year - 1}, headers=auth(t1))).json()
    assert lst["total"] == 1 and lst["items"][0]["rating"] == 3.0 and lst["items"][0]["is_mine"] is False
    by_job = (await client.get(f"/api/community/companies/{cid}/reviews", params={"job": "mkt"}, headers=auth(t1))).json()
    assert by_job["total"] == 1 and by_job["items"][0]["job_family"] == "mkt"
    pay = (await client.get(f"/api/community/companies/{cid}/salary", headers=auth(t1))).json()
    assert pay["summary"]["median"] == 6500 and pay["total"] >= 1


@_async
async def test_helpful_and_follow_toggle_once_each_and_never_on_yourself(client: AsyncClient):
    _, writer = await signup(client)
    _, reader = await signup(client)
    cid = await make_company("토글상사")
    rid = (await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(), headers=auth(writer))).json()["review"]["id"]
    own = await client.post(f"/api/community/companies/reviews/{rid}/helpful", headers=auth(writer))
    assert own.status_code == 403 and own.json()["error"]["code"] == "own_review"
    a = (await client.post(f"/api/community/companies/reviews/{rid}/helpful", headers=auth(reader))).json()
    b = (await client.post(f"/api/community/companies/reviews/{rid}/helpful", headers=auth(reader))).json()
    assert a == {"helpful": True, "helpful_count": 1} and b == {"helpful": False, "helpful_count": 0}
    a = (await client.post(f"/api/community/companies/{cid}/follow", headers=auth(reader))).json()
    assert a == {"following": True, "follow_count": 1}
    lst = (await client.get("/api/community/companies", params={"q": "토글상사"}, headers=auth(reader))).json()
    assert lst["items"][0]["following"] is True and lst["items"][0]["follow_count"] == 1
    b = (await client.post(f"/api/community/companies/{cid}/follow", headers=auth(reader))).json()
    assert b == {"following": False, "follow_count": 0}


@_async
async def test_deleting_and_hiding_take_the_review_out_of_the_numbers(client: AsyncClient):
    _, tok = await signup(client)
    _, other = await signup(client)
    cid = await make_company("삭제물산")
    rid = (await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(), headers=auth(tok))).json()["review"]["id"]
    forbidden = await client.delete(f"/api/community/companies/reviews/{rid}", headers=auth(other))
    assert forbidden.status_code == 403
    assert (await client.delete(f"/api/community/companies/reviews/{rid}", headers=auth(tok))).status_code == 200
    d = (await client.get(f"/api/community/companies/{cid}", headers=auth(tok))).json()
    assert d["company"]["review_count"] == 0 and d["company"]["rating"] == 0 and d["my_review"] is None

    # Moderation: a reported review hidden from the console leaves the numbers too.
    rid = (await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(), headers=auth(other))).json()["review"]["id"]
    assert (await client.post(f"/api/community/companies/reviews/{rid}/report", json={"reason": "abuse"}, headers=auth(tok))).status_code == 201
    from blackmoa.db.session import session_scope
    from blackmoa.services import community as C
    async with session_scope("worker") as db:
        reports = await C.admin_reports(db, status="open")
        mine = next(r for r in reports if r["target"]["id"] == rid)
        assert mine["target"]["kind"] == "review" and mine["target"]["company_id"] == cid
        await C.admin_resolve_report(db, _uuid.UUID(mine["id"]), action="hide", admin_id=_uuid.uuid4())
        await db.commit()
    d = (await client.get(f"/api/community/companies/{cid}", headers=auth(other))).json()
    assert d["company"]["review_count"] == 0
    again = await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(), headers=auth(other))
    assert again.status_code == 403 and again.json()["error"]["code"] == "review_hidden"


@_async
async def test_the_form_is_checked_field_by_field(client: AsyncClient):
    _, tok = await signup(client)
    cid = await make_company("검증기업")
    short = await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(cons="짧음"), headers=auth(tok))
    assert short.status_code == 422 and short.json()["error"]["code"] == "review_too_short"
    assert short.json()["error"]["detail"]["field"] == "cons"
    bad = await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(rating_pay=9), headers=auth(tok))
    assert bad.status_code == 422 and bad.json()["error"]["detail"]["field"] == "rating_pay"
    # Unknown codes are dropped, not rejected: a stale form must still be able to save.
    ok = await client.post(f"/api/community/companies/{cid}/reviews",
                           json=review_body(job_code="nope", benefits=["meal", "unicorn"], growth="sideways",
                                            interview={"difficulty": None, "result": "maybe"}), headers=auth(tok))
    assert ok.status_code == 201, ok.text
    rv = ok.json()["review"]
    assert rv["job_code"] == "" and rv["benefits"] == ["meal"] and rv["growth"] == "flat" and rv["interview"] == {}


@_async
async def test_the_dashboard_has_something_to_say_before_anyone_has_reviewed(client: AsyncClient):
    """A fresh directory opens on popular companies and a pay shelf fed by postings; the
    "for me" row asks for a job until the profile names one, then explains each pick."""
    _, tok = await signup(client)
    await make_company("인기유가", market="유가")
    b = await make_company("연봉공고", codes=["it.game"])
    await make_company("상장셋째")   # three listed companies: the "newly listed" shelf's minimum
    from blackmoa.db.session import session_scope
    from blackmoa.services import community as C
    from blackmoa.services.companies.reviews import rank_all
    async with session_scope("worker") as db:
        from blackmoa.models import User
        u = (await db.execute(__import__("sqlalchemy").select(User).limit(1))).scalars().first()
        job = await C.create_job(db, user=u, data={"title": "게임 서버 개발자", "company": "연봉공고", "company_id": b,
                                                   "salary_min": 7000, "salary_max": 9000, "job_codes": ["dev.game"],
                                                   "region_codes": ["11"], "industry_codes": ["it.game"]})
        job_id = job.id
        await db.commit()
        await rank_all(db)
        await db.commit()
    h = (await client.get("/api/community/companies/home", headers=auth(tok))).json()
    assert h["totals"]["companies"] >= 2 and len(h["popular"]) >= 2
    assert len(h["salary_top"]) >= 1 and all(it["source"] in ("reviews", "jobs") for it in h["salary_top"])
    # The shelf holds three; other tests may already have filled them with reviewed
    # companies, so the fallback is checked where it cannot be crowded out.
    from blackmoa.services.companies.reviews import salary_top
    async with session_scope("worker") as db:
        wide = await salary_top(db, u, limit=50)
    pick = next(it for it in wide if it["company"]["id"] == b)
    assert pick["source"] == "jobs" and pick["snippet"]["salary_max"] == 9000
    assert [it["source"] for it in wide] == sorted((it["source"] for it in wide), key=lambda s: s != "reviews"), \
        "reviews come before postings on the pay shelf"
    assert h["for_me"]["needs_profile"] is True
    assert any(sh["key"] == "new_listed" for sh in h["shelves"]), [sh["key"] for sh in h["shelves"]]
    hiring = (await client.get("/api/community/companies", params={"q": "연봉공고"}, headers=auth(tok))).json()["items"][0]
    assert hiring["open_jobs"] == 1 and "hiring" in hiring["tags"]

    # Name a job in the profile and the row fills in, each company with its reason.
    r = await client.put("/api/users/me/profile", json={"data": {"job_codes": ["dev.game"], "industry_codes": ["it"]}, "visibility": {}}, headers=auth(tok))
    assert r.status_code == 200, r.text
    h = (await client.get("/api/community/companies/home", headers=auth(tok))).json()
    assert h["for_me"]["needs_profile"] is False
    whys = {it["id"]: it["why"] for it in h["for_me"]["items"]}
    assert whys.get(b) == "jobs", whys
    assert h["for_me"]["job_labels"] == ["게임 개발"]
    # The posting must not outlive the test: the job board's own tests count open postings.
    async with session_scope("worker") as db:
        from blackmoa.models import CommunityJob
        j = await db.get(CommunityJob, job_id)
        await C.close_job(db, job=j, user=u)
        await db.commit()


@_async
async def test_reviews_move_a_company_onto_the_rated_shelves_and_into_popular(client: AsyncClient):
    cid = await make_company("승진회사")
    toks = [(await signup(client))[1] for _ in range(3)]
    for t in toks:
        r = await client.post(f"/api/community/companies/{cid}/reviews",
                              json=review_body(rating_promotion=5, rating=5, recommend=True, growth="up"), headers=auth(t))
        assert r.status_code == 201
    others = [await make_company(f"승진동료{i}") for i in range(2)]
    for oc in others:
        for t in toks[:2]:
            await client.post(f"/api/community/companies/{oc}/reviews", json=review_body(rating_promotion=4), headers=auth(t))
    h = (await client.get("/api/community/companies/home", headers=auth(toks[0]))).json()
    promo = next((sh for sh in h["shelves"] if sh["key"] == "promotion"), None)
    assert promo is not None and promo["items"][0]["id"] == cid
    assert "promotion" in promo["items"][0]["tags"] and "recommended" in promo["items"][0]["tags"]
    assert any(rv["company"]["id"] == cid for rv in h["recent_reviews"])
    lst = (await client.get("/api/community/companies", params={"sort": "rating"}, headers=auth(toks[0]))).json()
    assert lst["items"][0]["id"] == cid
    allq = (await client.get("/api/community/companies/search", params={"q": "승진회사"}, headers=auth(toks[0]))).json()
    assert allq["companies"]["items"][0]["id"] == cid and allq["companies"]["total"] == 1
    assert "jobs" in allq and "posts" in allq


@_async
async def test_static_paths_are_not_read_as_company_ids(client: AsyncClient):
    _, tok = await signup(client)
    for path in ("home", "search", "suggest", "meta", "reviews/mine"):
        r = await client.get(f"/api/community/companies/{path}", headers=auth(tok))
        assert r.status_code == 200, (path, r.status_code, r.text[:120])
    meta = (await client.get("/api/community/companies/meta", headers=auth(tok))).json()
    assert {"code", "group"} <= set(meta["benefits"][0]) and meta["axes"] == ["pay", "balance", "culture", "promotion", "management"]


@_async
async def test_followers_hear_about_new_reviews_and_postings(client: AsyncClient):
    """Following has to mean something: a new review or a new posting at a followed
    company lands in the follower's inbox — not the author's own, and not for an edit."""
    _, fan = await signup(client)
    _, writer = await signup(client)
    cid = await make_company("팔로우전자")
    assert (await client.post(f"/api/community/companies/{cid}/follow", headers=auth(fan))).json()["following"] is True
    assert (await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(), headers=auth(writer))).status_code == 201
    # an edit is not news
    assert (await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(rating=5), headers=auth(writer))).status_code == 201
    inbox = (await client.get("/api/inbox", headers=auth(fan))).json()["items"]
    reviews = [it for it in inbox if it["kind"] == "company_review" and it["payload"]["company_id"] == cid]
    assert len(reviews) == 1 and reviews[0]["payload"]["company_name"].startswith("팔로우전자")
    # Deleted and written again: to a follower that is a new review, not an edit.
    rid = reviews[0]["payload"]["review_id"]
    assert (await client.delete(f"/api/community/companies/reviews/{rid}", headers=auth(writer))).status_code == 200
    assert (await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(title="다시 씀"), headers=auth(writer))).status_code == 201
    inbox = (await client.get("/api/inbox", headers=auth(fan))).json()["items"]
    assert len([it for it in inbox if it["kind"] == "company_review" and it["payload"]["company_id"] == cid]) == 2
    assert not [it for it in (await client.get("/api/inbox", headers=auth(writer))).json()["items"] if it["kind"] == "company_review"]
    from blackmoa.db.session import session_scope
    from blackmoa.services import community as C
    async with session_scope("worker") as db:
        from blackmoa.models import User
        u = await db.get(User, _uuid.UUID((await client.get("/api/auth/me", headers=auth(writer))).json()["id"]))
        job = await C.create_job(db, user=u, data={"title": "팔로우 테스트 공고", "company": "팔로우전자", "company_id": cid,
                                                   "job_codes": ["dev.backend"], "region_codes": ["11"]})
        await db.commit()
        job_id = job.id
    inbox = (await client.get("/api/inbox", headers=auth(fan))).json()["items"]
    jobs = [it for it in inbox if it["kind"] == "company_job" and it["payload"]["company_id"] == cid]
    assert len(jobs) == 1 and jobs[0]["payload"]["title"] == "팔로우 테스트 공고"
    async with session_scope("worker") as db:
        from blackmoa.models import CommunityJob
        await C.close_job(db, job=await db.get(CommunityJob, job_id), user=u)
        await db.commit()


@_async
async def test_compare_puts_up_to_four_side_by_side_in_the_order_picked(client: AsyncClient):
    _, tok = await signup(client)
    a, b, c_ = await make_company("비교A"), await make_company("비교B"), await make_company("비교C")
    await client.post(f"/api/community/companies/{a}/reviews", json=review_body(rating=5, salary=9000), headers=auth(tok))
    r = (await client.get("/api/community/companies/compare", params={"ids": f"{b},{a},{c_},{a}"}, headers=auth(tok))).json()
    assert [x["id"] for x in r["items"]] == [b, a, c_], "order follows the picks; duplicates collapse"
    assert r["items"][1]["stats"]["rating"] == 5.0 and r["items"][1]["stats"]["salary"]["median"] == 9000
    assert r["items"][0]["stats"]["n"] == 0 and r["max"] == 4
    bad = await client.get("/api/community/companies/compare", params={"ids": "nope"}, headers=auth(tok))
    assert bad.status_code == 422


@_async
async def test_the_detail_page_carries_the_readers_own_job_slice(client: AsyncClient):
    _, tok = await signup(client)
    _, other = await signup(client)
    cid = await make_company("내직군전자")
    await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(job_code="mkt.perf", salary=5200), headers=auth(other))
    d = (await client.get(f"/api/community/companies/{cid}", headers=auth(tok))).json()
    assert d["my_job"] is None
    await client.put("/api/users/me/profile", json={"data": {"job_codes": ["mkt.brand"]}, "visibility": {}}, headers=auth(tok))
    d = (await client.get(f"/api/community/companies/{cid}", headers=auth(tok))).json()
    assert d["my_job"]["family"] == "mkt" and d["my_job"]["label"] == "마케팅·광고"
    assert d["my_job"]["stats"]["n"] == 1 and d["my_job"]["stats"]["salary"]["median"] == 5200


@_async
async def test_the_secretary_can_look_a_company_up_and_shows_a_card(client: AsyncClient):
    """The owner names a company in chat; the secretary reads the directory and the chat
    shows a company card that links to the page. Reviews stay anonymous in the tool result."""
    from tests.conftest import read_sse

    _, tok = await signup(client)
    cid = await make_company("비서조회전자")
    _, other = await signup(client)
    await client.post(f"/api/community/companies/{cid}/reviews", json=review_body(title="비서가 읽을 리뷰"), headers=auth(other))
    r = await client.post("/api/agents", json={"name": "조회비서"}, headers=auth(tok))
    assert r.status_code in (200, 201), r.text
    agent = r.json()
    conv = (await client.post(f"/api/agents/{agent['id']}/conversations", json={"title": ""}, headers=auth(tok))).json()
    name = (await client.get(f"/api/community/companies/{cid}", headers=auth(tok))).json()["company"]["name"]
    async with client.stream("POST", f"/api/agents/{agent['id']}/conversations/{conv['id']}/turns",
                             json={"text": f'{name} 어떤 회사야? [[tool:company_lookup {{"name":"{name[:6]}"}}]]'}, headers=auth(tok)) as resp:
        events = await read_sse(resp)
    tools = [e["data"].get("name") for e in events if e.get("type") == "tool.start"]
    cards = [e["data"] for e in events if e.get("type") == "card"]
    assert "company_lookup" in tools, tools
    card = next(cd for cd in cards if cd["card_type"] == "company_card")
    assert card["payload"]["company"]["id"] == cid and card["payload"]["stats"]["n"] == 1
    # What the model actually receives: the review's words, never who wrote them.
    from types import SimpleNamespace

    from blackmoa.pipeline.tools.company_tools import CompanyLookup
    emitted: list = []
    tool = CompanyLookup(SimpleNamespace(card=lambda kind, payload: emitted.append((kind, payload))))  # type: ignore[arg-type]
    out = await tool.run({"name": name[:6]})
    assert out["found"] and out["company"]["id"] == cid and out["top_reviews"][0]["title"] == "비서가 읽을 리뷰"
    assert "author" not in str(out).lower() and emitted[0][0] == "company_card"
    miss = await tool.run({"name": "존재하지않는회사zz"})
    assert miss["found"] is False and "do not invent" in miss["note"]


def answers_body(**over) -> dict:
    """The current form: answers, not stars."""
    a = {"pay_level": "high", "raise": "perf", "hours": "h45_52", "overtime": "weekly", "vacation": "free", "flex": ["remote"],
         "comm": "flat", "peers": "learn", "safety": "yes", "promo_speed": "normal", "promo_basis": "perf",
         "trust": "trust", "vision": "clear", "stability": "stable", "outlook": "up", "again": "probably",
         "fit": ["growth", "pay"], "unfit": ["balance"]}
    a.update(over)
    return {"employment": "current", "job_code": "dev.backend", "work_year": datetime.now(UTC).year, "title": "질문에 답한 리뷰",
            "pros": "연봉이 높고 동료들에게 배울 점이 많아요. 휴가도 눈치 없이 씁니다.",
            "cons": "주 45시간은 넘기고 야근이 주 1~2회는 있어요. 승진은 보통 속도예요.",
            "answers": a}


@_async
async def test_answers_become_scores_facts_and_the_old_booleans(client: AsyncClient):
    """The form asks concrete questions; every number the page shows is derived from them,
    and the facts a reader wants ("주 45~52시간") are tallied per company."""
    from blackmoa.services.companies import questions as Q

    _, tok = await signup(client)
    cid = await make_company("질문전자")
    r = await client.post(f"/api/community/companies/{cid}/reviews", json=answers_body(), headers=auth(tok))
    assert r.status_code == 201, r.text
    rv, st = r.json()["review"], r.json()["stats"]
    assert rv["rating"] == 4.0 and rv["recommend"] is True and rv["ceo_approval"] is True and rv["growth"] == "up"
    # 보상 = mean(high 4.2, perf 4.5) ; 시간 = mean(45~52 2.5, weekly 2.5, free 5.0)
    assert rv["axes"]["pay"] == 4.35 and abs(rv["axes"]["balance"] - 3.33) < 0.01
    assert rv["answers"]["hours"] == "h45_52" and rv["answers"]["fit"] == ["growth", "pay"]
    assert st["facts"]["hours"] == {"h45_52": 1} and st["facts"]["fit"] == {"growth": 1, "pay": 1} and st["answered"] == 1
    assert st["axes"]["pay"] == 4.35
    # A required question left blank is refused by name; unknown options are dropped.
    bad = await client.post(f"/api/community/companies/{cid}/reviews", json=answers_body(again=None), headers=auth(tok))
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "review_unanswered" and bad.json()["error"]["detail"]["questions"] == ["again"]
    ok = await client.post(f"/api/community/companies/{cid}/reviews", json=answers_body(hours="h99", flex=["teleport", "remote"]), headers=auth(tok))
    assert ok.status_code == 422 and ok.json()["error"]["detail"]["questions"] == ["hours"], "an unknown answer to a required question is a blank"
    ok = await client.post(f"/api/community/companies/{cid}/reviews", json=answers_body(flex=["teleport", "remote"], unfit=["nope"]), headers=auth(tok))
    assert ok.status_code == 201 and ok.json()["review"]["answers"]["flex"] == ["remote"] and "unfit" not in ok.json()["review"]["answers"]
    assert Q.area_scores({"again": "must"}) == {a: None for a in Q.AREAS}
    meta = (await client.get("/api/community/companies/meta", headers=auth(tok))).json()
    assert any(q["code"] == "hours" and q["required"] and "h45_52" in q["options"] for q in meta["questions"])
    assert meta["fact_questions"][0] == "hours"


@_async
async def test_the_dashboard_ranks_companies_by_each_of_our_five_areas(client: AsyncClient):
    """Not "companies people mention pay at" — the five things a review asks about, each
    with its top companies and the fact that headlines that area."""
    _, tok = await signup(client)
    strong = await make_company("보상강자")
    weak = await make_company("보상약자")
    assert (await client.post(f"/api/community/companies/{strong}/reviews", json=answers_body(pay_level="top"), headers=auth(tok))).status_code == 201
    _, other = await signup(client)
    assert (await client.post(f"/api/community/companies/{weak}/reviews", json=answers_body(pay_level="low", hours="le40"), headers=auth(other))).status_code == 201
    h = (await client.get("/api/community/companies/home", headers=auth(tok))).json()
    areas = {a["key"]: a["items"] for a in h["areas"]}
    assert list(areas) == ["pay", "balance", "culture", "promotion", "management"]
    assert all(len(v) <= 5 and all({"score", "fact", "review_count"} <= set(c) for c in v) for v in areas.values())
    # The ranking itself, over the whole shared test database rather than the top five.
    from blackmoa.db.session import session_scope
    from blackmoa.models import User
    from blackmoa.services.companies.reviews import area_top
    async with session_scope("worker") as db:
        me = await db.get(User, _uuid.UUID((await client.get("/api/auth/me", headers=auth(tok))).json()["id"]))
        pay = [c["id"] for c in await area_top(db, me, "pay", limit=1000)]
        assert pay.index(strong) < pay.index(weak)
        top = next(c for c in await area_top(db, me, "pay", limit=1000) if c["id"] == strong)
        assert top["score"] >= 4.5 and top["fact"] == {"question": "pay_level", "option": "top", "n": 1, "total": 1, "pct": 100}
        # 시간: the company with 40-hour weeks leads the one with 45–52
        bal = await area_top(db, me, "balance", limit=1000)
        ids = [c["id"] for c in bal]
        assert ids.index(weak) < ids.index(strong)
        assert next(c for c in bal if c["id"] == weak)["fact"]["option"] == "le40"
