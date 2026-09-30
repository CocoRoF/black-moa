"""카카오 데이터 (plan/59): 톡캘린더 가져오기·넣기, 카카오톡 나에게 보내기.

토큰·갱신은 services/connections 가 맡는다. 필요한 동의항목:
- 톡캘린더 ``talk_calendar`` (카카오 콘솔에서 권한을 신청해 받은 앱만)
- 나에게 보내기 ``talk_message`` — 메시지의 링크 주소는 카카오 앱의 [플랫폼 › Web › 사이트 도메인]에 등록돼 있어야 열린다.

톡캘린더는 한 번에 31일까지만 조회된다. 스케줄이 쓰는 범위(지난 7일 ~ 앞으로 60일)를 31일씩 나눠 받는다.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from memora.config import get_settings
from memora.models import Connection, IntegrationEvent, User
from memora.providers.http import request
from memora.services import connections as CN

API = "https://kapi.kakao.com"
WINDOW = timedelta(days=31)


def _z(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(v: str | None) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


async def _owner_tz(db: AsyncSession, conn: Connection) -> ZoneInfo:
    owner = await db.get(User, conn.owner_id)
    try:
        return ZoneInfo(getattr(owner, "timezone", None) or "Asia/Seoul")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Seoul")


async def sync_calendar(db: AsyncSession, conn: Connection) -> int:
    """톡캘린더의 일정을 가져와 그 연결의 일정을 통째로 바꾼다."""
    tok = await CN.access_token(db, conn)
    hdr = {"Authorization": f"Bearer {tok}"}
    tz = await _owner_tz(db, conn)
    now = datetime.now(UTC).replace(microsecond=0)
    start, end = now - timedelta(days=7), now + timedelta(days=60)
    items: list[dict[str, Any]] = []
    cur = start
    while cur < end:
        nxt = min(cur + WINDOW, end)
        url: str | None = f"{API}/v2/api/calendar/events"
        params: dict[str, Any] | None = {"from": _z(cur), "to": _z(nxt), "limit": 100}
        pages = 0
        while url and pages < 20:
            r = await request("GET", url, headers=hdr, params=params, retries=2)
            body = r.json()
            items += body.get("events") or []
            url = body.get("after_url") if body.get("has_next_events") else None
            params = None       # after_url 에는 질의가 이미 들어 있다
            pages += 1
        cur = nxt
    await db.execute(text("DELETE FROM integration_events WHERE connection_id = :c"), {"c": conn.id})
    seen: set[str] = set()
    n = 0
    for ev in items:
        eid = str(ev.get("id") or "")
        if not eid or eid in seen:
            continue
        seen.add(eid)
        t = ev.get("time") or {}
        s_at, e_at = _parse(t.get("start_at")), _parse(t.get("end_at"))
        if s_at is None:
            continue
        all_day = bool(t.get("all_day"))
        if all_day:
            # 종일 일정의 날짜는 주인의 날짜다 — UTC 자정으로 두면 한국에서는 오전 9시 일정이 된다.
            s_day = date.fromisoformat(t["start_at"][:10])
            e_day = date.fromisoformat((t.get("end_at") or t["start_at"])[:10])
            if e_day <= s_day:
                e_day = s_day + timedelta(days=1)
            s_at = datetime.combine(s_day, datetime.min.time(), tz)
            e_at = datetime.combine(e_day, datetime.min.time(), tz)
        if e_at is None or e_at <= s_at:
            e_at = s_at + timedelta(hours=1)
        db.add(IntegrationEvent(owner_id=conn.owner_id, connection_id=conn.id, ext_id=eid, title=str(ev.get("title") or "")[:500],
                                start_at=s_at, end_at=e_at, all_day=all_day, location="", attendees=[], status="confirmed",
                                description_summary="", busy=True))
        n += 1
    cursor = dict(conn.sync_cursor or {})
    cursor["calendar_last_sync"] = now.isoformat()
    conn.sync_cursor = cursor
    return n


def _five(d: datetime, *, up: bool) -> datetime:
    """톡캘린더는 5분 단위 시각만 받는다."""
    d = d.astimezone(UTC).replace(second=0, microsecond=0)
    r = d.minute % 5
    if not r:
        return d
    return d + timedelta(minutes=5 - r) if up else d - timedelta(minutes=r)


async def create_event(db: AsyncSession, conn: Connection, *, summary: str, start: datetime, end: datetime,
                       description: str = "", location: str = "", attendees: list[str] | None = None,
                       timezone: str = "Asia/Seoul") -> dict[str, Any]:
    """톡캘린더에 일정을 하나 넣는다. 카카오는 이메일로 초대하지 않으므로 ``attendees`` 는 받지만 쓰지 않는다."""
    tok = await CN.access_token(db, conn)
    s, e = _five(start, up=False), _five(end, up=True)
    if e <= s:
        e = s + timedelta(minutes=30)
    event: dict[str, Any] = {"title": summary[:50] or "일정", "time": {"start_at": _z(s), "end_at": _z(e), "time_zone": timezone,
                                                                    "all_day": False, "lunar": False}}
    if description:
        event["description"] = description[:5000]
    if location:
        event["location"] = {"name": location[:50]}
    r = await request("POST", f"{API}/v2/api/calendar/create/event", headers={"Authorization": f"Bearer {tok}"},
                      data={"calendar_id": "primary", "event": json.dumps(event, ensure_ascii=False)}, retries=1)
    return {"id": str(r.json().get("event_id") or ""), "html_link": ""}


async def send_memo(db: AsyncSession, conn: Connection, *, text_: str, link_path: str = "/app/inbox",
                    button: str = "Memora 열기") -> None:
    """카카오톡 "나와의 채팅" 으로 보낸다. 링크는 서비스 주소 안의 경로로만 만든다."""
    tok = await CN.access_token(db, conn)
    base = get_settings().public_url.rstrip("/")
    url = f"{base}{link_path if link_path.startswith('/') else '/app'}"
    tpl = {"object_type": "text", "text": text_[:200], "link": {"web_url": url, "mobile_web_url": url}, "button_title": button[:14]}
    await request("POST", f"{API}/v2/api/talk/memo/default/send", headers={"Authorization": f"Bearer {tok}"},
                  data={"template_object": json.dumps(tpl, ensure_ascii=False)}, retries=1)
