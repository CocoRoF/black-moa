"""atomic active-job deduplication

Revision ID: 0005_job_dedupe
Revises: 0004_credit_reservations
"""
from __future__ import annotations

from alembic import op

revision = "0005_job_dedupe"
down_revision = "0004_credit_reservations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Older workers used check-then-insert, so clean up any already-raced active
    # duplicates before establishing the database invariant. Keep one stable
    # winner; dedupe_key explicitly means these active jobs are interchangeable.
    op.execute("""
        DELETE FROM jobs newer
        USING jobs older
        WHERE newer.dedupe_key IS NOT NULL
          AND newer.dedupe_key = older.dedupe_key
          AND newer.status IN ('queued', 'running')
          AND older.status IN ('queued', 'running')
          AND (
            newer.created_at > older.created_at
            OR (newer.created_at = older.created_at AND newer.id::text > older.id::text)
          )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_jobs_active_dedupe
        ON jobs (dedupe_key)
        WHERE dedupe_key IS NOT NULL AND status IN ('queued', 'running')
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_jobs_active_dedupe")
