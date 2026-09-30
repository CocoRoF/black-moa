"""What the owner said about an answer their secretary gave (plan/41 §8)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from memora.db.base import Base, IdMixin, utcnow
from memora.models._types import fk, owner_col


class TurnFeedback(Base, IdMixin):
    """One verdict on one turn.

    A wrong answer is not a bug report, it is a fact the secretary got wrong about its
    owner. So the row keeps what was asked and what was said, and points at the correction
    it produced.
    """

    __tablename__ = "turn_feedback"
    __table_args__ = (UniqueConstraint("turn_id", name="uq_turn_feedback"),)

    turn_id: Mapped[uuid.UUID] = fk("turns")
    owner_id: Mapped[uuid.UUID] = owner_col()
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    #: wrong | good
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    question: Mapped[str] = mapped_column(Text, default="", server_default="")
    answer: Mapped[str] = mapped_column(Text, default="", server_default="")
    faq_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=utcnow)
