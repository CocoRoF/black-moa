"""Who a secretary looked up for its owner (plan/39): a candidate must be confirmed by the owner
in a later turn before a message goes out, and this is the record that makes it enforceable."""
from __future__ import annotations

from alembic import op

revision = "0037_relay_candidates"
down_revision = "0036_relay_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS relay_candidates (
        id UUID PRIMARY KEY,
        owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        conversation_id UUID,
        turn_id UUID,
        query VARCHAR(200) NOT NULL DEFAULT '',
        target_user_id UUID,
        target_agent_id UUID,
        link_code VARCHAR(64),
        source VARCHAR(16) NOT NULL DEFAULT 'directory',
        reachable BOOLEAN NOT NULL DEFAULT true,
        meta JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_relay_candidates_conversation_id ON relay_candidates (conversation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_relay_candidates_owner_id ON relay_candidates (owner_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS relay_candidates")
