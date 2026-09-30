"""[내 정보 → 스케줄] (plan/56).

1. ``schedule_events`` — Memora 에 직접 넣는 일정. Google 을 쓰지 않아도 스케줄이 온전하다.
2. ``integration_events.busy`` — Google 에서 "한가함" 으로 표시한 일정(생일 등)은 빈 시간을 막지 않는다.
3. 비서마다의 캘린더 설정을 원장으로: 주인의 비서 중 하나라도 [캘린더 공유 = 안 함] 이었거나 [캘린더]
   능력을 꺼 두었으면, 그 주인의 연락 가능 시간 공개 범위를 "나만" 으로 둔다. 옮기면서 더 많이 내보내지 않는다.

Revision ID: 0075_schedule
Revises: 0074_file_ingest_attempts
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0075_schedule"
down_revision = "0074_file_ingest_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("location", sa.Text, nullable=False, server_default=""),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("busy", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("source", sa.String(16), nullable=False, server_default="owner"),
        sa.Column("agent_id", pg.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("inbox_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("inbox_items.id", ondelete="SET NULL")),
        sa.Column("google_event_id", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_schedule_events_owner_time", "schedule_events", ["owner_id", "start_at"])
    op.add_column("integration_events", sa.Column("busy", sa.Boolean, nullable=False, server_default="true"))
    op.execute("""
        UPDATE owner_profiles p
           SET visibility = coalesce(p.visibility, '{}'::jsonb) || '{"availability_window": "private"}'::jsonb
         WHERE EXISTS (SELECT 1 FROM agents a WHERE a.owner_id = p.owner_id
                         AND (coalesce(a.disclosure_policy->>'calendar_mode', 'busy_only') = 'none'
                              OR coalesce(a.capabilities->>'google_calendar', 'true') = 'false'))
    """)


def downgrade() -> None:
    op.drop_column("integration_events", "busy")
    op.drop_index("ix_schedule_events_owner_time", table_name="schedule_events")
    op.drop_table("schedule_events")
