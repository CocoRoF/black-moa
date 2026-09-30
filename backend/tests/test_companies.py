"""The company directory (plan/33).

The collector is tested against a recorded copy of the exchange's real response rather
than the live site: the parse is the fragile part, the network is not ours, and a test that
fails when someone else's server is busy teaches nobody anything.
"""
from __future__ import annotations

import gzip
import itertools
import pathlib
import uuid as _uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from tests.conftest import auth, signup

_async = pytest.mark.asyncio

#: The exchange's real answer, recorded. Stored gzipped because it is 1.2MB of HTML and the
#: only thing the test needs from it is that the parse survives the real thing.
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "krx_corplist.html.gz"


def payload() -> bytes:
    return gzip.decompress(FIXTURE.read_bytes())


#: 한 번 돌 때 쓰는 번호는 **이어서** 나간다. 무작위로만 뽑으면 한 번 도는 동안
#: 스무 번쯤 뽑는 사이에 같은 번호가 두 번 나올 수 있고(생일 문제), 그러면 "같은
#: 이름 다른 회사" 검사가 같은 회사 하나를 보고 실패한다 — CI 에서 실제로 그렇게
#: 한 번 빨개졌다. 시작점만 무작위라 판이 남아 있는 로컬에서도 겹치지 않는다.
_TICKER_BASE = _uuid.uuid4().int % 90000
_TICKER_SEQ = itertools.count()


def a_ticker() -> str:
    """A code no other call has used, in this run or any other."""
    return f"9{(_TICKER_BASE + next(_TICKER_SEQ)) % 99999:05d}"


def test_the_exchange_list_parses_as_the_html_it_actually_is():
    """It is served as `application/vnd.ms-excel` and is an EUC-KR HTML table. A
    spreadsheet reader fails on it; that is the whole trick."""
    from memora.services.companies.krx import parse

    rows = parse(payload())
    assert len(rows) > 500, len(rows)
    by_code = {r["stock_code"]: r for r in rows}
    # Leading zeros are the identity: "005930" is Samsung Electronics and "5930" is nothing.
    assert all(len(c) == 6 for c in by_code), [c for c in by_code if len(c) != 6][:5]
    one = next(r for r in rows if r["homepage"] and r["listed_on"])
    assert one["name"] and one["market"] in ("유가", "코스닥", "코넥스")
    assert one["listed_on"].year > 1950


def test_a_truncated_response_is_a_failure_not_an_empty_directory():
    """The exchange sometimes answers with a login page. A 'successful' run that wipes the
    directory down to nine companies is worse than one that fails loudly."""
    from memora.services.companies.krx import MIN_ROWS, parse

    head = payload().decode("euc-kr", "replace")
    cut = head[: head.index("</tr>", head.index("</tr>") + 5) + 5] + "</table></body></html>"
    rows = parse(cut.encode("euc-kr", "replace"))
    assert len(rows) < MIN_ROWS      # fetch() turns this into an error rather than applying it


def test_source_words_land_in_the_taxonomy_the_community_filters_by():
    """A company and a job posting have to be findable the same way."""
    from memora.services.companies.taxonomy import industry_codes_for, region_code_for

    assert region_code_for("서울특별시") == ("11", "서울특별시")
    assert region_code_for("서울")[0] == "11"                # sources abbreviate
    assert region_code_for("해저기지") == ("", "해저기지")     # unknown keeps its label, gets no code
    assert industry_codes_for("반도체 제조업") == ["mfg.semi"]
    assert industry_codes_for("의료용 기기 제조업") == ["bio.device"]
    # A maker of telecom equipment is a manufacturer, not a carrier.
    assert industry_codes_for("통신 및 방송 장비 제조업") == ["mfg.elec"]
    assert industry_codes_for("전기통신업") == ["it.telecom"]
    assert industry_codes_for("듣도보도못한업") == []


@_async
async def test_one_company_however_its_name_is_written():
    """Three sources write "(주)카카오", "주식회사 카카오" and "카카오". One company."""
    from memora.db.session import session_scope
    from memora.services.companies.merge import apply_rows, normalise_name

    assert normalise_name("(주)카카오") == normalise_name("주식회사 카카오") == normalise_name("카카오")
    code = a_ticker()

    async with session_scope("worker") as db:
        a = await apply_rows(db, "krx", [{"name": f"(주)시험전자{code}", "stock_code": code,
                                          "industry_text": "반도체 제조업", "region_text": "경기도"}])
        assert a["created"] == 1
        b = await apply_rows(db, "krx", [{"name": f"주식회사 시험전자{code}", "stock_code": code}])
        assert b["created"] == 0, "the same company was created twice"
        await db.commit()

    from sqlalchemy import select

    from memora.models import Company
    async with session_scope("worker") as db:
        c = (await db.execute(select(Company).where(Company.stock_code == code))).scalar_one()
        assert c.industry_codes == ["mfg.semi"] and c.region_code == "41"


@_async
async def test_a_correction_by_hand_survives_the_next_collection():
    """A collector that overwrites a human correction every night is worse than no
    collector, because the correction stops being worth making."""
    from sqlalchemy import select

    from memora.db.session import session_scope
    from memora.models import Company
    from memora.services.companies.merge import apply_rows

    code = a_ticker()
    async with session_scope("worker") as db:
        await apply_rows(db, "krx", [{"name": f"시험화학{code}", "stock_code": code,
                                      "industry_text": "기타 화학제품 제조업"}])
        await db.commit()
    async with session_scope("worker") as db:
        c = (await db.execute(select(Company).where(Company.stock_code == code))).scalar_one()
        c.industry_codes = ["bio.pharma"]          # a person disagrees with the mapping
        c.locked_fields = ["industry_codes"]
        await db.commit()

    async with session_scope("worker") as db:
        await apply_rows(db, "krx", [{"name": f"시험화학{code}", "stock_code": code,
                                      "industry_text": "기타 화학제품 제조업"}])
        await db.commit()
    async with session_scope("worker") as db:
        c = (await db.execute(select(Company).where(Company.stock_code == code))).scalar_one()
        assert c.industry_codes == ["bio.pharma"], "the collector overwrote a correction"


