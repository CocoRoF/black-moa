from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core import bus
from blackmoa.core.errors import NotFound
from blackmoa.core.logging import get_logger
from blackmoa.models import InboxItem
from blackmoa.services import jobs as J

log = get_logger("blackmoa.inbox")

KINDS = ("message", "meeting_request", "contact_share", "question_unanswered",
         "community_comment", "community_reply", "relay_result", "relay_visit",
         # A company the owner follows got a new review or a new posting (plan/40 §7).
         "company_review", "company_job",
         # Somebody asked to connect, or answered the owner's own request (plan/41 §9.1).
         # 인맥 신청/수락은 사라졌다: 연결은 하는 순간 끝난다 (plan/43).
         "person_follow", "post_comment", "post_reply", "post_mention")
EVENT_FOR = {"message": "visitor_message", "meeting_request": "meeting_request", "contact_share": "contact_share",
             "question_unanswered": "question_unanswered",
             "community_comment": "community_comment", "community_reply": "community_reply",
             "relay_result": "relay_result", "relay_visit": "relay_visit",
             "company_review": "company_update", "company_job": "company_update",
             "person_follow": "network_link",
             "post_comment": "network_link", "post_reply": "network_link",
             "post_mention": "network_link"}


async def create(db: AsyncSession, *, owner_id: uuid.UUID, agent_id: uuid.UUID | None, kind: str, payload: dict[str, Any],
                 conversation_id: uuid.UUID | None = None, visitor_id: uuid.UUID | None = None,
                 urgency: int = 1, notify: bool = True) -> InboxItem:
    if kind not in KINDS:
        kind = "message"
    item = InboxItem(owner_id=owner_id, agent_id=agent_id, kind=kind, payload=payload, conversation_id=conversation_id,
                     visitor_id=visitor_id, status="new")
    db.add(item)
    await db.flush()
    if notify:
        await J.enqueue(db, "notify.evaluate", {"event": EVENT_FOR[kind], "owner_id": str(owner_id),
                                                "agent_id": str(agent_id) if agent_id else None,
                                                "inbox_item_id": str(item.id), "urgency": urgency}, priority=2)
    # The badge should move when the thing happens, not when someone reloads.
    await bus.publish(db, owner_id=owner_id, kind="inbox", data={"id": str(item.id), "kind": kind,
                                                                 "title_payload": payload})
    return item


