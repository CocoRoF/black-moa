"""knowledge_chunks trigram index

Revision ID: 0002_chunk_trgm
Revises: 0001_initial
"""
from __future__ import annotations

from alembic import op

revision = "0002_chunk_trgm"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_text_trgm ON knowledge_chunks USING gin (text gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_text_trgm")