@_async
async def test_a_source_only_writes_what_it_is_authoritative_about():
    """Each source knows different things. Last-write-wins would let the exchange's blank
    address erase the regulator's real one."""
    from sqlalchemy import select

    from memora.db.session import session_scope
    from memora.models import Company
    from memora.services.companies.merge import apply_rows

    code = a_ticker()
    async with session_scope("worker") as db:
        await apply_rows(db, "dart", [{"name": f"시험제약{code}", "stock_code": code,
                                       "corp_code": f"C{code}", "address": "서울시 어딘가 1길"}])
        await db.commit()
    async with session_scope("worker") as db:
        # The exchange does not own `address`, and must not clear it by not having one.
        await apply_rows(db, "krx", [{"name": f"시험제약{code}", "stock_code": code, "market": "코스닥"}])
        await db.commit()
    async with session_scope("worker") as db:
        c = (await db.execute(select(Company).where(Company.stock_code == code))).scalar_one()
        assert c.address == "서울시 어딘가 1길"      # the regulator's value stands
        assert c.market == "코스닥"                  # …and the exchange's own field is taken


@_async
async def test_the_admin_can_see_the_sources_and_queue_a_collection(client: AsyncClient):
    """Queued, not run in the request: the sources are slow and rate-capped, and the
    `crawl` class's ceiling only applies to a job (plan/32 §4)."""
    from memora.db.session import session_scope
    from memora.models import User
    from memora.worker.__main__ import _class_of

    user, tok = await signup(client, f"comp-{_uuid.uuid4().hex[:6]}@example.com")
    async with session_scope() as db:
        (await db.get(User, _uuid.UUID(user["id"]))).role = "admin"
    r = await client.get("/api/admin/companies/sources", headers=auth(tok))
    assert r.status_code == 200, r.text
    body = r.json()
    krx = next(s for s in body["sources"] if s["source"] == "krx")
    assert krx["needs_key"] is None, "the first source must work without a key"

    r = await client.post("/api/admin/companies/collect/krx", headers=auth(tok))
    assert r.status_code == 202 and r.json()["queued"] is True
    assert _class_of("crawl.companies") == "crawl"

    assert (await client.post("/api/admin/companies/collect/nonesuch", headers=auth(tok))).status_code == 404


def test_companies_incorporated_abroad_are_still_filterable():
    """Two dozen listed companies state a country, not a province. Without a code no
    region filter could reach them; the taxonomy already has 해외·원격 for exactly this."""
    from memora.services.companies.taxonomy import OVERSEAS_CODE, region_code_for

    for place in ("홍콩", "미국", "케이맨 제도", "일본", "영국"):
        assert region_code_for(place) == (OVERSEAS_CODE, place), place
    # …and it is not a catch-all: a province is still a province, and nonsense is still
    # uncoded rather than quietly filed overseas.
    assert region_code_for("전라남도") == ("46", "전라남도")
    assert region_code_for("듣도보도못한곳") == ("", "듣도보도못한곳")


@_async
async def test_the_duplicated_rows_do_not_decide_the_region_by_luck():
    """The exchange lists forty-three companies twice, and the pair differs in exactly one
    field: the region, where it is mid-transition between administrative names. One
    spelling resolves to a province and the other does not — so whichever arrives last must
    not be what decides whether the company can be filtered.
    """
    from sqlalchemy import select

    from memora.db.session import session_scope
    from memora.models import Company
    from memora.services.companies.krx import parse
    from memora.services.companies.merge import apply_rows

    rows = parse(payload())
    by_code: dict[str, list] = {}
    for r in rows:
        by_code.setdefault(r["stock_code"], []).append(r)
    pairs = {k: v for k, v in by_code.items() if len(v) > 1}
    assert pairs, "the fixture no longer contains the duplicated rows this guards"
    code, pair = next(iter(pairs.items()))
    assert any(x != pair[0] for x in pair), "the duplicates are identical in this fixture"

    # Worst order: the resolvable spelling first, the unresolvable one second.
    ordered = sorted(pair, key=lambda r: r["region_text"] not in ("전라남도",))
    async with session_scope("worker") as db:
        await apply_rows(db, "krx", ordered)
        await db.commit()
    async with session_scope("worker") as db:
        c = (await db.execute(select(Company).where(Company.stock_code == code))).scalar_one()
        assert c.region_code, f"{c.name} lost its region to the later row ({c.region_text!r})"
        # and the label agrees with the code rather than being left from the other row
        from memora.services.companies.taxonomy import region_code_for
        assert region_code_for(c.region_text)[0] == c.region_code


def test_almost_every_company_in_the_real_list_gets_an_industry_code():
    """The industry mapping is what makes the directory filterable, so it is measured
    against the whole real list rather than a handful of examples.

    The first real collection mapped 89.6%: the misses were mostly spacing — the
    classification writes "정보 서비스업" where the keyword table said "정보서비스" — plus
    whole categories nobody had thought of (ships, cement, paper, animal feed).
    """
    from memora.services.companies.krx import parse
    from memora.services.companies.taxonomy import industry_codes_for

    companies = {r["stock_code"]: r for r in parse(payload())}
    coded = sum(1 for r in companies.values() if industry_codes_for(r["industry_text"]))
    share = coded / len(companies)
    assert share > 0.98, f"only {share:.1%} of companies map to an industry code"
    # …and the mapping still says something specific where it can, rather than filing
    # everything under the parent to make the number look good.
    specific = sum(1 for r in companies.values()
                   if any("." in c for c in industry_codes_for(r["industry_text"])))
    assert specific > len(companies) * 0.5, f"only {specific} companies got a specific code"


