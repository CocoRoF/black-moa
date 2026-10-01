from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, date, datetime, time

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from blackmoa.core.deps import DB, CurrentUser
from blackmoa.models import Agent, Conversation, InboxItem, Message, Visitor
from blackmoa.services import inbox as I
from blackmoa.services import jobs as J
from blackmoa.services import knowledge as K

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


def item_out(i: InboxItem) -> dict:
    return {"id": str(i.id), "agent_id": str(i.agent_id) if i.agent_id else None, "conversation_id": str(i.conversation_id) if i.conversation_id else None,
            "visitor_id": str(i.visitor_id) if i.visitor_id else None, "kind": i.kind, "payload": i.payload, "status": i.status,
            "owner_reply": i.owner_reply, "created_at": i.created_at.isoformat(), "updated_at": i.updated_at.isoformat() if i.updated_at else None}


def _day(raw: str | None, *, end: bool = False) -> datetime | None:
    """`YYYY-MM-DD` 하루의 처음이나 끝. 읽히지 않으면 없는 것으로 둔다: 날짜를 잘못
    보냈다고 인박스가 비어 보이는 것보다 거르지 않는 편이 낫다."""
    try:
        d = date.fromisoformat((raw or "").strip())
    except ValueError:
        return None
    return datetime.combine(d, time.max if end else time.min, tzinfo=UTC)


@router.get("")
async def list_inbox(user: CurrentUser, db: DB, agent_id: uuid.UUID | None = None, kind: str | None = None, status: str | None = None, source: str | None = None,
                     after: uuid.UUID | None = None, limit: int = 50,
                     since: str | None = None, until: str | None = None):
    items = await I.list_items(db, user.id, agent_id=agent_id, kind=kind, status=status, limit=min(limit, 200), after=after, source=source,
                               since=_day(since), until=_day(until, end=True))
    new_q = select(func.count(InboxItem.id)).where(InboxItem.owner_id == user.id, InboxItem.status == "new")
    if hidden := await I.hidden_kinds(db):
        new_q = new_q.where(InboxItem.kind.notin_(hidden))
    new_count = int((await db.execute(new_q)).scalar_one())
    return {"items": [item_out(i) for i in items], "new_count": new_count}


@router.get("/{item_id}")
async def get_item(item_id: uuid.UUID, user: CurrentUser, db: DB):
    it = await I.get_owned(db, user.id, item_id)
    if it.status == "new":
        it.status = "read"
    out = item_out(it)
    # 비서끼리 나눈 대화의 두 사람(인맥 맺기에 쓴다). 사람을 적기 전에 생긴 소식은 그 대화에서 찾아 채운다(plan/70).
    pay = dict(it.payload or {})
    if it.kind in ("relay_result", "relay_visit") and pay.get("relay_id") and not pay.get("target_user_id"):
        from blackmoa.models import AgentRelay
        with contextlib.suppress(ValueError):
            r = await db.get(AgentRelay, uuid.UUID(str(pay["relay_id"])))
            if r is not None:
                pay.update(initiator_user_id=str(r.initiator_owner_id), target_user_id=str(r.target_owner_id))
                out["payload"] = pay
    if it.visitor_id:
        v = await db.get(Visitor, it.visitor_id)
        if v:
            out["visitor"] = {"display_name": v.display_name, "email": v.email, "note": v.note, "turn_count": v.turn_count,
                              "first_seen_at": v.first_seen_at.isoformat(), "blocked": v.blocked}
    if it.conversation_id:
        msgs = (await db.execute(select(Message).where(Message.conversation_id == it.conversation_id).order_by(Message.created_at).limit(100))).scalars().all()
        out["conversation"] = [{"role": m.role, "content": m.content, "cards": m.cards, "created_at": m.created_at.isoformat()} for m in msgs]
    await db.commit()
    return out


class StatusIn(BaseModel):
    status: str
    reply: str | None = None
    send_email: bool = False
    #: Accepting a meeting: when it is, and for how long (plan/41 §9.2).
    start_at: datetime | None = None
    duration_minutes: int | None = None


@router.post("/{item_id}/status")
async def set_status(item_id: uuid.UUID, body: StatusIn, user: CurrentUser, db: DB):
    it = await I.get_owned(db, user.id, item_id)
    await I.set_status(it, body.status, body.reply)
    calendar = None
    if body.status == "accepted" and body.start_at is not None and it.kind == "meeting_request":
        calendar = await I.schedule_meeting(db, user, it, start_at=body.start_at, minutes=body.duration_minutes)
    if body.reply and it.conversation_id:
        conv = await db.get(Conversation, it.conversation_id)
        if conv:
            from blackmoa.services.conversations import add_message
            await add_message(db, conv, role="card", content="", cards=[{"card_type": "owner_reply", "payload": {"text": body.reply[:2000]}}])
    if body.reply and body.send_email and (it.payload or {}).get("visitor_email") or (body.reply and body.send_email and it.visitor_id):
        email = (it.payload or {}).get("visitor_email")
        if not email and it.visitor_id:
            v = await db.get(Visitor, it.visitor_id)
            email = v.email if v else None
        if email:
            from blackmoa.services import emails as E
            agent = await db.get(Agent, it.agent_id) if it.agent_id else None
            subject, text, html = E.owner_reply(owner_name=user.nickname or user.display_name or "", reply=body.reply,
                                                agent_name=agent.name if agent else "")
            await J.enqueue(db, "mail.send", {"to": email, "subject": subject, "text": text, "html": html}, priority=2)
    await db.commit()
    return {**item_out(it), "calendar": calendar}


class TeachIn(BaseModel):
    answer: str


@router.post("/{item_id}/teach")
async def teach(item_id: uuid.UUID, body: TeachIn, user: CurrentUser, db: DB):
    it = await I.get_owned(db, user.id, item_id)
    q = (it.payload or {}).get("question") or (it.payload or {}).get("text") or ""
    # 가르친 답은 내 지식이다. 한 비서의 선반이 아니라 내 원장에 올라가고, 내
    # 비서들이 전부 본다 (plan/50 §2). 외부인이 물은 것에 주인이 답한 것이라, 그 질문을
    # 받은 비서는 외부인과의 대화에서도 이 답을 쓴다 — [지식] 탭의 고른 목록에 저절로 (plan/57).
    f = await K.upsert_faq(db, user.id, question=q, answer=body.answer, source="taught")
    if it.agent_id:
        from blackmoa.services import outsider as OUT
        await OUT.pick(db, it.agent_id, "knowledge", faq_id=f.id)
    await I.set_status(it, "replied", body.answer)
    await db.commit()
    return {"faq_id": str(f.id)}


@router.post("/visitors/{visitor_id}/block")
async def block_visitor(visitor_id: uuid.UUID, user: CurrentUser, db: DB, unblock: bool = False):
    from blackmoa.core.errors import NotFound
    v = await db.get(Visitor, visitor_id)
    if v is None or v.owner_id != user.id:
        raise NotFound("visitor not found")
    v.blocked = not unblock
    await db.commit()
    return {"blocked": v.blocked}
