"""Whose work a job is, so the queue can be fair (plan/45).

Ordering was priority then age, which is first-come — one owner enqueuing five hundred
documents put their five hundred ahead of everyone else's one.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0024_job_owner"
down_revision = "0023_ttfb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("owner_id", UUID(as_uuid=True), nullable=True))
    # The claim reads the head of the queue and ranks it per owner; this is the index it
    # walks to find that head.
    op.create_index("ix_jobs_claim", "jobs", ["status", "run_at", "priority"])
    op.create_index("ix_jobs_owner_id", "jobs", ["owner_id"])
    # Existing rows keep NULL: they are already queued and mostly already done, and a
    # backfill would have to guess an owner out of five different payload shapes.


def downgrade() -> None:
    op.drop_index("ix_jobs_owner_id", table_name="jobs")
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_column("jobs", "owner_id")