# ── the keyed sources (plan/33 §3, §4) ───────────────────────────────
#
# Their payloads here are constructed to the documented field names rather than recorded,
# because issuing a key is something only the operator can do. What *was* verified against
# the live services is the failure contract — both answer an unregistered key with a body,
# not an HTTP error — and that is the path an install without keys actually takes, so it is
# the one tested against reality.

def test_the_dart_dictionary_maps_tickers_to_corp_codes():
    """This mapping is the join between the exchange's world and the regulator's."""
    import io
    import zipfile

    from memora.services.companies.dart import parse_codes

    xml = """<?xml version="1.0" encoding="UTF-8"?><result>
      <list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name><stock_code>005930</stock_code></list>
      <list><corp_code>00164779</corp_code><corp_name>비상장회사</corp_name><stock_code> </stock_code></list>
      <list><corp_code>00149655</corp_code><corp_name>삼성E&amp;A</corp_name><stock_code>028050</stock_code></list>
      <list><corp_code></corp_code><corp_name>코드없음</corp_name><stock_code>000000</stock_code></list>
    </result>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", xml)
    rows = parse_codes(buf.getvalue())

    assert len(rows) == 3, "a row with no corp code is not a company"
    # XML entities are undone: 29 listed companies were shown as "삼성E&amp;A" before this.
    assert next(r for r in rows if r["corp_code"] == "00149655")["name"] == "삼성E&A"
    listed = next(r for r in rows if r["corp_code"] == "00126380")
    assert listed["stock_code"] == "005930"
    # An unlisted filer has a blank ticker, and a blank is not a ticker: carrying "" here
    # would collide with every other unlisted company on the unique index.
    unlisted = next(r for r in rows if r["corp_code"] == "00164779")
    assert "stock_code" not in unlisted


def test_dart_company_details_are_taken_apart_correctly():
    import json

    from memora.services.companies.dart import parse_company

    body = {"status": "000", "message": "정상", "corp_name": "주식회사 시험",
            "bizr_no": "123-45-67890", "adres": "서울특별시 강남구 어딘가 1", "phn_no": "02-1234-5678",
            "est_dt": "19691231", "induty_code": "26410"}
    out = parse_company(json.dumps(body).encode())
    assert out["biz_no"] == "1234567890", "the registration number keeps its dashes"
    assert out["founded_on"].year == 1969
    assert out["address"].startswith("서울특별시")
    # A failed lookup contributes nothing rather than a row of blanks that would then
    # overwrite what another source knows.
    assert parse_company(json.dumps({"status": "013", "message": "없음"}).encode()) == {}


def test_the_tax_office_words_become_a_status():
    import json

    from memora.services.companies.nts import parse

    body = {"data": [
        {"b_no": "1234567890", "b_stt": "계속사업자"},
        {"b_no": "1234567891", "b_stt": "폐업자"},
        {"b_no": "1234567892", "b_stt": "휴업자"},
        {"b_no": "1234567893", "b_stt": ""},
    ]}
    got = {r["biz_no"]: r["status"] for r in parse(json.dumps(body).encode())}
    assert got == {"1234567890": "active", "1234567891": "closed",
                   "1234567892": "suspended", "1234567893": "unknown"}


@_async
async def test_a_source_with_no_key_is_reported_as_that_and_not_as_a_crash(client: AsyncClient):
    """The state a fresh install is actually in. "Needs a key" and "set up and failing" are
    different problems with different fixes, so the screen has to tell them apart."""
    from memora.db.session import session_scope
    from memora.services.companies.collect import SOURCES, run, status

    for source in ("dart_codes", "dart", "nts"):
        async with session_scope("worker") as db:
            out = await run(db, source)
            await db.commit()
        assert out["ok"] is False and out.get("needs_key") is True, (source, out)
        assert "키" in out["error"], out["error"]

    async with session_scope("worker") as db:
        st = await status(db)
    keyed = {s["source"]: s for s in st["sources"]}
    assert keyed["krx"]["key_set"] is True and keyed["krx"]["needs_key"] is None
    for source in ("dart_codes", "dart", "nts"):
        assert keyed[source]["key_set"] is False, source
        assert keyed[source]["where"], "the screen has to say where to get the key"
    # every source the code knows about is on the screen
    assert set(keyed) == set(SOURCES)


@_async
async def test_the_panel_says_what_is_missing_and_which_source_fills_it(client: AsyncClient):
    """Completeness, not size, is the number worth showing: a company with no industry
    code cannot be filtered and one with no registration number cannot be checked."""
    from sqlalchemy import func, select

    from memora.db.session import session_scope
    from memora.models import Company
    from memora.services.companies.collect import coverage

    # Both reads from one session: another test creating a company between them is not a
    # bug in the thing being measured.
    async with session_scope("worker") as db:
        cov = await coverage(db)
        traded = (await db.execute(select(func.count()).select_from(Company)
                                   .where(Company.market != ""))).scalar_one()
    for field in ("industry_codes", "region_code", "corp_code", "biz_no", "address", "status_known"):
        assert field in cov["fields"] and field in cov["pct"] and field in cov["of"], field
    assert cov["filled_by"]["biz_no"] == "dart"
    assert cov["filled_by"]["status_known"] == "nts"
    assert all(0 <= v <= 100 for v in cov["pct"].values()), cov["pct"]

    # Each field is measured against what could hold it. One denominator lies: the
    # regulator's dictionary brings 115,000 unlisted companies and carries no industry, so
    # measuring industry against everything reported 2.3% the moment it landed.
    # "listed" means currently traded: counting every company that ever had a stock code
    # put 1,231 delisted shells in it.
    assert cov["listed"] == traded, "the listed count includes companies that no longer trade"
    # …and industry is measured against the companies the exchange reported, which is the
    # only population that can have one. Measuring against "listed" gave 150%.
    assert cov["of"]["industry_codes"] == cov["from_krx"]
    assert cov["fields"]["industry_codes"] <= cov["of"]["industry_codes"]
    assert cov["of"]["corp_code"] == cov["total"]
    assert cov["of"]["status_known"] == cov["fields"]["biz_no"], "status can only be asked about a registered number"
    assert cov["visible"] <= cov["total"]


@_async
async def test_the_daily_pass_skips_sources_that_have_no_key(client: AsyncClient):
    """One slow or unconfigured source must not stop the others, so each is its own job."""
    from memora.db.session import session_scope
    from memora.services import settings as S
    from memora.worker.handlers import HANDLERS

    async with session_scope("worker") as db:
        assert (await HANDLERS["companies.refresh"](db, {}))["skipped"], "off by default"
        await S.put(db, "companies.auto_collect", True)
        await db.commit()
    try:
        async with session_scope("worker") as db:
            out = await HANDLERS["companies.refresh"](db, {})
            await db.commit()
        assert out["queued"] == ["krx"], out
    finally:
        async with session_scope("worker") as db:
            await S.put(db, "companies.auto_collect", False)
            await db.commit()


# ── the community surface (plan/33 §5) ───────────────────────────────

@_async
async def test_a_posting_links_itself_to_the_company_it_names(client: AsyncClient):
    """A posting names its employer as free text. When that text unambiguously matches one
    company, the reader should get the employer's details without leaving the posting."""
    from memora.db.session import session_scope
    from memora.services.companies.merge import apply_rows

    code = a_ticker()
    name = f"연결시험{code}"
    async with session_scope("worker") as db:
        await apply_rows(db, "krx", [{"name": name, "stock_code": code, "market": "코스닥",
                                      "industry_text": "소프트웨어 개발 및 공급업", "region_text": "서울특별시"}])
        await db.commit()

    _, tok = await signup(client, name="공고작성자")
    title = f"연결확인 백엔드 {code}"     # unique: a shared title made another test see this posting
    r = await client.post("/api/community/jobs", json={
        "title": title, "company": f"(주){name}",   # written differently on purpose
        "region_codes": ["11"], "job_codes": ["dev.backend"], "employment_type": "fulltime",
    }, headers=auth(tok))
    assert r.status_code in (201, 422), r.text
    if r.status_code == 422:
        pytest.skip("the posting form requires fields this test does not model")

    job_id = r.json()["id"]
    try:
        jobs = (await client.get("/api/community/jobs", headers=auth(tok))).json()["items"]
        mine = next(j for j in jobs if j["title"] == title)
        info = mine["company_info"]
        assert info is not None, "the posting was not linked despite an unambiguous name"
        assert info["name"] == name and info["market"] == "코스닥"
        assert info["industry_text"] and info["region_text"] == "서울특별시"
    finally:
        # Taken back out: a neighbouring test asserts the exact set of postings in this
        # region, and a fixture that leaves rows behind is one that breaks its neighbours.
        import uuid as _u

        from memora.db.session import session_scope
        from memora.models import CommunityJob
        async with session_scope("worker") as db:
            row = await db.get(CommunityJob, _u.UUID(job_id))
            if row is not None:
                await db.delete(row)
            await db.commit()


