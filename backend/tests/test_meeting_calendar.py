"""Accepting a meeting puts it on the calendar (plan/41 §9.2).

"일정을 잡아요" was on the landing page while accepting a meeting only changed a status
field. These tests are about the sentence being true, and about the ways it can fail
without taking the acceptance down with it.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from blackmoa.db.session import session_scope
from blackmoa.models import Agent, Connection, InboxItem
from tests.conftest import auth, signup


async def _meeting(owner_id: str, *, slots_iso: list[str] | None = None, email: str | None = None) -> str:
    async with session_scope() as db:
        agent = Agent(owner_id=_uuid.UUID(owner_id), name="비서", provider="fake", model_id="fake-1")
        db.add(agent)
        await db.flush()
        item = InboxItem(owner_id=_uuid.UUID(owner_id), agent_id=agent.id, kind="meeting_request", status="new",
                         payload={"visitor_name": "김민수", "purpose": "제안서 이야기", "duration_minutes": 45,
                                  "slots": ["9월 22일 오후 3시"], "slots_iso": slots_iso or [],
                                  **({"visitor_email": email} if email else {})})
        db.add(item)
        await db.flush()
        iid = str(item.id)
        await db.commit()
    return iid


async def _providers_on(on: bool) -> None:
    """관리자 [연결] 에서 Google·카카오를 켠다 (plan/59) — 꺼져 있으면 바깥 달력에 넣지 않는다."""
    from blackmoa.services import settings as S
    async with session_scope() as db:
        for p in ("google", "kakao"):
            await S.put(db, f"oauth.{p}.enabled", on)
            await S.put(db, f"oauth.{p}.client_id", "cid" if on else "")
            await S.put(db, f"oauth.{p}.client_secret", "sec" if on else "")
        await db.commit()
    S.invalidate("oauth.")


@pytest_asyncio.fixture(autouse=True)
async def _admin_turned_providers_on(app):
    await _providers_on(True)
    yield
    await _providers_on(False)


async def _connect(owner_id: str, caps: list[str], provider: str = "google") -> None:
    async with session_scope() as db:
        db.add(Connection(owner_id=_uuid.UUID(owner_id), provider=provider, account_label="who@example.com",
                          capabilities=caps, access_token_enc="", refresh_token_enc="", status="active",
                          token_expires_at=datetime.now(UTC) + timedelta(hours=1)))
        await db.commit()


def _when() -> str:
    return (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0).isoformat()


def _around(iso: str) -> str:
    """그 시각을 품는 기간 — 주인 시간대(서울)에서는 UTC 날짜가 하루 넘어가 있을 수 있다."""
    d = datetime.fromisoformat(iso).date()
    return f"from={d - timedelta(days=1)}&to={d + timedelta(days=1)}"


async def test_accepting_writes_the_event_and_invites_the_visitor(client: AsyncClient, monkeypatch):
    user, tok = await signup(client)
    await _connect(user["id"], ["calendar_read", "calendar_write"])
    iid = await _meeting(user["id"], email="minsu@example.com")
    seen = {}

    async def fake_create(db, conn, **kw):
        seen.update(kw)
        return {"id": "ev_1", "html_link": "https://calendar.google.com/ev_1"}

    monkeypatch.setattr("blackmoa.services.google.create_event", fake_create)
    start = _when()
    r = await client.post(f"/api/inbox/{iid}/status", json={"status": "accepted", "start_at": start, "duration_minutes": 45},
                          headers=auth(tok))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "accepted" and j["calendar"]["created"] is True and j["calendar"]["external"] == {"provider": "google", "label": "Google Calendar", "status": "added"}
    assert j["calendar"]["html_link"].endswith("ev_1") and j["calendar"]["attendee"] == "minsu@example.com"
    # 스케줄에 한 번만 보인다 — Google 에도 넣은 일정은 동기화분과 겹치지 않는다 (plan/56).
    sched = (await client.get(f"/api/schedule?{_around(start)}", headers=auth(tok))).json()["events"]
    assert [e["source"] for e in sched] == ["meeting"] and "김민수" in sched[0]["title"]
    # 45 minutes, the visitor's name on it, the purpose as the description.
    assert seen["attendees"] == ["minsu@example.com"] and "김민수" in seen["summary"]
    assert seen["description"] == "제안서 이야기"
    assert (seen["end"] - seen["start"]) == timedelta(minutes=45)
    # And the item remembers it, so reopening does not offer to schedule it again.
    again = (await client.get(f"/api/inbox/{iid}", headers=auth(tok))).json()
    assert again["payload"]["calendar_event_id"] == "ev_1" and again["payload"]["scheduled_at"].startswith(start[:16])
    assert again["payload"]["calendar_provider"] == "google"   # 화면이 "Google 캘린더에도 넣었어요" 를 보인다

    # 같은 요청을 시간을 바꿔 다시 수락해도 일정은 하나로 남아 옮겨 가고, Google 사본은 늘지 않는다.
    later = (datetime.fromisoformat(start) + timedelta(hours=2)).isoformat()
    seen.clear()
    r = await client.post(f"/api/inbox/{iid}/status", json={"status": "accepted", "start_at": later, "duration_minutes": 45},
                          headers=auth(tok))
    assert r.json()["calendar"]["external"]["status"] == "unchanged" and not seen
    sched = (await client.get(f"/api/schedule?{_around(later)}", headers=auth(tok))).json()["events"]
    assert len(sched) == 1 and datetime.fromisoformat(sched[0]["start"]) == datetime.fromisoformat(later)


async def test_the_acceptance_stands_when_the_calendar_cannot_be_written(client: AsyncClient, monkeypatch):
    """Three ways it can fail. None of them may swallow the owner's yes."""
    user, tok = await signup(client)
    iid = await _meeting(user["id"])
    when = _when()
    r = await client.post(f"/api/inbox/{iid}/status", json={"status": "accepted", "start_at": when}, headers=auth(tok))
    assert r.json()["status"] == "accepted" and r.json()["calendar"]["external"]["status"] == "no_connection"
    # Google 이 없어도 약속은 스케줄에 들어간다 (plan/56).
    assert r.json()["calendar"]["created"] is True
    sched = (await client.get(f"/api/schedule?{_around(when)}", headers=auth(tok))).json()["events"]
    assert len(sched) == 1 and sched[0]["source"] == "meeting"
    # The appointment was still made. Losing the hour because Google is not connected
    # would leave the owner having said yes to a time nothing remembers.
    again = (await client.get(f"/api/inbox/{iid}", headers=auth(tok))).json()
    assert again["payload"]["scheduled_at"].startswith(when[:16])
    assert "calendar_event_id" not in again["payload"]

    await _connect(user["id"], ["calendar_read"])
    iid2 = await _meeting(user["id"])
    r = await client.post(f"/api/inbox/{iid2}/status", json={"status": "accepted", "start_at": _when()}, headers=auth(tok))
    assert r.json()["status"] == "accepted" and r.json()["calendar"]["external"]["status"] == "off"

    async def boom(db, conn, **kw):
        raise RuntimeError("google said no")

    monkeypatch.setattr("blackmoa.services.google.create_event", boom)
    async with session_scope() as db:
        c = (await db.execute(select(Connection).where(Connection.owner_id == _uuid.UUID(user["id"])))).scalars().first()
        c.capabilities = ["calendar_write"]
        await db.commit()
    iid3 = await _meeting(user["id"])
    r = await client.post(f"/api/inbox/{iid3}/status", json={"status": "accepted", "start_at": _when()}, headers=auth(tok))
    assert r.json()["status"] == "accepted" and r.json()["calendar"]["external"]["status"] == "failed" and r.json()["calendar"]["created"] is True


