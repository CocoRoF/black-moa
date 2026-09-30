"""연결 동기화 (plan/76) — 바로바로, 한 번에 하나씩, 실패는 보이게.

운영에서 겪은 것(2026-09-30): 카카오를 잇자 5초 만에 가져왔는데 화면은 새로 고칠 때까지 "마지막 동기화: –" 였다.
달력 자동 가져오기는 연결의 "마지막 동기화" 를 찍지 않았고, Google 일정은 1시간마다만 들어왔고, 메일함은 버튼을
누를 때만, 연락처는 처음 한 번만 들어왔다. 권한 실패는 다섯 번 조용히 되풀이되고 화면에는 아무것도 없었다.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from httpx import AsyncClient
from sqlalchemy import select

from memora.db.session import session_scope
from memora.models import Connection, IntegrationEvent, Job
from memora.providers.http import ProviderHTTPError
from memora.services import calendar_sources as CS
from memora.services import connections as CN
from memora.services import google as G
from tests.conftest import auth, signup
from tests.test_calendar_sources import _connected, _google_on


async def _jobs(conn_id: uuid.UUID, kind: str = "calendar.sync") -> list[Job]:
    async with session_scope() as db:
        rows = (await db.execute(select(Job).where(Job.kind == kind))).scalars().all()
        return [j for j in rows if (j.payload or {}).get("connection_id") == str(conn_id) and j.status == "queued"]


def _event(i: int) -> dict:
    start = datetime.now(UTC) + timedelta(days=1, hours=i)
    return {"id": f"e{i}", "summary": f"일정 {i}", "status": "confirmed",
            "start": {"dateTime": start.isoformat()}, "end": {"dateTime": (start + timedelta(hours=1)).isoformat()}}


async def test_google_pushes_a_change_and_the_calendar_is_fetched_again(client: AsyncClient, monkeypatch):
    """Google 이 "바뀌었다" 고 알리면 곧 가져온다. 우리가 연 채널·토큰이 아니면 아무것도 하지 않는다."""
    await _google_on(True)
    user, _ = await signup(client)
    cid = await _connected(user["id"], caps=["calendar_read"], scopes=[])
    channel = f"memora-{cid.hex}-1790000000"
    async with session_scope() as db:
        c = await db.get(Connection, cid)
        c.settings = {"gcal_watch": {"id": channel, "resource_id": "r1",
                                     "expiration": int((datetime.now(UTC) + timedelta(days=5)).timestamp() * 1000)}}
        await db.commit()
    good = {"X-Goog-Channel-ID": channel, "X-Goog-Resource-State": "exists",
            "X-Goog-Channel-Token": G.channel_token(cid, channel)}

    r = await client.post("/api/integrations/google/push", headers={**good, "X-Goog-Channel-Token": "forged"})
    assert r.status_code == 204 and await _jobs(cid) == []
    r = await client.post("/api/integrations/google/push", headers={**good, "X-Goog-Resource-State": "sync"})
    assert r.status_code == 204 and await _jobs(cid) == []          # 채널을 연 순간의 인사는 변경이 아니다
    r = await client.post("/api/integrations/google/push", headers={**good, "X-Goog-Channel-ID": f"memora-{uuid.uuid4().hex}-1"})
    assert r.status_code == 204 and await _jobs(cid) == []

    r = await client.post("/api/integrations/google/push", headers=good)
    assert r.status_code == 204 and len(await _jobs(cid)) == 1
    # 가져오기가 아직 대기 중이면 같은 칸에는 하나만 — 알림이 몰려도 가져오기는 한 번.
    await client.post("/api/integrations/google/push", headers=good)
    assert len(await _jobs(cid)) <= 2
    await _google_on(False)


async def test_calendar_sync_stamps_the_connection_and_a_permission_failure_is_kept_not_retried(client: AsyncClient, monkeypatch):
    await _google_on(True)
    user, tok = await signup(client)
    cid = await _connected(user["id"], caps=["calendar_read"], scopes=[])

    async def token(db, conn):
        return "tok"
    monkeypatch.setattr(CN, "access_token", token)
    pages = {None: {"items": [_event(i) for i in range(3)], "nextPageToken": "p2"}, "p2": {"items": [_event(i) for i in range(3, 5)]}}

    async def google(method, url, *, params=None, **kw):
        if url.endswith("/events/watch"):
            raise ProviderHTTPError(400, "push needs https")        # 개발 환경 — 가져오기에는 상관없다
        return httpx.Response(200, request=httpx.Request(method, url), json=pages[(params or {}).get("pageToken")])
    monkeypatch.setattr(G, "request", google)

    async with session_scope() as db:
        n = await CS.sync_connection(db, cid)
        await db.commit()
    assert n == 5                                                     # 두 쪽 모두 — 예전에는 첫 쪽만
    async with session_scope() as db:
        c = await db.get(Connection, cid)
        assert c.last_sync_at is not None and c.error is None         # 연동 화면의 "마지막 동기화" 도 찍힌다
        rows = (await db.execute(select(IntegrationEvent).where(IntegrationEvent.connection_id == cid))).scalars().all()
        assert sorted(e.ext_id for e in rows) == [f"e{i}" for i in range(5)]

    async def forbidden(method, url, **kw):
        raise ProviderHTTPError(403, "insufficient permission")
    monkeypatch.setattr(G, "request", forbidden)
    async with session_scope() as db:
        assert await CS.sync_connection(db, cid) == 0                 # 올려 보내지 않는다 — 다섯 번 되풀이하지 않는다
        await db.commit()
    async with session_scope() as db:
        c = await db.get(Connection, cid)
        assert c.status == "active" and c.error == "calendar_forbidden"
    items = (await client.get("/api/schedule/sources", headers=auth(tok))).json()["items"]
    assert next(i for i in items if i["provider"] == "google")["sync_error"] == "calendar_forbidden"

    monkeypatch.setattr(G, "request", google)
    async with session_scope() as db:
        await CS.sync_connection(db, cid)
        await db.commit()
    async with session_scope() as db:
        c = await db.get(Connection, cid)
        assert c.error is None and "calendar_error" not in (c.sync_cursor or {})    # 다시 되면 지운다
    await _google_on(False)


async def test_opening_the_schedule_fetches_a_stale_calendar_and_mail_and_contacts_come_on_time(client: AsyncClient):
    await _google_on(True)
    user, tok = await signup(client)
    cid = await _connected(user["id"], caps=["calendar_read", "contacts"], scopes=[])
    # 한 번도 가져오지 않은 달력 — 스케줄을 열면 가져오기가 걸린다.
    r = await client.get("/api/schedule", headers=auth(tok))
    assert r.status_code == 200 and len(await _jobs(cid)) == 1
    # 방금 가져왔으면 걸지 않는다.
    async with session_scope() as db:
        c = await db.get(Connection, cid)
        c.sync_cursor = {"calendar_last_sync": datetime.now(UTC).isoformat()}
        await db.commit()
    for j in await _jobs(cid):
        async with session_scope() as db:
            (await db.get(Job, j.id)).status = "done"
            await db.commit()
    await client.get("/api/schedule", headers=auth(tok))
    assert await _jobs(cid) == []

    # 연락처는 처음, 그리고 하루가 지나면 다시.
    now = datetime.now(UTC)
    async with session_scope() as db:
        c = await db.get(Connection, cid)
        assert G.contacts_due(c, now)
        c.sync_cursor = {**(c.sync_cursor or {}), "contacts_imported": True, "contacts_last_sync": now.isoformat()}
        await db.commit()
        assert not G.contacts_due(c, now) and G.contacts_due(c, now + timedelta(hours=25))
        assert cid not in await CN.due(db, now) and cid in await CN.due(db, now + timedelta(hours=25))

    # 메일함은 10분마다.
    async with session_scope() as db:
        m = Connection(owner_id=uuid.UUID(user["id"]), provider="imap", account_label="me@example.com", capabilities=["mail_read"],
                       scopes=[], access_token_enc="", status="active", last_sync_at=now)
        db.add(m)
        await db.commit()
        assert m.id not in await CN.due(db, now + timedelta(minutes=5)) and m.id in await CN.due(db, now + timedelta(minutes=11))
    await _google_on(False)


def test_a_channel_id_names_its_connection_and_nothing_else():
    cid = uuid.uuid4()
    assert G.channel_conn(f"memora-{cid.hex}-1790000000") == cid
    for bad in ("", "memora", f"other-{cid.hex}-1", f"memora-{cid.hex}", "memora-zz-1"):
        assert G.channel_conn(bad) is None
    assert G.channel_token(cid, "a") != G.channel_token(cid, "b") and len(G.channel_token(cid, "a")) == 48
