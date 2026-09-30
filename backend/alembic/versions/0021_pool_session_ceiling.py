"""A session ceiling, not a request ceiling (plan/38).

Four concurrent *requests* is a sane number; four concurrent *conversations* on one login
is not — a single owner exhausted it in minutes and every further conversation was refused.
Existing installs are moved off the old default; anything an admin chose above it is left
alone.
"""
from __future__ import annotations

from alembic import op

revision = "0021_pool_session_ceiling"
down_revision = "0020_agent_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE claude_accounts ALTER COLUMN max_concurrency SET DEFAULT 16")
    op.execute("UPDATE claude_accounts SET max_concurrency = 16 WHERE max_concurrency <= 4")


def downgrade() -> None:
    op.execute("ALTER TABLE claude_accounts ALTER COLUMN max_concurrency SET DEFAULT 4")
