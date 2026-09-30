"""방 — 누가 들어와 있고, 무슨 말이 오갔고, 어디까지 읽었나 (plan/44).

Everything that gets said inside Memora lands in a room. A room has members, and a member
is a person or a secretary. That is the whole idea; the rest of this file is bookkeeping.

Two kinds:

* **secretary** — a person and a secretary. **One room per pair.** The turn pipeline keeps
  its own conversations underneath, one per sitting, and the messenger shows all of them
  as one timeline — the way a person thinks of talking to somebody, not the way a log is
  filed. The room remembers which conversation a turn from the messenger goes to.
* **dm** — two people. No conversation behind it; the messages are all there is.

How far somebody has read is written on their membership. That is what makes a phone and a
desktop agree: the answer lives with the person, not with the device that asked.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.errors import Conflict, NotFound, ValidationFailed
from memora.models import Agent, Conversation, Message, PersonFollow, Room, RoomMember, User
from memora.models.room import dm_key
from memora.services.uploads import with_urls

#: One thing said. Longer than a chat line ever is, shorter than an essay.
MAX_BODY = 4000
PAGE = 30
_EPOCH = datetime.min.replace(tzinfo=UTC)


# ── 방을 찾거나 만든다 ────────────────────────────────────────────────

async def _members(db: AsyncSession, room_id: uuid.UUID) -> list[RoomMember]:
    return list((await db.execute(select(RoomMember).where(RoomMember.room_id == room_id)
                                  .order_by(RoomMember.joined_at))).scalars().all())


async def connected(db: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    """Either of them reached for the other. Talking starts with connecting (plan/44 §4)."""
    row = (await db.execute(select(PersonFollow.id).where(
        or_((PersonFollow.follower_id == a) & (PersonFollow.target_id == b),
            (PersonFollow.follower_id == b) & (PersonFollow.target_id == a))))).first()
    return row is not None


async def dm_with(db: AsyncSession, me: User, other_id: uuid.UUID) -> Room:
    """The room between the two of us, made the first time either of us asks for it."""
    if other_id == me.id:
        raise ValidationFailed("you cannot write to yourself", code="dm_self")
    other = await db.get(User, other_id)
    if other is None or other.status != "active":
        raise NotFound("account not found", code="account_not_found")
    key = dm_key(me.id, other_id)
    room = (await db.execute(select(Room).where(Room.dm_key == key))).scalars().first()
    if room is not None:
        return room
    # A room that does not exist yet is a first message, and a first message needs the two
    # of them to have reached for each other at least once. Answering somebody who already
    # wrote is always allowed, because their room is already here.
    if not await connected(db, me.id, other_id):
        raise Conflict("connect first", code="not_connected")
    room = Room(kind="dm", dm_key=key)
    db.add(room)
    await db.flush()
    db.add(RoomMember(room_id=room.id, user_id=me.id, role="member"))
    db.add(RoomMember(room_id=room.id, user_id=other_id, role="member"))
    await db.flush()
    return room


async def pair_room(db: AsyncSession, person_id: uuid.UUID, agent_id: uuid.UUID) -> Room:
    """The one room between this person and this secretary."""
    room = (await db.execute(select(Room).where(Room.person_id == person_id,
                                                Room.agent_id == agent_id))).scalars().first()
    if room is not None:
        return room
    room = Room(kind="secretary", person_id=person_id, agent_id=agent_id)
    db.add(room)
    await db.flush()
    db.add(RoomMember(room_id=room.id, user_id=person_id, role="member"))
    db.add(RoomMember(room_id=room.id, agent_id=agent_id, role="secretary"))
    await db.flush()
    return room


def _sits_in_a_room(conv: Conversation) -> bool:
    # A relay is two secretaries talking. Neither person is in it: one asked for it and
    # both read the result afterwards, which is what the conversation list is for. Typing
    # into such a room would push a bare message into an exchange that is counting hops.
    return not (conv.simulated or conv.kind == "agent" or conv.relay_id is not None)


async def for_conversation(db: AsyncSession, conv: Conversation, *, person_id: uuid.UUID | None) -> Room | None:
    """The room a secretary conversation lives in, made the first time it is needed.

    `person_id` is who is on the human side: the owner in their own chat, the signed-in
    visitor otherwise. An anonymous visit has nobody to show it to and gets no room.

    A newer conversation with the same secretary joins the same room and becomes the one a
    turn from the messenger goes to.
    """
    if not _sits_in_a_room(conv) or person_id is None:
        return None
    room = await pair_room(db, person_id, conv.agent_id)
    current = await db.get(Conversation, room.conversation_id) if room.conversation_id else None
    if current is None or current.id == conv.id or (conv.created_at or _EPOCH) >= (current.created_at or _EPOCH):
        room.conversation_id = conv.id
    return room


async def _visit(db: AsyncSession, me: User, agent: Agent, link) -> Conversation:
    """Start talking to somebody else's secretary from here, the way the public page would.

    The public page keeps its visitor in one browser. Somebody signed in is the same person
    on every device, so the messenger makes the visit under their account; a later visit
    through the page lands in the same room, because the room is the pair.
    """
    from memora.core.security import sha256
    from memora.models import ShareLink, Visitor
    from memora.services import conversations as CV

    live = (await db.execute(select(ShareLink).where(ShareLink.id == link.id).with_for_update())).scalars().first()
    if live is None:
        raise NotFound("secretary not found", code="agent_not_found")
    now = datetime.now(UTC)
    visitor = Visitor(owner_id=agent.owner_id, agent_id=agent.id, share_link_id=live.id,
                      token_hash=sha256(uuid.uuid4().hex),
                      display_name=(me.nickname or me.display_name or "").strip() or None,
                      email=me.email, user_id=me.id, first_seen_at=now, last_seen_at=now,
                      meta={"via": "messenger"})
    db.add(visitor)
    await db.flush()
    live.conversation_count = (live.conversation_count or 0) + 1
    # The owner's graph learns who this is in the same breath (plan/31).
    try:
        from memora.services import people as PEOPLE
        await PEOPLE.fuse_visitor(db, visitor)
    except Exception:  # noqa: BLE001 - a graph that lags is not a visit that failed
        pass
    return await CV.create(db, owner_id=agent.owner_id, agent_id=agent.id, audience="visitor",
                           visitor_id=visitor.id, share_link_id=live.id)


async def with_agent(db: AsyncSession, me: User, agent_id: uuid.UUID) -> Room:
    """The room between me and a secretary: my own, or somebody's published one."""
    from memora.models import ShareLink, Visitor
    from memora.services import agents as A
    from memora.services import conversations as CV

    agent = await db.get(Agent, agent_id)
    if agent is None or agent.status != "active":
        raise NotFound("secretary not found", code="agent_not_found")
    if agent.owner_id == me.id:
        conv = (await db.execute(select(Conversation).where(
            Conversation.owner_id == me.id, Conversation.agent_id == agent.id,
            Conversation.audience == "owner", Conversation.simulated.is_(False))
            .order_by(Conversation.last_message_at.desc().nullslast(),
                      Conversation.created_at.desc()))).scalars().first()
        if conv is None:
            conv = await CV.create(db, owner_id=me.id, agent_id=agent.id, audience="owner")
        room = await for_conversation(db, conv, person_id=me.id)
    else:
        link = (await db.execute(select(ShareLink).where(ShareLink.agent_id == agent.id, A.open_link())
                                 .order_by(ShareLink.created_at))).scalars().first()
        if link is None:
            raise NotFound("secretary not found", code="agent_not_found")
        conv = (await db.execute(
            select(Conversation).join(Visitor, Visitor.id == Conversation.visitor_id)
            .where(Visitor.user_id == me.id, Visitor.kind != "agent", Visitor.blocked.is_(False),
                   Conversation.agent_id == agent.id, Conversation.simulated.is_(False))
            .order_by(Conversation.last_message_at.desc().nullslast(),
                      Conversation.created_at.desc()))).scalars().first()
        if conv is None:
            conv = await _visit(db, me, agent, link)
        room = await for_conversation(db, conv, person_id=me.id)
    if room is None:
        raise NotFound("conversation not found", code="conversation_not_found")
    return room


