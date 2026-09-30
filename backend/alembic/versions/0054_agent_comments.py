"""A secretary's reply is signed by the secretary (plan/43 §6).

When a secretary was named in a post it read the post and answered, but the comment went
up under its owner's name. Whoever reads it sees a person saying something a person did
not write. The comment now carries which secretary wrote it, and the byline is that
secretary.

The owner stays on the row: they are who may delete it, and a secretary is not an account.

Revision ID: 0054_agent_comments
Revises: 0053_network_settings
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0054_agent_comments"
down_revision = "0053_network_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("post_comments",
                  sa.Column("agent_id", UUID(as_uuid=True),
                            sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("post_comments", "agent_id")
