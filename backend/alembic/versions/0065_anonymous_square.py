"""광장을 익명으로 (plan/51).

커뮤니티는 익명 커뮤니티다. 그런데 글을 쓸 때 [실명으로 쓰기] 가 기본으로 켜져
있어서, 운영의 11편 중 8편이 실명으로 남아 있었다. 익명이라는 말과 어긋난다.

이 이관은 **이름을 가리는 쪽으로만 간다.** 필명이 없는 글에 그 사람의 광장 이름을
붙인다. 같은 사람은 늘 같은 이름이라 지난 글들의 대화가 끊기지 않는다.
드러내는 쪽으로는 아무것도 바꾸지 않는다.

비서가 광장 글을 재료로 삼던 문서도 함께 지운다. 익명이라는 말은 그 글이 나와
이어지지 않는다는 뜻이고, 내 비서가 알고 있으면 언젠가 두 이름이 만난다.

Revision ID: 0065_anonymous_square
Revises: 0064_turn_simulated
"""
from alembic import op

revision = "0065_anonymous_square"
down_revision = "0064_turn_simulated"
branch_labels = None
depends_on = None


def upgrade() -> None:
    import sqlalchemy as sa

    from memora.services.community import pen_name_for

    conn = op.get_bind()
    # asyncpg 는 `%s` 자리표시자를 모른다. 이름 붙은 자리를 쓴다.
    rows = conn.execute(sa.text(
        "SELECT id, author_id FROM community_posts WHERE coalesce(meta->>'author_name', '') = ''")).fetchall()
    for post_id, author_id in rows:
        # 자리표시자에 타입을 붙인다. asyncpg 는 `jsonb_build_object` 안의 인자를
        # 보고 타입을 정하지 못해 "could not determine data type of parameter" 로 멈춘다.
        conn.execute(sa.text(
            "UPDATE community_posts "
            "   SET meta = coalesce(meta, '{}'::jsonb) || jsonb_build_object('author_name', CAST(:pen AS text)) "
            " WHERE id = CAST(:pid AS uuid)"), {"pen": pen_name_for(author_id), "pid": str(post_id)})
    # 광장에서 온 지식 문서는 남기지 않는다.
    op.execute("DELETE FROM knowledge_chunks WHERE document_id IN "
               "(SELECT id FROM knowledge_documents WHERE kind = 'community')")
    op.execute("DELETE FROM knowledge_documents WHERE kind = 'community'")
    op.execute("UPDATE community_posts SET meta = meta - 'knowledge_document_id' "
               "WHERE meta ? 'knowledge_document_id'")


def downgrade() -> None:
    # 이름을 도로 벗기지 않는다. 익명이던 것을 실명으로 되돌리는 것은 되돌릴 수 없다.
    pass
