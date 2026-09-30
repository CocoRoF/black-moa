"""비서의 파일과 하나의 저장 공간 (plan/55 §3).

1. ``agent_files`` — 대화로 건넨 자료가 그 턴에만 있다가 사라지던 것을 비서마다 쌓는다.
2. ``plans.max_knowledge_mb`` → ``max_storage_mb``. 지식과 파일이 한 한도를 나눠 쓴다
   (결정 1). 기본값은 Free 1GB · Pro 3GB (결정 1-a). 50MB 는 사진 몇 장이면 찬다.
3. 이미 대화에 붙어 있던 파일을 원장에 옮겨 적는다. 읽기(글·설명·썸네일)는 작업자가
   ``files.sweep`` 에서 이어 한다.

Revision ID: 0071_agent_files
Revises: 0070_triggers_are_the_admins
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0071_agent_files"
down_revision = "0070_triggers_are_the_admins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_files",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("agent_id", pg.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("upload_id", pg.UUID(as_uuid=True), sa.ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("visitor_id", pg.UUID(as_uuid=True), sa.ForeignKey("visitors.id", ondelete="SET NULL"), index=True),
        sa.Column("conversation_id", pg.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="SET NULL"), index=True),
        sa.Column("message_id", pg.UUID(as_uuid=True)),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("caption", sa.Text, nullable=False, server_default=""),
        sa.Column("preview", sa.Text, nullable=False, server_default=""),
        sa.Column("text_path", sa.Text),
        sa.Column("text_chars", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pages", sa.Integer, nullable=False, server_default="0"),
        sa.Column("thumb_path", sa.Text),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_files_agent_live", "agent_files", ["agent_id", "created_at"])
    op.create_index("ix_agent_files_dedupe", "agent_files", ["agent_id", "scope", "visitor_id", "sha256"])

    op.alter_column("plans", "max_knowledge_mb", new_column_name="max_storage_mb")
    op.alter_column("plans", "max_storage_mb", server_default="1024")
    # 관리자가 이미 바꾼 값은 그 사람의 결정이다. 옛 기본값 그대로인 것만 새 기본값으로.
    op.execute("UPDATE plans SET max_storage_mb = 1024 WHERE code = 'free' AND max_storage_mb = 50")
    op.execute("UPDATE plans SET max_storage_mb = 3072 WHERE code = 'pro' AND max_storage_mb = 500")

    op.execute("""
        INSERT INTO agent_files (id, owner_id, agent_id, upload_id, source, scope, visitor_id, conversation_id, message_id,
                                 filename, mime, kind, size_bytes, sha256, status, created_at, updated_at)
        SELECT DISTINCT ON (c.agent_id, c.audience, c.visitor_id, u.sha256)
               gen_random_uuid(), c.owner_id, c.agent_id, u.id,
               CASE WHEN c.audience = 'visitor' THEN 'public' ELSE 'chat' END,
               CASE WHEN c.audience = 'visitor' THEN 'visitor' ELSE 'owner' END,
               c.visitor_id, c.id, m.id, u.filename, u.mime,
               CASE WHEN u.mime LIKE 'image/%' THEN 'image'
                    WHEN u.mime = 'application/pdf' THEN 'pdf'
                    WHEN u.mime LIKE '%wordprocessingml%' THEN 'document'
                    WHEN u.mime LIKE '%spreadsheetml%' OR u.mime = 'text/csv' THEN 'sheet'
                    WHEN u.mime LIKE '%presentationml%' THEN 'slides'
                    WHEN u.mime LIKE 'text/%' THEN 'text'
                    WHEN u.mime LIKE 'audio/%' THEN 'audio' ELSE 'other' END,
               u.size_bytes, u.sha256, 'pending', m.created_at, m.created_at
          FROM messages m
          JOIN conversations c ON c.id = m.conversation_id
          CROSS JOIN LATERAL jsonb_array_elements(coalesce(m.attachments, '[]'::jsonb)) a
          JOIN uploads u ON u.id::text = a->>'upload_id' AND u.owner_id = c.owner_id
         WHERE m.role = 'user' AND coalesce(c.simulated, false) = false
         ORDER BY c.agent_id, c.audience, c.visitor_id, u.sha256, m.created_at
    """)


def downgrade() -> None:
    op.alter_column("plans", "max_storage_mb", new_column_name="max_knowledge_mb", server_default="50")
    op.drop_index("ix_agent_files_dedupe", table_name="agent_files")
    op.drop_index("ix_agent_files_agent_live", table_name="agent_files")
    op.drop_table("agent_files")
