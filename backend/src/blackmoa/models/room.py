"""방 — 블랙모아 안에서 오가는 모든 말이 담기는 자리 (plan/44).

A conversation used to be a pair: one owner, one secretary. A room has members instead, and
a member is a person or a secretary. That one change is what lets two people talk, what
gives a signed-in visitor a way back to what they said to somebody else's secretary, and
what makes the same conversation the same on a phone and on a desktop — because how far you
have read is written on your membership, not on the device you read it with.

Messages stay where they were. The room is the envelope.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from blackmoa.db.base import Base, IdMixin, TimestampMixin
from blackmoa.models._types import UUID, fk


class Room(Base, IdMixin, TimestampMixin):
    __tablename__ = "rooms"
    __table_args__ = (Index("ix_rooms_last", "last_message_at"),
                      Index("uq_room_pair", "person_id", "agent_id", unique=True))

    #: secretary — a person and a secretary; dm — two people.
    kind: Mapped[str] = mapped_column(String(16), default="dm", server_default="dm")
    #: The pair, for a secretary room. One room per person and secretary, however many
    #: conversations the turn pipeline keeps under it.
    person_id: Mapped[uuid.UUID | None] = fk("users", nullable=True)
    agent_id: Mapped[uuid.UUID | None] = fk("agents", nullable=True)
    #: The conversation a turn from the messenger goes to: the pair's most recent one. The
    #: pipeline still speaks to that row and knows nothing about rooms.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    #: The two people, sorted and joined, so "open the room with X" always lands on one room.
    dm_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    title: Mapped[str] = mapped_column(String(160), default="", server_default="")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class RoomMember(Base, IdMixin):
    """Who is in the room. Exactly one of `user_id` / `agent_id` is set."""

    __tablename__ = "room_members"
    __table_args__ = (UniqueConstraint("room_id", "user_id", name="uq_room_user"),
                      UniqueConstraint("room_id", "agent_id", name="uq_room_agent"),
                      Index("ix_room_members_user", "user_id", "room_id"))

    room_id: Mapped[uuid.UUID] = fk("rooms")
    user_id: Mapped[uuid.UUID | None] = fk("users", nullable=True)
    agent_id: Mapped[uuid.UUID | None] = fk("agents", nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="member", server_default="member")
    #: How far this member has read. On the person, not on the device.
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoomGrant(Base, IdMixin):
    """비서가 사람끼리 방을 읽어도 된다는 주인의 허락 (plan/55 §6-4).

    비서는 사람끼리 방을 당연히 보지 않는다. 이 행이 살아 있는 동안에만, 이 비서가, 이 방의
    말과 파일을 본다. ``scope``: ``conversation`` — 허락한 그 비서 대화 안에서만 · ``always``.
    """

    __tablename__ = "room_grants"
    user_id: Mapped[uuid.UUID] = fk("users")
    agent_id: Mapped[uuid.UUID] = fk("agents")
    room_id: Mapped[uuid.UUID] = fk("rooms")
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = fk("conversations", nullable=True)
    reason: Mapped[str] = mapped_column(String, default="", server_default="")
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def dm_key(a: uuid.UUID, b: uuid.UUID) -> str:
    """One key for one pair, whichever of them is asking."""
    return ":".join(sorted((str(a), str(b))))


__all__ = ["Room", "RoomGrant", "RoomMember", "dm_key", "UUID"]