# ── 읽기 ──────────────────────────────────────────────────────────────

async def readable(db: AsyncSession, me: User, room_id: uuid.UUID) -> tuple[Room, RoomMember]:
    """The room, if I am in it. A room I am not in is not announced as existing."""
    room = await db.get(Room, room_id)
    if room is None:
        raise NotFound("room not found", code="room_not_found")
    mine = (await db.execute(select(RoomMember).where(RoomMember.room_id == room.id,
                                                      RoomMember.user_id == me.id))).scalars().first()
    if mine is None:
        raise NotFound("room not found", code="room_not_found")
    return room, mine


async def face(db: AsyncSession, me: User, m: RoomMember) -> dict[str, Any]:
    """Who this member is, as a row draws them.

    A secretary carries whose it is: two people can each have a 제니, and a list that says
    "제니" twice has told the reader nothing.
    """
    from memora.services.people import display_of

    if m.agent_id:
        a = await db.get(Agent, m.agent_id)
        holder = await db.get(User, a.owner_id) if a else None
        return {"kind": "agent", "id": str(m.agent_id), "name": a.name if a else "",
                "avatar_url": a.avatar_url if a else None,
                "mine": bool(a and a.owner_id == me.id),
                "owner_name": display_of(holder) if holder else ""}
    u = await db.get(User, m.user_id) if m.user_id else None
    return {"kind": "person", "id": str(m.user_id) if m.user_id else "",
            "name": display_of(u) if u else "", "avatar_url": u.avatar_url if u else None,
            "handle": (u.mail_handle or "") if u else ""}


