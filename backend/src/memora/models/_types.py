from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

EMBED_DIM = 1536


def owner_col(nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=nullable, index=True)


def fk(table: str, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{table}.id", ondelete=ondelete), nullable=nullable, index=True)


__all__ = ["Vector", "ARRAY", "CITEXT", "JSONB", "UUID", "Index", "EMBED_DIM", "owner_col", "fk"]
