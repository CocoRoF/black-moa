"""호감도 — 지금 우리 사이의 온도 (plan/45 §4).

쌓은 것과 지금을 나눈다. 자격(함께한 날·대화·기억)은 누적이라 내려가지 않고, 호감도는
지금의 상태라 방치하면 빠르게 식는다. 실제 단계는 둘 중 낮은 쪽이다.

이미 쌓여 있던 사이가 이 칸이 생겼다는 이유로 하루아침에 내려가면 안 되므로, 지금
단계가 허락하는 가장 높은 온도에서 시작한다.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0061_affinity"
down_revision = "0060_channels_verified"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_relationships", sa.Column("affinity", sa.Float(), nullable=False, server_default="0"))
    #: 마지막으로 하루 셈을 한 날(주인의 현지 날짜). 하루에 한 번만 센다.
    op.add_column("agent_relationships", sa.Column("affinity_day", sa.Date(), nullable=True))
    #: 그때 기억이 몇 개였나. 늘어난 만큼만 쳐 준다.
    op.add_column("agent_relationships", sa.Column("affinity_facts", sa.Integer(), nullable=False, server_default="0"))
    #: 이 사람이 발행한 글 수(캐시). 마지막 단계는 이야기만으로는 닿지 않는다.
    op.add_column("agent_relationships", sa.Column("posts_written", sa.Integer(), nullable=False, server_default="0"))
    #: 비서가 이미 들춰 본 글. 같은 글만 되풀이해 보지 않게.
    op.add_column("agent_relationships", sa.Column("glanced", postgresql.JSONB(), nullable=False, server_default="[]"))
    op.execute(sa.text("""
        UPDATE agent_relationships
           SET affinity = CASE stage WHEN 'companion' THEN 100 WHEN 'trusted' THEN 74
                                     WHEN 'familiar' THEN 49 ELSE 24 END,
               affinity_facts = COALESCE(facts_remembered, 0)
    """))


def downgrade() -> None:
    for c in ("glanced", "posts_written", "affinity_facts", "affinity_day", "affinity"):
        op.drop_column("agent_relationships", c)
