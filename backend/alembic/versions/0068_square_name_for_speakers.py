"""광장에서 말한 사람에게는 적어 둔 이름을 (plan/52).

0066 은 **글을 쓴** 사람에게 이름을 이식했다. 댓글만 단 사람은 이름이 없는 채로
남았고, 그 사람의 이름은 화면에서 계산됐다 — 계산해서 보여 주기만 하는 이름은
유일 제약도, name_taken 검사도, 이관 루프도 모두 비켜 간다.

그래서 열한 명에서 이미 부딪혔다: 한 사람이 고른 "커피마시는 팀원" 과 다른 사람의
지어 준 이름이 같은 이름이 됐다. 지어 주는 이름의 경우의 수는 80가지뿐이다.
익명 게시판에서 같은 이름 둘은 서로를 사칭하는 것과 같다.

광장에서 입을 연 사람 전부에게 이름을 받아 적는다. 부딪히면 뒤에 숫자를 붙인다
(0066 과 같은 방식). 스스로 고른 이름이 아니므로 시계(`community_name_at`)는
돌리지 않는다.

Revision ID: 0068_square_name_for_speakers
Revises: 0067_square_notice_pen
"""
from alembic import op

revision = "0068_square_name_for_speakers"
down_revision = "0067_square_notice_pen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    import sqlalchemy as sa

    from memora.services.community import pen_name_for

    conn = op.get_bind()
    taken = {
        (r[0] or "").strip().lower()
        for r in conn.execute(sa.text(
            "SELECT community_name FROM users WHERE coalesce(community_name, '') <> ''")).fetchall()
    }
    # 글은 0066 이 챙겼다. 남은 것은 댓글만 단 사람들이다.
    rows = conn.execute(sa.text(
        "SELECT DISTINCT c.author_id FROM community_comments c "
        "  JOIN users u ON u.id = c.author_id "
        " WHERE coalesce(u.community_name, '') = '' "
        " ORDER BY c.author_id")).fetchall()
    for (author_id,) in rows:
        base = pen_name_for(author_id)
        name, i = base, 2
        while name.lower() in taken:
            name = f"{base}{i}"
            i += 1
        taken.add(name.lower())
        conn.execute(sa.text(
            "UPDATE users SET community_name = CAST(:n AS citext) WHERE id = CAST(:u AS uuid)"),
            {"n": name, "u": str(author_id)})

    # 이미 나간 알림도 그 사람의 적어 둔 이름으로 맞춘다. 0067 이 덮을 때는 아직
    # 이름이 없어 계산한 값이 들어갔고, 그 값이 바로 부딪힌 이름이다.
    conn.execute(sa.text(
        "UPDATE inbox_items i "
        "   SET payload = coalesce(i.payload, '{}'::jsonb) "
        "                 || jsonb_build_object('actor_name', CAST(u.community_name AS text)) "
        "  FROM community_comments c, users u "
        " WHERE c.id = CAST(i.payload->>'comment_id' AS uuid) "
        "   AND u.id = c.author_id "
        "   AND i.kind IN ('community_comment', 'community_reply') "
        "   AND coalesce(u.community_name, '') <> '' "
        "   AND coalesce(i.payload->>'actor_name', '') <> u.community_name"))


def downgrade() -> None:
    # 받아 적은 이름을 도로 빼앗지 않는다. 그 이름으로 이미 대화가 오갔다.
    pass
