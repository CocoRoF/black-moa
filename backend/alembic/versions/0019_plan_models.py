"""Which pool models a plan may use (plan/33).

An empty list means the whole pool, so every existing plan keeps offering everything it
offers today.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0019_plan_models"
down_revision = "0018_profile_covers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("models", JSONB(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("plans", "models")
