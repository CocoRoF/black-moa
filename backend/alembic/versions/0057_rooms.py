"""방 — 블랙모아 안에서 오가는 모든 말이 담기는 자리 (plan/44).

Until now a conversation was a pair: one owner, one secretary. That works while the only
thing that talks is somebody's own secretary, and it falls apart everywhere else — there
was no person-to-person message at all, and a signed-in visitor who talked to somebody
else's secretary had no way back to what was said, because that conversation belonged to
the secretary's owner.

A room has members. A member is a person or a secretary. Messages land in the room, and how
far each member has read is written on their membership rather than on their device, which
is what makes the same conversation the same on a phone and on a desktop.

The turn pipeline is not touched. Messages stay in `messages`; the room is the envelope
around them. A secretary room points at the conversation it wraps, so every turn, tool and
credit path keeps working exactly as before. A room between two people has no conversation
at all, which is why `conversation_id` has to be allowed to be empty.

Revision ID: 0057_rooms
Revises: 0056_agent_memos
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0057_rooms"
down_revision = "0056_agent_memos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rooms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        # secretary — a person and a secretary; dm — two people.
        sa.Column("kind", sa.String(16), nullable=False, server_default="dm"),
        sa.Column("conversation_id", UUID(as_uuid=True),
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, unique=True),
        # The two people, sorted and joined, so "open the room with X" lands on one room.
        sa.Column("dm_key", sa.String(80), nullable=True, unique=True),
        sa.Column("title", sa.String(160), nullable=False, server_default=""),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rooms_last", "rooms", ["last_message_at"])

    op.create_table(
        "room_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("room_id", UUID(as_uuid=True), sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
        # Exactly one of these. A member is a person or a secretary.
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        # How far this member has read. On the person, not on the device.
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("room_id", "user_id", name="uq_room_user"),
        sa.UniqueConstraint("room_id", "agent_id", name="uq_room_agent"),
    )
    op.create_index("ix_room_members_user", "room_members", ["user_id", "room_id"])

    # The envelope's stamp on every message, and who actually spoke. `role` said user or
    # assistant, which is enough for one person talking to one secretary and nothing else.
    op.add_column("messages", sa.Column("room_id", UUID(as_uuid=True),
                                        sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True))
    op.add_column("messages", sa.Column("sender_user_id", UUID(as_uuid=True),
                                        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("messages", sa.Column("sender_agent_id", UUID(as_uuid=True),
                                        sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_messages_room", "messages", ["room_id", "created_at"])
    # A room between two people has no conversation behind it.
    op.alter_column("messages", "conversation_id", existing_type=UUID(as_uuid=True), nullable=True)
    op.alter_column("messages", "owner_id", existing_type=UUID(as_uuid=True), nullable=True)

    # ── 이미 있는 대화에 방을 준다 ─────────────────────────────────────
    #
    # Every owner conversation becomes a room the owner and the secretary are in. A visitor
    # conversation becomes one only when the visitor was signed in: an anonymous visit has
    # nobody to show it to. The secretary's owner is not a member of a visitor room — they
    # review visits where they always have.
    op.execute("""
        INSERT INTO rooms (id, kind, conversation_id, title, last_message_at, message_count, created_at, updated_at)
        SELECT gen_random_uuid(), 'secretary', c.id, COALESCE(c.title, ''),
               c.last_message_at, COALESCE(c.message_count, 0), c.created_at, c.updated_at
          FROM conversations c
          LEFT JOIN visitors v ON v.id = c.visitor_id
         WHERE c.simulated = false
           AND (c.audience = 'owner' OR (c.audience <> 'owner' AND v.user_id IS NOT NULL))
    """)
    # The person in the room: the owner for their own chat, the signed-in visitor otherwise.
    op.execute("""
        INSERT INTO room_members (id, room_id, user_id, role, last_read_at, joined_at)
        SELECT gen_random_uuid(), r.id,
               CASE WHEN c.audience = 'owner' THEN c.owner_id ELSE v.user_id END,
               'member',
               CASE WHEN c.audience = 'owner' AND c.unread_owner = false THEN c.last_message_at END,
               c.created_at
          FROM rooms r
          JOIN conversations c ON c.id = r.conversation_id
          LEFT JOIN visitors v ON v.id = c.visitor_id
         WHERE COALESCE(CASE WHEN c.audience = 'owner' THEN c.owner_id ELSE v.user_id END, NULL) IS NOT NULL
    """)
    op.execute("""
        INSERT INTO room_members (id, room_id, agent_id, role, joined_at)
        SELECT gen_random_uuid(), r.id, c.agent_id, 'secretary', c.created_at
          FROM rooms r JOIN conversations c ON c.id = r.conversation_id
    """)
    # And the messages already said move into the envelope their conversation now has.
    op.execute("""
        UPDATE messages m SET room_id = r.id,
               sender_user_id = CASE WHEN m.role = 'user' THEN rm.user_id END,
               sender_agent_id = CASE WHEN m.role = 'assistant' THEN c.agent_id END
          FROM rooms r
          JOIN conversations c ON c.id = r.conversation_id
          LEFT JOIN room_members rm ON rm.room_id = r.id AND rm.user_id IS NOT NULL
         WHERE m.conversation_id = r.conversation_id
    """)


def downgrade() -> None:
    op.drop_index("ix_messages_room", table_name="messages")
    op.drop_column("messages", "sender_agent_id")
    op.drop_column("messages", "sender_user_id")
    op.drop_column("messages", "room_id")
    op.drop_index("ix_room_members_user", table_name="room_members")
    op.drop_table("room_members")
    op.drop_index("ix_rooms_last", table_name="rooms")
    op.drop_table("rooms")