async def test_accepting_without_a_time_does_not_touch_the_calendar(client: AsyncClient):
    """Leaving the time empty is a real choice: say yes now, arrange it later."""
    user, tok = await signup(client)
    await _connect(user["id"], ["calendar_write"])
    iid = await _meeting(user["id"])
    r = await client.post(f"/api/inbox/{iid}/status", json={"status": "accepted"}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["calendar"] is None


async def test_the_meeting_goes_to_the_kakao_talk_calendar_too(client: AsyncClient, monkeypatch):
    """톡캘린더에 넣기를 켰으면 거기로. 카카오는 이메일로 초대하지 않으므로 초대했다고 말하지 않는다."""
    user, tok = await signup(client)
    await _connect(user["id"], ["calendar_read", "calendar_write"], provider="kakao")
    iid = await _meeting(user["id"], email="minsu@example.com")
    seen = {}

    async def fake_create(db, conn, **kw):
        seen.update(kw)
        return {"id": "kev_1", "html_link": ""}

    monkeypatch.setattr("blackmoa.services.kakao.create_event", fake_create)
    start = _when()
    r = await client.post(f"/api/inbox/{iid}/status", json={"status": "accepted", "start_at": start, "duration_minutes": 30},
                          headers=auth(tok))
    j = r.json()["calendar"]
    assert j["external"] == {"provider": "kakao", "label": "카카오 톡캘린더", "status": "added"} and j["attendee"] == ""
    assert "김민수" in seen["summary"]
    # 동기화해 온 같은 일정과 겹쳐 보이지 않는다.
    async with session_scope() as db:
        from blackmoa.models import IntegrationEvent
        c = (await db.execute(select(Connection).where(Connection.owner_id == _uuid.UUID(user["id"])))).scalars().first()
        db.add(IntegrationEvent(owner_id=c.owner_id, connection_id=c.id, ext_id="kev_1", title="김민수님과의 미팅",
                                start_at=seen["start"], end_at=seen["end"], all_day=False, status="confirmed", busy=True))
        await db.commit()
    sched = (await client.get(f"/api/schedule?{_around(start)}", headers=auth(tok))).json()["events"]
    assert [e["source"] for e in sched] == ["meeting"]


async def test_nothing_is_pushed_while_the_admin_has_the_provider_off(client: AsyncClient, monkeypatch):
    user, tok = await signup(client)
    await _connect(user["id"], ["calendar_read", "calendar_write"])
    called = []

    async def fake_create(db, conn, **kw):
        called.append(kw)
        return {"id": "x"}

    monkeypatch.setattr("blackmoa.services.google.create_event", fake_create)
    await _providers_on(False)
    iid = await _meeting(user["id"])
    r = await client.post(f"/api/inbox/{iid}/status", json={"status": "accepted", "start_at": _when()}, headers=auth(tok))
    assert r.json()["calendar"]["external"]["status"] == "off" and not called and r.json()["calendar"]["created"] is True