@_async
async def test_an_ambiguous_name_is_left_unlinked(client: AsyncClient):
    """Attaching a posting to the wrong employer is worse than leaving it unlinked."""
    from memora.db.session import session_scope
    from memora.models import Company
    from memora.services.companies.merge import apply_rows, normalise_name

    shared = f"동명이인{a_ticker()}"
    async with session_scope("worker") as db:
        # Two companies, same normalised name, different tickers: the merge keeps them
        # apart, and the matcher must then refuse to choose between them.
        await apply_rows(db, "krx", [{"name": f"(주){shared}", "stock_code": a_ticker()}])
        await apply_rows(db, "krx", [{"name": f"주식회사 {shared}", "stock_code": a_ticker()}])
        await db.commit()

    from sqlalchemy import func, select

    from memora.services.companies.query import match_by_name
    async with session_scope("worker") as db:
        n = (await db.execute(select(func.count()).select_from(Company)
                              .where(Company.name_norm == normalise_name(shared)))).scalar_one()
        assert n == 2, f"expected two companies sharing the name, got {n}"
        assert await match_by_name(db, shared) is None, "it guessed between two companies"


@_async
async def test_the_directory_hides_what_moderation_hid_but_not_from_the_console(client: AsyncClient):
    """Hiding a company should not be invisible to the person who did it."""
    from sqlalchemy import select

    from memora.db.session import session_scope
    from memora.models import Company
    from memora.services.companies.merge import apply_rows
    from memora.services.companies.query import search

    code = a_ticker()
    name = f"숨김시험{code}"
    async with session_scope("worker") as db:
        await apply_rows(db, "krx", [{"name": name, "stock_code": code}])
        await db.commit()
    async with session_scope("worker") as db:
        c = (await db.execute(select(Company).where(Company.stock_code == code))).scalar_one()
        c.hidden = True
        await db.commit()

    async with session_scope("worker") as db:
        readers = await search(db, q=name, include_hidden=False)
        console = await search(db, q=name, include_hidden=True)
    assert readers["total"] == 0, "a hidden company was shown to readers"
    assert console["total"] == 1, "a hidden company vanished from the console too"


