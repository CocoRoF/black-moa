"""한 사람과 한 비서 사이에 방은 하나다 (plan/44 §3).

The first pass gave every conversation its own room. Somebody with four conversations with
their secretary saw the secretary four times in the messenger, and the rooms were titled by
the first line ever typed into each — "ㅎㅇ?", "이분은 누구니" — which is what a chat log
calls a thread and not what a person calls the person they are talking to.

A room is the pair. Conversations under it are how the turn pipeline keeps context, and
the messenger shows all of them as one timeline. Existing rooms for the same pair are
folded into one: messages move, the furthest read mark wins, the rest are dropped.

Revision ID: 0059_rooms_by_pair
Revises: 0058_rooms_no_relay
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0059_rooms_by_pair"
down_revision = "0058_rooms_no_relay"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rooms", sa.Column("person_id", UUID(as_uuid=True),
                                     sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True))
    op.add_column("rooms", sa.Column("agent_id", UUID(as_uuid=True),
                                     sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True))
    # A room outlives any one of its conversations now.
    op.execute("ALTER TABLE rooms DROP CONSTRAINT IF EXISTS rooms_conversation_id_key")
    op.execute("ALTER TABLE rooms DROP CONSTRAINT IF EXISTS rooms_conversation_id_fkey")
    op.create_foreign_key("rooms_conversation_id_fkey", "rooms", "conversations",
                          ["conversation_id"], ["id"], ondelete="SET NULL")

    op.execute("""
        UPDATE rooms r SET person_id = rm.user_id FROM room_members rm
         WHERE rm.room_id = r.id AND rm.user_id IS NOT NULL AND r.kind = 'secretary'
    """)
    op.execute("""
        UPDATE rooms r SET agent_id = rm.agent_id FROM room_members rm
         WHERE rm.room_id = r.id AND rm.agent_id IS NOT NULL AND r.kind = 'secretary'
    """)
    # ── 같은 짝의 방을 하나로 접는다 ─────────────────────────────────
    op.execute("""
        CREATE TEMP TABLE keep AS
        SELECT DISTINCT ON (person_id, agent_id) id AS keep_id, person_id, agent_id
          FROM rooms
         WHERE kind = 'secretary' AND person_id IS NOT NULL AND agent_id IS NOT NULL
         ORDER BY person_id, agent_id, last_message_at DESC NULLS LAST, created_at DESC
    """)
    op.execute("""
        CREATE TEMP TABLE dup AS
        SELECT r.id AS dup_id, k.keep_id
          FROM rooms r JOIN keep k ON k.person_id = r.person_id AND k.agent_id = r.agent_id
         WHERE r.kind = 'secretary' AND r.id <> k.keep_id
    """)
    op.execute("UPDATE messages m SET room_id = d.keep_id FROM dup d WHERE m.room_id = d.dup_id")
    # The furthest anybody read in any of the folded rooms is how far they have read now.
    op.execute("""
        UPDATE room_members km SET last_read_at = GREATEST(km.last_read_at, x.mx)
          FROM (SELECT d.keep_id, rm.user_id, MAX(rm.last_read_at) AS mx
                  FROM dup d JOIN room_members rm ON rm.room_id = d.dup_id
                 WHERE rm.user_id IS NOT NULL GROUP BY d.keep_id, rm.user_id) x
         WHERE km.room_id = x.keep_id AND km.user_id = x.user_id AND x.mx IS NOT NULL
    """)
    op.execute("DELETE FROM rooms WHERE id IN (SELECT dup_id FROM dup)")
    op.execute("""
        UPDATE rooms r SET message_count = (SELECT count(*) FROM messages m WHERE m.room_id = r.id),
                           last_message_at = (SELECT max(created_at) FROM messages m WHERE m.room_id = r.id),
                           title = ''
         WHERE r.kind = 'secretary'
    """)
    # The conversation a turn from the messenger goes to: the pair's most recent one.
    op.execute("""
        UPDATE rooms r SET conversation_id = (
            SELECT c.id FROM conversations c LEFT JOIN visitors v ON v.id = c.visitor_id
             WHERE c.agent_id = r.agent_id AND c.simulated = false AND c.kind <> 'agent' AND c.relay_id IS NULL
               AND ((c.audience = 'owner' AND c.owner_id = r.person_id)
                    OR (c.audience <> 'owner' AND v.user_id = r.person_id AND v.kind <> 'agent'))
             ORDER BY c.last_message_at DESC NULLS LAST, c.created_at DESC LIMIT 1)
         WHERE r.kind = 'secretary'
    """)
    op.execute("DROP TABLE dup")
    op.execute("DROP TABLE keep")
    op.create_index("uq_room_pair", "rooms", ["person_id", "agent_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_room_pair", table_name="rooms")
    op.drop_column("rooms", "agent_id")
    op.drop_column("rooms", "person_id")
