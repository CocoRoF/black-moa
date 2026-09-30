"""스케줄의 [연동] 탭 (plan/58).

바깥 달력은 스케줄에 붙는 것이다. 붙일 수 있는지는 관리 설정([연결])이 정하고, 붙인 뒤
무엇을 가져올지·얼마나 자주·미팅을 거기에도 넣을지는 주인이 여기서 정한다. 가져오기를 끄면
그 달력의 일정은 스케줄에서도, 빈 시간 계산에서도 빠진다.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import AsyncClient

from memora.db.session import session_scope
from memora.models import Connection, IntegrationEvent
from memora.services import calendar_sources as CS
from memora.services import settings as S
from tests.conftest import auth, signup

READ = "https://www.googleapis.com/auth/calendar.readonly"


async def _google_on(on: bool = True) -> None:
    """관리자 [연결 → Google] 을 켜고 끈다 (plan/59)."""
    async with session_scope() as db:
        await S.put(db, "oauth.google.enabled", on)
        await S.put(db, "oauth.google.client_id", "cid" if on else "")
        await S.put(db, "oauth.google.client_secret", "sec" if on else "")
        await S.put(db, "oauth.google.features", ["calendar_read", "calendar_write", "contacts"])
        await db.commit()
    S.invalidate("oauth.")


@pytest_asyncio.fixture(autouse=True)
async def _admin_turned_google_on(app):
    # 관리자가 꺼 둔 공급자의 일정은 스케줄에서 빠진다 — 그 경우는 따로 확인한다.
    await _google_on(True)
    yield
    await _google_on(False)


async def _connected(owner_id: str, *, caps: list[str], scopes: list[str]) -> uuid.UUID:
    async with session_scope() as db:
        c = Connection(owner_id=uuid.UUID(owner_id), provider="google", account_label="me@example.com", capabilities=caps,
                       scopes=scopes, access_token_enc="", refresh_token_enc="", status="active",
                       token_expires_at=datetime.now(UTC) + timedelta(hours=1))
        db.add(c)
        await db.flush()
        start = (datetime.now(UTC) + timedelta(days=2)).replace(hour=3, minute=0, second=0, microsecond=0)
        db.add(IntegrationEvent(owner_id=c.owner_id, connection_id=c.id, ext_id="g1", title="구글 회의",
                                start_at=start, end_at=start + timedelta(hours=1), all_day=False, status="confirmed", busy=True))
        await db.commit()
        return c.id


def _around() -> str:
    d = (datetime.now(UTC) + timedelta(days=2)).date()
    return f"from={d - timedelta(days=1)}&to={d + timedelta(days=1)}"


async def test_turning_the_provider_off_hides_what_was_imported(client: AsyncClient):
    """관리자가 [연결] 에서 Google 을 끄면 가져온 일정이 스케줄·빈 시간 계산에서 빠지고, 다시 켜면 돌아온다."""
    user, tok = await signup(client)
    cid = await _connected(user["id"], caps=["calendar_read"], scopes=[READ])
    assert [e["title"] for e in (await client.get(f"/api/schedule?{_around()}", headers=auth(tok))).json()["events"]] == ["구글 회의"]
    await _google_on(False)
    assert (await client.get(f"/api/schedule?{_around()}", headers=auth(tok))).json()["events"] == []
    async with session_scope() as db:
        assert cid not in await CS.due(db), "꺼 둔 공급자는 자동으로 가져오지 않는다"
    await _google_on(True)
    assert [e["title"] for e in (await client.get(f"/api/schedule?{_around()}", headers=auth(tok))).json()["events"]] == ["구글 회의"]


async def test_a_calendar_is_offered_only_when_the_admin_turned_it_on(client: AsyncClient):
    _, tok = await signup(client)
    await _google_on(False)
    try:
        items = (await client.get("/api/schedule/sources", headers=auth(tok))).json()["items"]
        assert [(i["provider"], i["available"], i["connected"]) for i in items] == [("google", False, False), ("kakao", False, False)]
        r = await client.post("/api/schedule/sources/google/connect", headers=auth(tok))
        assert r.status_code == 422 and r.json()["error"]["code"] == "calendar_unavailable"
        await _google_on(True)
        assert (await client.get("/api/schedule/sources", headers=auth(tok))).json()["items"][0]["available"] is True
        url = (await client.post("/api/schedule/sources/google/connect", headers=auth(tok))).json()["url"]
        # 일정 읽기와 넣기를 함께 청하고, 끝나면 [연동] 탭으로 돌아온다.
        assert "calendar.readonly" in url and "calendar.events" in url
    finally:
        await _google_on(False)


async def test_turning_import_off_takes_the_calendar_out_of_the_schedule(client: AsyncClient):
    user, tok = await signup(client)
    await _connected(user["id"], caps=["calendar_read"], scopes=[READ])
    got = (await client.get(f"/api/schedule?{_around()}", headers=auth(tok))).json()["events"]
    assert [e["title"] for e in got] == ["구글 회의"]
    src = (await client.get("/api/schedule/sources", headers=auth(tok))).json()["items"][0]
    assert src["connected"] and src["read"] and not src["write"] and src["events"] == 1 and src["auto_every"] == 15

    r = (await client.patch("/api/schedule/sources/google", json={"read": False}, headers=auth(tok))).json()
    assert r["consent_url"] is None and r["items"][0]["read"] is False
    assert (await client.get(f"/api/schedule?{_around()}", headers=auth(tok))).json()["events"] == []
    # 빈 시간 계산에서도 빠진다.
    async with session_scope() as db:
        from memora.services import schedule as SCH
        now = datetime.now(UTC)
        assert await SCH.busy_between(db, uuid.UUID(user["id"]), now, now + timedelta(days=5)) == []
    # 다시 켜면 돌아온다 (이미 받은 권한이라 동의 화면이 필요 없다).
    r = (await client.patch("/api/schedule/sources/google", json={"read": True}, headers=auth(tok))).json()
    assert r["consent_url"] is None and r["items"][0]["read"] is True
    assert [e["title"] for e in (await client.get(f"/api/schedule?{_around()}", headers=auth(tok))).json()["events"]] == ["구글 회의"]


async def test_a_permission_not_yet_granted_goes_through_consent(client: AsyncClient):
    user, tok = await signup(client)
    await _google_on(True)
    try:
        await _connected(user["id"], caps=["calendar_read", "contacts"], scopes=[READ])
        r = (await client.patch("/api/schedule/sources/google", json={"write": True}, headers=auth(tok))).json()
        # 바꾸지 않고 동의 화면으로 — 이미 켠 일정 읽기·연락처는 그대로 청한다. 메일은 Google 에 청하지 않는다(plan/74).
        assert r["items"][0]["write"] is False and r["consent_url"] and "calendar.events" in r["consent_url"]
        assert "contacts.readonly" in r["consent_url"] and "gmail" not in r["consent_url"]
    finally:
        await _google_on(False)
    # 관리 설정에서 꺼져 있으면 권한을 더 받을 길이 없다 — 까닭을 밝혀 거절한다.
    r = await client.patch("/api/schedule/sources/google", json={"write": True}, headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "calendar_unavailable"


async def test_automatic_import_follows_each_calendars_interval(client: AsyncClient):
    user, tok = await signup(client)
    cid = await _connected(user["id"], caps=["calendar_read"], scopes=[READ])
    async with session_scope() as db:
        assert cid in await CS.due(db), "한 번도 가져오지 않았으면 가져올 때다"
        c = await db.get(Connection, cid)
        c.sync_cursor = {"calendar_last_sync": (datetime.now(UTC) - timedelta(minutes=10)).isoformat()}
        await db.commit()
    async with session_scope() as db:
        assert cid not in await CS.due(db), "15분마다(기본, plan/76)인데 10분 전에 가져왔다"
        c = await db.get(Connection, cid)
        c.sync_cursor = {"calendar_last_sync": (datetime.now(UTC) - timedelta(minutes=16)).isoformat()}
        await db.commit()
    async with session_scope() as db:
        assert cid in await CS.due(db), "15분이 지났다"
    assert (await client.patch("/api/schedule/sources/google", json={"auto_every": 7}, headers=auth(tok))).status_code == 422
    await client.patch("/api/schedule/sources/google", json={"auto_every": 0}, headers=auth(tok))
    async with session_scope() as db:
        c = await db.get(Connection, cid)
        c.sync_cursor = {}
        await db.commit()
    async with session_scope() as db:
        assert cid not in await CS.due(db), "자동 가져오기를 끄면 가져오지 않는다"
    # 가져오기를 끄면 [지금 가져오기] 도 거절한다.
    await client.patch("/api/schedule/sources/google", json={"read": False}, headers=auth(tok))
    r = await client.post("/api/schedule/sources/google/sync", headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "calendar_not_reading"


async def test_coming_back_from_consent_lands_on_the_tab_it_left(client: AsyncClient, monkeypatch):
    """연결을 마치면 시작한 화면(스케줄의 [연동] 탭)으로, 그 주소 그대로 돌아온다."""
    from fastapi import Response

    from memora.services import oauth as OA
    from memora.services.oauth import state as OST

    user, _ = await signup(client)
    g = OA.PROVIDERS["google"]

    async def fake_exchange(db, *, code, purpose):
        return {"access_token": "at", "refresh_token": "rt", "expires_in": 3600,
                "scope": "openid email https://www.googleapis.com/auth/calendar.readonly"}

    async def fake_identity(db, tokens, *, nonce):
        return OA.Identity(provider="google", subject="g-1", email="me@example.com", email_verified=True)

    monkeypatch.setattr(g, "exchange", fake_exchange)
    monkeypatch.setattr(g, "identity", fake_identity)
    await _google_on(True)
    try:
        def begin(next_url: str) -> tuple[str, str]:
            resp = Response()
            state, _ = OST.begin(resp, provider="google", purpose="connect", uid=user["id"], caps=["calendar_read"],
                                 next=OST.safe_next(next_url, "/app/account"))
            return state, resp.headers["set-cookie"].split(";")[0].split("=", 1)[1]

        state, bind = begin("/app/schedule?tab=sync")
        r = await client.get("/api/integrations/google/callback", params={"code": "c", "state": state},
                             cookies={"memora_oauth": bind}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"].endswith("/app/schedule?tab=sync&connected=google"), r.headers["location"]
        # 밖으로 나가는 주소는 받지 않는다.
        state, bind = begin("https://evil.example/x")
        r = await client.get("/api/integrations/google/callback", params={"code": "c", "state": state},
                             cookies={"memora_oauth": bind}, follow_redirects=False)
        assert r.headers["location"].endswith("/app/account?connected=google")
        # 흐름을 시작한 브라우저가 아니면(쿠키가 없거나 다르면) 받지 않는다.
        state, _ = begin("/app/account")
        r = await client.get("/api/integrations/google/callback", params={"code": "c", "state": state},
                             cookies={"memora_oauth": "someone-else"}, follow_redirects=False)
        assert "error=state_browser_mismatch" in r.headers["location"]
    finally:
        await _google_on(False)


async def test_a_contacts_failure_does_not_stop_calendar_import(client: AsyncClient, monkeypatch):
    """운영에서 겪은 것(2026-09-29): 프로젝트에 People API 가 꺼져 있어 연락처가 403 — 그 하나로 동기화 전체가
    실패하고 일정도 안 들어왔다. 연락처는 적어 두고 다음에 다시 하고, 일정은 들어와야 한다."""
    from memora.providers.http import ProviderHTTPError
    from memora.services import connections as CN
    from memora.services import google as G

    user, _ = await signup(client)
    cid = await _connected(user["id"], caps=["calendar_read", "contacts"], scopes=[])

    async def cal(db, conn):
        return 3

    async def contacts(db, owner, conn):
        raise ProviderHTTPError(403, "People API has not been used in project 1 before or it is disabled")
    monkeypatch.setattr(G, "sync_calendar", cal)
    monkeypatch.setattr(G, "import_contacts", contacts)
    async with session_scope() as db:
        conn = await db.get(Connection, cid)
        out = await CN.sync_all(db, conn)
        await db.commit()
    assert out == {"events": 3}
    async with session_scope() as db:
        conn = await db.get(Connection, cid)
        assert conn.last_sync_at is not None and conn.status == "active"
        assert conn.sync_cursor["contacts_error"] == "contacts_forbidden" and not conn.sync_cursor.get("contacts_imported")
