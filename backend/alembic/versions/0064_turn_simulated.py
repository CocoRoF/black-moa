"""턴이 심부름인지 표시한다 (plan/50 §2).

`simulated` 턴은 사람이 말을 건 것이 아니다. 사진 읽기, 글에 댓글 달기, 방문자
흉내처럼 우리가 비서에게 시킨 일이다. 그 턴의 지시문이 "주인이 한 말" 로 기억되면,
코드에 적힌 문장이 주인에 대한 사실이 된다(운영에서 실제로 나왔다).

대화 행에는 이미 같은 표시가 있었지만 턴 행에는 없어서, 증류가 턴만 보고는
심부름인지 알 수 없었다.

Revision ID: 0064_turn_simulated
Revises: 0063_visibility_words
"""
from alembic import op
import sqlalchemy as sa

revision = "0064_turn_simulated"
down_revision = "0063_visibility_words"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("turns", sa.Column("simulated", sa.Boolean(), nullable=False, server_default="false"))
    op.create_index("ix_turns_simulated", "turns", ["simulated"])
    # 이미 지나간 턴은 대화 쪽 표시로 메운다. 그것이 지금까지의 유일한 근거였다.
    op.execute("""
        UPDATE turns t SET simulated = true
          FROM conversations c
         WHERE c.id = t.conversation_id AND c.simulated = true
    """)


def downgrade() -> None:
    op.drop_index("ix_turns_simulated", table_name="turns")
    op.drop_column("turns", "simulated")
