"""Relay transcripts (plan/38): track, per side, the last ledger message that side's own
conversation has, so a close for any reason can fill in what was never delivered."""
from __future__ import annotations

from alembic import op

revision = "0036_relay_delivery"
down_revision = "0035_agent_relay"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_relays ADD COLUMN IF NOT EXISTS delivered_seq_initiator INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE agent_relays ADD COLUMN IF NOT EXISTS delivered_seq_target INTEGER NOT NULL DEFAULT 0")
    # Relays closed before this existed already have complete transcripts on the paths that
    # ran (a turn always writes what it answered); mark them as such so no sync re-adds lines.
    op.execute("""UPDATE agent_relays r SET delivered_seq_initiator = m.mx, delivered_seq_target = m.mx
                  FROM (SELECT relay_id, max(seq) mx FROM agent_relay_messages GROUP BY relay_id) m WHERE m.relay_id = r.id""")


def downgrade() -> None:
    op.execute("ALTER TABLE agent_relays DROP COLUMN IF EXISTS delivered_seq_target")
    op.execute("ALTER TABLE agent_relays DROP COLUMN IF EXISTS delivered_seq_initiator")
