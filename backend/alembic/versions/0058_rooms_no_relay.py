"""릴레이는 방이 아니다 (plan/44 §3).

A relay is two secretaries talking to each other. Neither person is in it: one asked for it
and both read the result afterwards, which is what the conversation list and the inbox are
for. The first pass gave those conversations rooms because the visitor row on the target
side carries the account the relay speaks for, so the owner turned up as a member of a room
between two secretaries — and typing into it would have pushed a bare message into a relay
that is counting hops.

Revision ID: 0058_rooms_no_relay
Revises: 0057_rooms
"""
from __future__ import annotations

from alembic import op

revision = "0058_rooms_no_relay"
down_revision = "0057_rooms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The messages keep their text; only the envelope goes.
    op.execute("""
        UPDATE messages SET room_id = NULL, sender_user_id = NULL
         WHERE room_id IN (SELECT r.id FROM rooms r JOIN conversations c ON c.id = r.conversation_id
                            WHERE c.kind = 'agent' OR c.relay_id IS NOT NULL)
    """)
    op.execute("""
        DELETE FROM rooms
         WHERE id IN (SELECT r.id FROM rooms r JOIN conversations c ON c.id = r.conversation_id
                       WHERE c.kind = 'agent' OR c.relay_id IS NOT NULL)
    """)


def downgrade() -> None:
    pass
