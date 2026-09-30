"""Cover photos on agent profiles

A profile is a photo on a background in every messenger anybody has used, and a secretary's
profile is the first thing a stranger who opened a shared link looks at. The person's side
keeps its cover in `owner_profiles.data` with the rest of the profile fields; an agent has
no such bag, so it gets a column.

Revision ID: 0018_profile_covers
Revises: 0017_super_admin
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0018_profile_covers"
down_revision = "0017_super_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("cover_url", sa.Text()))


def downgrade() -> None:
    op.drop_column("agents", "cover_url")
