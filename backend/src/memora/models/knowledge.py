from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Computed, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from memora.db.base import Base, IdMixin, TimestampMixin
from memora.models._types import EMBED_DIM, JSONB, UUID, Vector, fk, owner_col


class OwnerProfile(Base):
    __tablename__ = "owner_profiles"
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    visibility: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Fact(Base, IdMixin, TimestampMixin):
    __tablename__ = "facts"
    __table_args__ = (Index("ix_facts_owner_status", "owner_id", "status"),)
    owner_id: Mapped[uuid.UUID] = owner_col()
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    predicate: Mapped[str] = mapped_column(String(200), nullable=False)
    object: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), default="context", server_default="context")
    confidence: Mapped[float] = mapped_column(Float, default=0.8, server_default="0.8")
    visibility: Mapped[str] = mapped_column(String(24), default="private", server_default="private")
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    source_turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))


class KnowledgeDocument(Base, IdMixin, TimestampMixin):
    __tablename__ = "knowledge_documents"
    owner_id: Mapped[uuid.UUID] = owner_col()
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="file")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255))
    mime: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    storage_path: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="processing", server_default="processing")
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    text_preview: Mapped[str] = mapped_column(Text, default="", server_default="")
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class KnowledgeChunk(Base, IdMixin):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("ix_knowledge_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_knowledge_chunks_text_trgm", "text", postgresql_using="gin", postgresql_ops={"text": "gin_trgm_ops"}),
        Index(
            "ix_knowledge_chunks_embedding", "embedding", postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64}, postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    document_id: Mapped[uuid.UUID] = fk("knowledge_documents")
    owner_id: Mapped[uuid.UUID] = owner_col()
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    heading: Mapped[str] = mapped_column(Text, default="", server_default="")
    page: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    tsv: Mapped[str | None] = mapped_column(TSVECTOR, Computed("to_tsvector('simple', text)", persisted=True))


class KnowledgeFaq(Base, IdMixin, TimestampMixin):
    __tablename__ = "knowledge_faqs"
    owner_id: Mapped[uuid.UUID] = owner_col()
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    source: Mapped[str] = mapped_column(String(24), default="manual", server_default="manual")


class Upload(Base, IdMixin):
    __tablename__ = "uploads"
    owner_id: Mapped[uuid.UUID] = owner_col()
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: 방문자가 건넨 파일이면 그 방문자 (plan/55 §6-3). 바이트는 주인 소유, 쓰는 사람은 이 방문자.
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("visitors.id", ondelete="SET NULL"),
                                                         nullable=True)
