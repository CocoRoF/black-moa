"""광장 이름을 계정에 둔다 (plan/52).

글마다 이름을 적게 두면 같은 사람이 여러 이름으로 흩어져 대화가 이어지지 않는다.
운영에서 한 사람이 두 이름으로 쓰고 있었고, 한 사람은 **남의 실명**을 필명 칸에
적어 넣었다. 이름을 계정에 하나 두고 자주 못 바꾸게 한다.

이미 쓴 글의 이름에서 옮긴다. 가장 많이 쓴 이름을 그 사람의 이름으로 삼고, 같은
수면 지어 준 이름을 쓴다(사칭한 이름이 그대로 따라오지 않게). 이름이 겹치면 뒤에
숫자를 붙인다: 익명 게시판에서 같은 이름 둘은 서로를 사칭하는 것과 같다.

Revision ID: 0066_community_name
Revises: 0065_anonymous_square
"""
from collections import Counter

import sqlalchemy as sa
from alembic import op

revision = "0066_community_name"
down_revision = "0065_anonymous_square"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("community_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("community_name_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("ALTER TABLE users ALTER COLUMN community_name TYPE CITEXT USING community_name::citext")

    from blackmoa.services.community import pen_name_for

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT author_id, meta->>'author_name' AS name FROM community_posts "
        "WHERE coalesce(meta->>'author_name', '') <> ''")).fetchall()
    used: dict = {}
    for author_id, name in rows:
        used.setdefault(author_id, Counter())[name] += 1

    taken: set[str] = set()
    for author_id, counts in used.items():
        (top, n), = counts.most_common(1)
        # 같은 수로 갈리면 지어 준 이름을 쓴다. 사칭한 이름이 따라오지 않게.
        name = top if sum(1 for c in counts.values() if c == n) == 1 else pen_name_for(author_id)
        base, i = name, 2
        while name.lower() in taken:
            name = f"{base}{i}"
            i += 1
        taken.add(name.lower())
        conn.execute(sa.text("UPDATE users SET community_name = CAST(:n AS citext) WHERE id = CAST(:u AS uuid)"),
                     {"n": name, "u": str(author_id)})

    op.create_unique_constraint("uq_users_community_name", "users", ["community_name"])


def downgrade() -> None:
    op.drop_constraint("uq_users_community_name", "users", type_="unique")
    op.drop_column("users", "community_name_at")
    op.drop_column("users", "community_name")