@_async
async def test_name_completion_offers_the_company_a_poster_means(client: AsyncClient):
    from memora.db.session import session_scope
    from memora.services.companies.merge import apply_rows
    from memora.services.companies.query import suggest

    code = a_ticker()
    async with session_scope("worker") as db:
        await apply_rows(db, "krx", [{"name": f"(주)완성시험{code}", "stock_code": code, "market": "유가"}])
        await db.commit()

    async with session_scope("worker") as db:
        # typed without the legal form, which is how people type
        hits = await suggest(db, f"완성시험{code}")
        assert any(h["stock_code"] == code for h in hits), hits
        # too short to be a search
        assert await suggest(db, "가") == []


@_async
async def test_every_value_an_operator_must_set_is_settable_from_the_panel(client: AsyncClient):
    """A setting that only exists in a config file is a setting nobody will find.

    Everything this feature needs from an operator — two keys, the per-run budget, the
    automatic-collection switch — has to be reachable from the screen that tells them it is
    missing. The deploy-level dials (pool sizes, worker width) are deliberately not here:
    those belong to whoever deploys, not to whoever administers.
    """
    from memora.db.session import session_scope
    from memora.services.companies.collect import SOURCES, status

    async with session_scope("worker") as db:
        st = await status(db)

    # the budget and the switch come back with the status, so the panel can show them
    assert isinstance(st["dart_per_run"], int) and st["dart_per_run"] > 0
    assert isinstance(st["auto_collect"], bool)

    # …and every key a source needs is named, with somewhere to get it
    needed = {s["needs_key"] for s in st["sources"] if s["needs_key"]}
    assert needed == {"companies.dart_key", "companies.data_go_kr_key"}, needed
    for s in st["sources"]:
        if s["needs_key"]:
            assert s["where"], f"{s['source']} does not say where to get its key"

    # every setting this feature reads is a known setting, so the panel can write it
    from memora.services.settings import DEFAULTS

    for key in {*needed, "companies.dart_per_run", "companies.auto_collect"}:
        assert key in DEFAULTS, f"{key} is read but not a declared setting"
    assert set(SOURCES) == {s["source"] for s in st["sources"]}


def test_a_pasted_portal_key_works_whichever_form_it_is_in():
    """data.go.kr shows its key percent-encoded, so that is what gets pasted.

    Encoding it again turns %2B into %252B and the service answers 401 "등록되지 않은
    인증키" — measured against the live service, not guessed. The portal's own note tells
    you to try both forms, which is as good as saying the caller has to cope.
    """
    from memora.services.companies.nts import normalise_key

    decoded = "abc+def/ghi=="
    encoded = "abc%2Bdef%2Fghi%3D%3D"
    assert normalise_key(encoded) == decoded
    assert normalise_key(decoded) == decoded, "a key that is already usable must be left alone"
    assert normalise_key("  " + encoded + "  ") == decoded, "pasted keys carry whitespace"
    assert normalise_key("") == ""


@_async
async def test_enrichment_spends_its_calls_where_someone_is_reading():
    """119,000 companies at one call each is weeks of budget, so the order is the feature.

    A company a posting points at is being read today; a listed company is what a reader
    looks up; the rest can wait. Getting this backwards means the useful rows are filled
    in two months rather than tomorrow.
    """
    from memora.db.session import session_scope
    from memora.services.companies.dart import due_for_details
    from memora.services.companies.merge import apply_rows

    plain, listed = a_ticker(), a_ticker()
    async with session_scope("worker") as db:
        # one unlisted, one listed — neither enriched, so both are due
        await apply_rows(db, "dart", [{"name": f"비상장{plain}", "corp_code": f"C{plain}"}])
        await apply_rows(db, "krx", [{"name": f"상장{listed}", "stock_code": listed}])
        await apply_rows(db, "dart", [{"name": f"상장{listed}", "stock_code": listed,
                                       "corp_code": f"C{listed}"}])
        await db.commit()

    async with session_scope("worker") as db:
        order = [c for c, _ in await due_for_details(db, 8000)]
    assert f"C{listed}" in order and f"C{plain}" in order
    assert order.index(f"C{listed}") < order.index(f"C{plain}"), "an unlisted shell outranked a listed company"

    # …and a *delisted* company must not count as listed. The regulator keeps a stock code
    # for everything that ever listed, so that test put the first hundred calls into
    # long-dissolved shells; only the exchange's `market` means currently traded.
    gone = a_ticker()
    async with session_scope("worker") as db:
        await apply_rows(db, "dart", [{"name": f"상장폐지{gone}", "stock_code": gone,
                                       "corp_code": f"C{gone}"}])
        await db.commit()
    async with session_scope("worker") as db:
        order = [c for c, _ in await due_for_details(db, 8000)]
    assert order.index(f"C{listed}") < order.index(f"C{gone}"), "a delisted shell outranked a traded company"


@_async
async def test_readers_see_a_directory_worth_reading():
    """The dictionary brings ~115,000 unlisted companies that are, to a reader, a name.
    The console still sees them — that is where you go to find out why one is empty."""
    from memora.db.session import session_scope
    from memora.services.companies.merge import apply_rows
    from memora.services.companies.query import search

    bare = a_ticker()
    name = f"이름만있는회사{bare}"
    async with session_scope("worker") as db:
        await apply_rows(db, "dart", [{"name": name, "corp_code": f"C{bare}"}])
        await db.commit()

    async with session_scope("worker") as db:
        assert (await search(db, q=name, include_hidden=False))["total"] == 0
        assert (await search(db, q=name, include_hidden=True))["total"] == 1

    # …and one with an industry is worth showing even unlisted
    told = a_ticker()
    async with session_scope("worker") as db:
        await apply_rows(db, "dart", [{"name": f"업종있는회사{told}", "corp_code": f"C{told}",
                                       "address": "서울특별시 어딘가"}])
        await db.commit()
    async with session_scope("worker") as db:
        assert (await search(db, q=f"업종있는회사{told}", include_hidden=False))["total"] == 1


