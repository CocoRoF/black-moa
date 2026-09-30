"""Whether a person's public page may appear in search results.

The page has always been readable by anyone with the address. Being findable by name in a
search engine is a different thing to agree to, and there was no way to say no. Default
true: every page already carries no noindex, so starting anyone at false would quietly
remove pages that are indexed today.

Revision ID: 0045_page_indexable
Revises: 0044_turn_feedback
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_page_indexable"
down_revision = "0044_turn_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("page_indexable", sa.Boolean(), nullable=False, server_default="true"))


def downgrade() -> None:
    op.drop_column("users", "page_indexable")
