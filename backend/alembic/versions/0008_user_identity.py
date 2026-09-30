"""users.nickname and users.name_confirmed_at

A person here has two names: the one their secretary calls them by, and the real one the
account is billed and administered under. They were the same column, so a playful nickname
became the legal identity and vice versa.

Revision ID: 0008_user_identity
Revises: 0007_visitor_account
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_user_identity"
down_revision = "0007_visitor_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("nickname", sa.String(60), nullable=True))
    op.add_column("users", sa.Column("name_confirmed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "name_confirmed_at")
    op.drop_column("users", "nickname")
