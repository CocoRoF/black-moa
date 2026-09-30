"""한국의 특별한 날 (plan/60): 공식 출처에서 받아 온 공휴일·기념일·절기·잡절.

내장 계산(공휴일 라이브러리 · 음력 · 절기)은 저장하지 않는다. 관리자가 [연결 → 공휴일]에서
한국천문연구원 특일 정보를 이으면 받아 온 것이 여기 쌓이고, 받아 온 해·종류는 내장 계산 대신 쓴다.

Revision ID: 0078_special_days
Revises: 0077_oauth_settings
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0078_special_days"
down_revision = "0077_oauth_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "special_days",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("country", sa.String(2), nullable=False, server_default="KR"),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("off", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("source", sa.String(16), nullable=False, server_default="kasi"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("country", "day", "kind", "name"),
    )
    op.create_index("ix_special_days_year", "special_days", ["country", "year"])


def downgrade() -> None:
    op.drop_index("ix_special_days_year", table_name="special_days")
    op.drop_table("special_days")
