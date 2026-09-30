"""파일은 계정의 것 (plan/77) — 비서 칸을 비울 수 있게.

Drive 에서 가져오거나 직접 모은 파일은 어느 비서에게 온 것이 아니다. 비서를 지워도 주인이 준 파일은 남는다.

Revision ID: 0083_files_belong_to_owner
Revises: 0082_terms_consent
"""
from alembic import op

revision = "0083_files_belong_to_owner"
down_revision = "0082_terms_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("agent_files", "agent_id", nullable=True)
    # 주인이 준 파일은 계정 안에서 같은 바이트면 하나 — 찾는 길.
    op.create_index("ix_agent_files_owner_sha", "agent_files", ["owner_id", "scope", "sha256"])


def downgrade() -> None:
    op.drop_index("ix_agent_files_owner_sha", table_name="agent_files")
    op.execute("DELETE FROM agent_files WHERE agent_id IS NULL")
    op.alter_column("agent_files", "agent_id", nullable=False)
