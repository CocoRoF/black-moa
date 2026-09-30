"""One row per process, for what only that process can see (plan/32 §6)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0025_process_stats"
down_revision = "0024_job_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "process_stats",
        sa.Column("key", sa.String(160), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_process_stats_at", "process_stats", ["at"])


def downgrade() -> None:
    op.drop_index("ix_process_stats_at", table_name="process_stats")
    op.drop_table("process_stats")