async def view(db: AsyncSession, me: User, room: Room, mine: RoomMember | None = None) -> dict[str, Any]:
    """One room as a list row: who else is in it, the last thing said, and whether it is new."""
    members = await _members(db, room.id)
    mine = mine or next((m for m in members if m.user_id == me.id), None)
    others = [await face(db, me, m) for m in members if m.id != (mine.id if mine else None)]
    last = (await db.execute(select(Message).where(Message.room_id == room.id, Message.role.in_(("user", "assistant")))
                             .order_by(Message.created_at.desc()).limit(1))).scalars().first()
    unread = bool(room.last_message_at and (mine is None or mine.last_read_at is None
                                            or mine.last_read_at < room.last_message_at))
    # The title is the people in it, computed every time: a name that changes has to
    # change here too, and a stored one drifts.
    title = " · ".join(x["name"] for x in others if x["name"])
    own = any(x.get("mine") for x in others)
    return {"id": str(room.id), "kind": room.kind, "title": title, "others": others,
            "own_secretary": own,
            "last_message_at": room.last_message_at.isoformat() if room.last_message_at else None,
            "message_count": room.message_count,
            "last": {"body": last.content[:160], "role": last.role,
                     "at": last.created_at.isoformat()} if last else None,
            "unread": unread,
            "conversation_id": str(room.conversation_id) if room.conversation_id else None}


async def for_user(db: AsyncSession, me: User, *, limit: int = 100) -> list[dict[str, Any]]:
    """Every room I am in that has something in it, newest first.

    A room that was opened and never spoken in is not a conversation yet. It is still there
    for whoever opens it again from the person; it just does not sit on the list.
    """
    rows = (await db.execute(
        select(Room, RoomMember).join(RoomMember, RoomMember.room_id == Room.id)
        .where(RoomMember.user_id == me.id, Room.last_message_at.isnot(None))
        .order_by(Room.last_message_at.desc(), Room.created_at.desc())
        .limit(max(1, min(limit, 200))))).all()
    return [await view(db, me, room, mine) for room, mine in rows]


async def unread_count(db: AsyncSession, me: User) -> int:
    n = (await db.execute(
        select(func.count()).select_from(Room).join(RoomMember, RoomMember.room_id == Room.id)
        .where(RoomMember.user_id == me.id, Room.last_message_at.isnot(None),
               or_(RoomMember.last_read_at.is_(None),
                   RoomMember.last_read_at < Room.last_message_at)))).scalar_one()
    return int(n or 0)


def message_out(m: Message) -> dict[str, Any]:
    return {"id": str(m.id), "role": m.role, "body": m.content,
            "sender_user_id": str(m.sender_user_id) if m.sender_user_id else None,
            "sender_agent_id": str(m.sender_agent_id) if m.sender_agent_id else None,
            "attachments": with_urls(m.attachments), "cards": m.cards or [],
            "turn_id": str(m.turn_id) if m.turn_id else None,
            "created_at": m.created_at.isoformat()}


async def messages(db: AsyncSession, room: Room, *, before: str | None = None,
                   limit: int = PAGE) -> list[Message]:
    stmt = select(Message).where(Message.room_id == room.id).order_by(
        Message.created_at.desc(), Message.id.desc()).limit(max(1, min(limit, 100)))
    if before:
        try:
            b = await db.get(Message, uuid.UUID(before))
        except (ValueError, AttributeError, TypeError):
            b = None
        if b is not None:
            stmt = stmt.where(Message.created_at < b.created_at)
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    return rows


# ── 쓰기 ──────────────────────────────────────────────────────────────

