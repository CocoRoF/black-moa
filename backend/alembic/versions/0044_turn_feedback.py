"""Marking an answer wrong, and the correction that follows (plan/41 §8, M5).

The product could say what it must not disclose and could not say whether what it said was
true. This is the first half of that: the owner points at an answer, says what was actually
the case, and the correction becomes something the secretary answers from next time.
"""
from __future__ import annotations

from alembic import op

revision = "0044_turn_feedback"
down_revision = "0043_person_follows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS turn_feedback (
        id UUID PRIMARY KEY,
        turn_id UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
        owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        agent_id UUID,
        -- wrong | good
        verdict VARCHAR(16) NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        question TEXT NOT NULL DEFAULT '',
        answer TEXT NOT NULL DEFAULT '',
        faq_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_turn_feedback UNIQUE (turn_id)
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_turn_feedback_owner ON turn_feedback (owner_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS turn_feedback")
