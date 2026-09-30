"""Photos on a post (plan/42 §3).

A feed where a picture arrives shrunk beside a paragraph is a feed of writing with pictures
attached. The ids live on the post; the bytes are ordinary uploads, served through a signed
address so an <img> tag can fetch them without a token and a private post's photo still
cannot be read by a stranger who guesses the id.

Revision ID: 0047_post_images
Revises: 0046_feed_posts
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0047_post_images"
down_revision = "0046_feed_posts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("blog_posts", sa.Column("images", JSONB(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("blog_posts", "images")
