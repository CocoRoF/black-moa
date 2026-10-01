"""스케줄 — 연락 가능 시간과 일정 (plan/56).

**스케줄은 원장이다.** 연락 가능 시간과 일정은 [내 정보 → 스케줄] 한 곳에서 정하고, 비서는 그것을
쓴다. 비서마다 켜고 끄는 스위치는 없다 — 내 비서는 내 스케줄을 전부 안다(주인과의 대화).

**밖으로 나가는 것은 빈 시간뿐이다.** 방문자에게는 연락 가능 시간 안의 빈 시간만 나가고, 누가 그것을
알 수 있는지는 연락 가능 시간 한 칸의 공개 범위(plan/48 의 세 단어)가 정한다. 일정의 이름·장소·
참석자는 어떤 경우에도 나가지 않는다.

**black-moa 가 캘린더다.** 일정은 여기 직접 넣고, Google 을 연결하면 그 일정이 함께 보이고 빈 시간
계산에도 들어간다. 시간은 전부 주인의 시간대(`users.timezone`)로 읽고 쓴다.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.errors import NotFound, ValidationFailed
from blackmoa.models import Connection, IntegrationEvent, ScheduleEvent, User

SOURCES = ("owner", "secretary", "meeting")
TITLE_MAX = 200
MAX_SPAN = timedelta(days=31)
#: 연락 가능 시간을 정하지 않은 주인 자신에게만 쓰는 기본 틀. 밖으로는 절대 쓰지 않는다.
OWNER_DEFAULT_WEEKLY = [{"days": [0, 1, 2, 3, 4], "start": "10:00", "end": "18:00"}]
_DAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]


def zone(owner: Any) -> ZoneInfo:
    try:
        return ZoneInfo(getattr(owner, "timezone", None) or "Asia/Seoul")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Seoul")


def parse_when(value: Any, tz: ZoneInfo, *, field: str = "time") -> datetime:
    """"2026-09-25", "2026-09-25T15:00", ISO(오프셋 포함) 을 주인 시간대의 시각으로.

    오프셋이 없는 시각은 **주인의** 시각이다 — 브라우저나 서버의 시간대가 아니다."""
    s = str(value or "").strip()
    if not s:
        raise ValidationFailed(f"{field} is required", code="bad_time", detail={"field": field})
    try:
        if len(s) == 10:
            return datetime.combine(date.fromisoformat(s), time.min, tz)
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValidationFailed(f"cannot read {field}", code="bad_time", detail={"field": field}) from e
    return d if d.tzinfo else d.replace(tzinfo=tz)


def _local(d: datetime, tz: ZoneInfo) -> datetime:
    return d.astimezone(tz)


# ── 일정 ────────────────────────────────────────────────────────────────


def _normalize(tz: ZoneInfo, *, start: Any, end: Any, all_day: bool) -> tuple[datetime, datetime]:
    """종일이면 주인 시간대의 그날 자정 ~ 마지막 날 다음 자정. 끝 날짜는 포함(입력은 "25일~26일")."""
    if all_day:
        s = parse_when(str(start)[:10], tz, field="start")
        e_day = parse_when(str(end or start)[:10], tz, field="end")
        if e_day < s:
            raise ValidationFailed("the event ends before it starts", code="bad_range")
        e = e_day + timedelta(days=1)
    else:
        s = parse_when(start, tz, field="start")
        e = parse_when(end, tz, field="end") if end else s + timedelta(hours=1)
        if e <= s:
            raise ValidationFailed("the event ends before it starts", code="bad_range")
    if e - s > MAX_SPAN:
        raise ValidationFailed("an event can be at most 31 days long", code="range_too_long")
    return s.astimezone(UTC), e.astimezone(UTC)


async def create(db: AsyncSession, owner: User, *, title: str, start: Any, end: Any = None, all_day: bool = False,
                 location: str = "", note: str = "", busy: bool | None = None, source: str = "owner",
                 agent_id: uuid.UUID | None = None, inbox_item_id: uuid.UUID | None = None,
                 google_event_id: str | None = None) -> ScheduleEvent:
    title = (title or "").strip()[:TITLE_MAX]
    if not title:
        raise ValidationFailed("the event needs a name", code="empty_title")
    s, e = _normalize(zone(owner), start=start, end=end, all_day=all_day)
    ev = ScheduleEvent(owner_id=owner.id, title=title, start_at=s, end_at=e, all_day=bool(all_day),
                       location=(location or "").strip()[:500], note=(note or "").strip()[:2000],
                       # 종일 일정(생일·기념일)은 기본으로 빈 시간을 막지 않는다.
                       busy=(not all_day) if busy is None else bool(busy),
                       source=source if source in SOURCES else "owner", agent_id=agent_id, inbox_item_id=inbox_item_id,
                       google_event_id=google_event_id)
    db.add(ev)
    await db.flush()
    return ev


async def get_owned(db: AsyncSession, owner_id: uuid.UUID, event_id: Any) -> ScheduleEvent:
    try:
        eid = uuid.UUID(str(event_id))
    except (TypeError, ValueError) as e:
        raise NotFound("event not found", code="event_not_found") from e
    ev = await db.get(ScheduleEvent, eid)
    if ev is None or ev.owner_id != owner_id:
        raise NotFound("event not found", code="event_not_found")
    return ev


async def update(db: AsyncSession, owner: User, ev: ScheduleEvent, changes: dict[str, Any]) -> ScheduleEvent:
    tz = zone(owner)
    if "title" in changes:
        t = str(changes["title"] or "").strip()[:TITLE_MAX]
        if not t:
            raise ValidationFailed("the event needs a name", code="empty_title")
        ev.title = t
    if any(k in changes for k in ("start", "end", "all_day")):
        all_day = bool(changes.get("all_day", ev.all_day))
        s_loc, e_loc = _local(ev.start_at, tz), _local(ev.end_at, tz)
        if all_day:
            first = str(changes.get("start") or s_loc.date().isoformat())[:10]
            last_now = (e_loc - timedelta(days=1)) if ev.all_day else e_loc
            last = str(changes.get("end") or last_now.date().isoformat())[:10]
            if last < first:
                last = first
            start, end = first, last
        elif "start" in changes and "end" not in changes:
            # 시작만 옮기면 길이는 그대로 — "3시로 옮겨 줘" 가 일정을 늘리거나 줄이지 않게.
            s0 = parse_when(changes["start"], tz, field="start")
            length = (ev.end_at - ev.start_at) if not ev.all_day else timedelta(hours=1)
            start, end = s0.isoformat(), (s0 + length).isoformat()
        else:
            # 종일 → 시간 일정으로 바꾸며 시각을 주지 않았으면 그날 9시부터 한 시간.
            base = s_loc if not ev.all_day else datetime.combine(s_loc.date(), time(9), tz)
            start = changes.get("start") or base.isoformat()
            end = changes.get("end") or ((e_loc if not ev.all_day else base + timedelta(hours=1)).isoformat())
        ev.start_at, ev.end_at = _normalize(tz, start=start, end=end, all_day=all_day)
        if all_day != ev.all_day and "busy" not in changes:
            ev.busy = not all_day
        ev.all_day = all_day
    for k, cap in (("location", 500), ("note", 2000)):
        if k in changes:
            setattr(ev, k, str(changes[k] or "").strip()[:cap])
    if "busy" in changes and changes["busy"] is not None:
        ev.busy = bool(changes["busy"])
    ev.updated_at = datetime.now(UTC)
    return ev


async def remove(db: AsyncSession, ev: ScheduleEvent) -> None:
    await db.delete(ev)


def out(ev: ScheduleEvent, tz: ZoneInfo) -> dict[str, Any]:
    s, e = _local(ev.start_at, tz), _local(ev.end_at, tz)
    return {"id": str(ev.id), "source": ev.source, "readonly": False, "title": ev.title, "all_day": ev.all_day,
            "start": s.isoformat(), "end": e.isoformat(),
            # 종일 일정은 날짜로 — 끝 날짜는 포함(마지막 날). 화면이 시간대를 다시 계산하지 않게 한다.
            "start_date": s.date().isoformat(), "end_date": ((e - timedelta(days=1)) if ev.all_day else e).date().isoformat(),
            "location": ev.location, "note": ev.note, "busy": ev.busy,
            "agent_id": str(ev.agent_id) if ev.agent_id else None,
            "inbox_item_id": str(ev.inbox_item_id) if ev.inbox_item_id else None, "attendees": []}


def _external_out(g: IntegrationEvent, tz: ZoneInfo, provider: str) -> dict[str, Any]:
    """바깥 달력(Google·카카오 …)에서 가져온 일정 — 읽기 전용, ``source`` 는 그 공급자."""
    s = _local(g.start_at, tz) if g.start_at else None
    e = _local(g.end_at, tz) if g.end_at else None
    return {"id": f"{provider}:{g.ext_id}", "source": provider, "readonly": True, "title": g.title or "(제목 없음)",
            "all_day": g.all_day, "start": s.isoformat() if s else None, "end": e.isoformat() if e else None,
            "start_date": s.date().isoformat() if s else None,
            "end_date": (((e - timedelta(days=1)) if g.all_day else e).date().isoformat()) if e else None,
            "location": g.location, "note": g.description_summary, "busy": bool(getattr(g, "busy", True)),
            "agent_id": None, "inbox_item_id": None,
            "attendees": [a.get("name") or a.get("email") for a in (g.attendees or []) if isinstance(a, dict)][:10]}


async def events_between(db: AsyncSession, owner: User, start: datetime, end: datetime, *, limit: int = 300) -> list[dict[str, Any]]:
    """기간의 일정: black-moa 에 넣은 것 + 바깥 달력에서 가져온 것. 바깥 달력에도 넣은 black-moa 일정은 한 번만."""
    tz = zone(owner)
    mine = (await db.execute(select(ScheduleEvent).where(ScheduleEvent.owner_id == owner.id, ScheduleEvent.start_at < end,
                                                         ScheduleEvent.end_at > start)
                             .order_by(ScheduleEvent.start_at).limit(limit))).scalars().all()
    pushed = {e.google_event_id for e in mine if e.google_event_id}
    # 바깥 달력은 [연동] 에서 "일정 가져오기" 를 켜 둔 것만 붙는다 (plan/58).
    from blackmoa.services import calendar_sources as CS
    reading = await CS.reading_ids(db, owner.id)
    theirs = (await db.execute(select(IntegrationEvent, Connection.provider).join(Connection, Connection.id == IntegrationEvent.connection_id)
                               .where(IntegrationEvent.owner_id == owner.id, IntegrationEvent.start_at < end,
                                      IntegrationEvent.end_at > start, IntegrationEvent.status != "cancelled",
                                      IntegrationEvent.connection_id.in_(reading or [uuid.uuid4()]))
                               .order_by(IntegrationEvent.start_at).limit(limit))).all()
    items = [out(e, tz) for e in mine] + [_external_out(g, tz, prov) for g, prov in theirs if g.ext_id not in pushed]
    items.sort(key=lambda x: (x["start"] or "", x["title"]))
    return items[:limit]


async def busy_between(db: AsyncSession, owner_id: uuid.UUID, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    a = (await db.execute(select(ScheduleEvent.start_at, ScheduleEvent.end_at).where(
        ScheduleEvent.owner_id == owner_id, ScheduleEvent.busy.is_(True),
        ScheduleEvent.start_at < end, ScheduleEvent.end_at > start))).all()
    from blackmoa.services import calendar_sources as CS
    reading = await CS.reading_ids(db, owner_id)
    b = (await db.execute(select(IntegrationEvent.start_at, IntegrationEvent.end_at).where(
        IntegrationEvent.owner_id == owner_id, IntegrationEvent.busy.is_(True), IntegrationEvent.status != "cancelled",
        IntegrationEvent.connection_id.in_(reading or [uuid.uuid4()]),
        IntegrationEvent.start_at < end, IntegrationEvent.end_at > start))).all()
    return [(s, e) for s, e in [*a, *b] if s and e]


# ── 연락 가능 시간과 빈 시간 ─────────────────────────────────────────────────


def window_of(profile: Any) -> dict[str, Any]:
    return dict(((getattr(profile, "data", None) or {}).get("availability_window")) or {})


def skips_holidays(win: dict[str, Any]) -> bool:
    """공휴일에는 연락을 받지 않는가 (plan/60). 정한 적이 없으면 그렇다 — 추석에 미팅을 잡아 주면 안 된다."""
    return win.get("skip_holidays") is not False


def _hm(s: str) -> tuple[int, int]:
    try:
        h, m = str(s)[:5].split(":")
        return max(0, min(24, int(h))), max(0, min(59, int(m)))
    except (ValueError, AttributeError):
        return 0, 0


async def free_slots(db: AsyncSession, owner: User, profile: Any, *, start: datetime, end: datetime,
                     slot_minutes: int = 60, limit: int = 40, for_owner: bool = False) -> list[dict[str, str]]:
    """연락 가능 시간 안에서 일정이 없는 칸. 방문자 도구와 비서 [지식] 탭의 미리보기가 같은 이 함수를 쓴다.

    연락 가능 시간을 정하지 않았으면 방문자에게는 빈 목록이다(기본 틀을 내보내지 않는다). 주인 자신이
    물으면 평일 10–18시를 기본 틀로 쓴다.
    """
    tz = zone(owner)
    win = window_of(profile)
    weekly = win.get("weekly") or (OWNER_DEFAULT_WEEKLY if for_owner else [])
    if not weekly:
        return []
    step = timedelta(minutes=max(15, min(int(slot_minutes or 60), 240)))
    start_l, end_l = start.astimezone(tz), end.astimezone(tz)
    now = datetime.now(tz)
    busy = await busy_between(db, owner.id, start_l.astimezone(UTC), end_l.astimezone(UTC))
    # 공휴일(대체공휴일·선거일·임시공휴일 포함)은 통째로 비운다 — 주인이 끄지 않았다면 (plan/60).
    closed: dict[date, str] = {}
    if skips_holidays(win):
        from blackmoa.services import special_days as SD
        closed = await SD.off_days(db, start_l.date(), end_l.date())
    out_: list[dict[str, str]] = []
    day = start_l.date()
    while day <= end_l.date() and len(out_) < limit:
        if day in closed:
            day += timedelta(days=1)
            continue
        spans: list[tuple[datetime, datetime]] = []
        for row in weekly[:14]:
            if day.weekday() not in (row.get("days") or []):
                continue
            (sh, sm), (eh, em) = _hm(row.get("start", "")), _hm(row.get("end", ""))
            ws = datetime.combine(day, time(min(sh, 23), sm), tz)
            we = datetime.combine(day, time.min, tz) + timedelta(hours=eh, minutes=em)
            if we > ws:
                spans.append((ws, we))
        for ws, we in sorted(spans):
            cur = ws
            while cur + step <= we and len(out_) < limit:
                nxt = cur + step
                if cur >= start_l and nxt <= end_l + timedelta(seconds=1) and cur > now:
                    cu, nu = cur.astimezone(UTC), nxt.astimezone(UTC)
                    if not any(a < nu and b > cu for a, b in busy):
                        label = f"{cur.strftime('%Y-%m-%d')} {_DAYS_KO[cur.weekday()]} {cur.strftime('%H:%M')}–{nxt.strftime('%H:%M')}"
                        if not any(o["start"] == cur.isoformat() for o in out_):
                            out_.append({"start": cur.isoformat(), "end": nxt.isoformat(), "label": label})
                cur = nxt
        day += timedelta(days=1)
    return out_


async def save_availability(db: AsyncSession, owner: User, *, weekly: list[dict[str, Any]] | None, note: str | None,
                            skip_holidays: bool | None = None) -> Any:
    """연락 가능 시간을 적는다. 자리는 프로필 데이터의 한 칸이지만 프로필 칸은 아니다 — 공개 범위가 없고,
    외부인에게 빈 시간을 알려 줄지는 비서의 [지식] 탭 스케줄 줄이 정한다 (plan/57)."""
    from blackmoa.services import profile as PF

    rows = []
    for r in (weekly or [])[:14]:
        days = sorted({int(d) for d in (r.get("days") or []) if str(d).isdigit() and 0 <= int(d) <= 6})
        sh, sm = _hm(r.get("start", ""))
        eh, em = _hm(r.get("end", ""))
        if not days or (eh * 60 + em) <= (sh * 60 + sm):
            continue
        rows.append({"days": days, "start": f"{sh:02d}:{sm:02d}", "end": f"{eh:02d}:{em:02d}"})
    cur = window_of(await PF.get(db, owner.id))
    data = None
    if weekly is not None or note is not None or skip_holidays is not None:
        # 준 것만 바꾼다 — 메모만 고쳤는데 주간 표가 지워지면 안 된다.
        data = {"availability_window": {"weekly": rows if weekly is not None else (cur.get("weekly") or []),
                                        "note": (note or "").strip()[:200] if note is not None else (cur.get("note") or ""),
                                        "skip_holidays": skip_holidays if skip_holidays is not None else skips_holidays(cur)}}
    return await PF.update(db, owner.id, data=data)


def describe_for_prompt(profile: Any) -> str:
    from blackmoa.services import profile as PF
    return PF.render_window(window_of(profile))
