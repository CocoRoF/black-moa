"""메신저 — 방 (plan/44).

One door for everything that gets said inside black-moa: the list of rooms I am in, what was
said in one, and saying something. A secretary room's answers still come from the turn
pipeline; this router never runs a turn.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel, Field

from blackmoa.core.deps import DB, CurrentUser, client_ip
from blackmoa.core.errors import Forbidden, NotFound
from blackmoa.core.ratelimit import limiter
from blackmoa.services import rooms as R

router = APIRouter(prefix="/api/rooms", tags=["rooms"])

# ── how fast a person can be (plan/44 §10) ───────────────────────────
#
# Not a courtesy limit: a ceiling nothing human reaches. Somebody in an argument really can
# send a line every two seconds; nobody opens ten new rooms in a minute.
SAY_PER_MIN = 30
SAY_PER_HOUR = 600
OPEN_PER_MIN = 10


def _budget(user, what: str, limit: int, per: int) -> None:
    limiter.check(f"room:{what}:{user.id}", limit, per)


@router.get("")
async def list_rooms(user: CurrentUser, db: DB, limit: int = 30):
    """Every room I am in, newest first."""
    return {"items": await R.for_user(db, user, limit=limit), "unread": await R.unread_count(db, user)}


@router.get("/unread")
async def unread(user: CurrentUser, db: DB):
    return {"unread": await R.unread_count(db, user)}


class OpenIn(BaseModel):
    """Who to open a room with. Exactly one of these."""

    user_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None


@router.post("/open", status_code=201)
async def open_room(body: OpenIn, user: CurrentUser, db: DB):
    _budget(user, "open", OPEN_PER_MIN, 60)
    room = (await R.dm_with(db, user, body.user_id) if body.user_id
            else await R.with_agent(db, user, body.agent_id))
    await db.commit()
    return await R.view(db, user, room)


@router.get("/{room_id}")
async def read_room(room_id: uuid.UUID, user: CurrentUser, db: DB):
    room, mine = await R.readable(db, user, room_id)
    return await R.view(db, user, room, mine)


@router.get("/{room_id}/messages")
async def list_messages(room_id: uuid.UUID, user: CurrentUser, db: DB,
                        before: str | None = None, limit: int = R.PAGE):
    room, _mine = await R.readable(db, user, room_id)
    rows = await R.messages(db, room, before=before, limit=limit)
    return {"items": [R.message_out(m) for m in rows],
            "members": [await R.face(db, user, m) for m in await R._members(db, room.id)]}


class SayIn(BaseModel):
    body: str = Field(default="", max_length=R.MAX_BODY)
    attachments: list[dict] = Field(default_factory=list, max_length=8)   # 옛 클라이언트용, 읽지 않는다
    upload_ids: list[uuid.UUID] = Field(default_factory=list, max_length=8)


@router.post("/{room_id}/messages", status_code=201)
async def say(room_id: uuid.UUID, body: SayIn, user: CurrentUser, db: DB):
    _budget(user, "say", SAY_PER_MIN, 60)
    _budget(user, "say-hr", SAY_PER_HOUR, 3600)
    room, _mine = await R.readable(db, user, room_id)
    # 첨부는 내가 올린 파일의 id 로만 (plan/55). 요청에 실린 이름·주소를 믿으면 상대 화면에
    # 내가 쓰지 않은 링크가 "파일" 로 뜬다.
    atts = await R.attachments_of(db, user, body.upload_ids)
    m = await R.say(db, user, room, body=body.body, attachments=atts)
    await db.commit()
    return R.message_out(m)


@router.delete("/{room_id}/messages/{message_id}")
async def unsay(room_id: uuid.UUID, message_id: uuid.UUID, user: CurrentUser, db: DB):
    """Taking back something I said. Mine, and only between people."""
    room, _mine = await R.readable(db, user, room_id)
    await R.unsay(db, user, room, message_id)
    await db.commit()
    return {"ok": True}


@router.post("/{room_id}/read")
async def read(room_id: uuid.UUID, user: CurrentUser, db: DB):
    room, _mine = await R.readable(db, user, room_id)
    await R.mark_read(db, user, room)
    await db.commit()
    return {"ok": True, "unread": await R.unread_count(db, user)}


class TurnIn(BaseModel):
    text: str = Field(default="", max_length=8000)
    client_turn_id: str | None = Field(default=None, max_length=64)
    upload_ids: list[uuid.UUID] = Field(default_factory=list, max_length=8)


@router.post("/{room_id}/uploads", status_code=201)
async def upload_to_secretary(room_id: uuid.UUID, user: CurrentUser, db: DB, request: Request, file: UploadFile = File(...)):
    """남의 비서 방에 건네는 파일 (plan/55 §6-3). 공개 페이지의 방문자와 같은 규칙 —
    그 비서 주인의 한도를 쓰고, 그 방문자 칸에만 들어간다. 내 비서 방은 /api/uploads 를 쓴다."""
    from blackmoa.models import Agent, Conversation, Visitor
    from blackmoa.models import User as _User
    from blackmoa.services import files as FILES
    from blackmoa.services import uploads as U

    room, _mine = await R.readable(db, user, room_id)
    conv = await db.get(Conversation, room.conversation_id) if room.kind == "secretary" and room.conversation_id else None
    if conv is None or conv.audience == "owner":
        raise NotFound("room not found", code="room_not_found")
    visitor = await db.get(Visitor, conv.visitor_id) if conv.visitor_id else None
    agent = await db.get(Agent, conv.agent_id)
    holder = await db.get(_User, conv.owner_id)
    if visitor is None or visitor.user_id != user.id or visitor.blocked or agent is None or holder is None:
        raise NotFound("room not found", code="room_not_found")
    limiter.check(f"pubup:{visitor.id}", 20, 600)
    limiter.check(f"pubup-ip:{client_ip(request)}", 60, 3600)
    data = await U.read_capped(file, 25 * 1024 * 1024)
    up = await FILES.store_for_visitor(db, agent=agent, owner=holder, visitor=visitor, filename=file.filename or "file",
                                       mime=file.content_type or "", data=data)
    await db.commit()
    return {"upload_id": str(up.id), "url": U.signed_url(up.id), "mime": up.mime, "size": up.size_bytes, "filename": up.filename}


@router.post("/{room_id}/turns")
async def turn(room_id: uuid.UUID, body: TurnIn, user: CurrentUser, db: DB, request: Request):
    """Saying something to a secretary, from the messenger (plan/44 §7).

    The public page runs this with a visitor token kept in one browser. Somebody signed in
    has an account instead, which is the same person on every device — so the room is the
    handle, and the gates are the ones the public door has always had. Nothing new is
    allowed through: the member being visited still pays, and still says when to stop.
    """
    from blackmoa.models import Agent, Conversation, ShareLink, Visitor
    from blackmoa.models import User as _User
    from blackmoa.pipeline.runner import TurnRequest, launch_turn, start_turn
    from blackmoa.services import agents as AG
    from blackmoa.services import credits as CR

    room, _mine = await R.readable(db, user, room_id)
    if room.kind != "secretary" or not room.conversation_id:
        raise NotFound("room not found", code="room_not_found")
    conv = await db.get(Conversation, room.conversation_id)
    agent = await db.get(Agent, conv.agent_id) if conv else None
    holder = await db.get(_User, conv.owner_id) if conv else None
    if conv is None or agent is None or holder is None:
        raise NotFound("room not found", code="room_not_found")
    if agent.status != "active":
        raise Forbidden("secretary resting", code="secretary_resting")

    if conv.audience == "owner":
        if conv.owner_id != user.id:
            raise NotFound("room not found", code="room_not_found")
        from blackmoa.services.uploads import attachments_from_ids
        atts = await attachments_from_ids(db, user.id, body.upload_ids) if body.upload_ids else []
        req = TurnRequest(owner=user, agent=agent, conversation=conv, audience="owner",
                          text=body.text, client_turn_id=body.client_turn_id, attachments=atts)
    else:
        visitor = await db.get(Visitor, conv.visitor_id) if conv.visitor_id else None
        if visitor is None or visitor.user_id != user.id or visitor.blocked:
            raise NotFound("room not found", code="room_not_found")
        link = await db.get(ShareLink, conv.share_link_id) if conv.share_link_id else None
        if link is None or AG.link_effective_status(link, agent) != "active":
            raise Forbidden("link not active", code="link_closed")
        if (await CR.available_balance(db, holder.id)) <= 0:
            raise Forbidden("secretary resting", code="secretary_resting")
        # The same ceiling the public door has. An account is one visitor, so the per-visitor
        # count is the one that bites; the per-address one stays for the same reason.
        limiter.check(f"pubturn:{visitor.id}", 20, 600)
        limiter.check(f"pubturn-ip:{client_ip(request)}", 60, 3600)
        vatts: list = []
        if body.upload_ids:
            from blackmoa.services import files as FILES
            if not FILES.visitor_file_rules(agent)["accept"]:
                raise Forbidden("files are not accepted", code="visitor_files_unavailable")
            vatts = await FILES.visitor_attachments(db, owner_id=holder.id, visitor_id=visitor.id, ids=body.upload_ids)
        req = TurnRequest(owner=holder, agent=agent, conversation=conv, audience="visitor",
                          text=body.text, visitor=visitor, share_link=link,
                          client_turn_id=body.client_turn_id, attachments=vatts)

    t = await start_turn(db, req)
    await db.commit()
    launch_turn(t)
    from blackmoa.api.chat import turn_stream
    as_visitor = conv.audience != "owner"
    return turn_stream(t, 0, visitor=as_visitor, request=request)
