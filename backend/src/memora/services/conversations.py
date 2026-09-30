from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.errors import NotFound
from memora.models import Conversation, Message, Turn
from memora.services.uploads import with_urls


async def create(db: AsyncSession, *, owner_id: uuid.UUID, agent_id: uuid.UUID, audience: str,
                 visitor_id: uuid.UUID | None = None, share_link_id: uuid.UUID | None = None, title: str = "",
                 simulated: bool = False) -> Conversation:
    c = Conversation(owner_id=owner_id, agent_id=agent_id, audience=audience, visitor_id=visitor_id,
                     share_link_id=share_link_id, title=title[:160], simulated=simulated)
    db.add(c)
    await db.flush()
    await room_for(db, c)
    return c


async def room_for(db: AsyncSession, conv: Conversation):
    """The room this conversation lives in (plan/44 §3).

    Every conversation is somebody talking to a secretary, which is a room with two members
    in it. The owner's own chat puts the owner in; a visit puts the visitor in, but only
    when that visitor is signed in — an anonymous visit has nobody to show it to.
    """
    from memora.models import Visitor
    from memora.services import rooms as RM

    who = conv.owner_id if conv.audience == "owner" else None
    if who is None and conv.visitor_id:
        v = await db.get(Visitor, conv.visitor_id)
        # A peer secretary visiting through a relay is not a person, whatever account the
        # relay speaks for.
        who = v.user_id if v is not None and v.kind != "agent" else None
    return await RM.for_conversation(db, conv, person_id=who)


async def get_owned(db: AsyncSession, owner_id: uuid.UUID, cid: uuid.UUID, agent_id: uuid.UUID | None = None) -> Conversation:
    c = await db.get(Conversation, cid)
    if c is None or c.owner_id != owner_id or (agent_id and c.agent_id != agent_id):
        raise NotFound("conversation not found", code="conversation_not_found")
    return c


async def get_for_visitor(db: AsyncSession, visitor_id: uuid.UUID, cid: uuid.UUID) -> Conversation:
    c = await db.get(Conversation, cid)
    if c is None or c.visitor_id != visitor_id:
        raise NotFound("conversation not found", code="conversation_not_found")
    return c


async def list_for_agent(db: AsyncSession, owner_id: uuid.UUID, agent_id: uuid.UUID, *, audience: str | None = None,
                         kind: str | None = None, after: uuid.UUID | None = None, limit: int = 50) -> list[Conversation]:
    stmt = select(Conversation).where(Conversation.owner_id == owner_id, Conversation.agent_id == agent_id,
                                      Conversation.simulated.is_(False)).order_by(Conversation.last_message_at.desc().nullslast(),
                                                                                  Conversation.created_at.desc()).limit(limit)
    if audience:
        stmt = stmt.where(Conversation.audience == audience)
    if kind:
        stmt = stmt.where(Conversation.kind == kind)
    return list((await db.execute(stmt)).scalars().all())


async def messages(db: AsyncSession, cid: uuid.UUID, *, before: uuid.UUID | None = None, limit: int = 50) -> list[Message]:
    stmt = select(Message).where(Message.conversation_id == cid).order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
    if before:
        b = await db.get(Message, before)
        if b:
            stmt = stmt.where(Message.created_at < b.created_at)
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    return rows


async def add_message(db: AsyncSession, conv: Conversation, *, role: str, content: str, turn_id: uuid.UUID | None = None,
                      attachments: list | None = None, cards: list | None = None, content_blocks: list | None = None) -> Message:
    # The envelope, stamped in the one place messages are made (plan/44 §2). Everything
    # else about turns, tools and credits goes on exactly as it did.
    room = await room_for(db, conv)
    m = Message(conversation_id=conv.id, owner_id=conv.owner_id, role=role, content=content, turn_id=turn_id,
                room_id=room.id if room else None,
                sender_agent_id=conv.agent_id if role == "assistant" else None,
                attachments=attachments or [], cards=cards or [], content_blocks=content_blocks, created_at=datetime.now(UTC))
    if room is not None and role == "user":
        from memora.models import RoomMember
        mem = (await db.execute(select(RoomMember).where(RoomMember.room_id == room.id,
                                                          RoomMember.user_id.isnot(None)))).scalars().first()
        m.sender_user_id = mem.user_id if mem is not None else None
    db.add(m)
    conv.last_message_at = m.created_at
    conv.message_count = (conv.message_count or 0) + 1
    if room is not None:
        room.last_message_at = m.created_at
        room.message_count = (room.message_count or 0) + 1
    if not conv.title and role == "user" and content:
        conv.title = content.strip().replace("\n", " ")[:60]
    await db.flush()
    if room is not None and role in ("assistant", "user"):
        # Everyone in the room hears it, on whatever they have open (plan/44 §6). The
        # secretary's own stream carries a turn's words as they arrive; this is the record
        # landing, which a second device has no other way to learn about.
        from memora.services import rooms as RM
        await RM.announce(db, room, m)
    if turn_id is None and role in ("assistant", "user"):
        # A message no turn produced — the secretary writing first, a relay result, the other
        # secretary's line — reaches an open chat now, not on the next reload. Turn messages
        # already travel on the turn's own stream.
        from memora.core import bus
        await bus.publish(db, owner_id=conv.owner_id, kind="message", data={
            "conversation_id": str(conv.id), "agent_id": str(conv.agent_id), "audience": conv.audience,
            "message": {"id": str(m.id), "role": m.role, "content": m.content, "attachments": with_urls(m.attachments), "cards": m.cards or [],
                        "turn_id": None, "created_at": m.created_at.isoformat()}})
    return m


async def active_turn(db: AsyncSession, cid: uuid.UUID) -> Turn | None:
    return (await db.execute(select(Turn).where(Turn.conversation_id == cid, Turn.status == "running")
                             .order_by(Turn.started_at.desc()))).scalars().first()


async def mark_read(db: AsyncSession, cid: uuid.UUID) -> None:
    await db.execute(update(Conversation).where(Conversation.id == cid).values(unread_owner=False))
