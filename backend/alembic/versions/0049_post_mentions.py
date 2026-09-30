"""Naming somebody in a caption (plan/42 §11).

Every member already has an address, so a mention is that address written into the words.
The handles that resolved to a real account when the post was saved are kept on the post:
the card can then link exactly those and leave every other @word alone, and the person
named hears about it once.

Revision ID: 0049_post_mentions
Revises: 0048_album_into_posts
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0049_post_mentions"
down_revision = "0048_album_into_posts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("blog_posts", sa.Column("mentions", JSONB(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("blog_posts", "mentions")
