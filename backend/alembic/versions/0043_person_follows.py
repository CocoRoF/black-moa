"""Subscribing to somebody's writing (plan/41 §5).

A connection is mutual and says "we know each other". Following is one-sided and says only
"I read what you publish", so it is a different table and needs nobody's approval.
"""
from __future__ import annotations

from alembic import op

revision = "0043_person_follows"
down_revision = "0042_blog_posts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS person_follows (
        id UUID PRIMARY KEY,
        follower_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        target_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_person_follow UNIQUE (follower_id, target_id)
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_person_follows_target ON person_follows (target_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS person_follows")
