"""A conversation between two secretaries (plan/38).

The ledger of one exchange: who started it for whom, through which public link, and every
message either side sent. The two secretaries also keep their own conversation rows (each
with the other as a ``kind="agent"`` visitor), so each owner reviews it where they review
every other visit; this table is the one place the whole exchange exists in order.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from memora.db.base import Base, IdMixin, TimestampMixin
from memora.models._types import JSONB, UUID, fk


class AgentRelay(Base, IdMixin, TimestampMixin):
    __tablename__ = "agent_relays"
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open", index=True)
    # The side that spoke first, on its owner's instruction.
    initiator_agent_id: Mapped[uuid.UUID] = fk("agents")
    initiator_owner_id: Mapped[uuid.UUID] = fk("users")
    initiator_conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    initiator_visitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # The side that was reached through its public link.
    target_agent_id: Mapped[uuid.UUID] = fk("agents")
    target_owner_id: Mapped[uuid.UUID] = fk("users")
    target_link_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    target_conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    target_visitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Where the owner asked for it (their own chat), so the result can be reported there.
    origin_conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    origin_turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    purpose: Mapped[str] = mapped_column(Text, default="", server_default="")
    opener: Mapped[str] = mapped_column(Text, default="", server_default="")
    max_messages: Mapped[int] = mapped_column(Integer, default=8, server_default="8")
    credit_cap: Mapped[float] = mapped_column(Numeric(14, 4), default=40, server_default="40")
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Whose turn is due, and the turn that is answering it right now.
    hop_pending: Mapped[str | None] = mapped_column(String(16))
    pending_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    in_flight_turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Set by the relay_close tool during a turn; honoured when that turn finalizes.
    close_requested_by: Mapped[str | None] = mapped_column(String(16))
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[str | None] = mapped_column(String(16))
    close_reason: Mapped[str | None] = mapped_column(String(32))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The highest ledger seq each side's own conversation already contains. A close, for any
    # reason, appends whatever is above it — so "both transcripts equal the ledger" holds.
    delivered_seq_initiator: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    delivered_seq_target: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class AgentRelayMessage(Base, IdMixin):
    __tablename__ = "agent_relay_messages"
    relay_id: Mapped[uuid.UUID] = fk("agent_relays")
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)      # initiator | target | system
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(16), default="reply", server_default="reply")  # open | reply | close | system
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RelayCandidate(Base, IdMixin):
    """One person a secretary found for its owner (plan/39). Sending to a candidate is allowed
    only from a later turn than the one that found it — the owner has to have spoken since."""
    __tablename__ = "relay_candidates"
    owner_id: Mapped[uuid.UUID] = fk("users")
    agent_id: Mapped[uuid.UUID] = fk("agents")
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    query: Mapped[str] = mapped_column(String(200), default="", server_default="")
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    target_agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    link_code: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), default="directory", server_default="directory")  # network | friend | guest | directory
    reachable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
