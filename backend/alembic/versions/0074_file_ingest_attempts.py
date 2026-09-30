"""파일 읽기를 몇 번 시도했나 (plan/55).

밀린 읽기를 포기하는 기준이 "처음 받은 지 사흘" 이었다. 그러면 옛 파일을 다시 읽게
줄 세운 순간(0073 처럼) 한 번도 시도하지 않고 바로 "읽을 수 없음" 이 된다. 기준을 시도
횟수로 바꾼다.

Revision ID: 0074_file_ingest_attempts
Revises: 0073_agent_file_chunks
"""
import sqlalchemy as sa
from alembic import op

revision = "0074_file_ingest_attempts"
down_revision = "0073_agent_file_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_files", sa.Column("ingest_attempts", sa.Integer, nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("agent_files", "ingest_attempts")
