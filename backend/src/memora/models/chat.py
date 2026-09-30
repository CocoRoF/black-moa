from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, PrimaryKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from memora.db.base import Base, IdMixin, TimestampMixin
from memora.models._types import JSONB, UUID, fk, owner_col


class Visitor(Base, IdMixin):
    __tablename__ = "visitors"
    owner_id: Mapped[uuid.UUID] = owner_col()
    agent_id: Mapped[uuid.UUID] = fk("agents")
    share_link_id: Mapped[uuid.UUID | None] = fk("share_links", nullable=True, ondelete="SET NULL")
    # Set when the visitor arrived signed in: the secretary then knows a real name and a
    # reachable address instead of asking for them.
    user_id: Mapped[uuid.UUID | None] = fk("users", nullable=True, ondelete="SET NULL")
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    matched_node_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # human — a person; agent — another member's secretary talking through a relay (plan/38),
    # in which case ``peer_agent_id`` says which one.
    kind: Mapped[str] = mapped_column(String(16), default="human", server_default="human")
    peer_agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Conversation(Base, IdMixin, TimestampMixin):
    __tablename__ = "conversations"
    owner_id: Mapped[uuid.UUID] = owner_col()
    agent_id: Mapped[uuid.UUID] = fk("agents")
    audience: Mapped[str] = mapped_column(String(16), nullable=False, default="owner")
    visitor_id: Mapped[uuid.UUID | None] = fk("visitors", nullable=True)
    share_link_id: Mapped[uuid.UUID | None] = fk("share_links", nullable=True, ondelete="SET NULL")
    title: Mapped[str] = mapped_column(String(160), default="", server_default="")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unread_owner: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    simulated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # human — the other party is a person; agent — one side of a secretary relay (plan/38).
    kind: Mapped[str] = mapped_column(String(16), default="human", server_default="human")
    relay_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)


class Message(Base, IdMixin):
    __tablename__ = "messages"
    #: Empty for a room between two people: there is no secretary conversation behind it.
    conversation_id: Mapped[uuid.UUID | None] = fk("conversations", nullable=True)
    owner_id: Mapped[uuid.UUID | None] = owner_col(nullable=True)
    #: The envelope (plan/44). Every message said from here on lands in a room.
    room_id: Mapped[uuid.UUID | None] = fk("rooms", nullable=True)
    #: Who actually spoke. `role` says user or assistant, which is enough for one person
    #: and one secretary and for nothing with more people in it.
    sender_user_id: Mapped[uuid.UUID | None] = fk("users", nullable=True, ondelete="SET NULL")
    sender_agent_id: Mapped[uuid.UUID | None] = fk("agents", nullable=True, ondelete="SET NULL")
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    content_blocks: Mapped[list | None] = mapped_column(JSONB)
    attachments: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    cards: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class Turn(Base, IdMixin):
    __tablename__ = "turns"
    conversation_id: Mapped[uuid.UUID] = fk("conversations")
    owner_id: Mapped[uuid.UUID] = owner_col()
    agent_id: Mapped[uuid.UUID] = fk("agents")
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    client_turn_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running", server_default="running", index=True)
    provider: Mapped[str] = mapped_column(String(32), default="", server_default="")
    model_id: Mapped[str] = mapped_column(String(128), default="", server_default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, server_default="0")
    credits: Mapped[float] = mapped_column(Numeric(14, 4), default=0, server_default="0")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ttft_ms: Mapped[int | None] = mapped_column(Integer)
    stop_reason: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    injection_suspect: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    #: 사람이 말을 건 턴이 아니다 — 심부름(사진 읽기, 글에 댓글 달기)이나 방문자
    #: 흉내다. **증류가 이 값을 보고 거절한다** (plan/50 §2): 심부름 지시문이 주인이
    #: 한 말로 기억되면, 내가 코드에 적은 문장이 주인에 대한 사실이 된다.
    simulated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    redactions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    user_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    answer_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TurnEvent(Base):
    __tablename__ = "turn_events"
    __table_args__ = (PrimaryKeyConstraint("turn_id", "seq"),)
    turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ToolSpan(Base, IdMixin):
    __tablename__ = "tool_spans"
    turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    owner_id: Mapped[uuid.UUID] = owner_col()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    input: Mapped[dict] = mapped_column(JSONB, default=dict)
    output_preview: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_error: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InboxItem(Base, IdMixin, TimestampMixin):
    __tablename__ = "inbox_items"
    owner_id: Mapped[uuid.UUID] = owner_col()
    # Null for community notifications: they are addressed to the person, not to a secretary.
    agent_id: Mapped[uuid.UUID | None] = fk("agents", nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = fk("conversations", nullable=True, ondelete="SET NULL")
    visitor_id: Mapped[uuid.UUID | None] = fk("visitors", nullable=True, ondelete="SET NULL")
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), default="new", server_default="new", index=True)
    owner_reply: Mapped[str | None] = mapped_column(Text)