async def attachments_of(db: AsyncSession, me: User, ids: list[uuid.UUID]) -> list[dict[str, Any]]:
    """사람끼리 방에 붙일 파일: 내가 올린 것만, 보낸 순서대로, 메타데이터만.

    바이트와 주소는 싣지 않는다 — 주소는 읽을 때마다 새로 서명한다(``with_urls``). 이 파일은
    어느 비서의 [파일] 에도 들어가지 않는다(plan/55 §6-4). 한도는 올린 사람의 [메신저] 칸.
    """
    from memora.models import Upload

    if not ids:
        return []
    rows = {u.id: u for u in (await db.execute(select(Upload).where(Upload.id.in_(ids), Upload.owner_id == me.id))).scalars().all()}
    out = []
    for i in dict.fromkeys(ids):
        u = rows.get(i)
        if u is None:
            continue
        if u.kind != "room":
            u.kind = "room"          # 메신저로 건넨 파일이다 — 저장 공간의 [메신저] 칸에 선다
        out.append({"upload_id": str(u.id), "filename": u.filename, "mime": u.mime, "size": u.size_bytes})
    return out


async def say(db: AsyncSession, me: User, room: Room, *, body: str,
              attachments: list | None = None) -> Message:
    """A person saying something in a room between people.

    Saying something to a secretary is not this. It is a turn: something is spent, tools may
    run, an answer comes back. That goes through the pipeline that has always run it, and
    this door refuses rather than quietly dropping a line the secretary will never answer.
    """
    if room.kind == "secretary":
        raise Conflict("a secretary answers in turns", code="use_turn",
                       detail={"conversation_id": str(room.conversation_id) if room.conversation_id else None})
    text = (body or "").replace("\r\n", "\n").strip()[:MAX_BODY]
    if not text and not attachments:
        raise ValidationFailed("write something first", code="empty_message")
    m = Message(room_id=room.id, conversation_id=None, owner_id=me.id,
                sender_user_id=me.id, role="user", content=text,
                attachments=attachments or [], created_at=datetime.now(UTC))
    db.add(m)
    await touch(db, room, m)
    await db.flush()
    await mark_read(db, me, room, at=m.created_at)
    await announce(db, room, m)
    return m


async def unsay(db: AsyncSession, me: User, room: Room, message_id: uuid.UUID) -> None:
    """Taking back something I said.

    Mine, and only in a room between people: a secretary's answer is part of a conversation
    that was paid for and reviewed elsewhere, and pulling one line out of it would leave a
    transcript that reads as though the secretary answered nothing.
    """
    if room.kind != "dm":
        raise Conflict("a conversation is not edited line by line", code="not_a_dm")
    m = await db.get(Message, message_id)
    if m is None or m.room_id != room.id or m.sender_user_id != me.id:
        raise NotFound("message not found", code="message_not_found")
    await db.delete(m)
    room.message_count = max(0, (room.message_count or 0) - 1)
    await db.flush()
    last = (await db.execute(select(Message).where(Message.room_id == room.id)
                             .order_by(Message.created_at.desc()).limit(1))).scalars().first()
    room.last_message_at = last.created_at if last else None
    await db.flush()
    from memora.core import bus
    for mem in await _members(db, room.id):
        if mem.user_id:
            await bus.publish(db, owner_id=mem.user_id, kind="room",
                              data={"room_id": str(room.id), "removed": str(message_id)})


async def touch(db: AsyncSession, room: Room, m: Message) -> None:
    room.last_message_at = m.created_at
    room.message_count = (room.message_count or 0) + 1


async def mark_read(db: AsyncSession, me: User, room: Room, *, at: datetime | None = None) -> None:
    mine = (await db.execute(select(RoomMember).where(RoomMember.room_id == room.id,
                                                      RoomMember.user_id == me.id))).scalars().first()
    if mine is not None:
        mine.last_read_at = at or datetime.now(UTC)


async def announce(db: AsyncSession, room: Room, m: Message) -> None:
    """Tell every person in the room, on every device they have open.

    The bus fans out per person, so a room with two people is two nudges. A member who is
    not looking will see the same thing on their next fetch; this is the difference between
    now and in a moment, not between arriving and not.
    """
    from memora.core import bus

    for mem in await _members(db, room.id):
        if not mem.user_id:
            continue
        await bus.publish(db, owner_id=mem.user_id, kind="room", data={
            "room_id": str(room.id), "message": message_out(m)})
