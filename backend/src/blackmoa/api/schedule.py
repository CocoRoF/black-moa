"""[내 정보 → 스케줄] (plan/56): 일정과 연락 가능 시간."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from blackmoa.core.deps import DB, CurrentUser
from blackmoa.core.errors import ValidationFailed
from blackmoa.services import calendar_sources as CS
from blackmoa.services import profile as PF
from blackmoa.services import schedule as SCH

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

#: 한 번에 볼 수 있는 기간. 달력 한 장(6주)에 여유를 둔다.
MAX_RANGE = timedelta(days=62)


def _range(tz, frm: date | None, to: date | None) -> tuple[datetime, datetime]:
    today = datetime.now(tz).date()
    frm = frm or today.replace(day=1)
    to = to or (frm + timedelta(days=41))
    if to < frm:
        raise ValidationFailed("the range ends before it starts", code="bad_range")
    start = datetime.combine(frm, time.min, tz)
    end = datetime.combine(to + timedelta(days=1), time.min, tz)
    if end - start > MAX_RANGE:
        raise ValidationFailed("the range is too long", code="range_too_long")
    return start.astimezone(UTC), end.astimezone(UTC)


@router.get("")
async def overview(user: CurrentUser, db: DB, frm: date | None = Query(default=None, alias="from"), to: date | None = None):
    """달력 한 장: 그 기간의 일정(black-moa + 가져오기를 켠 바깥 달력)과 시간대 — 이 사람의 것만.
    공휴일·명절·음력은 한 해치로 따로 받는다(``/api/calendar/KR/{year}``, plan/60)."""
    tz = SCH.zone(user)
    start, end = _range(tz, frm, to)
    events = await SCH.events_between(db, user, start, end)
    # 오래된 바깥 달력은 가져오기를 걸어 둔다 — 끝나면 화면이 소식을 받아 다시 읽는다(plan/76).
    if await CS.refresh_if_stale(db, user.id):
        await db.commit()
    return {"timezone": str(tz), "events": events}


class EventIn(BaseModel):
    title: str = Field(..., max_length=SCH.TITLE_MAX)
    all_day: bool = False
    #: "2026-09-25T15:00"(주인 시간대) 또는 종일이면 "2026-09-25"
    start: str = Field(..., max_length=40)
    end: str | None = Field(default=None, max_length=40)
    location: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=2000)
    busy: bool | None = None


class EventPatch(BaseModel):
    title: str | None = Field(default=None, max_length=SCH.TITLE_MAX)
    all_day: bool | None = None
    start: str | None = Field(default=None, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=2000)
    busy: bool | None = None


@router.post("/events", status_code=201)
async def create_event(body: EventIn, user: CurrentUser, db: DB):
    ev = await SCH.create(db, user, title=body.title, start=body.start, end=body.end, all_day=body.all_day,
                          location=body.location, note=body.note, busy=body.busy, source="owner")
    await db.commit()
    return SCH.out(ev, SCH.zone(user))


@router.patch("/events/{event_id}")
async def patch_event(event_id: str, body: EventPatch, user: CurrentUser, db: DB):
    ev = await SCH.get_owned(db, user.id, event_id)
    await SCH.update(db, user, ev, body.model_dump(exclude_unset=True))
    await db.commit()
    return SCH.out(ev, SCH.zone(user))


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(event_id: str, user: CurrentUser, db: DB):
    ev = await SCH.get_owned(db, user.id, event_id)
    await SCH.remove(db, ev)
    await db.commit()
    return Response(status_code=204)


async def _availability(db, user) -> dict[str, Any]:
    """연락 가능 시간 — 요일·시각 줄과 메모. 외부인에게 알려 줄지는 비서의 [지식] 탭이 정한다 (plan/57)."""
    prof = await PF.get(db, user.id)
    win = SCH.window_of(prof)
    return {"weekly": win.get("weekly") or [], "note": win.get("note") or "", "timezone": str(SCH.zone(user)),
            "skip_holidays": SCH.skips_holidays(win)}


@router.get("/availability")
async def get_availability(user: CurrentUser, db: DB):
    return await _availability(db, user)


class AvailabilityIn(BaseModel):
    weekly: list[dict[str, Any]] | None = Field(default=None, max_length=14)
    note: str | None = Field(default=None, max_length=200)
    #: 공휴일에는 빈 시간을 내지 않는다 (plan/60). 정하지 않았으면 켜진 것으로 본다.
    skip_holidays: bool | None = None


@router.put("/availability")
async def put_availability(body: AvailabilityIn, user: CurrentUser, db: DB):
    await SCH.save_availability(db, user, weekly=body.weekly, note=body.note, skip_holidays=body.skip_holidays)
    await db.commit()
    return await _availability(db, user)


# ── [연동] 탭 (plan/58) ───────────────────────────────────────────────────

@router.get("/sources")
async def sources(user: CurrentUser, db: DB):
    """붙일 수 있는 달력마다 연결 상태와 가져오기 설정."""
    return {"items": await CS.sources(db, user.id)}


class SourcePatch(BaseModel):
    read: bool | None = None
    write: bool | None = None
    auto_every: int | None = None


@router.patch("/sources/{provider}")
async def patch_source(provider: str, body: SourcePatch, user: CurrentUser, db: DB, response: Response):
    """가져오기·자동 가져오기·미팅 넣기를 바꾼다. 아직 받지 않은 권한을 켜려 하면 동의 화면 주소를 준다."""
    r = await CS.update(db, user.id, provider, read=body.read, write=body.write, auto_every=body.auto_every)
    consent_url = None
    if r["needs_consent"]:
        # 권한을 더 받으려면 동의 화면을 거쳐야 하는데, 관리 설정에서 꺼져 있으면 그 길이 없다.
        if not await CS.PROVIDERS[provider].available(db):
            raise ValidationFailed("this calendar cannot be connected right now", code="calendar_unavailable")
        consent_url = await _connect_url(db, user, provider, r["needs_consent"], response)
    await db.commit()
    return {"items": await CS.sources(db, user.id), "consent_url": consent_url}


async def _connect_url(db, user, provider: str, caps: list[str], response: Response) -> str:
    # 이미 허락한 것(메일·연락처)은 그대로 두고 달력 권한을 더한다. 끝나면 이 탭으로 돌아온다.
    from blackmoa.api.integrations import start_url
    return await start_url(db, user, provider, caps, "/app/schedule?tab=sync", response)


@router.post("/sources/{provider}/connect")
async def connect_source(provider: str, user: CurrentUser, db: DB, response: Response):
    """이 달력을 연결한다 — 일정 읽기와 미팅 넣기를 함께 청한다."""
    p = CS.PROVIDERS.get(provider)
    if p is None:
        raise ValidationFailed("no such calendar", code="calendar_provider_unknown")
    if not await p.available(db):
        raise ValidationFailed("this calendar cannot be connected right now", code="calendar_unavailable")
    return {"url": await _connect_url(db, user, provider, [p.read_cap, p.write_cap], response)}


@router.post("/sources/{provider}/sync")
async def sync_source(provider: str, user: CurrentUser, db: DB):
    """지금 가져오기."""
    n = await CS.sync_now(db, user.id, provider)
    await db.commit()
    return {"events": n, "items": await CS.sources(db, user.id)}
