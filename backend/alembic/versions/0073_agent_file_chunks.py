"""파일 본문을 찾을 수 있게 (plan/55 P4).

파일의 글은 객체 저장소에 통째로 있고 행에는 앞 2,000자만 있었다 — 뒤쪽에 적힌 말로는
찾지 못했다. 지식과 같은 모양의 조각 색인을 둔다(벡터 ∪ 전문 ∪ 한국어 부분일치). 사진은
설명 한 조각. 조각은 파일을 지우면 같이 사라진다.

Revision ID: 0073_agent_file_chunks
Revises: 0072_visitor_files_grants
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

revision = "0073_agent_file_chunks"
down_revision = "0072_visitor_files_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_file_chunks",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("file_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_files.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("page", sa.Integer),
        sa.Column("embedding", Vector(1536)),
        sa.Column("tsv", pg.TSVECTOR, sa.Computed("to_tsvector('simple', text)", persisted=True)),
    )
    op.create_index("ix_agent_file_chunks_tsv", "agent_file_chunks", ["tsv"], postgresql_using="gin")
    op.create_index("ix_agent_file_chunks_text_trgm", "agent_file_chunks", ["text"], postgresql_using="gin",
                    postgresql_ops={"text": "gin_trgm_ops"})
    op.create_index("ix_agent_file_chunks_embedding", "agent_file_chunks", ["embedding"], postgresql_using="hnsw",
                    postgresql_with={"m": 16, "ef_construction": 64}, postgresql_ops={"embedding": "vector_cosine_ops"})
    # 이미 읽어 둔 파일도 조각을 만들도록 다시 읽기 줄에 세운다(files.sweep 이 잡는다).
    op.execute("UPDATE agent_files SET status = 'pending' WHERE status = 'ready' AND deleted_at IS NULL")


def downgrade() -> None:
    op.drop_table("agent_file_chunks")
