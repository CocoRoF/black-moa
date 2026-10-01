"""[내 정보 → 스케줄] (plan/56).

- 일정은 주인의 시간대로 읽고 쓴다(오프셋 없는 "15:00" 은 주인의 15시).
- 빈 시간은 연락 가능 시간 안에서, 바쁜 일정만 막는다(종일 일정은 기본으로 막지 않는다).
- 방문자에게는 연락 가능 시간의 공개 범위가 허락할 때만 빈 시간이 나간다.
- 방문자 프롬프트에 [나만 보기] 로 둔 연락 가능 시간·연락 규칙이 들어가던 누수.
- Google 종일 일정은 주인의 자정, "한가함" 표시는 빈 시간을 막지 않는다. Google 에도 넣은 일정은 한 번만.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from tests.conftest import auth, signup

pytestmark = pytest.mark.asyncio
KST = ZoneInfo("Asia/Seoul")


def _next_weekday(wd: int) -> date:
    """다음 그 요일 — 공휴일이면 그다음 주로. 공휴일에는 빈 시간이 나지 않는다 (plan/60)."""
    from blackmoa.services import special_days as SD
    d = datetime.now(KST).date() + timedelta(days=1)
    off = {x.day for y in (d.year, d.year + 1) for x in SD.builtin(y) if x.off}
    while d.weekday() != wd or d in off:
        d += timedelta(days=1)
    return d


async def test_events_are_written_and_read_in_the_owners_time(client: AsyncClient):
    _, tok = await signup(client)
    day = _next_weekday(2)
    r = await client.post("/api/schedule/events", headers=auth(tok),
                          json={"title": "치과", "start": f"{day}T15:00", "end": f"{day}T16:00", "location": "강남"})
    assert r.status_code == 201, r.text
    ev = r.json()
    assert ev["start"] == f"{day}T15:00:00+09:00" and ev["busy"] is True and ev["source"] == "owner"
    # 시작만 옮기면 길이는 그대로.
    moved = (await client.patch(f"/api/schedule/events/{ev['id']}", headers=auth(tok), json={"start": f"{day}T17:30"})).json()
    assert moved["start"].startswith(f"{day}T17:30") and moved["end"].startswith(f"{day}T18:30")
    allday = (await client.post("/api/schedule/events", headers=auth(tok),
                                json={"title": "생일", "all_day": True, "start": str(day), "end": str(day)})).json()
    assert allday["start_date"] == allday["end_date"] == str(day) and allday["busy"] is False
    listed = (await client.get(f"/api/schedule?from={day}&to={day}", headers=auth(tok))).json()
    assert [e["title"] for e in listed["events"]] == ["생일", "치과"] and listed["timezone"] == "Asia/Seoul"
    bad = await client.post("/api/schedule/events", headers=auth(tok), json={"title": "x", "start": f"{day}T15:00", "end": f"{day}T14:00"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "bad_range"
    assert (await client.delete(f"/api/schedule/events/{ev['id']}", headers=auth(tok))).status_code == 204
    _, other = await signup(client)
    assert (await client.delete(f"/api/schedule/events/{allday['id']}", headers=auth(other))).status_code == 404


async def test_free_time_sits_inside_the_hours_and_around_busy_events(client: AsyncClient):
    _, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "일정비서"}, headers=auth(tok))).json()
    mon = _next_weekday(0)
    r = await client.put("/api/schedule/availability", headers=auth(tok),
                         json={"weekly": [{"days": [0], "start": "10:00", "end": "12:00"}], "note": "오전만"})
    # 연락 가능 시간에는 공개 범위가 없다 — 외부인에게 알려 줄지는 비서의 [지식] 탭이 정한다 (plan/57).
    assert r.status_code == 200 and "visibility" not in r.json() and "preview" not in r.json()
    await client.post("/api/schedule/events", headers=auth(tok), json={"title": "회의", "start": f"{mon}T10:00", "end": f"{mon}T11:00"})
    await client.post("/api/schedule/events", headers=auth(tok), json={"title": "기념일", "all_day": True, "start": str(mon)})
    view = (await client.get(f"/api/agents/{agent['id']}/outsider", headers=auth(tok))).json()
    mine = [s for s in view["schedule"]["preview"] if s["start"].startswith(str(mon))]
    # 10–11 은 회의, 11–12 만 빈다. 종일 기념일은 막지 않는다.
    if datetime.now(KST).date() + timedelta(days=5) >= mon:
        assert [s["label"][-11:] for s in mine] == ["11:00–12:00"]
    # 메모만 고쳐도 주간 표는 그대로.
    kept = (await client.put("/api/schedule/availability", headers=auth(tok), json={"note": "바뀐 메모"})).json()
    assert kept["weekly"] == [{"days": [0], "start": "10:00", "end": "12:00"}] and kept["note"] == "바뀐 메모"
    hidden = (await client.patch(f"/api/agents/{agent['id']}/outsider", headers=auth(tok), json={"schedule": "off"})).json()
    assert hidden["schedule"]["preview"] == [] and hidden["settings"]["schedule"] == "off"


async def _world(client, visibility: str):
    """``visibility``: 이 비서가 외부인에게 빈 시간을 알려 주는 범위이자, 연락 규칙 칸의 프로필 공개 범위."""
    from blackmoa.db.session import session_scope
    from blackmoa.models import Agent, User
    from blackmoa.services import profile as PF

    user, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "일정비서"}, headers=auth(tok))).json()
    await client.put("/api/schedule/availability", headers=auth(tok),
                     json={"weekly": [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "09:00", "end": "18:00"}]})
    await client.patch(f"/api/agents/{agent['id']}/outsider", headers=auth(tok),
                       json={"schedule": "off" if visibility == "private" else visibility})
    await client.put("/api/users/me/profile", headers=auth(tok),
                     json={"data": {"contact_rules": "급한 일만 연락"}, "visibility": {"contact_rules": visibility}})
    async with session_scope() as db:
        owner = await db.get(User, uuid.UUID(user["id"]))
        a = await db.get(Agent, uuid.UUID(agent["id"]))
        prof = await PF.get(db, owner.id)
        return owner, a, prof, tok


def _ctx(owner, a, prof, audience="owner", viewer="owner", disclosure=None):
    cards = []
    ctx = SimpleNamespace(owner=owner, owner_id=owner.id, agent=a, audience=audience, profile=prof, viewer_level=viewer,
                          visitor=None, relay_id=None, cards=cards, emit=None, disclosure=disclosure)
    ctx.card = lambda t, p: cards.append({"card_type": t, "payload": p})
    return ctx


async def _vctx(owner, a, prof, viewer):
    """러너가 턴마다 하는 것처럼 — 이 비서의 [지식] 탭대로 이 사람에게 쓸 것을 정한 외부인 대화."""
    from blackmoa.db.session import session_scope
    from blackmoa.services import outsider as OUT
    async with session_scope() as db:
        return _ctx(owner, a, prof, "visitor", viewer, await OUT.for_turn(db, a, viewer))


async def test_visitors_get_free_time_only_when_the_owner_shares_it(client: AsyncClient):
    from blackmoa.pipeline.tools.schedule_tools import CalendarAvailability

    owner, a, prof, _ = await _world(client, "private")
    stranger = json.loads((await CalendarAvailability(await _vctx(owner, a, prof, "stranger")).execute({}, None)).content)
    assert stranger["error"]["code"] == "calendar_private"
    mine = json.loads((await CalendarAvailability(_ctx(owner, a, prof)).execute({}, None)).content)
    assert mine["free_slots"]                                     # 주인 자신에게는 늘

    owner2, a2, prof2, _ = await _world(client, "known")
    assert "error" in json.loads((await CalendarAvailability(await _vctx(owner2, a2, prof2, "stranger")).execute({}, None)).content)
    assert json.loads((await CalendarAvailability(await _vctx(owner2, a2, prof2, "known")).execute({}, None)).content)["free_slots"]


async def test_private_hours_and_rules_stay_out_of_visitor_prompts(client: AsyncClient):
    from blackmoa.db.session import session_scope
    from blackmoa.pipeline.runtime import collect_resources

    owner, a, prof, _ = await _world(client, "private")
    async with session_scope() as db:
        vis = await collect_resources(db, owner, a, "visitor", prof)
        own = await collect_resources(db, owner, a, "owner", prof)
    assert vis.availability_window is None and vis.contact_rules == ""
    assert own.availability_window and own.contact_rules == "급한 일만 연락"
    owner2, a2, prof2, _ = await _world(client, "public")
    async with session_scope() as db:
        vis2 = await collect_resources(db, owner2, a2, "visitor", prof2)
    assert vis2.availability_window and vis2.contact_rules


async def test_the_secretary_reads_and_writes_the_schedule_in_owner_chats(client: AsyncClient, google_on):
    from blackmoa.db.session import session_scope
    from blackmoa.models import Connection, IntegrationEvent
    from blackmoa.pipeline.tools.base import tool_names_for
    from blackmoa.pipeline.tools.schedule_tools import (
        CalendarList,
        ScheduleAdd,
        ScheduleRemove,
        ScheduleUpdate,
    )

    owner, a, prof, tok = await _world(client, "public")
    ctx = _ctx(owner, a, prof)
    day = _next_weekday(3)
    added = json.loads((await ScheduleAdd(ctx).execute({"title": "치과", "start": f"{day}T15:00"}, None)).content)["added"]
    assert added["when"].startswith(f"{day} (") and " 15:00" in added["when"] and ctx.cards[0]["card_type"] == "schedule_saved"
    json.loads((await ScheduleUpdate(ctx).execute({"event_id": added["id"], "start": f"{day}T16:00"}, None)).content)
    # Google 에서 가져온 일정도 함께, Google 에도 넣은 black-moa 일정은 한 번만.
    async with session_scope() as db:
        conn = Connection(owner_id=owner.id, provider="google", account_label="g@example.com", capabilities=["calendar_read"],
                          access_token_enc="", refresh_token_enc="", status="active", token_expires_at=datetime.now(UTC) + timedelta(hours=1))
        db.add(conn)
        await db.flush()
        start = datetime.combine(day, datetime.min.time(), KST) + timedelta(hours=11)
        db.add(IntegrationEvent(owner_id=owner.id, connection_id=conn.id, ext_id="g1", title="팀 점심", start_at=start, end_at=start + timedelta(hours=1)))
        await db.commit()
    listed = json.loads((await CalendarList(ctx).execute({"start": str(day), "end": str(day)}, None)).content)["events"]
    assert [(e["title"], e["from"]) for e in listed] == [("팀 점심", "Google Calendar"), ("치과", "black-moa")]
    assert "external_readonly" in json.dumps(json.loads((await ScheduleRemove(ctx).execute({"event_id": "google:g1"}, None)).content))
    json.loads((await ScheduleRemove(ctx).execute({"event_id": added["id"]}, None)).content)
    assert (await client.get(f"/api/schedule?from={day}&to={day}", headers=auth(tok))).json()["events"][0]["source"] == "google"
    # 쓰는 도구는 주인 대화에만, 빈 시간은 방문자에게도.
    v = tool_names_for(SimpleNamespace(**{**vars(_ctx(owner, a, prof, "visitor", "stranger")), "features": set(), "is_owner": False}))
    assert "calendar_availability" in v and not {"calendar_list", "schedule_add", "schedule_update", "schedule_remove"} & set(v)


async def test_google_all_day_events_start_at_the_owners_midnight(client: AsyncClient, monkeypatch, google_on):
    from blackmoa.db.session import session_scope
    from blackmoa.models import Connection, IntegrationEvent, User
    from blackmoa.services import google as G

    user, _ = await signup(client)
    async with session_scope() as db:
        conn = Connection(owner_id=uuid.UUID(user["id"]), provider="google", account_label="g@example.com", capabilities=["calendar_read"],
                          access_token_enc="", refresh_token_enc="", status="active", token_expires_at=datetime.now(UTC) + timedelta(hours=1))
        db.add(conn)
        await db.commit()
        cid = conn.id

    async def fake_token(db, conn):
        return "t"

    class R:
        def json(self):
            return {"items": [{"id": "b1", "summary": "생일", "start": {"date": "2026-10-03"}, "end": {"date": "2026-10-04"},
                               "transparency": "transparent"},
                              {"id": "m1", "summary": "회의", "start": {"dateTime": "2026-10-05T10:00:00+09:00"}, "end": {"dateTime": "2026-10-05T11:00:00+09:00"}}]}

    async def fake_request(*a, **k):
        return R()

    monkeypatch.setattr("blackmoa.services.connections.access_token", fake_token)
    monkeypatch.setattr(G, "request", fake_request)
    async with session_scope() as db:
        conn = await db.get(Connection, cid)
        assert await G.sync_calendar(db, conn) == 2
        await db.commit()
    from sqlalchemy import select
    async with session_scope() as db:
        rows = {e.ext_id: e for e in (await db.execute(select(IntegrationEvent).where(IntegrationEvent.connection_id == cid))).scalars().all()}
        assert rows["b1"].start_at.astimezone(KST).hour == 0 and rows["b1"].busy is False
        assert rows["m1"].busy is True
        assert await db.get(User, uuid.UUID(user["id"])) is not None
