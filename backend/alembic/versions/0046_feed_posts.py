"""The feed's own surface: short posts, likes and comments on one's own page (plan/42).

A post now has a kind. A `note` is what somebody types into the box at the top of 소식 and
has no title; an `article` is what the blog editor writes. Both are posts with an address.

Likes and comments get their own tables rather than borrowing the community's. The two
houses keep separate data on purpose (plan/41 §1) — one shared table is how a pen name and
a real name end up in the same row.

Revision ID: 0046_feed_posts
Revises: 0045_page_indexable
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0046_feed_posts"
down_revision = "0045_page_indexable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("blog_posts", sa.Column("kind", sa.String(16), nullable=False, server_default="article"))
    op.add_column("blog_posts", sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("blog_posts", sa.Column("comment_count", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "post_reactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("post_id", UUID(as_uuid=True), sa.ForeignKey("blog_posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("post_id", "user_id", name="uq_post_reaction"),
    )
    op.create_index("ix_post_reactions_user", "post_reactions", ["user_id"])

    op.create_table(
        "post_comments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("post_id", UUID(as_uuid=True), sa.ForeignKey("blog_posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_post_comments_post_created", "post_comments", ["post_id", "created_at"])


def downgrade() -> None:
    op.drop_table("post_comments")
    op.drop_table("post_reactions")
    for col in ("comment_count", "like_count", "kind"):
        op.drop_column("blog_posts", col)
