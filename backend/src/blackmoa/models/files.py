"""비서의 파일 (plan/55 §3-1).

사용자가 대화로 건넨 자료가 그 턴에만 있다가 사라지던 것을, 비서마다 쌓이는 원장으로
만든다. 바이트는 ``uploads`` 에 그대로 두고 이 행은 "어느 비서가, 어디서, 언제 받았나"
와 읽은 결과(글·설명·썸네일)를 적는다.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Computed, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from blackmoa.db.base import Base, IdMixin, TimestampMixin
from blackmoa.models._types import EMBED_DIM, UUID, Vector, fk, owner_col


class AgentFile(Base, IdMixin, TimestampMixin):
    __tablename__ = "agent_files"
    __table_args__ = (
        Index("ix_agent_files_agent_live", "agent_id", "created_at"),
        Index("ix_agent_files_dedupe", "agent_id", "scope", "visitor_id", "sha256"),
        Index("ix_agent_files_owner_sha", "owner_id", "scope", "sha256"),
    )
    owner_id: Mapped[uuid.UUID] = owner_col()
    #: 이 파일이 들어온 비서. 파일은 계정의 것이다(plan/77) — Drive·직접 모은 파일은 비어 있고, 비서를 지우면
    #: 주인이 준 파일은 여기만 비운다. 방문자가 준 파일은 그 비서·그 방문자 대화에 딸린다.
    agent_id: Mapped[uuid.UUID | None] = fk("agents", nullable=True)
    upload_id: Mapped[uuid.UUID] = fk("uploads")
    #: chat · messenger · public · manual · drive
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="chat")
    #: owner — 주인이 건넨 것 · visitor — 그 방문자가 건넨 것(그 방문자 칸에만 보인다)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="owner")
    visitor_id: Mapped[uuid.UUID | None] = fk("visitors", nullable=True, ondelete="SET NULL")
    conversation_id: Mapped[uuid.UUID | None] = fk("conversations", nullable=True, ondelete="SET NULL")
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    #: image · pdf · document · sheet · slides · text · audio · other
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 그림을 한두 문장으로. 검색과 그림을 못 보는 모델이 쓴다.
    caption: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: 추출한 글의 첫 부분(목록·검색용). 전체는 객체 저장소 ``text_path``.
    preview: Mapped[str] = mapped_column(Text, default="", server_default="")
    text_path: Mapped[str | None] = mapped_column(Text)
    text_chars: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pages: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    thumb_path: Mapped[str | None] = mapped_column(Text)
    #: pending · ready · unreadable
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    #: 읽기를 몇 번 시도했나. 다섯 번이면 "읽을 수 없음" 으로 둔다.
    ingest_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentFileChunk(Base, IdMixin):
    """파일 본문의 한 조각 — 지식 조각과 같은 모양으로 찾는다 (plan/55 P4)."""

    __tablename__ = "agent_file_chunks"
    __table_args__ = (
        Index("ix_agent_file_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_agent_file_chunks_text_trgm", "text", postgresql_using="gin", postgresql_ops={"text": "gin_trgm_ops"}),
        Index("ix_agent_file_chunks_embedding", "embedding", postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64}, postgresql_ops={"embedding": "vector_cosine_ops"}),
    )
    file_id: Mapped[uuid.UUID] = fk("agent_files")
    owner_id: Mapped[uuid.UUID] = owner_col()
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    tsv: Mapped[str | None] = mapped_column(TSVECTOR, Computed("to_tsvector('simple', text)", persisted=True))