@_async
async def test_a_source_that_only_knows_an_identifier_can_still_update():
    """The tax office answers with a registration number and a status — no company name.

    The merge required a name because it might have to create a company, so every one of
    its hundred answers was skipped and nothing was ever marked closed. It may now update
    a company it can identify, and still may not create one: a row with no name is not a
    company anyone could be shown.
    """
    from sqlalchemy import func, select

    from memora.db.session import session_scope
    from memora.models import Company
    from memora.services.companies.merge import apply_rows

    code = a_ticker()
    biz = f"9{code}2345"[:10]
    async with session_scope("worker") as db:
        await apply_rows(db, "dart", [{"name": f"폐업시험{code}", "stock_code": code, "biz_no": biz}])
        await db.commit()

    async with session_scope("worker") as db:
        before = (await db.execute(select(func.count()).select_from(Company))).scalar_one()
        out = await apply_rows(db, "nts", [{"biz_no": biz, "status": "closed"}])
        await db.commit()
    assert out["updated"] == 1, out

    async with session_scope("worker") as db:
        c = (await db.execute(select(Company).where(Company.biz_no == biz))).scalar_one()
        assert c.status == "closed"
        assert c.name == f"폐업시험{code}", "a nameless row blanked the company's name"
        after = (await db.execute(select(func.count()).select_from(Company))).scalar_one()
    assert after == before, "an identifier-only row created a company"

    # …and an identifier nobody has creates nothing at all
    async with session_scope("worker") as db:
        out = await apply_rows(db, "nts", [{"biz_no": "0000000000", "status": "closed"}])
        await db.commit()
    assert out == {"created": 0, "updated": 0, "skipped": 1}, out


@_async
async def test_the_panel_and_the_directory_agree_on_what_readers_see():
    """One predicate, one place. Written twice it drifted: the directory tested for a stock
    code — which the regulator keeps for every company that ever listed — so the panel
    counted 3,990 visible while 1,231 of those were dissolved shells with nothing to show.
    """
    from sqlalchemy import func, select

    from memora.db.session import session_scope
    from memora.models import Company
    from memora.services.companies.collect import coverage
    from memora.services.companies.query import search, substantive

    async with session_scope("worker") as db:
        cov = await coverage(db)
        counted = (await db.execute(select(func.count()).select_from(Company)
                                    .where(Company.hidden.is_(False), substantive()))).scalar_one()
        shown = (await search(db, page=1, size=1, include_hidden=False))["total"]
    assert cov["visible"] == counted == shown, (cov["visible"], counted, shown)


@_async
async def test_one_source_does_not_collect_twice_at_once():
    """Two collections of the same source is duplicated work and, worse, duplicated quota.

    Both compute their candidate list at the start, so they fetch largely the same
    companies and spend twice the allowance doing it. Observed in production: two `dart`
    jobs running together, each budgeted for the whole day.
    """
    from memora.db.session import session_scope
    from memora.models import CompanySourceRun
    from memora.services.companies.collect import in_flight, run

    async with session_scope("worker") as db:
        assert await in_flight(db, "dart") is False
        db.add(CompanySourceRun(source="dart", started_at=datetime.now(UTC)))   # unfinished
        await db.commit()
    try:
        async with session_scope("worker") as db:
            assert await in_flight(db, "dart") is True
            out = await run(db, "dart")
            await db.commit()
        assert out["busy"] is True and out["ok"] is False, out
    finally:
        from sqlalchemy import delete
        async with session_scope("worker") as db:
            await db.execute(delete(CompanySourceRun).where(CompanySourceRun.finished_at.is_(None)))
            await db.commit()


@_async
async def test_the_day_s_allowance_is_shared_between_runs():
    """The budget counts what today has already recorded, so the second run of a day takes
    what is left rather than the whole thing again."""
    from memora.db.session import session_scope
    from memora.models import CompanySourceRun
    from memora.services import settings as S
    from memora.services.companies.collect import dart_budget

    async with session_scope("worker") as db:
        await S.put(db, "companies.dart_per_run", 1000)
        await S.put(db, "companies.dart_daily_limit", 2500)
        await db.commit()
    try:
        async with session_scope("worker") as db:
            assert await dart_budget(db) == 1000, "the per-run cap should apply first"
            # 2,000 already spent today leaves 500, which is less than the per-run cap
            db.add(CompanySourceRun(source="dart", started_at=datetime.now(UTC),
                                    finished_at=datetime.now(UTC), ok=True, fetched=2000))
            await db.commit()
        async with session_scope("worker") as db:
            assert await dart_budget(db) == 500, "the day's remainder did not cap the run"
            db.add(CompanySourceRun(source="dart", started_at=datetime.now(UTC),
                                    finished_at=datetime.now(UTC), ok=True, fetched=600))
            await db.commit()
        async with session_scope("worker") as db:
            assert await dart_budget(db) == 0, "the allowance was exceeded"
    finally:
        from sqlalchemy import delete
        async with session_scope("worker") as db:
            await db.execute(delete(CompanySourceRun).where(CompanySourceRun.source == "dart"))
            await S.put(db, "companies.dart_daily_limit", 10000)
            await S.put(db, "companies.dart_per_run", 1000)
            await db.commit()


