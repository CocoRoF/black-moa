"""Bookkeeping for messages the secretary sends first (plan/37 §4): which pause it already
followed up on, so a pair is not asked about the same conversation twice."""
from __future__ import annotations

from alembic import op

revision = "0034_relationship_state"
down_revision = "0033_relationship"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_relationships ADD COLUMN IF NOT EXISTS proactive_state JSONB NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE agent_relationships DROP COLUMN IF EXISTS proactive_state")
