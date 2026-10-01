"""Google 데이터 (plan/11, plan/59): Gmail·Calendar·People 가져오기와 읽기·쓰기.

로그인·토큰·갱신·철회는 공급자 틀(services/oauth, services/connections)이 맡는다. 여기는 데이터만.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.config import get_settings
from blackmoa.core.errors import Conflict
from blackmoa.core.logging import get_logger
from blackmoa.models import Connection, IntegrationEvent, User
from blackmoa.models import NetworkNode as NetworkNodeProxy
from blackmoa.providers.http import ProviderHTTPError, request
from blackmoa.services import connections as CN
from blackmoa.services import network as N

log = get_logger("blackmoa.google")

# ── Gmail ──────────────────────────────────────────────────────────────
# Gmail 은 Google API 로 읽지 않는다(plan/74): gmail.readonly 는 "제한 범위"라 매년 유료 보안 평가가 붙는다.
# 메일함은 IMAP + 앱 비밀번호로 잇는다(services/imap_mail).

# ── Calendar ───────────────────────────────────────────────────────────

async def sync_calendar(db: AsyncSession, conn: Connection) -> int:
    tok = await CN.access_token(db, conn)
    now = datetime.now(UTC)
    items: list[dict[str, Any]] = []
    page: str | None = None
    # 한 쪽에 250개까지 — 예전에는 첫 쪽만 받아 바쁜 달력의 뒷일정이 빠졌다. 다음 쪽까지(최대 10쪽).
    for _ in range(10):
        params: dict[str, Any] = {"timeMin": (now - timedelta(days=7)).isoformat(), "timeMax": (now + timedelta(days=60)).isoformat(),
                                  "singleEvents": "true", "orderBy": "startTime", "maxResults": 250}
        if page:
            params["pageToken"] = page
        r = await request("GET", "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                          headers={"Authorization": f"Bearer {tok}"}, params=params)
        j = r.json()
        items += j.get("items", [])
        page = j.get("nextPageToken")
        if not page:
            break
    # 종일 일정의 날짜는 주인의 날짜다. UTC 자정으로 두면 한국에서는 오전 9시에 시작하는 일정이 된다.
    from zoneinfo import ZoneInfo
    owner = await db.get(User, conn.owner_id)
    try:
        tz = ZoneInfo(getattr(owner, "timezone", None) or "Asia/Seoul")
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("Asia/Seoul")
    await db.execute(text("DELETE FROM integration_events WHERE connection_id = :c"), {"c": conn.id})
    n = 0
    for ev in items:
        if ev.get("status") == "cancelled":
            continue
        st = ev.get("start", {})
        en = ev.get("end", {})
        all_day = "date" in st

        def _dt(d):
            if not d:
                return None
            if "dateTime" in d:
                return datetime.fromisoformat(d["dateTime"].replace("Z", "+00:00"))
            return datetime.fromisoformat(d["date"]).replace(tzinfo=tz)

        db.add(IntegrationEvent(owner_id=conn.owner_id, connection_id=conn.id, ext_id=ev.get("id", ""), title=(ev.get("summary") or "")[:500],
                                start_at=_dt(st), end_at=_dt(en), all_day=all_day, location=(ev.get("location") or "")[:500],
                                attendees=[{"email": a.get("email"), "name": a.get("displayName"), "status": a.get("responseStatus")}
                                           for a in ev.get("attendees", [])][:30], status=ev.get("status", "confirmed"),
                                description_summary=(ev.get("description") or "")[:500],
                                # "한가함" 으로 표시한 일정(생일 등)은 빈 시간을 막지 않는다 (plan/56).
                                busy=ev.get("transparency") != "transparent"))
        n += 1
    cursor = dict(conn.sync_cursor or {})
    cursor["calendar_last_sync"] = now.isoformat()
    conn.sync_cursor = cursor
    return n


async def create_event(db: AsyncSession, conn: Connection, *, summary: str, start: datetime, end: datetime,
                       description: str = "", location: str = "", attendees: list[str] | None = None,
                       timezone: str = "Asia/Seoul") -> dict[str, Any]:
    """Put one event on the owner's primary calendar.

    The event is written to our own table as well, so the owner sees it the moment they
    accept rather than after the next sync (plan/41 §9.2).
    """
    tok = await CN.access_token(db, conn)
    body: dict[str, Any] = {
        "summary": summary[:500],
        "description": description[:2000],
        "start": {"dateTime": start.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end.isoformat(), "timeZone": timezone},
    }
    if location:
        body["location"] = location[:500]
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees[:10]]
    r = await request("POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                      headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                      params={"sendUpdates": "all" if attendees else "none"}, json=body)
    ev = r.json()
    db.add(IntegrationEvent(owner_id=conn.owner_id, connection_id=conn.id, ext_id=ev.get("id", ""),
                            title=summary[:500], start_at=start, end_at=end, all_day=False,
                            location=location[:500], attendees=[{"email": a} for a in (attendees or [])][:30],
                            status=ev.get("status", "confirmed"), description_summary=description[:500]))
    return {"id": ev.get("id", ""), "html_link": ev.get("htmlLink", "")}


# ── Contacts ───────────────────────────────────────────────────────────

async def import_contacts(db: AsyncSession, owner: User, conn: Connection, *, limit: int = 2000) -> int:
    tok = await CN.access_token(db, conn)
    hdrs = {"Authorization": f"Bearer {tok}"}
    page = None
    n = 0
    while n < limit:
        params = {"personFields": "names,emailAddresses,organizations,phoneNumbers", "pageSize": 200}
        if page:
            params["pageToken"] = page
        r = await request("GET", "https://people.googleapis.com/v1/people/me/connections", headers=hdrs, params=params)
        j = r.json()
        for p in j.get("connections", []):
            names = p.get("names") or []
            if not names:
                continue
            name = names[0].get("displayName") or ""
            emails = [e.get("value") for e in p.get("emailAddresses") or [] if e.get("value")]
            phones = [x.get("value") for x in p.get("phoneNumbers") or [] if x.get("value")]
            orgs = p.get("organizations") or []
            attrs = {"emails": emails[:5], "phones": phones[:3]}
            if orgs:
                attrs["company"] = orgs[0].get("name", "")
                attrs["title"] = orgs[0].get("title", "")
            ext = p.get("resourceName", "")
            existing = (await db.execute(select(NetworkNodeProxy).where(NetworkNodeProxy.owner_id == owner.id, NetworkNodeProxy.source == "google_contacts",
                                                                       NetworkNodeProxy.external_ref == ext))).scalars().first()
            if existing:
                existing.attrs = {**(existing.attrs or {}), **attrs}
                existing.name = name or existing.name
            else:
                try:
                    await N.create_node(db, owner, kind="person", name=name, attrs=attrs, source="google_contacts",
                                        external_ref=ext, tags=["google"])
                except Conflict:
                    break
            n += 1
        page = j.get("nextPageToken")
        if not page:
            break
    return n




async def sync_all(db: AsyncSession, conn: Connection, owner: User) -> dict[str, int]:
    """이 연결이 받은 기능대로 가져온다. 상태·오류 기록은 services/connections.sync_all 이 한다."""
    out: dict[str, int] = {}
    caps = set(conn.capabilities or [])
    if "calendar_read" in caps:
        out["events"] = await CN.calendar_part(conn, sync_calendar(db, conn))
        await ensure_watch(db, conn)
    if "contacts" in caps and contacts_due(conn):
        try:
            out["contacts"] = await import_contacts(db, owner, conn)
            c = dict(conn.sync_cursor or {})
            c["contacts_imported"] = True
            c["contacts_last_sync"] = datetime.now(UTC).isoformat()
            c.pop("contacts_error", None)
            conn.sync_cursor = c
        except ProviderHTTPError as e:
            # 연락처가 안 된다고(예: 프로젝트에 People API 가 꺼져 있음) 일정까지 못 가져오면 안 된다 —
            # 2026-09-29 운영에서 이 403 하나로 동기화 전체가 다섯 번 실패하고 화면에는 아무것도 안 보였다.
            # 적어 두고 다음 동기화에서 다시 한다.
            log.warning("google contacts import failed", status=e.status, conn=str(conn.id), err=str(e)[:200])
            CN.failed(conn, "contacts", CN.error_code("contacts", e))
    return out


#: 연락처는 하루에 한 번 새로 받는다 — 예전에는 처음 한 번만 받아 나중에 더한 사람이 들어오지 않았다.
CONTACTS_EVERY = timedelta(hours=24)


def contacts_due(conn: Connection, now: datetime | None = None) -> bool:
    cur = conn.sync_cursor or {}
    if not cur.get("contacts_imported") or cur.get("contacts_error"):
        return True
    try:
        last = datetime.fromisoformat(cur.get("contacts_last_sync") or "")
    except ValueError:
        return True
    return (now or datetime.now(UTC)) - last >= CONTACTS_EVERY


# ── 변경 알림(푸시, plan/76) ─────────────────────────────────────────────
#
# Google 캘린더는 바뀌면 우리 주소로 알려 준다(내용은 없다 — 알림을 받으면 가져온다). 그래서 Google 일정은
# 몇 초 안에 들어온다. 채널은 일주일쯤 살고, 달력 가져오기(15분마다)가 하루 안에 끝날 채널을 새로 연다.
# 알림 주소는 https 여야 해서 개발 환경(http://localhost)에서는 열지 않는다.

PUSH_PATH = "/api/integrations/google/push"
WATCH_TTL = 7 * 24 * 3600
WATCH_RENEW = timedelta(days=1)


def channel_token(conn_id: uuid.UUID, channel_id: str) -> str:
    """알림이 정말 우리가 연 채널에서 왔는가 — Google 이 알림마다 이 값을 그대로 돌려준다."""
    return hmac.new(get_settings().secret_key.encode(), f"gcal:{conn_id}:{channel_id}".encode(), hashlib.sha256).hexdigest()[:48]


def channel_conn(channel_id: str) -> uuid.UUID | None:
    """``blackmoa-<연결 id hex>-<시각>`` 에서 연결을 찾는다."""
    parts = (channel_id or "").split("-")
    if len(parts) != 3 or parts[0] != "blackmoa":
        return None
    try:
        return uuid.UUID(hex=parts[1])
    except ValueError:
        return None


def watching(conn: Connection, now: datetime | None = None) -> bool:
    w = (conn.settings or {}).get("gcal_watch") or {}
    exp = int(w.get("expiration") or 0) / 1000
    return bool(w.get("id")) and exp > (now or datetime.now(UTC)).timestamp()


async def ensure_watch(db: AsyncSession, conn: Connection) -> None:
    """알림 채널이 없거나 하루 안에 끝나면 새로 연다. 실패해도 가져오기는 그대로다(주기 가져오기가 뒤를 받친다)."""
    base = get_settings().public_url.rstrip("/")
    if not base.startswith("https://") or "calendar_read" not in (conn.capabilities or []):
        return
    w = (conn.settings or {}).get("gcal_watch") or {}
    if watching(conn, datetime.now(UTC) + WATCH_RENEW):
        return
    try:
        tok = await CN.access_token(db, conn)
        cid = f"blackmoa-{conn.id.hex}-{int(datetime.now(UTC).timestamp())}"
        r = await request("POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events/watch",
                          headers={"Authorization": f"Bearer {tok}"}, retries=1,
                          json={"id": cid, "type": "web_hook", "address": base + PUSH_PATH,
                                "token": channel_token(conn.id, cid), "params": {"ttl": str(WATCH_TTL)}})
        j = r.json()
        conn.settings = {**(conn.settings or {}), "gcal_watch": {"id": cid, "resource_id": j.get("resourceId", ""),
                                                                 "expiration": int(j.get("expiration") or 0)}}
    except Exception as e:  # noqa: BLE001
        log.warning("google calendar watch failed", conn=str(conn.id), err=str(e)[:200])
        return
    if w.get("id"):
        await _stop_channel(tok, w)


async def _stop_channel(tok: str, w: dict[str, Any]) -> None:
    try:
        await request("POST", "https://www.googleapis.com/calendar/v3/channels/stop", headers={"Authorization": f"Bearer {tok}"},
                      json={"id": w.get("id"), "resourceId": w.get("resource_id")}, retries=0)
    except Exception as e:  # noqa: BLE001 — 끝나지 않은 채널은 곧 스스로 끝난다
        log.info("google channel stop failed", err=str(e)[:200])


async def stop_watch(db: AsyncSession, conn: Connection) -> None:
    """가져오기를 끄거나 연결을 끊을 때 — 알림을 그만 받는다."""
    w = (conn.settings or {}).get("gcal_watch")
    if not w:
        return
    try:
        tok = await CN.access_token(db, conn)
        await _stop_channel(tok, w)
    except Exception as e:  # noqa: BLE001
        log.info("google watch stop skipped", err=str(e)[:200])
    conn.settings = {k: v for k, v in (conn.settings or {}).items() if k != "gcal_watch"}