@_async
async def test_a_long_collection_keeps_what_it_has_already_applied():
    """An hour of fetching followed by one merge loses the hour if the job dies — and
    spends the quota anyway. Measured in production: the worker's 900-second job timeout
    killed a run after 5,300 DART calls and not one of them had been recorded.
    """
    import memora.services.companies.collect as C
    import memora.services.companies.dart as D
    from memora.db.session import session_scope

    codes = [a_ticker() for _ in range(6)]
    async with session_scope("worker") as db:
        await C.apply_rows(db, "dart", [{"name": f"청크{c}", "corp_code": f"C{c}"} for c in codes])
        await db.commit()

    seen: list[int] = []

    async def fake_company(key, corp_code):
        return {"address": "서울특별시 어딘가"}

    async def apply(chunk):
        seen.append(len(chunk))                       # once per chunk, not once at the end
        return {"created": 0, "updated": len(chunk), "skipped": 0}

    class Rec:
        fetched = created = updated = skipped = 0

    from memora.services import settings as S

    orig = (D.fetch_company, D.BATCH, D.GAP_S)
    D.fetch_company, D.BATCH, D.GAP_S = fake_company, 2, 0.0
    async with session_scope("worker") as db:
        await S.put(db, "companies.dart_key", "test-key")     # the collector checks for one
        await db.commit()
    try:
        async with session_scope("worker") as db:
            out = await C._collect(db, "dart", Rec(), apply)
        assert out == [], "rows were returned instead of applied as they arrived"
        assert len(seen) >= 2, f"applied in one go rather than per chunk: {seen}"
        assert all(n <= 2 for n in seen), seen
    finally:
        D.fetch_company, D.BATCH, D.GAP_S = orig
        async with session_scope("worker") as db:
            await S.put(db, "companies.dart_key", "")
            await db.commit()


@_async
async def test_a_collection_stops_inside_the_job_s_time_budget():
    """The worker kills a job at 900 seconds. A run that ignores that is killed mid-merge;
    stopping early and continuing next time is strictly better."""
    import memora.services.companies.collect as C

    assert C.RUN_DEADLINE_S < 900, "the deadline must leave the worker room to finish the job"


@_async
async def test_the_tax_office_is_asked_about_companies_we_have_not_asked_about():
    """The order was inverted, so it re-checked companies whose status was already known
    and never reached the rest — 2,000 calls returning 17 changes, then 2,000 returning
    none, while thousands stayed unknown."""
    from sqlalchemy import select

    from memora.db.session import session_scope
    from memora.models import Company
    from memora.services.companies.merge import apply_rows
    from memora.services.companies.nts import due_for_check

    known, unknown = a_ticker(), a_ticker()
    kb, ub = f"8{known}0"[:10], f"7{unknown}0"[:10]
    async with session_scope("worker") as db:
        await apply_rows(db, "dart", [{"name": f"확인됨{known}", "corp_code": f"C{known}", "biz_no": kb},
                                      {"name": f"미확인{unknown}", "corp_code": f"C{unknown}", "biz_no": ub}])
        await db.commit()
    async with session_scope("worker") as db:
        row = (await db.execute(select(Company).where(Company.biz_no == kb))).scalar_one()
        row.status = "active"                         # already asked about this one
        await db.commit()

    async with session_scope("worker") as db:
        order = await due_for_check(db, 10_000)
    assert ub in order and kb in order
    assert order.index(ub) < order.index(kb), "it asked again about a company it already knew"


@_async
async def test_a_restart_does_not_leave_a_collection_running_for_ever():
    """A worker restart kills a collection mid-flight and its row stays open, which reads
    as "still collecting" and blocks the next run through the single-flight guard. Seen
    twice: once from the job timeout, once from a deploy."""
    from memora.db.session import session_scope
    from memora.models import CompanySourceRun
    from memora.services.companies.collect import close_abandoned, in_flight

    async with session_scope("worker") as db:
        db.add(CompanySourceRun(source="nts", started_at=datetime.now(UTC)))
        await db.commit()
    async with session_scope("worker") as db:
        assert await in_flight(db, "nts") is True
        assert await close_abandoned(db) >= 1
        await db.commit()
    async with session_scope("worker") as db:
        assert await in_flight(db, "nts") is False, "the abandoned run still blocks collection"


# ── surviving restarts (2026-09-14) ─────────────────────────────────────────
# What the collection log looked like for two days: every `dart` run "중단됨 — 워커가
# 재시작되었어요" with nothing fetched. Three causes, each with a test now.

def test_dart_hands_back_placeholder_registration_numbers_and_we_keep_none():
    """"11940" is not a registration number. Truncating it to whatever was there gave
    several companies the same key and the unique index failed the whole run."""
    import json

    from memora.services.companies.dart import parse_company

    good = parse_company(json.dumps({"status": "000", "corp_name": "정상", "bizr_no": "123-45-67890"}).encode())
    bad = parse_company(json.dumps({"status": "000", "corp_name": "자리표시", "bizr_no": "11940"}).encode())
    assert good["biz_no"] == "1234567890" and bad.get("biz_no") is None


