"""비서의 원본 그림 (plan/63).

프로필 사진은 동그라미에 맞춰 자르고 흰 바탕의 JPEG 로 저장한다. PC 앱의 아바타는 그 동그라미가 아니라 올린
그림 그대로(투명한 PNG 면 투명한 채로)를 띄워야 하므로, 자르기 전의 원본을 따로 둔다. 비어 있으면 앱은 프로필
사진을 쓴다.

Revision ID: 0080_agent_character
Revises: 0079_affinity_engine
"""
import sqlalchemy as sa
from alembic import op

revision = "0080_agent_character"
down_revision = "0079_affinity_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("character_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "character_url")
