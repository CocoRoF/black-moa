"""스케줄 도구 (plan/56). 비서는 주인의 스케줄에 연결되어 쓴다 — 비서마다의 스위치는 없다.

읽기: 주인 대화는 일정 전부(black-moa + 가져온 바깥 달력), 방문자 대화는 연락 가능 시간 안의 **빈 시간만**, 그것도
연락 가능 시간의 공개 범위가 허락할 때만. 쓰기(넣기·고치기·지우기)는 주인 대화에서, 주인이 시킬 때만.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from blackmoa.db.session import session_scope
from blackmoa.models import User
from blackmoa.pipeline.tools.base import SecretaryTool, secretary_tool
from blackmoa.services import outsider as OUT
from blackmoa.services import schedule as SCH
from blackmoa.services import special_days as SD

_OWNER = frozenset({"owner"})
#: 일정이 어디서 왔는지 — 바깥 달력은 [연동] 에서 가져오기를 켠 것 (plan/58·59).
_FROM = {"google": "Google Calendar", "kakao": "Kakao Talk Calendar", "meeting": "accepted meeting request"}


def _external(event_id) -> str | None:
    """가져온 바깥 달력의 일정이면 그 달력의 이름 — 그런 일정은 거기서 고친다."""
    head, sep, _ = str(event_id or "").partition(":")
    return _FROM.get(head) if sep and head in ("google", "kakao") else None


_WD = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _day(d: str | None) -> str:
    """날짜에 요일을 붙인다 — 모델이 요일을 스스로 셈하면 하루씩 틀린다(2026-09-29 데모에서 10/2 금을 목요일로)."""
    try:
        return f"{d} ({_WD[date.fromisoformat(str(d)[:10]).weekday()]})"
    except ValueError:
        return str(d or "")


def _when(ev: dict) -> str:
    if ev.get("all_day"):
        a, b = ev.get("start_date"), ev.get("end_date")
        return f"{_day(a)} (all day)" if a == b else f"{_day(a)} – {_day(b)} (all day)"
    s, e = ev.get("start") or "", ev.get("end") or ""
    if s[:10] == e[:10]:
        return f"{_day(s[:10])} {s[11:16]}–{e[11:16]}"
    return f"{_day(s[:10])} {s[11:16]} – {_day(e[:10])} {e[11:16]}"


@secretary_tool
class CalendarList(SecretaryTool):
    tool_name = "calendar_list"
    tool_description = ("List the owner's schedule for a range (default: today through +7 days): events the owner put in "
                        "black-moa and, if connected, their outside calendars, plus the Korean public holidays and special "
                        "days in that range. Times are in the owner's timezone.")
    schema = {"type": "object", "properties": {"start": {"type": "string", "description": "ISO date or datetime"},
                                               "end": {"type": "string"}}}
    audiences = _OWNER
    label_template = "일정을 확인하는 중"

    async def run(self, args):
        # 바깥 달력이 오래됐으면 먼저 가져온다 — 방금 Google·톡캘린더에서 바꾼 일정으로 답하게 (plan/76).
        from blackmoa.services import calendar_sources as CS
        await CS.ensure_fresh(self.ctx.owner_id)
        tz = SCH.zone(self.ctx.owner)
        now = datetime.now(tz)
        start = SCH.parse_when(args["start"], tz) if args.get("start") else now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = SCH.parse_when(args["end"], tz) if args.get("end") else start + timedelta(days=7)
        if len(str(args.get("end") or "")) == 10:
            end += timedelta(days=1)          # 끝 날짜는 그날 하루를 포함한다
        end = min(end, start + timedelta(days=62))
        async with session_scope() as db:
            owner = await db.get(User, self.ctx.owner_id)
            evs = await SCH.events_between(db, owner, start, end, limit=100)
            days = await SD.between(db, start.date(), (end - timedelta(seconds=1)).date())
        # 공휴일·명절·절기·기념일 (plan/60) — "그날은 추석이에요" 를 비서가 알고 말하도록.
        special = [{"date": _day(d), "names": [n["name"] for n in v["names"]], **({"day_off": True} if v["off"] else {})}
                   for d, v in days.items() if v["names"]][:40]
        return {"timezone": str(tz), **({"special_days": special} if special else {}), "events": [
            {"id": e["id"], "title": e["title"], "when": _when(e), "location": e["location"] or None,
             "from": _FROM.get(e["source"], "black-moa"),
             "editable": not e["readonly"], **({"attendees": e["attendees"]} if e["attendees"] else {}),
             **({"note": e["note"][:300]} if e["note"] else {})} for e in evs]}


@secretary_tool
class CalendarAvailability(SecretaryTool):
    tool_name = "calendar_availability"
    tool_description = ("Free time slots inside the owner's contactable hours for a date range. Returns free slots only — "
                        "never what the owner is doing.")
    schema = {"type": "object", "properties": {"start": {"type": "string", "description": "ISO date or datetime"},
                                               "end": {"type": "string"},
                                               "slot_minutes": {"type": "integer", "minimum": 15, "maximum": 240}}}
    outsider = "schedule"
    label_template = "가능한 시간을 확인하는 중"

    async def run(self, args):
        tz = SCH.zone(self.ctx.owner)
        d = OUT.disclosure_of(self.ctx)
        viewer = d.viewer
        # 인맥에게만 알려 주는 비서라면, 모르는 사람에게는 도구가 있어도 여기서 멈춘다 (plan/57).
        if not d.schedule:
            return {"error": {"code": "calendar_private", "message": "The owner does not share their available times with you."}}
        # 빈 시간은 바깥 달력까지 보고 센다 — 오래됐으면 먼저 가져와 이미 잡힌 시간을 내주지 않게 (plan/76).
        from blackmoa.services import calendar_sources as CS
        await CS.ensure_fresh(self.ctx.owner_id)
        now = datetime.now(tz)
        start = SCH.parse_when(args["start"], tz) if args.get("start") else now
        end = SCH.parse_when(args["end"], tz) if args.get("end") else start + timedelta(days=5)
        if len(str(args.get("end") or "")) == 10:
            end += timedelta(days=1)
        end = min(end, start + timedelta(days=14))
        async with session_scope() as db:
            owner = await db.get(User, self.ctx.owner_id)
            slots = await SCH.free_slots(db, owner, self.ctx.profile, start=start, end=end,
                                         slot_minutes=int(args.get("slot_minutes") or 60), for_owner=viewer == "owner")
            closed = {}
            if SCH.skips_holidays(SCH.window_of(self.ctx.profile)):
                closed = await SD.off_days(db, start.date(), end.date())
        out = {"timezone": str(tz), "free_slots": [s["label"] for s in slots],
               "note": "Only free time inside the owner's contactable hours is shared — never what fills the rest."}
        if closed:
            # 공휴일은 공공의 사실이다 — 왜 그날이 비어 있지 않은지 말할 수 있게 (plan/60).
            out["public_holidays_off"] = [f"{d.isoformat()} {n}" for d, n in sorted(closed.items())]
        return out


def _card(ctx, action: str, ev: dict) -> None:
    ctx.card("schedule_saved", {"action": action, "title": ev["title"], "when": _when(ev), "event_id": ev["id"],
                                "all_day": ev["all_day"], "start_date": ev["start_date"]})


@secretary_tool
class ScheduleAdd(SecretaryTool):
    tool_name = "schedule_add"
    tool_description = ("Put an event on the owner's schedule when the owner asks you to. Times are in the owner's timezone "
                        "(e.g. 2026-09-25T15:00). For an all-day event give dates and all_day=true.")
    schema = {"type": "object", "properties": {
        "title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
        "all_day": {"type": "boolean"}, "location": {"type": "string"}, "note": {"type": "string"},
        "busy": {"type": "boolean", "description": "whether it blocks the owner's free time (default: yes, no for all-day)"}},
        "required": ["title", "start"]}
    audiences = _OWNER
    read_only = False
    label_template = "일정을 넣는 중"

    async def run(self, args):
        async with session_scope() as db:
            owner = await db.get(User, self.ctx.owner_id)
            ev = await SCH.create(db, owner, title=args["title"], start=args["start"], end=args.get("end"),
                                  all_day=bool(args.get("all_day")), location=args.get("location") or "",
                                  note=args.get("note") or "", busy=args.get("busy"), source="secretary",
                                  agent_id=self.ctx.agent.id)
            await db.commit()
            out = SCH.out(ev, SCH.zone(owner))
        _card(self.ctx, "added", out)
        return {"added": {"id": out["id"], "title": out["title"], "when": _when(out)}}


@secretary_tool
class ScheduleUpdate(SecretaryTool):
    tool_name = "schedule_update"
    tool_description = ("Change an event on the owner's schedule (title, time, place, note) when the owner asks. "
                        "Use the id from calendar_list. Events imported from an outside calendar can only be changed there.")
    schema = {"type": "object", "properties": {
        "event_id": {"type": "string"}, "title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
        "all_day": {"type": "boolean"}, "location": {"type": "string"}, "note": {"type": "string"}, "busy": {"type": "boolean"}},
        "required": ["event_id"]}
    audiences = _OWNER
    read_only = False
    label_template = "일정을 고치는 중"

    async def run(self, args):
        if (where := _external(args.get("event_id"))):
            return {"error": {"code": "external_readonly", "message": f"That event lives in {where}; change it there."}}
        changes = {k: args[k] for k in ("title", "start", "end", "all_day", "location", "note", "busy") if k in args}
        async with session_scope() as db:
            owner = await db.get(User, self.ctx.owner_id)
            ev = await SCH.get_owned(db, owner.id, args["event_id"])
            await SCH.update(db, owner, ev, changes)
            await db.commit()
            out = SCH.out(ev, SCH.zone(owner))
        _card(self.ctx, "updated", out)
        return {"updated": {"id": out["id"], "title": out["title"], "when": _when(out)}}


@secretary_tool
class ScheduleRemove(SecretaryTool):
    tool_name = "schedule_remove"
    tool_description = ("Remove an event from the owner's schedule when the owner asks. Events imported from an outside "
                        "calendar are removed there.")
    schema = {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"]}
    audiences = _OWNER
    read_only = False
    label_template = "일정을 지우는 중"

    async def run(self, args):
        if (where := _external(args.get("event_id"))):
            return {"error": {"code": "external_readonly", "message": f"That event lives in {where}; remove it there."}}
        async with session_scope() as db:
            owner = await db.get(User, self.ctx.owner_id)
            ev = await SCH.get_owned(db, owner.id, args["event_id"])
            out = SCH.out(ev, SCH.zone(owner))
            await SCH.remove(db, ev)
            await db.commit()
        _card(self.ctx, "removed", out)
        return {"removed": {"title": out["title"], "when": _when(out)}}
