from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from memora.db.base import Base, IdMixin, TimestampMixin
from memora.models._types import ARRAY, JSONB, UUID, owner_col


class NotificationChannel(Base, IdMixin, TimestampMixin):
    __tablename__ = "notification_channels"
    owner_id: Mapped[uuid.UUID] = owner_col()
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(80), default="", server_default="")
    config_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    config_public: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class NotificationRule(Base, IdMixin, TimestampMixin):
    __tablename__ = "notification_rules"
    owner_id: Mapped[uuid.UUID] = owner_col()
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    channel_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    quiet_hours: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    min_urgency: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Notification(Base, IdMixin):
    __tablename__ = "notifications"
    owner_id: Mapped[uuid.UUID] = owner_col()
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    channel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
