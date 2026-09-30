"""호감도 다시 세우기 (plan/61).

대화 상승분이 사실상 붙지 않던 결함을 고치면서 상태를 둘 더 둔다: 오늘의 셈·기다리는 말(``affinity_state``)과
증감 기록(``affinity_log``). ``affinity_day`` 는 "오늘 아침 정산을 마친 날" 에서 "정산을 마친 끝난 날" 로
뜻이 바뀌므로 하루 당긴다 — 정확한 값은 재계산 스크립트(``memora.scripts.recompute_affinity``)가 채운다.

Revision ID: 0079_affinity_engine
Revises: 0078_special_days
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0079_affinity_engine"
down_revision = "0078_special_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_relationships", sa.Column("affinity_state", pg.JSONB(), nullable=False, server_default="{}"))
    op.add_column("agent_relationships", sa.Column("affinity_log", pg.JSONB(), nullable=False, server_default="[]"))
    op.execute("UPDATE agent_relationships SET affinity_day = affinity_day - 1 WHERE affinity_day IS NOT NULL")


def downgrade() -> None:
    op.execute("UPDATE agent_relationships SET affinity_day = affinity_day + 1 WHERE affinity_day IS NOT NULL")
    op.drop_column("agent_relationships", "affinity_log")
    op.drop_column("agent_relationships", "affinity_state")
