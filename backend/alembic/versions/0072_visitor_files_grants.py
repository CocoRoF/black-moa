"""방문자가 건넨 파일, 그리고 사람끼리 방으로 가는 허락 (plan/55 §6-3·§6-4).

1. ``uploads.visitor_id`` — 방문자가 올린 파일은 바이트가 주인의 한도를 쓰지만(주인 소유),
   **그 방문자의 것**이라는 표시가 있어야 한다. 하루에 몇 개 올렸는지 세고, 그 방문자의 턴
   에만 붙일 수 있게 한다(다른 사람이 올린 파일의 id 를 찍어 붙이는 길을 막는다).
2. ``room_grants`` — 비서는 사람끼리 방을 당연히 보지 않는다. 주인이 이 방이라고 확인하고
   허락한 동안에만 그 방을 읽는다. 허락의 단위는 이 비서 × 이 방이고, [이번 대화에서만]
   또는 [계속]. 거두면 ``revoked_at``.

Revision ID: 0072_visitor_files_grants
Revises: 0071_agent_files
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0072_visitor_files_grants"
down_revision = "0071_agent_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("uploads", sa.Column("visitor_id", pg.UUID(as_uuid=True),
                                       sa.ForeignKey("visitors.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_uploads_visitor", "uploads", ["visitor_id", "created_at"])

    op.create_table(
        "room_grants",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("agent_id", pg.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("room_id", pg.UUID(as_uuid=True), sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("conversation_id", pg.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE")),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_read_at", sa.DateTime(timezone=True)),
    )
    # 한 비서 × 한 방에 살아 있는 허락은 하나.
    op.create_index("uq_room_grants_live", "room_grants", ["agent_id", "room_id"], unique=True,
                    postgresql_where=sa.text("revoked_at IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_room_grants_live", table_name="room_grants")
    op.drop_table("room_grants")
    op.drop_index("ix_uploads_visitor", table_name="uploads")
    op.drop_column("uploads", "visitor_id")