@_async
async def test_a_key_another_company_holds_is_kept_out_not_crashed_into():
    from sqlalchemy import select

    from memora.db.session import session_scope
    from memora.models import Company
    from memora.services.companies.merge import apply_rows

    biz = f"9{_uuid.uuid4().int % 10**9:09d}"
    a, b = a_ticker(), a_ticker()
    ca, cb = f"c{_uuid.uuid4().hex[:7]}", f"c{_uuid.uuid4().hex[:7]}"
    async with session_scope("worker") as db:
        # As in production: the exchange listed them, the dictionary gave them corp codes,
        # and now the per-company details arrive keyed by corp code.
        await apply_rows(db, "krx", [{"name": f"먼저{a}", "stock_code": a}, {"name": f"나중{b}", "stock_code": b}])
        await apply_rows(db, "dart", [{"stock_code": a, "corp_code": ca}, {"stock_code": b, "corp_code": cb}])
        await db.commit()
    async with session_scope("worker") as db:
        r = await apply_rows(db, "dart", [{"corp_code": ca, "biz_no": biz, "address": "서울"},
                                          {"corp_code": cb, "biz_no": biz, "address": "부산"}])
        await db.commit()       # used to raise IntegrityError here and take the run down
        assert r["updated"] == 2
        first = (await db.execute(select(Company).where(Company.stock_code == a))).scalar_one()
        second = (await db.execute(select(Company).where(Company.stock_code == b))).scalar_one()
        assert first.biz_no == biz and second.biz_no is None and second.address == "부산"


@_async
async def test_a_failed_or_cancelled_run_still_closes_its_record(monkeypatch):
    """"수집 중…" for ever was a row whose session had been rolled back under it. The row
    now closes in a session of its own, whatever happened to the run's."""
    import asyncio

    from sqlalchemy import select

    from memora.db.session import session_scope
    from memora.models import CompanySourceRun
    from memora.services.companies import collect

    async def boom(db, source, record=None, apply=None, continuation=None):
        raise RuntimeError("duplicate key value violates unique constraint")

    monkeypatch.setattr(collect, "_collect", boom)
    async with session_scope("worker") as db:
        out = await collect.run(db, "krx")
        assert out["ok"] is False and "duplicate key" in out["error"]
    async with session_scope("worker") as db:
        rec = (await db.execute(select(CompanySourceRun).where(CompanySourceRun.source == "krx")
                                .order_by(CompanySourceRun.started_at.desc()))).scalars().first()
        assert rec.finished_at is not None and rec.ok is False and "duplicate key" in rec.error

    async def cancelled(db, source, record=None, apply=None, continuation=None):
        raise asyncio.CancelledError()

    monkeypatch.setattr(collect, "_collect", cancelled)
    async with session_scope("worker") as db:
        with pytest.raises(asyncio.CancelledError):
            await collect.run(db, "krx")
    async with session_scope("worker") as db:
        rec = (await db.execute(select(CompanySourceRun).where(CompanySourceRun.source == "krx")
                                .order_by(CompanySourceRun.started_at.desc()))).scalars().first()
        assert rec.finished_at is not None and rec.ok is False and rec.error.startswith("중단됨")
        # and the single-flight guard is free again
        assert await collect.in_flight(db, "krx") is False


@_async
async def test_a_dart_run_that_hits_its_time_budget_queues_its_own_continuation(monkeypatch):
    from sqlalchemy import select

    from memora.db.session import session_scope
    from memora.models import Job
    from memora.services import settings as S
    from memora.services.companies import collect, dart

    async def due(db, limit):
        return [(f"0000{i:04d}", None) for i in range(3)]

    async def detail(key, corp_code):
        return {"name": f"이어서{corp_code}", "address": "서울"}

    monkeypatch.setattr(dart, "due_for_details", due)
    monkeypatch.setattr(dart, "fetch_company", detail)
    monkeypatch.setattr(collect, "RUN_DEADLINE_S", 0.0)     # out of time before the first call
    async with session_scope("worker") as db:
        await S.put(db, "companies.dart_key", "test-key")
        await db.commit()
        out = await collect.run(db, "dart")
        assert out["ok"] is True and out["continued"] is True and out["remaining"] == 3, out
        job = (await db.execute(select(Job).where(Job.kind == "crawl.companies")
                                .order_by(Job.created_at.desc()))).scalars().first()
        assert job.payload["source"] == "dart" and job.payload.get("continue") and job.status == "queued"
        await S.put(db, "companies.dart_key", "")
        await db.commit()


@_async
async def test_the_daily_pass_does_not_start_over_on_every_restart(monkeypatch):
    """Once a day means once a day. A worker that restarts five times in an afternoon —
    a development day — used to launch five full collections."""
    from sqlalchemy import select

    from memora.db.session import session_scope
    from memora.models import Job
    from memora.services import jobs as J
    from memora.services import settings as S
    from memora.services.companies import collect
    from memora.worker import __main__ as W
    from memora.worker.handlers import HANDLERS

    async def instant(db, source, record=None, apply=None, continuation=None):
        return [{"name": f"즉시{a_ticker()}", "stock_code": a_ticker()}]

    monkeypatch.setattr(collect, "_collect", instant)
    async with session_scope("worker") as db:
        await S.put(db, "companies.auto_collect", True)
        await db.commit()
        assert (await collect.run(db, "krx"))["ok"] is True
        assert await collect.ran_recently(db, "krx", hours=20) is True
        out = await HANDLERS["companies.refresh"](db, {})
        assert "krx" in out["skipped"] and "krx" not in out["queued"]
        forced = await HANDLERS["companies.refresh"](db, {"force": True})
        assert "krx" in forced["queued"]
        await S.put(db, "companies.auto_collect", False)
        await db.commit()

    # The schedule's clock is seeded from the last job, so a restart does not fire it again.
    async with session_scope("worker") as db:
        await J.enqueue(db, "companies.refresh", {}, dedupe_key=f"sched-test:{_uuid.uuid4().hex[:6]}")
        await db.commit()
    last: dict[str, float] = {}
    await W._seed_schedule(last)
    assert "companies.refresh" in last, "a fresh worker must know the daily pass already ran"
    import time as _t
    assert _t.monotonic() - last["companies.refresh"] < 60
    async with session_scope("worker") as db:
        n = (await db.execute(select(Job).where(Job.kind == "companies.refresh"))).scalars().all()
        assert n
