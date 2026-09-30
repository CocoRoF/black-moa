"""Secretary-to-secretary conversations (plan/38): the relay ledger, and the kind of a
conversation and of a visitor, so an exchange between two secretaries is told apart from a
person's visit everywhere it shows up."""
from __future__ import annotations

from alembic import op

revision = "0035_agent_relay"
down_revision = "0034_relationship_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'human'")
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS relay_id UUID")
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversations_relay_id ON conversations (relay_id)")
    op.execute("ALTER TABLE visitors ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'human'")
    op.execute("ALTER TABLE visitors ADD COLUMN IF NOT EXISTS peer_agent_id UUID")
    op.execute("""
    CREATE TABLE IF NOT EXISTS agent_relays (
        id UUID PRIMARY KEY,
        status VARCHAR(16) NOT NULL DEFAULT 'open',
        initiator_agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        initiator_owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        initiator_conversation_id UUID,
        initiator_visitor_id UUID,
        target_agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        target_owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        target_link_id UUID,
        target_conversation_id UUID,
        target_visitor_id UUID,
        origin_conversation_id UUID,
        origin_turn_id UUID,
        purpose TEXT NOT NULL DEFAULT '',
        opener TEXT NOT NULL DEFAULT '',
        max_messages INTEGER NOT NULL DEFAULT 8,
        credit_cap NUMERIC(14,4) NOT NULL DEFAULT 40,
        message_count INTEGER NOT NULL DEFAULT 0,
        hop_pending VARCHAR(16),
        pending_since TIMESTAMPTZ,
        in_flight_turn_id UUID,
        attempts INTEGER NOT NULL DEFAULT 0,
        close_requested_by VARCHAR(16),
        summary TEXT NOT NULL DEFAULT '',
        closed_at TIMESTAMPTZ,
        closed_by VARCHAR(16),
        close_reason VARCHAR(32),
        last_message_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""")
    for col in ("status", "initiator_agent_id", "initiator_owner_id", "target_agent_id", "target_owner_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_agent_relays_{col} ON agent_relays ({col})")
    op.execute("""
    CREATE TABLE IF NOT EXISTS agent_relay_messages (
        id UUID PRIMARY KEY,
        relay_id UUID NOT NULL REFERENCES agent_relays(id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        side VARCHAR(16) NOT NULL,
        agent_id UUID,
        kind VARCHAR(16) NOT NULL DEFAULT 'reply',
        content TEXT NOT NULL DEFAULT '',
        turn_id UUID,
        created_at TIMESTAMPTZ NOT NULL
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_relay_messages_relay_id ON agent_relay_messages (relay_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_relay_messages")
    op.execute("DROP TABLE IF EXISTS agent_relays")
    op.execute("ALTER TABLE visitors DROP COLUMN IF EXISTS peer_agent_id")
    op.execute("ALTER TABLE visitors DROP COLUMN IF EXISTS kind")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS relay_id")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS kind")
