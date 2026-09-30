"""한국의 특별한 날 (plan/60): 공휴일·대체공휴일·명절·24절기·기념일·음력.

내장 계산은 알려진 날짜로 확인한다(사용자가 보여 준 달력의 2026년 9월, 공식 발표된 2024·2025년 값).
공식 출처(한국천문연구원 특일 정보)는 HTTP 만 흉내 내고, 받아 온 해가 내장 계산을 대신하는지 본다.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from memora.db.session import session_scope
from memora.models import SpecialDay, User
from memora.services import settings as S
from memora.services import special_days as SD
from tests.conftest import auth, signup

KST = ZoneInfo("Asia/Seoul")


def _on(year: int, d: date) -> list[SD.Day]:
    return [x for x in SD.builtin(year) if x.day == d]


def _names(year: int, d: date) -> list[str]:
    return [x.name for x in _on(year, d)]


# ── 내장 계산 ──────────────────────────────────────────────────────────


def test_september_2026_reads_like_a_korean_calendar():
    """사용자가 보여 준 달력 그대로: 추석 사흘, 백로·추분, 청년의 날, 음력 8월 1일·15일."""
    for d, n in ((date(2026, 9, 24), "추석 전날"), (date(2026, 9, 25), "추석"), (date(2026, 9, 26), "추석 다음날")):
        x = _on(2026, d)
        assert [(y.name, y.off) for y in x if y.kind == "holiday"] == [(n, True)]
    assert "백로" in _names(2026, date(2026, 9, 7)) and "추분" in _names(2026, date(2026, 9, 23))
    assert "청년의 날" in _names(2026, date(2026, 9, 19))
    assert SD.lunar(date(2026, 9, 11)) == (8, 1, False) and SD.lunar(date(2026, 9, 25)) == (8, 15, False)
    # 쉬는 날이 아닌 날은 쉬는 날이 아니다.
    assert not any(x.off for x in _on(2026, date(2026, 9, 7)))


def test_substitute_and_election_and_temporary_holidays():
    off = {x.day: x.name for x in SD.builtin(2026) if x.off}
    # 2026년: 일요일·토요일과 겹친 날의 대체공휴일, 지방선거일, 법 개정으로 공휴일이 된 노동절·제헌절
    for d in (date(2026, 3, 2), date(2026, 5, 25), date(2026, 8, 17), date(2026, 10, 5)):
        assert off[d] == "대체공휴일"
    assert off[date(2026, 6, 3)] == "지방선거일" and off[date(2026, 5, 1)] == "노동절" and off[date(2026, 7, 17)] == "제헌절"
    assert off[date(2026, 1, 1)] == "신정" and off[date(2026, 12, 25)] == "성탄절"
    # 현충일은 대체공휴일이 없다(2026-06-06 토요일).
    assert date(2026, 6, 8) not in off
    off25 = {x.day: x.name for x in SD.builtin(2025) if x.off}
    # 2025년 1월 27일 임시공휴일, 어린이날·부처님오신날이 겹친 5월 5일의 다음 날, 추석이 일요일과 겹친 10월 8일
    assert off25[date(2025, 1, 27)] == "임시공휴일" and off25[date(2025, 5, 6)] == "대체공휴일"
    assert off25[date(2025, 10, 8)] == "대체공휴일" and off25[date(2025, 6, 3)] == "대통령 선거일"
    # 2026년 전에는 제헌절·근로자의 날이 쉬는 날이 아니었다 — 기념일로만.
    assert [(x.kind, x.off) for x in _on(2025, date(2025, 7, 17))] == [("anniversary", False)]


def test_solar_terms_are_on_the_korean_date():
    """태양의 겉보기 위치로 계산한다. 2025년 동지는 한국 시각 12월 22일 00:03 — 하루 앞당기면 틀린다."""
    terms25 = {n: (d, at) for d, n, at in SD.solar_terms(2025)}
    assert terms25["동지"][0] == date(2025, 12, 22) and terms25["동지"][1].strftime("%H:%M") in ("00:02", "00:03")
    terms26 = {n: d for d, n, _ in SD.solar_terms(2026)}
    assert terms26["입춘"] == date(2026, 2, 4) and len(terms26) == 24
    terms24 = {n: (d, at) for d, n, at in SD.solar_terms(2024)}
    assert terms24["춘분"][0] == date(2024, 3, 20) and terms24["동지"][0] == date(2024, 12, 21)


def test_folk_days_follow_the_lunar_and_sexagenary_rules():
    n24 = {x.name: x.day for x in SD.builtin(2024) if x.kind == "festival"}
    n25 = {x.name: x.day for x in SD.builtin(2025) if x.kind == "festival"}
    # 삼복: 하지 뒤 셋째·넷째 경일, 입추 뒤 첫 경일 (2024년은 말복이 한 번 건너뛴 월복)
    assert (n24["초복"], n24["중복"], n24["말복"]) == (date(2024, 7, 15), date(2024, 7, 25), date(2024, 8, 14))
    assert (n25["초복"], n25["중복"], n25["말복"]) == (date(2025, 7, 20), date(2025, 7, 30), date(2025, 8, 9))
    assert n25["한식"] == date(2025, 4, 5)
    n26 = {x.name: x.day for x in SD.builtin(2026) if x.kind == "festival"}
    assert n26["정월대보름"] == date(2026, 3, 3) and SD.lunar(n26["단오"])[:2] == (5, 5)


# ── 공식 출처 ──────────────────────────────────────────────────────────


class _R:
    def __init__(self, body):
        self._b = body
        self.text = json.dumps(body)

    def json(self):
        return self._b


def _envelope(items):
    body = {"items": "" if not items else {"item": items[0] if len(items) == 1 else items},
            "numOfRows": 100, "pageNo": 1, "totalCount": len(items)}
    return {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}, "body": body}}


def _kasi_year(year: int, *, extra_holiday: tuple[date, str] | None = None):
    """공식 출처가 줄 법한 한 해 — 내장 계산에서 만들고, 이름은 공식 출처의 이름으로."""
    base = SD.builtin(year)
    official_name = {"신정": "1월1일", "성탄절": "기독탄신일", "설날 전날": "설날", "설날 다음날": "설날",
                     "추석 전날": "추석", "추석 다음날": "추석"}
    table: dict[str, list[dict]] = {op: [] for op in SD.OPS}
    for x in base:
        item = {"locdate": int(x.day.strftime("%Y%m%d")), "dateName": official_name.get(x.name, x.name),
                "isHoliday": "Y" if x.off else "N", "seq": 1}
        op = {"holiday": "getRestDeInfo", "festival": "getSundryDayInfo", "solar_term": "get24DivisionsInfo"}.get(x.kind)
        if x.kind == "anniversary":
            op = "getAnniversaryInfo"
        table[op].append(item)
    # 기념일은 공식 출처가 훨씬 많다
    for i in range(25):
        d = date(year, 1, 1) + timedelta(days=i * 13)
        table["getAnniversaryInfo"].append({"locdate": int(d.strftime("%Y%m%d")), "dateName": f"기념일{i}", "isHoliday": "N"})
    if extra_holiday:
        d, n = extra_holiday
        table["getRestDeInfo"].append({"locdate": int(d.strftime("%Y%m%d")), "dateName": n, "isHoliday": "Y"})
    table["getHoliDeInfo"].append({"locdate": int(date(year, 7, 17).strftime("%Y%m%d")), "dateName": "제헌절", "isHoliday": "Y"})
    return table


def _fake_kasi(monkeypatch, years: dict[int, dict[str, list[dict]]], calls: list | None = None):
    async def fake_request(method, url, **kw):
        op = url.rsplit("/", 1)[1]
        p = kw["params"]
        if calls is not None:
            calls.append((op, p["solYear"], p["solMonth"], p["ServiceKey"]))
        y, m = int(p["solYear"]), int(p["solMonth"])
        items = [it for it in years.get(y, {}).get(op, []) if str(it["locdate"])[4:6] == f"{m:02d}"]
        return _R(_envelope(items))

    monkeypatch.setattr(SD, "request", fake_request)


@pytest_asyncio.fixture(autouse=True)
async def _clean(app):
    yield
    async with session_scope() as db:
        await db.execute(delete(SpecialDay))
        await S.put(db, "holidays.kasi.enabled", False)
        await S.put(db, "holidays.kasi.key", "")
        await S.put(db, "holidays.kasi.status", {})
        await db.commit()
    S.invalidate("holidays.")


def test_the_portal_answers_are_read_whatever_shape_they_come_in():
    one = _envelope([{"locdate": 20260925, "dateName": "추석", "isHoliday": "Y"}])
    assert SD._items(one) == [{"locdate": 20260925, "dateName": "추석", "isHoliday": "Y"}]      # 하나면 목록이 아니라 객체
    assert SD._items(_envelope([])) == []                                                        # 없으면 빈 문자열
    err = json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
                                                                   "returnAuthMsg": "등록되지 않은 서비스키", "returnReasonCode": "30"}}})
    assert SD._kasi_error(err).code == "invalid_key"
    xml = "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg><returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>"
    assert SD._kasi_error(xml).code == "quota"
    # 포털의 "Encoding" 키를 붙여 넣어도 두 번 인코딩되지 않는다.
    assert SD._key("abc%2Bdef%3D%3D") == "abc+def==" and SD._key(" abc+def== ") == "abc+def=="
    # 공식 출처의 "설날"·"추석" 사흘은 음력으로 전날·당일·다음날
    assert SD._norm("추석", date(2026, 9, 24)) == "추석 전날" and SD._norm("설날", date(2026, 2, 18)) == "설날 다음날"
    assert SD._norm("대체공휴일", date(2026, 3, 2)) == "대체공휴일" and SD._norm("1월1일", date(2026, 1, 1)) == "신정"


async def test_an_official_year_replaces_the_builtin_one(monkeypatch):
    y = datetime.now(KST).year
    surprise = date(y, 11, 17)         # 정부가 갑자기 정한 임시공휴일이라고 치자
    calls: list = []
    _fake_kasi(monkeypatch, {y: _kasi_year(y, extra_holiday=(surprise, "임시공휴일"))}, calls)
    async with session_scope() as db:
        before = (await SD.year_of(db, y)).version
        await S.put(db, "holidays.kasi.key", "k%2Bey")
        await S.put(db, "holidays.kasi.enabled", True)
        await db.commit()
    S.invalidate("holidays.")
    async with session_scope() as db:
        out = await SD.sync(db)
        await db.commit()
    assert out[str(y)]["holiday"] >= 10 and out[str(y)]["full"] is True and "error" not in out[str(y + 1)]
    # 처음에는 다섯 가지를 열두 달씩, 두 해. 키는 풀어서 보낸다.
    assert len(calls) == 5 * 12 * 2 and {c[3] for c in calls} == {"k+ey"}
    S.invalidate("holidays.")
    async with session_scope() as db:
        days = await SD.between(db, date(y, 11, 1), date(y, 11, 30))
        off = await SD.off_days(db, date(y, 1, 1), date(y, 12, 31))
        st = await SD.status(db)
        after = (await SD.year_of(db, y)).version
    assert after != before, "내용이 바뀌었으니 버전이 바뀐다 — 브라우저가 새로 받는다"
    assert days[surprise.isoformat()]["off"] and days[surprise.isoformat()]["names"][0]["name"] == "임시공휴일"
    assert off[surprise] == "임시공휴일"
    this = next(v for v in st["years"] if v["year"] == y)
    nxt = next(v for v in st["years"] if v["year"] == y + 1)
    assert this["sources"] == {"holiday": "kasi", "festival": "kasi", "solar_term": "kasi", "anniversary": "kasi"}
    assert this["complete"] is True and this["checked_at"] and this["changed_at"] and this["version"] == after
    # 공식 출처가 쉬는 날을 다르게 본 날을 관리자에게 보여 준다.
    assert this["only_official"] == [{"date": surprise.isoformat(), "name": "임시공휴일"}] and this["only_builtin"] == []
    # 내년은 아직 발표 전(개수가 모자람) — 내장 계산을 그대로 쓰고, 견주지 않는다.
    assert nxt["sources"]["holiday"] == "builtin" and nxt["only_official"] == [] and nxt["complete"] is False
    # 이름은 달력에서 읽히는 이름으로
    sept = {d: v for d, v in (await _between(y)).items() if v["off"]}
    assert all(n["name"] not in ("기독탄신일", "1월1일") for v in sept.values() for n in v["names"])


async def test_a_settled_year_is_only_checked_for_new_holidays(monkeypatch):
    """한 해치가 다 발표되면 고정 — 그 뒤로는 공휴일만 확인하고, 같으면 아무것도 쓰지 않는다(버전 그대로)."""
    from sqlalchemy import func, select

    y = datetime.now(KST).year
    table = _kasi_year(y)
    calls: list = []
    _fake_kasi(monkeypatch, {y: table}, calls)
    async with session_scope() as db:
        await S.put(db, "holidays.kasi.key", "key")
        await S.put(db, "holidays.kasi.enabled", True)
        await SD.sync(db)
        await db.commit()
    S.invalidate("holidays.")
    async with session_scope() as db:
        v1 = (await SD.year_of(db, y)).version
        stamp = (await db.execute(select(func.max(SpecialDay.fetched_at)).where(SpecialDay.year == y))).scalar_one()
    calls.clear()
    async with session_scope() as db:
        out = await SD.sync(db)
        await db.commit()
    # 올해는 공휴일 한 가지만 열두 달. 내년은 아직 덜 발표됐지만 일주일이 안 지나 역시 공휴일만.
    assert {c[0] for c in calls} == {"getRestDeInfo"} and len(calls) == 24
    assert out[str(y)] == {**out[str(y)], "full": False, "changed": []}
    S.invalidate("holidays.")
    async with session_scope() as db:
        assert (await SD.year_of(db, y)).version == v1, "바뀐 것이 없으면 버전도 그대로"
        again = (await db.execute(select(func.max(SpecialDay.fetched_at)).where(SpecialDay.year == y))).scalar_one()
        assert again == stamp, "같은 내용은 다시 쓰지 않는다"
    # 정부가 임시공휴일을 정했다 → 공휴일 확인에서 잡힌다.
    surprise = date(y, 12, 30)
    table["getRestDeInfo"].append({"locdate": int(surprise.strftime("%Y%m%d")), "dateName": "임시공휴일", "isHoliday": "Y"})
    async with session_scope() as db:
        out = await SD.sync(db)
        await db.commit()
    assert out[str(y)]["changed"] == ["holiday"]
    S.invalidate("holidays.")
    async with session_scope() as db:
        y2 = await SD.year_of(db, y)
        assert y2.version != v1 and [x.name for x in y2.by_date[surprise] if x.off] == ["임시공휴일"]
    # 포털이 잠깐 빈 답을 주면(오류) 앞서 받은 공휴일을 지우지 않는다.
    table["getRestDeInfo"].clear()
    async with session_scope() as db:
        out = await SD.sync(db)
        await db.commit()
    assert out[str(y)]["kept"] == ["holiday"]
    S.invalidate("holidays.")
    async with session_scope() as db:
        assert (await SD.year_of(db, y)).sources["holiday"] == "kasi"


async def test_a_year_is_built_once_per_process():
    y = datetime.now(KST).year
    async with session_scope() as db:
        a = await SD.year_of(db, y)
        b = await SD.year_of(db, y)
    assert a is b, "같은 버전이면 만들어 둔 것을 그대로"


async def _between(y: int):
    async with session_scope() as db:
        return await SD.between(db, date(y, 1, 1), date(y, 12, 31))


async def test_a_failed_sync_keeps_what_was_there(monkeypatch):
    y = datetime.now(KST).year
    _fake_kasi(monkeypatch, {y: _kasi_year(y)})
    async with session_scope() as db:
        await S.put(db, "holidays.kasi.key", "key")
        await SD.sync(db, force=True)
        await db.commit()

    async def refused(method, url, **kw):
        from memora.providers.http import ProviderHTTPError
        raise ProviderHTTPError(403, json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"}}}))

    monkeypatch.setattr(SD, "request", refused)
    async with session_scope() as db:
        out = await SD.sync(db, force=True)
        await db.commit()
    assert out[str(y)] == {"error": "invalid_key"}
    async with session_scope() as db:
        st = await SD.status(db)
    assert st["last_error"]["code"] == "invalid_key"
    assert next(v for v in st["years"] if v["year"] == y)["sources"]["holiday"] == "kasi", "앞서 받은 해는 그대로"


# ── 스케줄 ─────────────────────────────────────────────────────────────


async def test_the_calendar_page_gets_a_whole_year_once(client: AsyncClient):
    """공휴일은 한 해치로 따로, 로그인 없이. 브라우저는 받아 두고 ETag 로 확인만 한다. 스케줄은 내 일정만."""
    r = await client.get("/api/calendar/KR/2026")
    assert r.status_code == 200 and r.headers["etag"].startswith('"') and "max-age" in r.headers["cache-control"]
    j = r.json()
    assert j["year"] == 2026 and j["version"] == r.headers["etag"].strip('"') and len(j["lunar"]) == 365
    d = j["days"]
    assert d["2026-09-25"] == {"off": True, "names": [{"name": "추석", "kind": "holiday", "off": True}]}
    assert {"name": "백로", "kind": "solar_term", "off": False} in d["2026-09-07"]["names"] and not d["2026-09-07"]["off"]
    # 이름 없는 날은 싣지 않는다 — 음력은 날마다 따로(1월 1일이 0번째).
    assert "2026-09-11" not in d and j["lunar"][date(2026, 9, 11).timetuple().tm_yday - 1] == "8.1"
    # 일요일은 달력이 스스로 칠한다.
    assert "2026-09-27" not in d
    # 바뀌지 않았으면 본문 없이 304.
    again = await client.get("/api/calendar/KR/2026", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304 and not again.content and again.headers["etag"] == r.headers["etag"]
    weak = await client.get("/api/calendar/KR/2026", headers={"If-None-Match": "W/" + r.headers["etag"]})
    assert weak.status_code == 304
    # 지난해는 오래 둔다.
    assert "max-age=604800" in (await client.get("/api/calendar/KR/2020")).headers["cache-control"]
    assert (await client.get("/api/calendar/KR/2051")).status_code == 404
    assert (await client.get("/api/calendar/US/2026")).status_code == 404
    _, tok = await signup(client)
    sched = (await client.get("/api/schedule", params={"from": "2026-09-01", "to": "2026-09-30"}, headers=auth(tok))).json()
    assert set(sched) == {"timezone", "events"}, "스케줄은 이 사람의 것만"


def _next_off_weekday() -> date:
    """오늘 뒤 이틀 이상 지난, 평일에 든 공휴일."""
    today = datetime.now(KST).date()
    return next(x.day for y in (today.year, today.year + 1) for x in SD.builtin(y)
                if x.off and x.day > today + timedelta(days=2) and x.day.weekday() < 5)


async def test_free_time_skips_public_holidays_unless_told_otherwise(client: AsyncClient):
    from memora.services import profile as PF
    from memora.services import schedule as SCH

    user, tok = await signup(client)
    hol = _next_off_weekday()
    r = (await client.put("/api/schedule/availability", headers=auth(tok),
                          json={"weekly": [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "10:00", "end": "12:00"}]})).json()
    assert r["skip_holidays"] is True, "정한 적이 없으면 공휴일은 비운다"

    async def slots() -> list[str]:
        async with session_scope() as db:
            owner = await db.get(User, uuid.UUID(user["id"]))
            prof = await PF.get(db, owner.id)
            start = datetime.combine(hol - timedelta(days=1), datetime.min.time(), KST)
            got = await SCH.free_slots(db, owner, prof, start=start, end=start + timedelta(days=3), limit=40)
            return sorted({s["start"][:10] for s in got}), SCH.describe_for_prompt(prof)

    days, words = await slots()
    assert hol.isoformat() not in days and len(days) == 2 and "not on public holidays" in words
    r = (await client.put("/api/schedule/availability", headers=auth(tok), json={"skip_holidays": False})).json()
    assert r["skip_holidays"] is False and r["weekly"], "스위치만 바꿔도 주간 표는 그대로"
    days, words = await slots()
    assert hol.isoformat() in days and "public holidays" not in words


async def test_the_secretary_knows_the_holidays(client: AsyncClient):
    """주인에게는 그 기간의 특별한 날을, 외부인에게는 공휴일이라 비운 날을 말할 수 있게."""
    from types import SimpleNamespace

    from memora.pipeline.tools.schedule_tools import CalendarAvailability, CalendarList
    from memora.services import outsider as OUT
    from memora.services import profile as PF

    user, tok = await signup(client)
    hol = _next_off_weekday()
    await client.put("/api/schedule/availability", headers=auth(tok),
                     json={"weekly": [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "10:00", "end": "12:00"}]})
    async with session_scope() as db:
        owner = await db.get(User, uuid.UUID(user["id"]))
        prof = await PF.get(db, owner.id)
    ctx = SimpleNamespace(owner=owner, owner_id=owner.id, profile=prof, audience="owner", viewer="owner",
                          disclosure=OUT.OWNER, cards=[], card=lambda *a, **k: None)
    listed = json.loads((await CalendarList(ctx).execute({"start": str(hol), "end": str(hol)}, None)).content)
    assert listed["special_days"][0]["date"] == f"{hol.isoformat()} ({hol.strftime('%a')})" and listed["special_days"][0]["day_off"] is True   # 요일을 붙여 준다
    free = json.loads((await CalendarAvailability(ctx).execute(
        {"start": str(hol - timedelta(days=1)), "end": str(hol + timedelta(days=1))}, None)).content)
    assert any(x.startswith(hol.isoformat()) for x in free["public_holidays_off"])
    assert not any(s.startswith(hol.isoformat()) for s in free["free_slots"])


# ── 관리자 ─────────────────────────────────────────────────────────────


async def _admin(client: AsyncClient) -> str:
    user, _ = await signup(client)
    async with session_scope() as db:
        (await db.get(User, uuid.UUID(user["id"]))).role = "admin"
        await db.commit()
    return (await client.post("/api/auth/login", json={"email": user["email"], "password": "correct-horse-9"})).json()["access_token"]


async def test_the_admin_connects_the_official_source(client: AsyncClient, monkeypatch):
    from sqlalchemy import select

    from memora.models import Job

    tok = await _admin(client)
    _, utok = await signup(client)
    assert (await client.get("/api/admin/holidays", headers=auth(utok))).status_code == 403
    j = (await client.get("/api/admin/holidays", headers=auth(tok))).json()
    assert j["enabled"] is False and j["key"]["has_value"] is False and j["dataset_url"].startswith("https://www.data.go.kr/")
    assert all(v["sources"]["holiday"] == "builtin" for v in j["years"]) and j["builtin"].startswith("holidays ")
    r = await client.put("/api/admin/holidays", json={"enabled": True}, headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "holidays_key_missing"
    r = (await client.put("/api/admin/holidays", json={"key": "  secret-service-key  "}, headers=auth(tok))).json()
    assert r["key"]["has_value"] and "secret-service-key" not in json.dumps(r)

    async def refused(method, url, **kw):
        from memora.providers.http import ProviderHTTPError
        raise ProviderHTTPError(403, json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"}}}))

    monkeypatch.setattr(SD, "request", refused)
    chk = (await client.post("/api/admin/holidays/check", headers=auth(tok))).json()
    assert chk == {"ok": False, "code": "invalid_key", "detail": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"}
    y = datetime.now(KST).year
    _fake_kasi(monkeypatch, {y: _kasi_year(y)})
    assert (await client.post("/api/admin/holidays/check", headers=auth(tok))).json()["ok"] is True
    # 켜면 바로 한 번 받아 오게 건다.
    r = (await client.put("/api/admin/holidays", json={"enabled": True}, headers=auth(tok))).json()
    assert r["enabled"] is True
    async with session_scope() as db:
        assert (await db.execute(select(Job).where(Job.kind == "holidays.sync", Job.status == "queued"))).first()
    # 키를 지우면 꺼진다.
    r = (await client.put("/api/admin/holidays", json={"clear_key": True}, headers=auth(tok))).json()
    assert r["enabled"] is False and r["key"]["has_value"] is False
