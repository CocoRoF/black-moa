from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, PrimaryKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from memora.db.base import Base, IdMixin
from memora.models._types import UUID, owner_col


class CreditLedger(Base, IdMixin):
    __tablename__ = "credit_ledger"
    __table_args__ = (
        Index("ix_credit_ledger_owner_created", "owner_id", "created_at"),
        Index("uq_credit_ledger_turn_ref", "ref_type", "ref_id", unique=True, postgresql_where="kind = 'turn'"),
    )
    owner_id: Mapped[uuid.UUID] = owner_col()
    delta: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    balance_after: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CreditBalance(Base):
    __tablename__ = "credit_balances"
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    balance: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    # Held credits are not spent yet, but are unavailable to concurrent turns.
    reserved: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0, server_default="0")
    low_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CreditReservation(Base):
    """Atomic per-turn hold. ``turn_id`` is intentionally not an FK.

    Retention may delete old turns independently; reservation bookkeeping is
    settled/released before that and old reservation rows can then be swept.
    """
    __tablename__ = "credit_reservations"
    turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[uuid.UUID] = owner_col()
    amount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    actual_credits: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0, server_default="0")
    charged_credits: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0, server_default="0")
    day: Mapped[date] = mapped_column(Date, nullable=False)
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="held", server_default="held", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageEvent(Base, IdMixin):
    __tablename__ = "usage_events"
    owner_id: Mapped[uuid.UUID] = owner_col()
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="", server_default="")
    model_id: Mapped[str] = mapped_column(String(128), default="", server_default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    units: Mapped[float] = mapped_column(Numeric(14, 4), default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, server_default="0")
    credits: Mapped[float] = mapped_column(Numeric(14, 4), default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class UsageDaily(Base):
    __tablename__ = "usage_daily"
    __table_args__ = (PrimaryKeyConstraint("owner_id", "day"),)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    credits: Mapped[float] = mapped_column(Numeric(14, 4), default=0)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    visitor_turns: Mapped[int] = mapped_column(Integer, default=0)
    reserved_credits: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0, server_default="0")
    reserved_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reserved_visitor_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class Purchase(Base, IdMixin):
    __tablename__ = "purchases"
    owner_id: Mapped[uuid.UUID] = owner_col()
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    credits: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