async def schedule_meeting(db: AsyncSession, user: Any, item: InboxItem, *, start_at: datetime,
                           minutes: int | None = None) -> dict[str, Any]:
    """Accepting a meeting is supposed to mean it is on the calendar (plan/41 §9.2).

    It goes on the owner's schedule first (plan/56), whatever else happens — a Google
    calendar is optional and a missing or failing one never costs the appointment. If
    Google is connected with write access the event goes there too, and the schedule
    remembers its id so the synced copy is not shown twice.
    """
    minutes = int(minutes or (item.payload or {}).get("duration_minutes") or 30)
    end_at = start_at + timedelta(minutes=max(10, min(minutes, 480)))
    # The time is agreed the moment the owner says yes, so it is written down before the
    # calendar is touched: a calendar we cannot reach never costs them the appointment.
    payload = dict(item.payload or {})
    payload["scheduled_at"] = start_at.isoformat()
    payload["duration_minutes"] = int((end_at - start_at).total_seconds() // 60)

    def keep() -> None:
        item.payload = dict(payload)

    en = (getattr(user, "locale", None) or "ko") == "en"
    who = payload.get("visitor_name") or ("a visitor" if en else "방문자")
    # 일정 이름은 주인이 쓰는 말로 — 주인의 달력(Google 캘린더)에도 이 이름으로 들어간다.
    title = f"Meeting with {who}" if en else f"{who}님과의 미팅"
    guest = payload.get("visitor_email") or ""
    contact = str(payload.get("contact") or "")
    if not guest and "@" in contact:
        guest = contact.split()[0].strip(" ,;")
    # 수락은 스케줄에 먼저 들어간다 (plan/56). Google 이 없어도 약속은 일정이 된다.
    from blackmoa.models import ScheduleEvent
    from blackmoa.services import schedule as SCH
    # 같은 요청을 다시 수락하면(시간을 바꿔서) 일정이 둘이 되지 않고 그 일정이 옮겨 간다.
    ev = None
    if payload.get("schedule_event_id"):
        ev = (await db.execute(select(ScheduleEvent).where(
            ScheduleEvent.owner_id == item.owner_id, ScheduleEvent.inbox_item_id == item.id))).scalars().first()
    if ev is not None:
        await SCH.update(db, user, ev, {"start": start_at.isoformat(), "end": end_at.isoformat()})
    else:
        ev = await SCH.create(db, user, title=title, start=start_at.isoformat(), end=end_at.isoformat(),
                              location=str(payload.get("location") or ""), note=str(payload.get("purpose") or "")[:2000],
                              busy=True, source="meeting", agent_id=item.agent_id, inbox_item_id=item.id)
    payload["schedule_event_id"] = str(ev.id)
    result: dict[str, Any] = {"created": True, "schedule_event_id": str(ev.id), "start_at": start_at.isoformat(),
                              "end_at": end_at.isoformat()}
    if ev.google_event_id:
        # 이미 바깥 달력에 한 번 들어간 약속이다. 두 번째 사본을 만들지 않는다.
        keep()
        return {**result, "external": {"provider": None, "label": "", "status": "unchanged"}}
    # "수락한 미팅을 넣기" 를 켠 바깥 달력(Google 캘린더·카카오 톡캘린더)에도 (plan/58·59).
    from blackmoa.services import calendar_sources as CS
    pushed = await CS.push_event(db, item.owner_id, summary=title, start=start_at, end=end_at,
                                 description=str(payload.get("purpose") or "")[:2000], location=str(payload.get("location") or ""),
                                 attendees=[guest] if "@" in guest else None,
                                 timezone=getattr(user, "timezone", None) or "Asia/Seoul")
    if pushed["status"] == "failed":
        log.warning("calendar write failed", err=pushed.get("error", ""), item=str(item.id), provider=pushed["provider"])
    if pushed["status"] == "added":
        payload["calendar_event_id"] = pushed["event_id"]
        payload["calendar_provider"] = pushed.get("provider") or ""
        # 동기화해 온 같은 일정과 겹쳐 보이지 않게 — 어느 달력이든 그 달력의 일정 번호를 적어 둔다.
        ev.google_event_id = pushed["event_id"] or None
    keep()
    return {**result, "external": {k: pushed.get(k) for k in ("provider", "label", "status")},
            "html_link": pushed.get("html_link", ""),
            # 초대는 이메일로 부르는 달력(Google)만 한다.
            "attendee": guest if ("@" in guest and pushed["status"] == "added" and pushed["provider"] == "google") else ""}


COMMUNITY_KINDS = ("community_comment", "community_reply")
#: 관심 기업의 소식 (plan/40 §7). 기업 기능이 꺼져 있으면 인박스·비서·아침 메일 어디에도 없다 (plan/71).
COMPANY_KINDS = ("company_review", "company_job")


async def hidden_kinds(db: AsyncSession) -> tuple[str, ...]:
    """지금 보이지 않는 소식의 종류."""
    from blackmoa.services.companies import switch as CO

    return () if await CO.enabled(db) else COMPANY_KINDS
#: 광장 쪽 알림. 이 짝이 비서에게 보이지 않는 경계다.


async def get_owned(db: AsyncSession, owner_id: uuid.UUID, item_id: uuid.UUID,
                    *, secretary: bool = False) -> InboxItem:
    it = await db.get(InboxItem, item_id)
    if it is None or it.owner_id != owner_id:
        raise NotFound("inbox item not found", code="inbox_not_found")
    if secretary and it.kind in COMMUNITY_KINDS:
        # 비서는 광장을 보지 않는다 (plan/51 §2). 이 알림은 주인의 익명 글에 달린
        # 댓글이라, 제목 하나만 읽어도 "내 주인이 광장에 그 글을 썼다" 가 비서의
        # 아는 것이 된다. 설정으로 막는 것이 아니라 **길을 내지 않는다.**
        raise NotFound("inbox item not found", code="inbox_not_found")
    return it


#: The person's own house (plan/41): somebody asking to connect is neither a visitor a
#: secretary handled nor a thread in the square.
NETWORK_KINDS = ("person_follow", "post_comment", "post_reply", "post_mention")


async def list_items(db: AsyncSession, owner_id: uuid.UUID, *, agent_id: uuid.UUID | None = None, kind: str | None = None,
                     status: str | None = None, limit: int = 50, after: uuid.UUID | None = None,
                     source: str | None = None, since: datetime | None = None,
                     until: datetime | None = None, secretary: bool = False) -> list[InboxItem]:
    stmt = select(InboxItem).where(InboxItem.owner_id == owner_id).order_by(InboxItem.created_at.desc()).limit(limit)
    if hidden := await hidden_kinds(db):
        stmt = stmt.where(InboxItem.kind.notin_(hidden))
    if secretary:
        # 비서가 부른 것이면 광장은 아예 없는 것으로 한다 (plan/51 §2). 거르는 자리를
        # 부르는 쪽에 두면 다음 도구가 생기는 순간 다시 샌다.
        stmt = stmt.where(InboxItem.kind.notin_(COMMUNITY_KINDS))
    # 인박스는 처리하는 자리라 지금 들어온 것부터 본다. 기간은 화면이 정해서 보내고,
    # 서버는 받은 만큼만 자른다.
    if since is not None:
        stmt = stmt.where(InboxItem.created_at >= since)
    if until is not None:
        stmt = stmt.where(InboxItem.created_at <= until)
    # Community items have no secretary, so "which secretary" cannot be the only way to
    # narrow this list — source is the filter that separates the two halves of the inbox.
    if source == "community":
        stmt = stmt.where(InboxItem.kind.in_(COMMUNITY_KINDS))
    elif source == "people":
        stmt = stmt.where(InboxItem.kind.in_(NETWORK_KINDS))
    elif source == "agent":
        stmt = stmt.where(InboxItem.kind.notin_(COMMUNITY_KINDS + NETWORK_KINDS))
    if agent_id:
        stmt = stmt.where(InboxItem.agent_id == agent_id)
    if kind:
        stmt = stmt.where(InboxItem.kind == kind)
    if status:
        stmt = stmt.where(InboxItem.status == status)
    if after:
        a = await db.get(InboxItem, after)
        if a:
            stmt = stmt.where(InboxItem.created_at < a.created_at)
    return list((await db.execute(stmt)).scalars().all())


async def set_status(item: InboxItem, status: str, reply: str | None = None) -> InboxItem:
    if status in ("new", "read", "replied", "archived", "accepted", "declined"):
        item.status = status
    if reply is not None:
        item.owner_reply = reply[:4000]
        item.status = "replied" if status == "read" else item.status
    item.updated_at = datetime.now(UTC)
    return item
