"""비서 [지식] 탭 = 외부인과의 대화에서 무엇을 쓰나 (plan/57).

공개 범위는 이제 [내 정보 → 정보](프로필) 에만 있다. 문서·FAQ·파일·인맥을 외부인에게 쓸지는
비서마다 정한다: ``agents.outsider`` 가 줄마다의 수준을, ``agent_disclosures`` 가 고른 것을 적는다.

옮기기는 **지금 동작 그대로**다. 비서마다
- 지식·파일·인맥: [모두 공개]였던 것을 고른 것으로, 수준은 [모두에게]. [인맥에게만]만 있으면
  그것을 고르고 수준을 [인맥에게만]으로. 둘이 섞였으면 [모두 공개] 쪽만 옮긴다 — 더 좁게,
  더 넓게는 절대 아니다. (2026-09-25 운영 데이터에 [인맥에게만] 항목은 0개.)
- 스케줄: 연락 가능 시간의 공개 범위 (비공개 → 쓰지 않음).
- 파일 건네기 = 옛 [파일 공유], 방문자 기억 = 옛 [방문자 기억] ∧ [재방문 시 이어서 대화], 웹 검색 = 옛 [웹 검색].
그 뒤 원천의 공개 범위 열과, 이제 아무것도 정하지 않는 옛 설정 키를 걷는다.

Revision ID: 0076_outsider
Revises: 0075_schedule
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0076_outsider"
down_revision = "0075_schedule"
branch_labels = None
depends_on = None

#: 원천마다: (kind, 표, 대상 열, 이 비서의 것만 고르는 조건)
_SOURCES = (
    # 피드 글의 사본(kind=blog)은 고르지 않는다 — 글마다의 범위와 [정보] 줄을 따른다.
    ("knowledge", "knowledge_documents", "document_id", "t.owner_id = a.owner_id AND t.kind <> 'blog'"),
    ("knowledge", "knowledge_faqs", "faq_id", "t.owner_id = a.owner_id"),
    ("files", "agent_files", "file_id", "t.agent_id = a.id AND t.scope = 'owner' AND t.deleted_at IS NULL"),
    ("network", "network_nodes", "node_id", "t.owner_id = a.owner_id AND NOT t.is_self"),
)


def _level_sql(kind: str) -> str:
    """이 비서의 한 줄 수준: 공개가 하나라도 있으면 public, 인맥에게만만 있으면 known, 없으면 public(고른 것 0개)."""
    parts = [(table, cond) for k, table, _col, cond in _SOURCES if k == kind]
    pub = " OR ".join(f"EXISTS (SELECT 1 FROM {table} t WHERE {cond} AND t.visibility = 'public')" for table, cond in parts)
    known = " OR ".join(f"EXISTS (SELECT 1 FROM {table} t WHERE {cond} AND t.visibility IN ('known', 'friends'))" for table, cond in parts)
    return f"(CASE WHEN {pub} THEN 'public' WHEN {known} THEN 'known' ELSE 'public' END)"


def upgrade() -> None:
    op.add_column("agents", sa.Column("outsider", pg.JSONB, nullable=False, server_default="{}"))
    op.create_table(
        "agent_disclosures",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", pg.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("document_id", pg.UUID(as_uuid=True), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True),
        sa.Column("faq_id", pg.UUID(as_uuid=True), sa.ForeignKey("knowledge_faqs.id", ondelete="CASCADE"), index=True),
        sa.Column("file_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_files.id", ondelete="CASCADE"), index=True),
        sa.Column("node_id", pg.UUID(as_uuid=True), sa.ForeignKey("network_nodes.id", ondelete="CASCADE"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for col, name in (("document_id", "doc"), ("faq_id", "faq"), ("file_id", "file"), ("node_id", "node")):
        op.create_index(f"uq_agent_disclosures_{name}", "agent_disclosures", ["agent_id", col], unique=True,
                        postgresql_where=sa.text(f"{col} IS NOT NULL"))

    # 1. 줄마다의 수준과 스위치 — 지금 동작 그대로.
    op.execute(f"""
        UPDATE agents a SET outsider = jsonb_build_object(
            'profile', true,
            'knowledge', {_level_sql('knowledge')}, 'knowledge_scope', 'picked',
            'knowledge_files', coalesce(a.capabilities->>'file_share', 'false') = 'true',
            'files', {_level_sql('files')}, 'files_scope', 'picked',
            'network', {_level_sql('network')}, 'network_scope', 'picked',
            'schedule', coalesce((SELECT CASE coalesce(p.visibility->>'availability_window', 'public')
                                             WHEN 'public' THEN 'public' WHEN 'known' THEN 'known' WHEN 'friends' THEN 'known'
                                             ELSE 'off' END
                                    FROM owner_profiles p WHERE p.owner_id = a.owner_id), 'public'),
            'memory', true,
            'visitors', coalesce(a.capabilities->>'visitor_memory', 'true') = 'true'
                        AND coalesce(a.visitor_settings->>'continue_conversations', 'true') = 'true',
            'web', coalesce(a.capabilities->>'web_search', 'false') = 'true')
    """)
    # 2. 고른 것 — 그 수준과 같은 범위였던 항목만.
    for kind, table, col, cond in _SOURCES:
        op.execute(f"""
            INSERT INTO agent_disclosures (id, agent_id, kind, {col})
            SELECT gen_random_uuid(), a.id, '{kind}', t.id
              FROM agents a JOIN {table} t ON {cond}
             WHERE t.visibility = CASE a.outsider->>'{kind}' WHEN 'known' THEN 'known' ELSE 'public' END
                OR (a.outsider->>'{kind}' = 'known' AND t.visibility = 'friends')
        """)
    # 3. 이제 아무것도 정하지 않는 옛 키.
    op.execute("""
        UPDATE agents SET
            capabilities = (SELECT coalesce(jsonb_object_agg(k, v), '{}'::jsonb) FROM jsonb_each(capabilities) AS e(k, v)
                             WHERE k IN ('voice', 'leave_message', 'meeting_request')),
            disclosure_policy = disclosure_policy - 'allow_contact_share' - 'network_default' - 'calendar_mode' - 'profile_fields',
            visitor_settings = visitor_settings - 'continue_conversations'
    """)
    op.execute("UPDATE owner_profiles SET visibility = visibility - 'availability_window' WHERE visibility ? 'availability_window'")
    # 4. 원천의 공개 범위 — 이제 [정보] 만 공개 범위를 가진다.
    for table in ("knowledge_documents", "knowledge_faqs", "agent_files", "network_nodes", "network_edges"):
        op.drop_column(table, "visibility")


def downgrade() -> None:
    op.add_column("knowledge_documents", sa.Column("visibility", sa.String(16), server_default="private"))
    op.add_column("knowledge_faqs", sa.Column("visibility", sa.String(16), server_default="public"))
    op.add_column("agent_files", sa.Column("visibility", sa.String(16), nullable=False, server_default="private"))
    op.add_column("network_nodes", sa.Column("visibility", sa.String(16), server_default="public"))
    op.add_column("network_edges", sa.Column("visibility", sa.String(16), server_default="public"))
    # 고른 것은 다시 [모두 공개]로, 나머지는 [비공개]로. 인맥은 옛 기본값이 공개였지만 되돌릴 때는 좁게.
    op.execute("UPDATE knowledge_faqs SET visibility = 'private'")
    op.execute("UPDATE network_nodes SET visibility = 'private'")
    for kind, table, col, _cond in _SOURCES:
        op.execute(f"""UPDATE {table} t SET visibility = CASE WHEN EXISTS (
                           SELECT 1 FROM agent_disclosures d JOIN agents a ON a.id = d.agent_id
                            WHERE d.{col} = t.id AND a.outsider->>'{kind}' = 'public') THEN 'public' ELSE 'known' END
                        WHERE EXISTS (SELECT 1 FROM agent_disclosures d WHERE d.{col} = t.id)""")
    # 피드 글의 사본은 글의 범위를 그대로 되찾는다.
    op.execute("""UPDATE knowledge_documents k SET visibility = CASE b.visibility WHEN 'friends' THEN 'known' ELSE b.visibility END
                    FROM blog_posts b WHERE b.knowledge_document_id = k.id""")
    op.execute("""
        UPDATE agents SET capabilities = capabilities || jsonb_build_object(
            'file_share', coalesce(outsider->>'knowledge_files', 'false') = 'true',
            'visitor_memory', coalesce(outsider->>'visitors', 'true') = 'true',
            'web_search', coalesce(outsider->>'web', 'false') = 'true',
            'google_email', true, 'email_send', false)
    """)
    op.drop_index("uq_agent_disclosures_node", table_name="agent_disclosures")
    op.drop_index("uq_agent_disclosures_file", table_name="agent_disclosures")
    op.drop_index("uq_agent_disclosures_faq", table_name="agent_disclosures")
    op.drop_index("uq_agent_disclosures_doc", table_name="agent_disclosures")
    op.drop_table("agent_disclosures")
    op.drop_column("agents", "outsider")
