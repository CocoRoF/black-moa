"""A reply under a reply (plan/42 §5).

Comments were one layer deep. That works while a post has three of them and stops working
the moment two people answer the same person: the replies sit in the same column as
everything else and whoever reads it has to work out what answers what.

One more layer, and only one. A reply to a reply joins the thread it is already in rather
than starting a third column, so a conversation stays a conversation and never becomes a
board.

Revision ID: 0055_comment_replies
Revises: 0054_agent_comments
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0055_comment_replies"
down_revision = "0054_agent_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("post_comments",
                  sa.Column("parent_id", UUID(as_uuid=True),
                            sa.ForeignKey("post_comments.id", ondelete="CASCADE"), nullable=True))
    op.create_index("ix_post_comments_parent", "post_comments", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_post_comments_parent", table_name="post_comments")
    op.drop_column("post_comments", "parent_id")
