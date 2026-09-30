from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from memora.db.base import Base, IdMixin, TimestampMixin
from memora.models._types import ARRAY, EMBED_DIM, JSONB, Vector, fk, owner_col


class Connection(Base, IdMixin, TimestampMixin):
    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("owner_id", "provider", "account_label"),)
    owner_id: Mapped[uuid.UUID] = owner_col()
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    account_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_cursor: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)


class IntegrationEmail(Base, IdMixin):
    __tablename__ = "integration_emails"
    __table_args__ = (UniqueConstraint("connection_id", "ext_id"),)
    owner_id: Mapped[uuid.UUID] = owner_col()
    connection_id: Mapped[uuid.UUID] = fk("connections")
    ext_id: Mapped[str] = mapped_column(String(128), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(128))
    from_addr: Mapped[str] = mapped_column(String(320), default="", server_default="")
    to_addrs: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    subject: Mapped[str] = mapped_column(Text, default="", server_default="")
    snippet: Mapped[str] = mapped_column(Text, default="", server_default="")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    labels: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    importance: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unread: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))


class IntegrationEvent(Base, IdMixin):
    __tablename__ = "integration_events"
    __table_args__ = (UniqueConstraint("connection_id", "ext_id"),)
    owner_id: Mapped[uuid.UUID] = owner_col()
    connection_id: Mapped[uuid.UUID] = fk("connections")
    ext_id: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", server_default="")
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    location: Mapped[str] = mapped_column(Text, default="", server_default="")
    attendees: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    status: Mapped[str] = mapped_column(String(32), default="confirmed", server_default="confirmed")
    description_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: Google 에서 "한가함" 으로 표시한 일정은 빈 시간을 막지 않는다 (plan/56).
    busy: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
