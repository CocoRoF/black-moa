from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from memora.db.base import Base, IdMixin, TimestampMixin
from memora.models._types import ARRAY, EMBED_DIM, JSONB, UUID, Vector, fk, owner_col


class NetworkNode(Base, IdMixin, TimestampMixin):
    __tablename__ = "network_nodes"
    __table_args__ = (
        Index("ix_network_nodes_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
        Index("uq_network_nodes_ext", "owner_id", "source", "external_ref", unique=True, postgresql_where="external_ref IS NOT NULL"),
    )
    owner_id: Mapped[uuid.UUID] = owner_col()
    # Who this node actually is (plan/31). A node is a card until there is evidence: an
    # account it belongs to, or a visitor who talked to this owner's secretary. Promotion
    # only ever goes offline → guest → member, and it merges into the existing card rather
    # than making a second one.
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Exactly one per owner. The graph is an ego network and needs a middle.
    is_self: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="person")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    # Public by default (plan/31): a network exists to be introduced from, and the
    # exception is the person you want hidden.
    importance: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(24), default="manual", server_default="manual")
    external_ref: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))


class NetworkEdge(Base, IdMixin, TimestampMixin):
    __tablename__ = "network_edges"
    __table_args__ = (UniqueConstraint("owner_id", "src_id", "dst_id", "rel"),)
    owner_id: Mapped[uuid.UUID] = owner_col()
    src_id: Mapped[uuid.UUID] = fk("network_nodes")
    dst_id: Mapped[uuid.UUID] = fk("network_nodes")
    rel: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(12), default="directed", server_default="directed")
    strength: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")
    since: Mapped[date | None] = mapped_column(Date)
    until: Mapped[date | None] = mapped_column(Date)
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    source: Mapped[str] = mapped_column(String(24), default="manual", server_default="manual")


class NetworkInteraction(Base, IdMixin):
    __tablename__ = "network_interactions"
    owner_id: Mapped[uuid.UUID] = owner_col()
    node_id: Mapped[uuid.UUID] = fk("network_nodes")
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    ref: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class NetworkProposal(Base, IdMixin, TimestampMixin):
    __tablename__ = "network_proposals"
    owner_id: Mapped[uuid.UUID] = owner_col()
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    confidence: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")
    source_turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
