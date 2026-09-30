"""A memo about somebody's secretary (plan/44 §8).

The graph draws two kinds of thing you can press: people, who are rows in `network_nodes`
and have a `notes` field, and published secretaries, which are not rows at all — they are
assembled from the links hanging off the people. Pressing one used to open a new tab
instead of a panel, so there was nowhere to write anything down about it.

A memo about a secretary belongs to whoever wrote it, not to the secretary's owner, so it
gets its own small table rather than a column on `agents`.

Revision ID: 0056_agent_memos
Revises: 0055_comment_replies
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0056_agent_memos"
down_revision = "0055_comment_replies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_memos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("owner_id", "agent_id", name="uq_agent_memo"),
    )


def downgrade() -> None:
    op.drop_table("agent_memos")
