"""광장 알림에 남은 실명을 광장 이름으로 (plan/51 §2).

글과 댓글에서는 실명을 걷어냈는데 **알림이 실명을 들고 나갔다.** 익명 댓글 하나에
글쓴이의 인박스에는 그 사람의 계정 이름이 떴다. 익명 게시판에서 이건 글을 숨기고
알림으로 드러나는 것이라, 숨긴 줄 알고 쓰게 된다.

코드는 고쳤다. 이미 쌓인 알림에도 같은 규칙을 적용한다 — 인박스는 지우지 않는
자리라, 고치지 않으면 그 이름이 계속 거기 있다.

이 이관은 **이름을 가리는 쪽으로만 간다.** 댓글 글쓴이의 광장 이름으로 덮고,
댓글이 사라진 알림은 손대지 않는다(덮을 근거가 없다).

Revision ID: 0067_square_notice_pen
Revises: 0066_community_name
"""
from alembic import op

revision = "0067_square_notice_pen"
down_revision = "0066_community_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    import sqlalchemy as sa

    from memora.services.community import pen_name_for

    conn = op.get_bind()
    # 알림은 comment_id 만 들고 있다. 거기서 글쓴이로, 글쓴이에서 광장 이름으로 간다.
    # asyncpg 는 `%s` 를 모르고 타입도 스스로 정하지 못한다 — 이름 붙인 자리에
    # CAST 를 달아 준다 (0065 에서 배운 것).
    rows = conn.execute(sa.text(
        "SELECT i.id, c.author_id, u.community_name "
        "  FROM inbox_items i "
        "  JOIN community_comments c ON c.id = CAST(i.payload->>'comment_id' AS uuid) "
        "  JOIN users u ON u.id = c.author_id "
        " WHERE i.kind IN ('community_comment', 'community_reply') "
        "   AND coalesce(i.payload->>'actor_name', '') <> ''")).fetchall()
    for item_id, author_id, community_name in rows:
        pen = (community_name or "").strip() or pen_name_for(author_id)
        conn.execute(sa.text(
            "UPDATE inbox_items "
            "   SET payload = coalesce(payload, '{}'::jsonb) "
            "                 || jsonb_build_object('actor_name', CAST(:pen AS text)) "
            " WHERE id = CAST(:iid AS uuid)"), {"pen": pen, "iid": str(item_id)})


def downgrade() -> None:
    # 광장 이름을 실명으로 되돌리지 않는다. 가린 것을 다시 벗기는 쪽으로는 가지 않는다.
    pass
