"""turn execution invariants

Revision ID: 0003_turn_invariants
Revises: 0002_chunk_trgm

Database-level protection for races between concurrent HTTP workers:
- a client turn id is unique within a conversation
- at most one turn may be in status=running per conversation
"""
from __future__ import annotations

from alembic import op

revision = "0003_turn_invariants"
down_revision = "0002_chunk_trgm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Old deployments may already contain race-produced duplicates. Preserve all
    # turn rows, but keep the idempotency key only on the earliest occurrence.
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY conversation_id, client_turn_id
                       ORDER BY started_at, id
                   ) AS rn
            FROM turns
            WHERE client_turn_id IS NOT NULL
        )
        UPDATE turns t
        SET client_turn_id = NULL
        FROM ranked r
        WHERE t.id = r.id AND r.rn > 1
    """)

    # If a previous process race left multiple rows running, keep the newest one
    # active and close the rest before adding the partial unique index.
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY conversation_id
                       ORDER BY started_at DESC, id DESC
                   ) AS rn
            FROM turns
            WHERE status = 'running'
        )
        UPDATE turns t
        SET status = 'cancelled',
            error_code = COALESCE(error_code, 'superseded'),
            ended_at = COALESCE(ended_at, now())
        FROM ranked r
        WHERE t.id = r.id AND r.rn > 1
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_turns_conversation_client_turn
        ON turns (conversation_id, client_turn_id)
        WHERE client_turn_id IS NOT NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_turns_one_running_per_conversation
        ON turns (conversation_id)
        WHERE status = 'running'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_turns_one_running_per_conversation")
    op.execute("DROP INDEX IF EXISTS uq_turns_conversation_client_turn")
